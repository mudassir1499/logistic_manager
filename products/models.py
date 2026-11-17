"""
products/models.py

This module defines the database models for the Products app in a Django logistics management system.

The Products app manages the catalog of items that customers can order. In a logistics business,
products are typically goods sourced from suppliers (like Alibaba, 1688, or local manufacturers).
Each product has pricing, shipping dimensions (for calculating freight costs), and optional images.

Models:
    - Product: Represents a single item in the catalog with pricing, dimensions, and shipping info.
    - ProductImage: Stores one or more images for each product (e.g., photos from the supplier).
"""

# Import Django's ORM models module to define database fields and relationships
from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Category(models.Model):
    """
    A top-level grouping for products, e.g. "Health & Personal Care".

    Categories are the coarse buckets a customer browses by. Each one holds
    zero or more SubCategory rows (see below), so the portal can offer a
    two-level drill-down: pick "Home & Kitchen", then narrow to "Appliances".

    Attributes:
        name (str): Display name shown in the portal filter bar.
        slug (str): URL-safe identifier used in the ?category= query param.
                    Slugs are used rather than IDs so filter links stay
                    readable and survive a database reload.
        ordering (int): Manual sort weight. Lower numbers appear first, which
                    lets the admin surface the biggest categories at the top
                    instead of being stuck with alphabetical order.
        is_active (bool): Unchecking hides the category from the portal without
                    deleting it or orphaning the products underneath.
    """

    name = models.CharField(max_length=120, unique=True)

    # blank=True lets the admin leave this empty in a form; save() fills it in
    # from the name. It is still unique and non-null at the database level.
    slug = models.SlugField(max_length=140, unique=True, blank=True)

    ordering = models.PositiveIntegerField(
        default=0,
        help_text='Lower numbers appear first in the portal filter bar.'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Uncheck to hide this category from the customer portal.'
    )

    # The letters that start every SKU in this category, e.g. HEA-0007.
    #
    # Stored rather than derived from the name at generation time, for two
    # reasons this catalogue demonstrates. It holds both "Tools And Home
    # Improvements" and "Tools & Machinery", and any simple derivation gives
    # both TOO. And a derived prefix would silently change if the category were
    # renamed, so the next product would get a SKU that no longer matched its
    # neighbours - with the ones already issued left behind under the old
    # letters. Filled in automatically on save; editable when a different code
    # is wanted.
    sku_prefix = models.CharField(
        max_length=6,
        blank=True,
        unique=True,
        null=True,
        help_text='Prefix for auto-generated SKUs in this category, e.g. HEA. '
                  'Leave blank to derive it from the name.',
    )

    class Meta:
        verbose_name_plural = 'Categories'
        # Manual weight first, then alphabetical as a stable tiebreaker so the
        # order never depends on insertion order.
        ordering = ['ordering', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Derive the slug and the SKU prefix from the name when unset."""
        if not self.slug:
            self.slug = slugify(self.name)[:140]

        if not self.sku_prefix:
            from .sku import derive_prefix
            taken = set(
                Category.objects.exclude(pk=self.pk)
                .exclude(sku_prefix__isnull=True)
                .exclude(sku_prefix='')
                .values_list('sku_prefix', flat=True)
            )
            self.sku_prefix = derive_prefix(self.name, taken)

        super().save(*args, **kwargs)


class SkuSequence(models.Model):
    """
    The highest SKU number ever issued for a prefix.

    Exists so a SKU is never reused. Deriving the next number from the highest
    one currently in the products table looks equivalent and is not: delete the
    highest-numbered product and the maximum drops, so the next product created
    is handed a code that already appears on a printed packing list, an invoice
    and possibly a carton in a warehouse.

    This counter only ever goes up. A retired SKU stays retired.
    """

    prefix = models.CharField(
        max_length=6, unique=True,
        help_text='SKU prefix this counter belongs to, e.g. HEA.',
    )
    last_number = models.PositiveIntegerField(
        default=0,
        help_text='Highest number issued so far. Never decreases.',
    )

    class Meta:
        verbose_name = 'SKU sequence'
        ordering = ['prefix']

    def __str__(self):
        return '%s (last %s)' % (self.prefix, self.last_number)


class SubCategory(models.Model):
    """
    A second-level grouping nested under a Category, e.g. "Pain Relief"
    inside "Health & Personal Care".

    Subcategories are optional: a product may sit directly in a category with
    no subcategory at all. That matters for small categories such as "Photo
    Frames" where a further split would add clicks without adding clarity.

    Attributes:
        category (Category): The parent category this belongs to.
        name (str): Display name, unique within its parent (not globally) so
                    two categories can each have an "Accessories".
        slug (str): URL-safe identifier for the ?subcategory= query param.
    """

    category = models.ForeignKey(
        Category,
        related_name='subcategories',
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)

    ordering = models.PositiveIntegerField(
        default=0,
        help_text='Lower numbers appear first within the parent category.'
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'Sub categories'
        ordering = ['ordering', 'name']
        # Names and slugs only need to be unique *within* a parent category,
        # which is why these are composite constraints rather than unique=True
        # on the fields themselves.
        constraints = [
            models.UniqueConstraint(
                fields=['category', 'name'], name='uniq_subcategory_name_per_category'
            ),
            models.UniqueConstraint(
                fields=['category', 'slug'], name='uniq_subcategory_slug_per_category'
            ),
        ]

    def __str__(self):
        # Qualified with the parent so admin dropdowns are unambiguous when
        # two categories share a subcategory name.
        return f'{self.category.name} / {self.name}'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)


class ProductTag(models.Model):
    """
    A free-form label that can be put on any number of products.

    Categories already answer "what kind of thing is this", and every product
    has exactly one. Tags answer the questions that cut ACROSS categories and
    that a single-parent tree cannot express: which supplier something came
    from, which shipment it is going out on, whether it has been photographed
    yet, which marketplace it is listed on. A power bank and a photo frame can
    both be "Ramadan 2026" or "needs-repricing" without being related in any
    other way.

    That is the whole reason this is a many-to-many rather than another
    ForeignKey. A product carries as many tags as it needs and loses none of
    them by gaining another, which is exactly what a category cannot do.

    Attributes:
        name (str): What the operator types, e.g. "Needs photos".
        slug (str): URL-safe form, used in the ?tag= filter so a tagged view
                    can be bookmarked and shared.
        colour (str): Hex value for the chip. Colour is the point of a tag on a
                    dense list — you scan for it rather than read it.
    """

    # A palette rather than a colour picker. Free hex entry on a label that
    # exists to be recognised at a glance reliably produces ten similar greys,
    # and these are already checked for contrast against the chip background.
    COLOUR_CHOICES = [
        ('#2563eb', 'Blue'),
        ('#0f766e', 'Teal'),
        ('#15803d', 'Green'),
        ('#B08421', 'Amber'),
        ('#c2410c', 'Orange'),
        ('#b91c1c', 'Red'),
        ('#7c3aed', 'Purple'),
        ('#be185d', 'Pink'),
        ('#475569', 'Slate'),
    ]

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=80, unique=True, blank=True)
    colour = models.CharField(max_length=7, choices=COLOUR_CHOICES, default='#2563eb')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Product Tag'
        verbose_name_plural = 'Product Tags'

    def save(self, *args, **kwargs):
        # Same contract as Category.save: the form may leave the slug blank and
        # it is filled from the name, but it stays unique and non-null in the
        # database. Two tags whose names slugify identically ("Needs Photos"
        # and "needs photos") would collide, so the second gets a suffix rather
        # than raising at the database layer.
        if not self.slug:
            base = slugify(self.name) or 'tag'
            candidate = base[:80]
            n = 2
            existing = ProductTag.objects.exclude(pk=self.pk)
            while existing.filter(slug=candidate).exists():
                suffix = f'-{n}'
                candidate = f'{base[:80 - len(suffix)]}{suffix}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    """
    Represents a product in the logistics company's catalog.

    In this business, a "product" is an item that customers can order. The logistics company
    sources these products from suppliers (often in China) and arranges shipping (air/sea)
    to the customer's destination (UAE, KSA, etc.).

    Each product stores:
    - Basic info (name, SKU for barcode scanning)
    - Pricing (regular price, optional air/sea shipping prices)
    - Shipping specs (weight, carton dimensions, pieces per carton)
    - Visibility flags (draft vs. published, private vs. public)

    Attributes:
        name (str): Product name displayed to customers and in the admin.
        price (Decimal): Base product price per unit (e.g., per piece or per carton).
        moq (int): Minimum Order Quantity — the smallest number a customer can order.
        weight (Decimal, optional): Weight of one unit in kilograms (used for shipping cost calculation).
        carton_length (Decimal, optional): Carton length in centimeters.
        carton_width (Decimal, optional): Carton width in centimeters.
        carton_height (Decimal, optional): Carton height in centimeters.
        carton_qty (int, optional): Number of pieces per carton (for bulk orders).
        price_air (Decimal, optional): Pre-saved air shipping price per unit.
        price_sea (Decimal, optional): Pre-saved sea shipping price per unit.
        is_draft (bool): If True, product is not visible to customers yet.
        is_private (bool): If True, product only visible to assigned customers.
        sku (str): Stock Keeping Unit / Barcode for inventory and label printing.

    Business Logic:
        The admin creates products with supplier pricing. When a customer places an order,
        the system calculates total cost = (product price × quantity) + shipping cost.
        Shipping cost depends on the method (air/sea/ksa) and either weight (air) or volume/CBM (sea).
    """

    # CharField stores text up to 255 characters. Product name is required.
    # This is the display name shown in catalogs, invoices, and order lists.
    # db_index=True improves search performance for product lookups by name.
    name = models.CharField(max_length=255, db_index=True)

    # URL slug for the public catalogue, e.g. /shop/cordless-vacuum-120w/.
    # Generated from the name on first save and then frozen — see save().
    # Nullable so the migration can add it to existing rows before backfilling.
    slug = models.SlugField(max_length=200, unique=True, null=True, blank=True)

    # DecimalField: Used for money/currency to avoid floating-point precision errors.
    # max_digits=10 means up to 10 digits total. decimal_places=2 means 2 decimal places (e.g., 12345678.90).
    # This is the base price the customer pays per unit (could be per piece or per carton).
    price = models.DecimalField(max_digits=10, decimal_places=2)

    # PositiveIntegerField: Only accepts whole numbers >= 0.
    # MOQ = Minimum Order Quantity. The smallest quantity a customer can order for this product.
    # verbose_name is the human-readable label shown in Django admin forms.
    moq = models.PositiveIntegerField(verbose_name='Minimum Order Quantity')

    # Weight of the product in kilograms. Used for calculating air freight costs.
    # Air freight is typically charged "per KG", so accurate weight is essential for cost estimates.
    # null=True, blank=True means the admin can leave this empty if weight is unknown.
    weight = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name='Weight (KG)')

    # Carton dimensions in centimeters. Used to calculate CBM (Cubic Meters) for sea freight.
    # Sea freight charges are based on volume, not weight. CBM = (L × W × H) / 1,000,000.
    # All three dimensions are optional because some products may not have carton info yet.
    carton_length = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Carton Length (CM)')
    carton_width = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Carton Width (CM)')
    carton_height = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Carton Height (CM)')

    # How many individual pieces are inside one carton. Useful for bulk pricing and label generation.
    # For example, if carton_qty = 50, ordering 100 pieces means 2 cartons.
    carton_qty = models.PositiveIntegerField(null=True, blank=True, verbose_name='Pieces per Carton')

    # Optional pre-calculated shipping prices. The admin can save these after getting quotes from shipping companies.
    # These are used to quickly estimate order totals without recalculating every time.
    # null=True, blank=True means these are optional fields.
    price_air = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Saved Air Price')
    price_sea = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Saved Sea Price')

    # Draft flag: When True, the product is only visible in the admin, not to customers.
    # The admin can set is_draft=True while gathering product info from suppliers before publishing.
    is_draft = models.BooleanField(default=False, verbose_name='Draft')

    # Private flag: When True, the product is only visible to customers who have a CustomerProduct assignment.
    # This is useful when a customer has exclusive products they don't want competitors to see.
    # db_index=True improves filtering performance for public vs private catalog queries.
    is_private = models.BooleanField(default=False, verbose_name='Private', db_index=True)

    # SKU (Stock Keeping Unit) or barcode string. Used for inventory tracking and label printing.
    # blank=True, default='' means if left empty, it stores an empty string (not NULL).
    # db_index=True enables fast SKU lookups and barcode scanning.
    sku = models.CharField(max_length=100, blank=True, default='', verbose_name='SKU / Barcode', db_index=True)

    # Product source / marketplace tag. Used to group products by sourcing channel.
    SOURCE_CHOICES = [
        ('general', 'General'),
        ('amazon', 'Amazon'),
        ('noon', 'Noon'),
    ]
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default='general',
        db_index=True,
        verbose_name='Product Source',
        help_text='Tag products as General, Amazon, or Noon. Controls where they appear in the portal.'
    )

    # Ready-to-ship flag: When True, the product is in stock/available for immediate shipment.
    # Customers ordering ready-to-ship Amazon/Noon products are prompted to upload shipping
    # and carton labels during checkout.
    ready_to_ship = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name='Ready to Ship',
        help_text='If checked, customers must provide shipping and carton labels when ordering this product.'
    )

    # The supplier listing this product came from — normally a 1688 offer page.
    #
    # Saved so that months later, when a customer reorders or a spec needs
    # checking, the buyer can go straight back to the supplier and message them
    # rather than re-searching 1688 for a product whose Chinese name nobody
    # kept. The browser extension fills this in automatically; it can also be
    # pasted in by hand.
    #
    # STAFF-ONLY DATA. Which factory supplies a product at what price is the
    # core of a sourcing agency's margin, so this is never rendered anywhere in
    # the customer portal — only on the internal product screens.
    source_url = models.URLField(
        max_length=500,
        blank=True,
        default='',
        verbose_name='Supplier listing URL',
        help_text='Link to the supplier’s page (e.g. the 1688 offer). Staff only — never shown to customers.',
    )

    # ---------------------------------------------------------------------
    # CATEGORISATION
    # ---------------------------------------------------------------------
    # Products carry BOTH a category and an optional subcategory rather than
    # only a subcategory. Two reasons:
    #   1. A product can live in a category that has no meaningful subdivision
    #      (e.g. "Photo Frames"), which a subcategory-only design cannot express.
    #   2. Filtering by category stays a single indexed column lookup instead of
    #      a join through the subcategory table.
    # The redundancy this introduces is kept honest by save() below, which
    # forces category to match the subcategory's parent.
    #
    # on_delete=SET_NULL: deleting a category must never delete the products
    # inside it. They simply become uncategorised and can be reassigned.
    # blank=True only: a product with no tags is the normal case, and there is
    # no null for a many-to-many to be.
    tags = models.ManyToManyField(
        'ProductTag',
        related_name='products',
        blank=True,
        help_text='Cross-cutting labels. A product can carry any number.',
    )

    category = models.ForeignKey(
        Category,
        related_name='products',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
    )
    subcategory = models.ForeignKey(
        SubCategory,
        related_name='products',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        verbose_name='Sub category',
    )

    class Meta:
        """
        Meta options for the Product model.
        """
        # Add composite indexes for common query patterns
        indexes = [
            models.Index(fields=['is_draft', 'is_private', 'name']),
            models.Index(fields=['is_draft', 'is_private']),
            models.Index(fields=['source', 'is_draft', 'is_private']),
            # Backs the portal's category filter, which always runs alongside
            # the published/public predicates.
            models.Index(fields=['category', 'is_draft', 'is_private']),
            models.Index(fields=['subcategory', 'is_draft', 'is_private']),
        ]

    def _build_slug(self):
        """
        A unique, URL-safe slug derived from the name.

        Public product pages are addressed by slug rather than id because the
        words in the URL are read by both search engines and people deciding
        whether to click. A numeric id tells neither anything.

        Uniqueness is settled with a counter suffix rather than by raising:
        product names are unique, but two different names can slugify to the same
        string ("Vacuum 2.0" and "Vacuum 20"), and an import failing on that would
        be a baffling error to debug.
        """
        base = slugify(self.name)[:180] or 'product'
        slug = base
        counter = 2
        while (
            Product.objects.filter(slug=slug)
            .exclude(pk=self.pk)
            .exists()
        ):
            suffix = f'-{counter}'
            slug = base[:180 - len(suffix)] + suffix
            counter += 1
        return slug

    def save(self, *args, **kwargs):
        """
        Keeps category and subcategory from drifting out of sync, and fills in
        the public URL slug.

        Because both columns are stored, it is possible to set a subcategory
        belonging to one category while `category` still points at another —
        which would make a product visible under the wrong filter. Rather than
        rejecting that with a validation error (which would break bulk imports
        and the admin's inline editing), we treat the subcategory as the more
        specific statement of intent and derive the category from it.
        """
        if self.subcategory_id:
            # Only touch the parent when it actually disagrees, so the common
            # case costs no extra query.
            if self.category_id != self.subcategory.category_id:
                self.category_id = self.subcategory.category_id

        # Only ever generated when missing. A slug that changed with the name
        # would break every link and search result already pointing at the old
        # one; renaming a product must not cost its ranking.
        if not self.slug:
            self.slug = self._build_slug()

        # Same rule for the SKU, and for a stronger reason: a SKU is what goes
        # on a packing list, an invoice and a warehouse shelf. Regenerating it
        # because a product moved category would leave printed paperwork
        # pointing at a code that no longer exists. Assigned once, then fixed.
        if not (self.sku or '').strip():
            from .sku import next_sku
            self.sku = next_sku(self)

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        """The canonical public URL for this product."""
        from django.urls import reverse
        return reverse('shop_product_detail', args=[self.slug])

    def __str__(self):
        """
        Returns the human-readable name of the product.

        Django uses __str__ for displaying the object in admin dropdowns, list views,
        and debugging. Showing the product name makes it easy to identify.

        Returns:
            str: The product's name.
        """
        return self.name

    # -------------------------------------------------------------------------
    # VARIANTS
    # -------------------------------------------------------------------------
    # A product either has no variants (the ordinary case — one thing, one price)
    # or several, each with its own price. These helpers let a template ask about
    # that without knowing which, so the catalogue card and the detail page have
    # one code path instead of two.
    #
    # They read ``self.variants.all()`` rather than issuing their own aggregate
    # query, so a caller that has already used ``prefetch_related('variants')``
    # pays nothing extra. Callers that have not will issue one query per product —
    # prefetch on any list view.
    # -------------------------------------------------------------------------

    @property
    def active_variants(self):
        """The orderable variants, in display order."""
        return [v for v in self.variants.all() if v.is_active]

    @property
    def displayable_images(self):
        """
        The images that actually render, in order.

        A ProductImage whose download never succeeded holds a ``source_url`` and
        no file, and shows nothing (see ``ProductImage.src``). Such rows must not
        reach a template: a gallery would render an empty thumbnail slot, and
        ``og:image`` / the JSON-LD ``image`` array would carry an empty string,
        which Facebook and Google both treat as a malformed tag rather than an
        absent one.

        Reads the prefetched list, like ``active_variants`` above, so a caller
        that has already used ``prefetch_related('images')`` pays nothing extra.
        """
        return [image for image in self.images.all() if image.src]

    @property
    def primary_image(self):
        """
        The first image that can actually be displayed, or None.

        Not ``images.first()``: that returns whatever is first in the table,
        which may be a row with no file — leaving a product card showing the
        empty-image placeholder while a perfectly good photo sat second in the
        list.
        """
        images = self.displayable_images
        return images[0] if images else None

    @property
    def has_variants(self):
        return bool(self.active_variants)

    @property
    def price_range(self):
        """
        ``(lowest, highest)`` across active variants, or ``None`` when there are
        none. Equal values mean every variant costs the same and the caller should
        show a single price rather than a range of one number repeated.
        """
        prices = [v.price for v in self.active_variants if v.price is not None]
        if not prices:
            return None
        return min(prices), max(prices)

    @property
    def display_price(self):
        """
        The figure to headline. For a product with variants that is the cheapest
        one — the "from" price — because quoting the dearest variant as the
        product's price makes the whole catalogue look overpriced.
        """
        span = self.price_range
        return span[0] if span else self.price


class ProductImage(models.Model):
    """
    Stores an image file associated with a Product.

    A product can have multiple images (e.g., front view, back view, packaging photo).
    This model implements a one-to-many relationship: one Product can have many ProductImages.

    Attributes:
        product (Product): The product this image belongs to.
        image (ImageField): The actual image file uploaded by the admin.

    Business Logic:
        Product images are shown in the customer portal so buyers can see what they are ordering.
        They may also be used in invoices and quotations. The related_name='images' on the
        ForeignKey allows easy access: product.images.all() gives all images for a product.
    """

    # ForeignKey creates a many-to-one relationship: multiple ProductImages can belong to one Product.
    # related_name='images': This lets us access all images from a product object using product.images.all().
    # Without related_name, Django would use the default name: product.productimage_set.all()
    # on_delete=models.CASCADE: if the Product is deleted, all its images are also deleted.
    product = models.ForeignKey(Product, related_name='images', on_delete=models.CASCADE)

    # ImageField: Specialized field for uploading image files. Django handles file storage.
    # upload_to='product_images/': Uploaded images are stored in the MEDIA_ROOT/product_images/ directory.
    # This organizes files into a subfolder and prevents filename collisions.
    #
    # blank=True because a row may carry only ``source_url`` — see below. Read the
    # image through ``src``, never through ``image.url`` directly, or a URL-only
    # row raises ValueError ("The 'image' attribute has no file associated").
    image = models.ImageField(upload_to='product_images/', blank=True)

    # The remote address the picture lives at, for imported products whose file we
    # do not hold locally.
    #
    # Imports download images into MEDIA_ROOT and that stays the preferred outcome:
    # a local file cannot rot when the supplier delists the product or the CDN adds
    # hotlink protection. But the download can fail for reasons that have nothing to
    # do with the URL being bad — a blocked host, a proxy, no outbound network — and
    # throwing the address away made that failure permanent and invisible.
    #
    # Storing it means the picture still renders, and a later retry can fill in the
    # local file. Writers must only store hosts on the marketplace-CDN allowlist in
    # products/api.py: this value is interpolated into an <img src> on staff AND
    # customer pages, so an arbitrary URL here is an injection point.
    source_url = models.URLField(
        max_length=500,
        blank=True,
        default='',
        help_text='Remote address of the image, used when no local file was downloaded.',
    )

    @property
    def src(self):
        """
        Where to point an ``<img>`` at — the local file, or '' when there is none.

        NEVER the supplier's CDN. This used to fall back to ``source_url`` so a
        product whose download failed still showed a picture, and that is exactly
        the behaviour customers could not use: alicdn is unreachable or heavily
        throttled from Pakistan and much of the region we sell into, so a
        hotlinked photo is a broken frame for the buyer while looking perfectly
        fine to staff in a browser that can reach it. A missing image renders a
        clean placeholder; a hotlink renders as damage.

        Every template and JSON endpoint reads this rather than ``image.url``, so
        the guarantee holds everywhere rather than at each call site. Callers must
        treat '' as "no image" — see the ``{% if %}`` guards in the templates.

        ``source_url`` is still recorded, and is what
        ``manage.py fetch_remote_images`` retries from. It is data, not a source
        to render.
        """
        if self.image:
            try:
                return self.image.url
            except ValueError:
                # The field holds a name but the storage cannot build a URL for it.
                pass
        return ''

    @property
    def is_remote(self):
        """
        True when this row has no local file, only a remote address.

        Such a row now renders NOTHING (see ``src``) — it is a placeholder for a
        download that has not happened yet, not an image being served from the
        CDN. ``fetch_remote_images`` finds these; ``--purge-failed`` removes the
        ones that can never be fetched.
        """
        return not self.image and bool(self.source_url)

    def __str__(self):
        """
        Returns a descriptive string indicating which product this image belongs to.

        Returns:
            str: A string like "Image for Wireless Headphones".
        """
        # f-string embedding the product name for clear identification in admin lists.
        return f"Image for {self.product.name}"


class ProductVariant(models.Model):
    """
    One sellable variation of a product — a colour, a size, a kit configuration.

    WHY THIS EXISTS: a single 1688 listing routinely sells a dozen or more SKUs
    under one page ("3 Sections One Gun", "5 Sections Two Battery", ...), each with
    its own price, stock and photo. The sourcing extension used to import each of
    those as its own top-level Product, so one listing produced seventeen catalogue
    cards that were all the same item. The catalogue became unbrowsable and the
    duplicate-name guard started rejecting legitimately different products.

    A variant carries only what actually differs between siblings. Weight, carton
    dimensions, category and description live on the parent Product, because they
    are properties of the item rather than of the colour you picked.

    PRICE is per variant and is the number that gets ordered. ``Product.price`` is
    kept as the headline "from" figure — see ``Product.price_range``.
    """

    product = models.ForeignKey(
        Product,
        related_name='variants',
        on_delete=models.CASCADE,
    )

    # The supplier's own label for this SKU, translated where possible:
    # "High Pressure Water Gun [3 Sections One Gun]".
    name = models.CharField(max_length=255)

    price = models.DecimalField(max_digits=10, decimal_places=2)

    # What the supplier claimed was in stock at scrape time. Advisory only — it is
    # a number from a webpage, not a reservation, so nothing enforces it.
    stock = models.PositiveIntegerField(null=True, blank=True)

    sku = models.CharField(max_length=100, blank=True, default='')

    # Variants get their own photo far more often than not — the whole point of a
    # colour variant is that it looks different. Same local-file-or-remote-URL
    # arrangement as ProductImage; read it through ``src``.
    image = models.ImageField(upload_to='product_images/', blank=True)
    image_url = models.URLField(max_length=500, blank=True, default='')

    # Display order, mirroring the order the supplier's page listed them in.
    sort_order = models.PositiveIntegerField(default=0)

    # Lets staff retire a variation without deleting it, which would break the
    # order history that references it.
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Product Variant'
        verbose_name_plural = 'Product Variants'
        indexes = [
            models.Index(fields=['product', 'sort_order']),
        ]

    def __str__(self):
        return f'{self.product.name} — {self.name}'

    @property
    def src(self):
        """
        Where to point an <img> at: the local file, or '' when there is none.

        Never ``image_url`` — same reason as ProductImage.src, which see. A
        variation whose photo has not been downloaded shows no photo rather than
        a frame that is broken for every customer on a network that cannot reach
        alicdn. ``image_url`` remains as the address fetch_remote_images retries
        from.

        Templates must guard on this being non-empty; a variation legitimately
        has no photo far more often than a product does.
        """
        if self.image:
            try:
                return self.image.url
            except ValueError:
                pass
        return ''


class ProductAttribute(models.Model):
    """
    One free-form spec line on a product — "Model: ST-128PlusMax", "Voltage: 220V".

    WHY NOT COLUMNS ON Product: the useful specs differ per category. A vacuum has
    voltage and suction; a picture frame has aperture and glass type; a cable has a
    length and a connector. Adding a column per spec would mean a migration for every
    new product type and a form full of fields that are blank for most rows.

    WHY NOT A PREDEFINED ATTRIBUTE TABLE: a shared list keeps naming consistent and
    can drive filters, but it puts a setup step in front of the first product. This
    is deliberately the free-form version — type any name and value on any product.
    The cost is that "Model No." and "Model Number" are different attributes as far
    as the database is concerned, so if you later want filtering, normalise the names
    first.

    Values are stored as text, always. "220V", "2-3 days", "approx. 5kg" and "12"
    are all things people legitimately write in a spec line, and coercing them to
    numbers would reject most of them.
    """

    product = models.ForeignKey(
        Product,
        related_name='attributes',
        on_delete=models.CASCADE,
    )

    # e.g. "Model", "Model Number", "Material", "Colour"
    name = models.CharField(max_length=100)

    # e.g. "ST-128PlusMax", "Stainless steel"
    value = models.CharField(max_length=500)

    # Display order within a product. The editor writes the row's position here so
    # the operator controls the order specs are read in — an alphabetical list would
    # put "Warranty" above "Model", which is not how anyone reads a spec sheet.
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        # sort_order first, then id so rows added in one save keep a stable order
        # rather than shuffling between page loads when several share a sort_order.
        ordering = ['sort_order', 'id']
        verbose_name = 'Product Attribute'
        verbose_name_plural = 'Product Attributes'
        indexes = [
            models.Index(fields=['product', 'sort_order']),
        ]

    def __str__(self):
        return f'{self.name}: {self.value}'


class PriceAdjustment(models.Model):
    """
    A record of one bulk price change: who, when, how much, and over what.

    WHY A TABLE RATHER THAN THE AUDIT LOG: adjustments are already written to
    AuditLog, but that stores a sentence. Answering "how many times have prices
    moved this month, and by how much" from prose means parsing it back out, and
    the answer would break the first time the wording changed. These columns are
    queryable.

    THIS DOES NOT AFFECT PLACED ORDERS. OrderItem stores the unit price on the
    line at checkout, so an order raised at ¥5 stays at ¥5 however often the
    product's price moves afterwards. That is a property of the order model, not
    something this log enforces — it is recorded here because it is the first
    question anyone asks when they see a price-change history.
    """

    SCOPE_SELECTED = 'selected'
    SCOPE_ALL = 'all'
    SCOPE_CATEGORY = 'category'
    SCOPE_CHOICES = [
        (SCOPE_SELECTED, 'Selected products'),
        (SCOPE_ALL, 'Whole catalogue'),
        (SCOPE_CATEGORY, 'By category'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,                      # NULL = the account was deleted since
        on_delete=models.SET_NULL,
        related_name='price_adjustments',
    )

    # Signed: positive raised prices, negative lowered them.
    percentage = models.DecimalField(max_digits=7, decimal_places=2)

    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_SELECTED)
    # Human-readable target, e.g. "Home & Kitchen" or "12 selected".
    scope_label = models.CharField(max_length=200, blank=True, default='')

    products_affected = models.PositiveIntegerField(default=0)
    variants_affected = models.PositiveIntegerField(default=0)

    # The summed catalogue price before and after, so the log answers "how much
    # did this move" in money rather than only in percent. A percentage alone
    # cannot be compared across runs of different sizes.
    total_before = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_after = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # Whether private products were left alone. Recorded because it changes what
    # the counts above mean.
    excluded_private = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Price Adjustment'
        verbose_name_plural = 'Price Adjustments'

    def __str__(self):
        sign = '+' if self.percentage > 0 else ''
        return f'{sign}{self.percentage}% on {self.products_affected} product(s)'

    @property
    def difference(self):
        """Money added to (or taken off) the catalogue's summed price."""
        return self.total_after - self.total_before
