"""
portal/models.py

This module defines the database models for the Customer Portal app in a Django logistics management system.

The Portal app manages the public-facing website and customer-facing portal features:
1. ProductRequest — Customers submit product sourcing requests (e.g., "I found this on Alibaba, can you source it?")
2. ProductRequestImage — Images attached to a product request (reference photos, screenshots, etc.)
3. PortfolioItem — Media (images/videos) shown on the homepage and portfolio page to showcase the business.

Business Context:
    The customer portal allows registered customers to:
    - Browse their assigned products and place orders
    - Submit product sourcing requests (if they want a product not in the catalog)
    - View their order history, invoices, and payment status
    - Track shipments

    The portfolio/public pages attract new customers by showing past work, products, and capabilities.
"""

# Import Django's ORM models for database field definitions
from django.db import models

# Import Decimal for precise financial calculations in the cart subtotal property
from decimal import Decimal

# Import timezone utility for timestamp fields that need the current time as default
from django.utils import timezone

# Import reverse URL resolver. Used by models to generate URLs for their detail pages.
from django.urls import reverse

# Import Customer model. Product requests are submitted by customers.
from customers.models import Customer

# Import Product model. ProductRequests may eventually be converted into Products.
from products.models import Product

# Import secrets for generating secure random tokens
import secrets


class PasswordResetRequest(models.Model):
    """
    Represents a password reset request submitted by a customer.

    When a customer forgets their password, they can request a reset link via email.
    This model stores the reset token, the email address, creation time, and usage status.
    The token is a cryptographically secure random string that is sent to the customer
    via email (or displayed inline in a teaching/demo context). The customer uses the
    token to verify their identity and set a new password.

    Attributes:
        email (str): The email address of the customer requesting the reset.
        token (str): A cryptographically secure random token used to verify the request.
        created_at (datetime): When the reset request was created. Used to enforce expiry.
        is_used (bool): Whether this token has already been used to reset a password.

    Business Logic:
        Password reset tokens expire after 24 hours for security. Each token can only
        be used once (is_used=True after consumption). We store the email rather than
        a ForeignKey to Customer because the customer might not exist (e.g., typo in email)
        and we want to handle that gracefully without database integrity errors.
    """

    # EmailField: the customer's email address. Not a ForeignKey to Customer because
    # we want to handle cases where the email doesn't exist in the system (to prevent
    # email enumeration attacks, we still show a success message even if the email is unknown).
    email = models.EmailField(help_text="Email address of the customer requesting a password reset")

    # CharField: the secure random token. 64 characters provides plenty of entropy.
    # The token is generated automatically in the save() method if not provided.
    token = models.CharField(max_length=64, unique=True, help_text="Secure random token for verification")

    # DateTimeField: when the request was created. Used to enforce a 24-hour expiry window.
    created_at = models.DateTimeField(default=timezone.now, help_text="When the reset request was created")

    # BooleanField: tracks whether this token has been consumed. Prevents replay attacks.
    is_used = models.BooleanField(default=False, help_text="Whether this token has already been used")

    class Meta:
        """
        Meta options for the PasswordResetRequest model.
        """
        # ordering = ['-created_at'] means newest requests appear first in the admin list.
        ordering = ['-created_at']

        # Human-readable names for the Django admin interface.
        verbose_name = 'Password Reset Request'
        verbose_name_plural = 'Password Reset Requests'

    def __str__(self):
        """
        Returns a human-readable identifier for this password reset request.

        Returns:
            str: A string like "Reset for john@example.com (Pending)" showing the email
                 and whether the token has been used.
        """
        status = 'Used' if self.is_used else 'Pending'
        return f"Reset for {self.email} ({status})"

    def save(self, *args, **kwargs):
        """
        Overrides the default save method to auto-generate a secure token if none is provided.

        We use secrets.token_urlsafe(32) which generates a 43-character URL-safe random string
        with sufficient entropy for cryptographic purposes. This is more secure than
        Django's default random string generators because it uses the operating system's
        CSPRNG (Cryptographically Secure Pseudo-Random Number Generator).
        """
        if not self.token:
            # token_urlsafe(32) generates a string with ~32 bytes of entropy (~43 chars).
            # We store it in a 64-char field to leave room for future larger tokens.
            self.token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        """
        A computed property that checks whether this token has expired.

        Tokens are valid for 24 hours from creation. After that, they are considered
        expired and cannot be used to reset a password. This is a security measure
        to prevent old tokens from being exploited if they are intercepted.

        Returns:
            bool: True if the token is older than 24 hours, False otherwise.
        """
        expiry = self.created_at + timezone.timedelta(hours=24)
        return timezone.now() > expiry

    def mark_used(self):
        """
        Marks this token as used, preventing any further password resets with it.

        This method should be called immediately after a successful password reset
        to ensure the token cannot be reused (replay attack prevention).
        """
        self.is_used = True
        self.save(update_fields=['is_used'])


