"""
orders/models.py

This module defines the database models for the Orders app in a Django logistics management system.

The Orders app is the core of the logistics business. It tracks every customer order from creation
through shipping and delivery. An order contains products, shipping details, costs, and payment status.

Models:
    - Order: The main order record linking a customer to their purchase with shipping and payment info.
    - OrderItem: An individual product line within an order (e.g., "100x Wireless Headphones").
    - OrderExtraCost: Additional costs added to an order (e.g., customs fees, inspection fees).
    - OrderNote: A chat/notes system for admins and customers to communicate about an order.
    - Notification: In-app notifications for users and customers about order updates.

Business Concepts:
    - Shipping Methods: manual (admin calculates), air (fast, per KG), sea (slow, per CBM), KSA variants.
    - Cargo Types: standard (normal goods) vs. no_brand_battery (special handling for batteries).
    - Payment Status: unpaid, partial, or fully paid.
    - Order Status: draft (being prepared) or confirmed (sent to supplier).
"""

# Decimal is required for the money math in OrderItem.subtotal.
from decimal import Decimal

# Import Django's ORM models for defining database tables and fields
from django.db import models

# Import the Customer model from the customers app. This is a ForeignKey relationship:
# each order belongs to exactly one customer, but a customer can have many orders.
from customers.models import Customer

# Import the Product model from the products app. OrderItems reference products.
from products.models import Product

# Import ShippingCompany from settings_manager. Orders and OrderItems need to know
# which shipping company handles the freight.
from settings_manager.models import ShippingCompany

# Import Django's built-in User model for Notification admin links
from django.contrib.auth.models import User


# --- Choice Constants ---
# In Django, choices are defined as lists of tuples: (database_value, human_readable_label).
# The database stores the short code (e.g., 'air'), but forms and admin show the label (e.g., 'Air').
# Using constants improves code readability and prevents typos.

SHIPPING_METHOD_CHOICES = [
    # 'manual': The admin manually calculates or enters the shipping cost.
    # Used when the shipping company hasn't provided a rate, or the cost is negotiated.
    ('manual', 'Manual'),

    # 'air': International air freight. Charged per kilogram. Fast but expensive.
    # Typically used for urgent or lightweight shipments.
    ('air', 'Air'),

    # 'sea': International sea freight. Charged per CBM (cubic meter). Slower but cheaper.
    # Typically used for bulk, heavy shipments.
    ('sea', 'Sea'),

    # 'ksa_air': Air freight specifically to Saudi Arabia (KSA = Kingdom of Saudi Arabia).
    # May have different rates and routing than general air freight.
    ('ksa_air', 'KSA Air'),

    # 'ksa_sea': Sea freight specifically to Saudi Arabia.
    ('ksa_sea', 'KSA Sea'),

    # 'ksa': A general/default KSA shipping method. May be used for combined or unspecified KSA routes.
    ('ksa', 'KSA'),
]

# Cargo type determines how goods are handled. Some items (like batteries) require special
# documentation, packaging, and shipping company approval due to safety regulations.
CARGO_TYPE_CHOICES = [
    # 'standard': Normal goods without hazardous material restrictions.
    ('standard', 'Standard'),

    # 'no_brand_battery': No-brand (generic/unbranded) batteries. These are treated as hazardous goods
    # and may require special shipping rates, different shipping companies, and extra paperwork.
    ('no_brand_battery', 'No Brand Battery'),
]

# Payment status tracks whether the customer has paid for their order.
# Logistics companies often require partial or full payment before shipping.
PAYMENT_STATUS_CHOICES = [
    ('unpaid', 'Unpaid'),      # Customer hasn't paid anything yet.
    ('partial', 'Partial'),    # Customer paid a deposit or part of the total.
    ('paid', 'Paid'),          # Full payment received.
]

# User type choices for OrderNote to distinguish between admin and customer messages
USER_TYPE_CHOICES = [
    ('admin', 'Admin'),
    ('customer', 'Customer'),
]

