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
from django.db import models


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

    class Meta:
        """
        Meta options for the Product model.
        """
        # Add composite indexes for common query patterns
        indexes = [
            models.Index(fields=['is_draft', 'is_private', 'name']),
            models.Index(fields=['is_draft', 'is_private']),
            models.Index(fields=['source', 'is_draft', 'is_private']),
        ]

    def __str__(self):
        """
        Returns the human-readable name of the product.

        Django uses __str__ for displaying the object in admin dropdowns, list views,
        and debugging. Showing the product name makes it easy to identify.

        Returns:
            str: The product's name.
        """
        return self.name


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
    image = models.ImageField(upload_to='product_images/')

    def __str__(self):
        """
        Returns a descriptive string indicating which product this image belongs to.

        Returns:
            str: A string like "Image for Wireless Headphones".
        """
        # f-string embedding the product name for clear identification in admin lists.
        return f"Image for {self.product.name}"