class ProductRequest(models.Model):
    """
    Represents a customer's request for a product that is not currently in the catalog.

    In a logistics business, customers often find products on sites like Alibaba, 1688, or Amazon
    and ask the logistics company: "Can you source this for me?" This model tracks those requests
    from submission through quoting to conversion into a real catalog product.

    Status Flow:
        pending → quoted → converted (or rejected)
        1. Customer submits a request with name, description, link, and quantity.
        2. Admin reviews and researches the product (checks supplier, pricing, availability).
        3. Admin may add notes and either reject the request or quote a price.
        4. If accepted, the admin creates a Product and links it via converted_product.
        5. Status changes to 'converted' and the customer can now order it.

    Attributes:
        customer (Customer): The customer who submitted this request.
        name (str): Product name or description provided by the customer.
        description (str, optional): Additional details about the product.
        product_link (str, optional): URL to the product on a supplier site (e.g., Alibaba, 1688).
        requested_quantity (int): How many units the customer estimates they need.
        status (str): Current state of the request — pending, quoted, rejected, or converted.
        admin_notes (str, optional): Internal notes for the admin team.
        converted_product (Product, optional): The Product record created from this request.
        created_at (datetime): When the request was submitted.
        updated_at (datetime): When the request was last modified (auto-updated).

    Business Logic:
        This workflow allows the logistics company to expand its catalog based on customer demand.
        Instead of the admin guessing what products to stock, they respond to direct customer requests.
        The status tracking ensures nothing falls through the cracks, and the converted_product link
        preserves the history: "Product X was originally requested by Customer Y on Date Z."
    """

    # STATUS_CHOICES defines the four stages of a product request lifecycle.
    # Each tuple is (database_value, display_label).
    STATUS_CHOICES = [
        ('pending', 'Pending'),      # Request submitted, waiting for admin review.
        ('quoted', 'Quoted'),          # Admin has researched and provided a price quote.
        ('rejected', 'Rejected'),      # Admin cannot source this product or it's not viable.
        ('converted', 'Converted to Product'),  # Admin created a Product record; customer can now order.
    ]

    # ForeignKey to Customer: each request belongs to one customer.
    # on_delete=models.CASCADE: if the customer is deleted, their requests are also deleted.
    # related_name='product_requests': allows reverse lookup: customer.product_requests.all()
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='product_requests',
    )

    # CharField for the product name or description. The customer may not know the exact product name,
    # so help_text guides them to provide a name or description.
    name = models.CharField(max_length=255, help_text="Product name or description")

    # TextField for additional details. The customer can describe specs, colors, sizes, etc.
    # blank=True means it's optional.
    description = models.TextField(blank=True, help_text="Additional details about the product")

    # URLField validates that the input is a valid URL. The customer can paste a link to the product
    # on Alibaba, 1688, Amazon, etc. This helps the admin find the exact product.
    # blank=True, null=True means the link is optional (the customer might not have a URL).
    product_link = models.URLField(blank=True, null=True, help_text="Link to product (e.g., Alibaba, 1688)")

    # PositiveIntegerField for the estimated quantity the customer wants.
    # Default is 1. This helps the admin estimate costs and MOQ feasibility.
    requested_quantity = models.PositiveIntegerField(default=1, help_text="Estimated quantity needed")

    # Status field with choices. Default is 'pending' because all new requests start in review.
    # The status is updated by the admin as they process the request.
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
    )

    # Admin fills these fields when processing the request. They are not visible to the customer.
    # admin_notes is for internal communication (e.g., "Check with supplier XYZ", "Waiting for MOQ confirmation").
    admin_notes = models.TextField(blank=True, help_text="Internal notes for admin")

    # converted_product links to the Product record created when the admin decides to add this item to the catalog.
    # on_delete=models.SET_NULL: if the Product is deleted, this field becomes NULL instead of deleting the request.
    # This preserves the request history even if the product is later removed from the catalog.
    # null=True, blank=True means it's optional (not all requests become products).
    converted_product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='from_request',
        help_text="The product created from this request",
    )

    # default=timezone.now: when the request is created, this is set to the current time.
    # This is a static default (not auto_now_add), so it captures the time at creation.
    created_at = models.DateTimeField(default=timezone.now)

    # auto_now=True: Django automatically updates this field to the current time EVERY time the model is saved.
    # This tracks the last modification time (e.g., when status was updated from pending to quoted).
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """
        Meta options for the ProductRequest model.
        """
        # ordering = ['-created_at'] means newest requests appear first in lists and admin.
        # This helps the admin see the most recent submissions immediately.
        ordering = ['-created_at']

        # Human-readable names for the Django admin interface.
        verbose_name = 'Product Request'
        verbose_name_plural = 'Product Requests'

    def __str__(self):
        """
        Returns a human-readable identifier for this product request.

        Returns:
            str: A string like "#42 - Wireless Headphones (ABC Trading)" showing the ID,
                 product name, and customer name.
        """
        # f-string with the request ID, product name, and customer name for quick identification.
        return f"#{self.id} - {self.name} ({self.customer.name})"

    def get_status_display_class(self):
        """
        Returns a Bootstrap CSS class name corresponding to the request status.

        This method is used in templates to color-code status badges:
        - pending → yellow (warning)
        - quoted → blue (info)
        - rejected → red (danger)
        - converted → green (success)

        Returns:
            str: A Bootstrap contextual class name (e.g., 'warning', 'success').

        Business Logic:
            In the admin dashboard and customer portal, status badges help users quickly understand
            the state of each request. Bootstrap's badge classes provide consistent color coding.
            If the status is unknown, it falls back to 'secondary' (gray).
        """
        # Dictionary mapping each status to a Bootstrap CSS class for visual indication.
        mapping = {
            'pending': 'warning',   # Yellow — needs attention, admin should review.
            'quoted': 'info',       # Blue — admin has responded, waiting for customer.
            'rejected': 'danger',   # Red — cannot be fulfilled, customer should be informed.
            'converted': 'success', # Green — fully processed, product is now available.
        }
        # dict.get() returns the mapped value if found, otherwise 'secondary' (gray fallback).
        return mapping.get(self.status, 'secondary')