# Notification type choices for categorizing in-app notifications
NOTIFICATION_TYPE_CHOICES = [
    ('order_status', 'Order Status'),
    ('payment', 'Payment'),
    ('shipment', 'Shipment'),
    ('note', 'Note'),
    ('system', 'System'),
]



class Order(models.Model):
    """
    Represents a customer order in the logistics system.

    This is the central model of the business. An order records:
    - WHO placed it (customer)
    - WHAT was ordered (via OrderItem records)
    - HOW it ships (method, company, cargo type)
    - HOW MUCH it costs (product total + shipping + commission + extras)
    - PAYMENT status (unpaid, partial, paid)
    - STATUS (draft = still being prepared, confirmed = placed with supplier)

    Attributes:
        customer (Customer): The client who placed this order.
        date (datetime): When the order was created in the system.
        total (Decimal): Grand total amount including all costs.
        commission_amount (Decimal): Calculated commission fee for this order.
        commission_percentage (Decimal): The commission rate applied (e.g., 5.00 means 5%).
        cargo_type (str): Standard or No Brand Battery (affects shipping rules).
        shipping_method (str): Air, Sea, KSA Air, KSA Sea, or Manual.
        shipping_rate (Decimal): The rate used to calculate shipping cost (e.g., per KG or per CBM).
        shipping_cost (Decimal): Total calculated shipping cost for the entire order.
        shipping_companies (ManyToManyField): One or more companies handling this shipment.
        other_cost (Decimal): Miscellaneous additional cost (e.g., packaging, customs).
        other_cost_reason (str): Explanation of what the other_cost is for.
        total_weight (Decimal): Sum of all item weights in KG (used for air freight).
        total_cbm (Decimal): Sum of all item volumes in cubic meters (used for sea freight).
        status (str): 'draft' or 'confirmed' — whether the order is finalized.
        payment_status (str): 'unpaid', 'partial', or 'paid'.
        is_placed (bool): Whether the admin has already submitted this order to the supplier.
        notes (str): Free-text admin notes about the order.
        show_shipping_details (bool): Whether the customer can see shipping breakdown in their portal.

    Business Logic:
        When an order is created, it starts as a draft. The admin adds products (OrderItems),
        selects shipping method, and the system calculates totals. Once confirmed, the order
        is sent to the supplier for fulfillment. The logistics company then arranges shipping
        and updates the customer through the portal.
    """

    # Define status constants as class attributes for clean code.
    # These are used in views, templates, and admin logic instead of raw strings.
    STATUS_DRAFT = 'draft'
    STATUS_CONFIRMED = 'confirmed'

    # STATUS_CHOICES is a list of (value, display_label) tuples used by the status field.
    # Using class constants here means views can check: if order.status == Order.STATUS_DRAFT:
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),       # Order is being prepared, not yet sent to supplier.
        (STATUS_CONFIRMED, 'Confirmed'),  # Order is finalized and placed with the supplier.
    ]

    # ForeignKey: Many orders can belong to one customer. on_delete=models.CASCADE means
    # if a customer is deleted, all their orders are also deleted. This prevents orphaned orders.
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, db_index=True)

    # auto_now_add=True: Automatically sets the field to the current date and time when the
    # Order object is FIRST created. It never changes after that. This tracks when the order was placed.
    date = models.DateTimeField(auto_now_add=True, db_index=True)

    # DecimalField for the grand total of the order (product costs + shipping + commission + extras).
    # Default is 0. Calculated by the business logic in views, not by the database.
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Commission is a fee the logistics company charges on top of the product cost.
    # commission_amount is the actual money value (e.g., $50.00).
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # commission_percentage is the rate used to calculate the commission (e.g., 5.00 = 5%).
    # The actual calculation might be: commission_amount = (product_subtotal × commission_percentage) / 100
    commission_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # cargo_type uses the CARGO_TYPE_CHOICES defined above. Default is 'standard'.
    # This affects which shipping rates apply (e.g., no-brand battery rates are different).
    cargo_type = models.CharField(max_length=30, choices=CARGO_TYPE_CHOICES, default='standard')

    # shipping_method uses the SHIPPING_METHOD_CHOICES defined above. Default is 'manual'.
    # The admin selects the shipping method, and the system applies the appropriate rate.
    shipping_method = models.CharField(max_length=20, choices=SHIPPING_METHOD_CHOICES, default='manual')

    # The shipping rate per unit (e.g., $5.00 per KG for air, or $100 per CBM for sea).
    # This rate is multiplied by total_weight or total_cbm to get shipping_cost.
    shipping_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # The total shipping cost calculated from rate × weight or rate × CBM.
    # This is the amount the customer pays for freight.
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ManyToManyField: An order can involve multiple shipping companies, and a shipping company
    # can handle many orders. This allows splitting shipments or using backup carriers.
    # blank=True means no shipping company is required (e.g., for draft orders).
    shipping_companies = models.ManyToManyField(ShippingCompany, blank=True, verbose_name='Shipping Companies')

    # Other cost is a catch-all for miscellaneous fees (customs, inspection, repackaging, etc.).
    other_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # A text explanation of what the other_cost represents. Shown to the customer if shipping details are visible.
    other_cost_reason = models.CharField(max_length=255, blank=True, default='')

    # Total weight of the entire order in kilograms. Sum of all OrderItem weights.
    # Used for air freight calculations (air = per KG).
    total_weight = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name='Total Weight (KG)')

    # Total CBM (Cubic Meters) of the entire order. Sum of all OrderItem volumes.
    # Used for sea freight calculations (sea = per CBM). CBM = (L×W×H in cm) / 1,000,000.
    total_cbm = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name='Total CBM')

    # Order status: 'draft' (being prepared) or 'confirmed' (finalized and placed).
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CONFIRMED, db_index=True)

    # Payment tracking: has the customer paid? This helps the admin manage cash flow and collections.
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='unpaid')

    # is_placed indicates whether the admin has actually submitted this order to the supplier.
    # It's possible for an order to be "confirmed" in the system but not yet placed with the supplier.
    is_placed = models.BooleanField(default=False, verbose_name='Placed with Supplier')

    # Free-text notes for internal admin use. Not shown to the customer unless explicitly configured.
    notes = models.TextField(blank=True, default='')

    # Controls customer portal visibility. If True, the customer can see shipping cost breakdown
    # (rate, weight, CBM, etc.) in their order view. If False, they only see the total.
    show_shipping_details = models.BooleanField(default=True, verbose_name='Show Shipping Details to Customer')

    class Meta:
        """
        Meta options for the Order model.
        """
        # Add a composite index on (customer, status) for fast filtered lookups by customer order status.
        indexes = [
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['customer', 'date']),
            models.Index(fields=['status', 'date']),
        ]

    def __str__(self):
        """
        Returns a human-readable identifier for this order.

        Returns:
            str: A string like "Order #42 - ABC Trading", showing the order ID and customer name.
        """
        # self.id is the auto-generated primary key. Every Order gets a unique number automatically.
        return f"Order #{self.id} - {self.customer.name}"

    @property
    def has_ready_to_ship_labels(self):
        """
        Returns True if the order contains at least one ready-to-ship marketplace
        item (Amazon/Noon) with a shipping or carton label uploaded.
        """
        return any(
            item.product.ready_to_ship
            and item.product.source in {'amazon', 'noon'}
            and (item.shipping_label or item.carton_label)
            for item in self.items.select_related('product').all()
        )