class ProductRequestImage(models.Model):
    """
    Represents an image uploaded for a ProductRequest.

    When a customer submits a product request, they often include reference images:
    screenshots from Alibaba, photos of the desired item, packaging examples, etc.
    Admins may also upload images (e.g., supplier photos, sample photos) during processing.

    Attributes:
        request (ProductRequest): The product request this image belongs to.
        image (ImageField): The actual image file.
        uploaded_by (str): Indicates whether the customer or the admin uploaded this image.
        uploaded_at (datetime): When the image was uploaded.

    Business Logic:
        Images help the admin understand exactly what the customer wants. A customer might say
        "Wireless Headphones" but the image shows a specific model. This reduces confusion
        and sourcing errors. Tracking who uploaded each image helps the admin know whether
        it's a customer reference or an admin-provided update.
    """

    # ForeignKey to ProductRequest: each image belongs to one request.
    # on_delete=models.CASCADE: if the request is deleted, all its images are also deleted.
    # related_name='images': allows reverse access: request.images.all()
    request = models.ForeignKey(
        ProductRequest,
        on_delete=models.CASCADE,
        related_name='images',
    )

    # ImageField for the uploaded image file. Django handles file storage and upload.
    # upload_to='request_images/': images are saved in the MEDIA_ROOT/request_images/ directory.
    image = models.ImageField(upload_to='request_images/')

    # CharField with choices tracking who uploaded the image. Default is 'customer'.
    # This helps the admin identify the source of each image in the request timeline.
    uploaded_by = models.CharField(
        max_length=10,
        choices=[('customer', 'Customer'), ('admin', 'Admin')],
        default='customer',
    )

    # default=timezone.now: sets the upload time to the current moment when the image is created.
    # This timestamps each image for chronological display in the request timeline.
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        """
        Meta options for the ProductRequestImage model.
        """
        # ordering = ['uploaded_at'] means images are shown in chronological order (oldest first).
        # This creates a natural timeline as the customer and admin exchange images.
        ordering = ['uploaded_at']

    def __str__(self):
        """
        Returns a human-readable description of this image.

        Returns:
            str: A string like "Image for Request #42" indicating which request this image belongs to.
        """
        return f"Image for Request #{self.request.id}"