class OrderItem(models.Model):
    """
    Represents a single product line within an Order.

    An order can contain multiple products. Each OrderItem is one row on the invoice:
    "Product X, Quantity 100, Price $5.00 each, Shipment 1, Air freight..."

    OrderItem also supports split shipments: a single order can have items shipped in
    multiple batches (different shipment numbers, different shipping companies, different methods).

    Attributes:
        order (Order): The parent order this line item belongs to.
        product (Product): The product being ordered.
        shipment_no (int): The shipment batch number (1, 2, 3...) for split deliveries.
        shipment_name (str): Optional label for this shipment batch (e.g., "Batch A").
        shipment_company (ShippingCompany): Which company handles this specific shipment batch.
        shipment_method (str): Shipping method for this specific batch (may differ from order default).
        cargo_type (str): Cargo type for this batch (standard or no-brand battery).
        shipment_cbm (Decimal): Volume of this shipment batch in cubic meters.
        shipment_weight (Decimal): Actual weight of this shipment batch in KG.
        shipment_volumetric_weight (Decimal): Volumetric weight for air freight (may differ from actual weight).
        shipment_shipping_cost (Decimal): Shipping cost for this specific batch.
        is_checked (bool): Admin checkbox to mark this item as verified/checked.
        quantity (int): How many units of this product were ordered.
        price (Decimal): The per-unit price at the time of order (may differ from current product price).

    Business Logic:
        When a customer orders, the admin creates an Order, then adds OrderItems for each product.
        Each OrderItem captures the price at the time of order (so historical orders remain accurate
        even if product prices change later). Items can be split into multiple shipments, allowing
        partial deliveries if some products are ready before others.
    """

    # ForeignKey to Order: each OrderItem belongs to exactly one Order.
    # related_name='items' allows reverse access: order.items.all() gives all line items for an order.
    # on_delete=models.CASCADE: if the Order is deleted, all its OrderItems are deleted too.
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)

    # ForeignKey to Product: each line item references one product from the catalog.
    # on_delete=models.CASCADE: if the Product is deleted, the OrderItem is also deleted.
    # Note: In practice, products should probably use PROTECT to preserve order history.
    product = models.ForeignKey(Product, on_delete=models.PROTECT, db_index=True)

    # Shipment number for split shipments. Default is 1 (all items in one shipment).
    # If an order is split, some items might have shipment_no=1 and others shipment_no=2.
    shipment_no = models.PositiveIntegerField(default=1)

    # Optional human-readable name for the shipment batch (e.g., "First Batch", "Air Part").
    shipment_name = models.CharField(max_length=100, blank=True, default='', verbose_name='Shipment Name')

    # The shipping company handling this specific shipment batch.
    # null=True, blank=True means it's optional. on_delete=models.SET_NULL means if the company
    # is deleted, this field becomes NULL instead of deleting the OrderItem (preserving order history).
    shipment_company = models.ForeignKey(ShippingCompany, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='Shipment Company')

    # The shipping method for this specific shipment. May differ from the order's overall method
    # if some items go by air and others by sea.
    shipment_method = models.CharField(max_length=20, choices=SHIPPING_METHOD_CHOICES, default='manual', verbose_name='Shipment Method')

    # The cargo type for this shipment. Needed because some products in an order might be standard
    # while others contain batteries, requiring different handling.
    cargo_type = models.CharField(max_length=30, choices=CARGO_TYPE_CHOICES, default='standard', verbose_name='Cargo Type')

    # CBM (Cubic Meters) for this specific shipment batch. Calculated from carton dimensions.
    shipment_cbm = models.DecimalField(max_digits=10, decimal_places=3, default=0)

    # Actual weight of this shipment batch in kilograms.
    shipment_weight = models.DecimalField(max_digits=10, decimal_places=3, default=0)

    # Volumetric weight for air freight. Airlines charge based on volumetric weight if it exceeds actual weight.
    # Formula: (L × W × H in cm) / 5000 (or 6000 depending on the airline).
    shipment_volumetric_weight = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name='Volumetric Weight (KG)')

    # The shipping cost specifically for this shipment batch. Allows per-batch cost tracking.
    shipment_shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Shipment Shipping Cost')

    # Admin verification flag. The admin can check this to mark the item as reviewed/verified.
    is_checked = models.BooleanField(default=False, verbose_name='Checked')

    # Label information for ready-to-ship marketplace products (Amazon/Noon).
    # Customers provide these during checkout; admins use them to generate or verify labels.
    label_mark = models.CharField(max_length=100, blank=True, default='', verbose_name='Label Mark')
    carton_mark = models.CharField(max_length=100, blank=True, default='', verbose_name='Carton Mark')
    carton_asn = models.CharField(max_length=100, blank=True, default='', verbose_name='Carton ASN')
    carton_quantity = models.PositiveIntegerField(default=1, verbose_name='Carton Quantity')

    # Uploaded label files for ready-to-ship marketplace products.
    shipping_label = models.FileField(
        upload_to='order_labels/shipping/%Y/%m/',
        blank=True, null=True,
        verbose_name='Shipping Label File'
    )
    carton_label = models.FileField(
        upload_to='order_labels/carton/%Y/%m/',
        blank=True, null=True,
        verbose_name='Carton Label File'
    )

    # PositiveIntegerField: quantity must be >= 1. No zero or negative quantities allowed.
    # This is the number of units ordered for this product line.
    quantity = models.PositiveIntegerField()

    # Price per unit at the time of ordering. This is a snapshot price.
    # If the product price changes later, this historical order remains accurate.
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        """
        Meta options for the OrderItem model.
        """
        # Add a composite index on (order, product) for fast lookups of items by order and product.
        indexes = [
            models.Index(fields=['order', 'product']),
            models.Index(fields=['order', 'shipment_no']),
        ]

    def __str__(self):
        """
        Returns a human-readable description of this line item.

        Returns:
            str: A string like "Wireless Headphones x 100", showing product name and quantity.
        """
        return f"{self.product.name} x {self.quantity}"

    @property
    def subtotal(self):
        """
        Returns the line subtotal (price × quantity) rounded to 2 decimals.
        """
        return (self.price * self.quantity).quantize(Decimal('0.01'))