class PortfolioItem(models.Model):
    """
    Represents a media item (image or video) displayed on the public website.

    Portfolio items showcase the logistics company's products, capabilities, and past work
    to attract new customers. They appear on the homepage and a dedicated portfolio page.

    Attributes:
        title (str): The title displayed on the portfolio card.
        description (str, optional): Short text shown below the title.
        media_type (str): 'image' or 'video' — determines how the file is rendered.
        file (FileField): The uploaded image or video file.
        is_active (bool): Whether this item is visible on the website.
        display_order (int): Controls the sort order (lower = shown first).
        created_at (datetime): When this item was added to the portfolio.
        updated_at (datetime): When this item was last modified.

    Business Logic:
        The logistics company uses its website to attract new customers. Portfolio items show
        product photos, warehouse videos, packaging examples, and customer testimonials in visual form.
        The display_order field lets the admin control which items appear first (e.g., bestsellers
        or most impressive work at the top). is_active allows temporarily hiding items without deleting them.
    """

    # MEDIA_CHOICES defines the two types of media supported in the portfolio.
    MEDIA_CHOICES = [
        ('image', 'Image'),  # Static image file (JPG, PNG, etc.)
        ('video', 'Video'),  # Video file (MP4, etc.)
    ]

    # CharField for the display title. This is the headline shown on the portfolio card.
    # The title should be catchy and descriptive to attract potential customers.
    title = models.CharField(max_length=255, help_text="Title displayed on the card")

    # TextField for a short description. Shown below the title on the portfolio card.
    # blank=True means it's optional — some images may speak for themselves without text.
    description = models.TextField(blank=True, help_text="Short description shown below the title")

    # CharField with choices for the media type. Default is 'image'.
    # The template uses this to decide whether to render an <img> tag or a <video> tag.
    media_type = models.CharField(
        max_length=10,
        choices=MEDIA_CHOICES,
        default='image',
    )

    # FileField: a generic file upload field that accepts both images and videos.
    # upload_to='portfolio/%Y/%m/': organizes files into year/month subfolders (e.g., portfolio/2024/06/).
    # This prevents a single folder from getting too crowded and makes backup easier.
    file = models.FileField(
        upload_to='portfolio/%Y/%m/',
        help_text="Upload an image or video file"
    )

    # Boolean flag controlling visibility. Only active items are shown on the public website.
    # This allows the admin to prepare items in advance and activate them when ready.
    is_active = models.BooleanField(default=True, help_text="Only active items are shown on the website")

    # PositiveIntegerField for sort order. Default is 0.
    # Lower numbers appear first. The admin can use 0, 10, 20, 30... to leave room for reordering.
    display_order = models.PositiveIntegerField(default=0, help_text="Lower number = shown first")

    # auto_now_add=True: records the creation time when the item is first added to the portfolio.
    created_at = models.DateTimeField(auto_now_add=True)

    # auto_now=True: updates the timestamp every time the item is saved (e.g., title changed, reordered).
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """
        Meta options for the PortfolioItem model.
        """
        # ordering: first by display_order (ascending — lower numbers first),
        # then by -created_at (newest first) as a tiebreaker for items with the same order.
        ordering = ['display_order', '-created_at']

        # Human-readable names for the Django admin sidebar.
        verbose_name = 'Portfolio Item'
        verbose_name_plural = 'Portfolio Items'

    def __str__(self):
        """
        Returns the title of the portfolio item.

        Returns:
            str: The title string (used in admin lists and dropdowns).
        """
        return self.title

    @property
    def is_image(self):
        """
        A computed property that checks if this portfolio item is an image.

        The @property decorator allows accessing this as an attribute: item.is_image
        instead of calling it as a method: item.is_image().

        Returns:
            bool: True if media_type is 'image', False otherwise.

        Template Usage:
            In templates, this is used to decide rendering:
            {% if item.is_image %}<img src="...">{% else %}<video src="...">{% endif %}
        """
        # Simple string comparison against the 'image' choice value.
        return self.media_type == 'image'

    @property
    def is_video(self):
        """
        A computed property that checks if this portfolio item is a video.

        Returns:
            bool: True if media_type is 'video', False otherwise.

        Template Usage:
            Complementary to is_image. Used for conditional rendering in templates.
        """
        return self.media_type == 'video'

    @property
    def file_extension(self):
        """
        A computed property that extracts the file extension from the uploaded file's name.

        Returns:
            str: The lowercase file extension (e.g., 'jpg', 'mp4', 'png') or empty string if unknown.

        Business Logic:
            Sometimes the template or view needs to know the file type for additional processing
            (e.g., showing a PDF icon, validating file types, or generating thumbnails).
            This property extracts the extension safely even if the filename has multiple dots.
        """
        # Check if the file exists and has a name attribute.
        if self.file and self.file.name:
            # rsplit('.', 1) splits from the right at most once, giving [filename, extension].
            # Example: "my.video.file.mp4" → ["my.video.file", "mp4"]
            parts = self.file.name.rsplit('.', 1)
            # If there was exactly one dot and we got 2 parts, return the extension in lowercase.
            if len(parts) == 2:
                return parts[1].lower()
        # If no file, no name, or no extension, return an empty string.
        return ''


class CartItem(models.Model):
    """
    Represents an item in a customer's shopping cart.

    In the customer portal, customers can browse their assigned products and add them
    to a cart before proceeding to checkout. This model supports both logged-in customers
    (linked via ForeignKey to Customer) and session-based guests (linked via session_key).

    Attributes:
        customer (Customer, optional): The logged-in customer who owns this cart item.
        session_key (str, optional): The Django session key for guests who haven't logged in.
        product (Product): The product being added to the cart.
        quantity (int): How many units the customer wants to order.
        created_at (datetime): When the item was added to the cart.
        updated_at (datetime): When the item was last modified (e.g., quantity changed).

    Business Logic:
        The cart is the bridge between browsing and ordering. Customers add products they want
        to order, adjust quantities, and then proceed to checkout. Each cart item is linked to
        a product, so the price and specs are always current. When the customer checks out,
        cart items are converted into OrderItems and the cart is cleared.
    """

    # ForeignKey to Customer: links the cart item to a registered customer.
    # null=True, blank=True means guests can also have cart items (tracked by session_key).
    # on_delete=models.CASCADE: if the customer is deleted, their cart items are also deleted.
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='cart_items',
        help_text="The logged-in customer who owns this cart item"
    )

    # CharField for the Django session key. Used when the user is not logged in.
    # db_index=True makes lookups by session key fast.
    # blank=True means it's optional (only used for guest sessions).
    session_key = models.CharField(
        max_length=40,
        blank=True,
        db_index=True,
        help_text="Django session key for guest carts"
    )

    # ForeignKey to Product: each cart item references exactly one product.
    # on_delete=models.CASCADE: if the product is deleted, remove it from carts too.
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='cart_entries',
        help_text="The product in the cart"
    )

    # PositiveIntegerField: how many units the customer wants to order.
    # Default is 1. The checkout view validates against the product's MOQ.
    quantity = models.PositiveIntegerField(default=1, help_text="Number of units to order")

    # Label information collected during checkout for ready-to-ship marketplace products.
    # These are copied to the OrderItem when the order is placed.
    label_mark = models.CharField(max_length=100, blank=True, default='', help_text="Product label mark")
    carton_mark = models.CharField(max_length=100, blank=True, default='', help_text="Carton label mark")
    carton_asn = models.CharField(max_length=100, blank=True, default='', help_text="Carton ASN number")
    carton_quantity = models.PositiveIntegerField(default=1, help_text="Number of cartons")

    # Uploaded label files for ready-to-ship marketplace products.
    shipping_label = models.FileField(
        upload_to='cart_labels/shipping/%Y/%m/',
        blank=True, null=True,
        help_text="Customer-uploaded shipping label file"
    )
    carton_label = models.FileField(
        upload_to='cart_labels/carton/%Y/%m/',
        blank=True, null=True,
        help_text="Customer-uploaded carton label file"
    )

    # auto_now_add=True: records the time when the item was first added to the cart.
    created_at = models.DateTimeField(auto_now_add=True)

    # auto_now=True: updates the timestamp every time the quantity is changed.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """
        Meta options for the CartItem model.
        """
        # ordering = ['-created_at'] means newest items appear first in the cart.
        ordering = ['-created_at']

        # Human-readable names for the Django admin sidebar.
        verbose_name = 'Cart Item'
        verbose_name_plural = 'Cart Items'

    def __str__(self):
        """
        Returns a human-readable description of this cart item.

        Returns:
            str: A string like "CartItem: Wireless Headphones x 5 (James Chen)".
        """
        owner = self.customer.name if self.customer else f"Guest ({self.session_key[:8]}...)"
        return f"CartItem: {self.product.name} x {self.quantity} ({owner})"

    @property
    def subtotal(self):
        """
        A computed property that calculates the line subtotal for this cart item.

        Returns:
            Decimal: product.price × quantity, rounded to 2 decimal places.

        Business Logic:
            The subtotal is the per-line cost before shipping, taxes, or commissions.
            It is computed dynamically from the product's current price, so if the admin
            changes the price between cart-add and checkout, the customer sees the updated price.
        """
        # Decimal multiplication to avoid floating-point errors in money calculations.
        return (self.product.price * self.quantity).quantize(Decimal('0.01'))


class ContactMessage(models.Model):
    """
    Stores a message submitted through the public "Contact Us" form.

    When a visitor fills out the contact form on the marketing site, this model
    preserves the submission so admins can review, follow up, and track inbound
    leads without relying solely on email notifications.

    Attributes:
        name (str): Full name of the person contacting the company.
        email (str): Email address for replies.
        phone (str, optional): Phone or WhatsApp number.
        subject (str, optional): Subject line or lead source tag.
        message (str): The actual message content.
        is_read (bool): Whether an admin has reviewed this message.
        created_at (datetime): When the message was submitted.
    """

    name = models.CharField(max_length=200, help_text="Full name of the sender")
    email = models.EmailField(help_text="Email address for replies")
    phone = models.CharField(max_length=50, blank=True, help_text="Phone or WhatsApp number")
    subject = models.CharField(max_length=255, blank=True, help_text="Subject or lead source")
    message = models.TextField(help_text="Message content")
    is_read = models.BooleanField(default=False, help_text="Whether an admin has reviewed this message")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Meta options for the admin interface."""
        ordering = ['-created_at']
        verbose_name = 'Contact Message'
        verbose_name_plural = 'Contact Messages'

    def __str__(self):
        """Return a short identifier used in Django admin lists."""
        return f"Message from {self.name} — {self.email}"

    def mark_read(self):
        """Mark the message as reviewed by an admin."""
        self.is_read = True
        self.save(update_fields=['is_read'])