class OrderExtraCost(models.Model):
    """
    Represents an additional cost added to an Order.

    Sometimes an order has extra fees that don't fit neatly into product or shipping costs.
    Examples: customs duty, inspection fees, repackaging costs, storage fees, or supplier charges.

    Attributes:
        order (Order): The order this extra cost applies to.
        amount (Decimal): The monetary value of the extra cost.
        reason (str): A description explaining what this cost is for.

    Business Logic:
        Extra costs are added by the admin after the order is created. They appear on the invoice
        and increase the total amount the customer must pay. Each extra cost has its own line item
        so the customer can see a transparent breakdown of all charges.
    """

    # ForeignKey to Order: each extra cost belongs to one order.
    # related_name='extra_costs' allows: order.extra_costs.all() to list all extra charges.
    # on_delete=models.CASCADE: if the order is deleted, its extra costs are also deleted.
    order = models.ForeignKey(Order, related_name='extra_costs', on_delete=models.CASCADE)

    # The amount of the extra cost. Default is 0. Can be any monetary value up to 99,999,999.99.
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # A text explanation of what the extra cost is for. Shown on the invoice for transparency.
    # blank=True, default='' means it's optional but stores an empty string if not provided.
    reason = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        """
        Meta options for OrderExtraCost.
        """
        # ordering = ['id'] means extra costs are listed in the order they were created.
        # This keeps the invoice consistent: items appear in the same order every time.
        ordering = ['id']

    def __str__(self):
        """
        Returns a human-readable string showing the reason and amount of the extra cost.

        Returns:
            str: A string like "Customs Duty: 150.00" or ": 0" if no reason was given.
        """
        return f"{self.reason}: {self.amount}"


class OrderNote(models.Model):
    """
    Represents a note or chat message attached to an Order.

    This model enables communication between admin staff and customers about a specific order.
    Each note records who wrote it (admin or customer), the message content, and when it was created.

    Attributes:
        order (Order): The parent order this note belongs to.
        user_type (str): 'admin' or 'customer' — identifies which side of the conversation wrote the note.
        message (str): The text content of the note.
        created_at (datetime): When the note was created (auto-set).

    Business Logic:
        Admins can add internal notes about an order (e.g., "Customer called about shipping delay").
        Customers can view notes and reply, creating a threaded conversation around the order.
        Notes are displayed in chronological order on the order detail page.
    """

    # ForeignKey to Order: each note belongs to exactly one order.
    # related_name='order_notes' allows reverse access: order.order_notes.all() to list all notes.
    # on_delete=models.CASCADE: if the order is deleted, all its notes are deleted too.
    order = models.ForeignKey(Order, related_name='order_notes', on_delete=models.CASCADE)

    # user_type identifies whether an admin or a customer wrote this note.
    # This is used to style the note differently in the UI (e.g., admin notes on the left, customer on the right).
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='admin')

    # The actual message text. No length limit — TextField can store arbitrarily long messages.
    message = models.TextField()

    # auto_now_add=True automatically sets the field to the current date and time when the note is FIRST created.
    # This creates a chronological timeline of all notes on an order.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """
        Meta options for OrderNote.
        """
        # ordering = ['created_at'] means notes are listed in chronological order (oldest first).
        # This makes the conversation read naturally from top to bottom.
        ordering = ['created_at']

        # Human-readable names for the Django admin interface.
        verbose_name = 'Order Note'
        verbose_name_plural = 'Order Notes'

    def __str__(self):
        """
        Returns a human-readable summary of the note.

        Returns:
            str: A string like "Note on Order #42 by Admin".
        """
        return f"Note on {self.order} by {self.user_type.title()}"


class Notification(models.Model):
    """
    Represents an in-app notification for a user or customer.

    Notifications are used to alert users about important events:
    - Order status changes (confirmed, shipped, delivered)
    - Payment updates (paid, partial, unpaid)
    - New notes on an order
    - System announcements

    Attributes:
        user (User, optional): The Django admin/staff user to notify. Null for customer-only notifications.
        customer (Customer, optional): The Customer to notify. Null for admin-only notifications.
        order (Order, optional): The related order, if this notification is about an order.
        message (str): The notification text displayed to the user.
        notification_type (str): The category of notification (order_status, payment, shipment, note, system).
        is_read (bool): Whether the user has seen and dismissed the notification.
        created_at (datetime): When the notification was created (auto-set).

    Business Logic:
        When an order's status changes, the system creates a notification for the customer
        so they see it when they next log into the portal. Admin users also get notifications
        for new customer notes or system events. The toast system polls for unread notifications
        and displays them in real-time.
    """

    # ForeignKey to Django's built-in User model. Used for admin/staff notifications.
    # null=True, blank=True means the notification may not be for a Django user (e.g., customer-only).
    # on_delete=models.CASCADE: if the user is deleted, their notifications are also deleted.
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name='notifications')

    # ForeignKey to Customer. Used for customer portal notifications.
    # null=True, blank=True means the notification may not be for a customer (e.g., admin-only).
    # on_delete=models.CASCADE: if the customer is deleted, their notifications are also deleted.
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.CASCADE, related_name='notifications')

    # ForeignKey to Order. Optional — notifications may be about general events, not specific orders.
    # null=True, blank=True means the notification may not relate to a specific order.
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.CASCADE, related_name='notifications')

    # The notification message text. Short and concise for toast display.
    message = models.TextField()

    # The type of notification, used for styling and filtering.
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPE_CHOICES, default='system')

    # Boolean flag indicating whether the recipient has read/dismissed the notification.
    # Default is False (unread). When the user clicks the notification or marks it as read, this becomes True.
    is_read = models.BooleanField(default=False)

    # auto_now_add=True automatically sets the field to the current date and time when the notification is FIRST created.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """
        Meta options for Notification.
        """
        # ordering = ['-created_at'] means newest notifications first.
        # Users want to see the most recent notifications at the top of their list.
        ordering = ['-created_at']

        # Human-readable names for the Django admin interface.
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'

    def __str__(self):
        """
        Returns a human-readable summary of the notification.

        Returns:
            str: A string like "Order Status: Order #42 confirmed".
        """
        recipient = self.user.username if self.user else (self.customer.name if self.customer else 'Unknown')
        return f"{self.get_notification_type_display()}: {self.message[:50]}... — {recipient}"
