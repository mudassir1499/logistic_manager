"""
customers/models.py

This module defines the database models for the Customers app in a Django logistics management system.

The Customers app manages all client-related data: who the customers are, how to contact them,
and which products are assigned to each customer. In a logistics business, customers are the
buyers who place orders for goods sourced from suppliers (often in China) and shipped to
their destination (UAE, KSA, etc.).

Models:
    - Customer: Represents a business client (buyer) who places orders.
    - CustomerProduct: Links a customer to a specific product they are allowed to order.
      This is useful when a logistics company serves multiple clients and each client
      has their own product catalog or private products.
"""

# Import Django's models module to define database models (tables, columns, relationships)
from django.db import models

# Import password hashing utilities so we can securely store customer passwords
# Django's auth system uses PBKDF2 by default, which is much safer than plain text
from django.contrib.auth.hashers import make_password, check_password

# Import timezone utility so we can set default timestamps to the current time
from django.utils import timezone


class Customer(models.Model):
    """
    Represents a customer (business client) in the logistics system.

    In this logistics business, a customer is typically a buyer/retailer who:
    - Places orders for products sourced from suppliers (e.g., Alibaba, 1688)
    - Has orders shipped via air or sea freight to UAE, KSA, or other destinations
    - May access a customer portal to view their orders, invoices, and product catalog

    Attributes:
        name (str): The full name or business name of the customer.
        phone (str): Contact phone number for order coordination and delivery.
        address (str): Physical delivery address where shipments are sent.
        email (str, optional): Email address used for portal login and notifications.
        password (str, optional): Hashed password for the customer portal (if enabled).
        is_active (bool): Whether the customer account is enabled. Admins can deactivate.
        created_at (datetime): When the customer was first added to the system.

    Returns:
        str: The customer's name (used in admin dropdowns, lists, etc.)
    """

    # CharField: Stores text up to a max length. Used for customer name.
    # The name is required (no blank=True, no null=True) because every customer must have a name.
    name = models.CharField(max_length=255)

    # Phone number stored as CharField (not IntegerField) because phone numbers may have
    # leading zeros, country codes (+971), dashes, and spaces. Storing as text prevents data loss.
    phone = models.CharField(max_length=20)

    # TextField: Unlimited (or very long) text. Used for the full delivery address.
    # The address is required because the logistics company needs to know where to ship.
    address = models.TextField()

    # EmailField: Validates that the input looks like an email address (has @ and domain).
    # blank=True means the field is optional in forms.
    # null=True means the database allows NULL for this column (needed for optional fields on TextField/CharField).
    # unique=True ensures no two customers can share the same email (important for portal login).
    email = models.EmailField(blank=True, null=True, unique=True)

    # Password field: stores the HASHED password, never the raw password.
    # blank=True, null=True means some customers may not have portal access.
    # When a customer sets a password, we call set_password() which hashes it using Django's make_password().
    password = models.CharField(max_length=128, blank=True, null=True)

    # BooleanField: Simple true/false flag.
    # is_active controls whether the customer can log in to the portal.
    # Default is True (active). Admins can deactivate problematic customers.
    is_active = models.BooleanField(default=True)

    # DateTimeField: Stores both date and time.
    # default=timezone.now means when a new Customer is created, created_at is set to the current server time.
    # This helps track when a customer was added to the system.
    # db_index=True improves query performance when filtering or ordering by created_at.
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        """
        Meta options for the Customer model.
        """
        # ordering by -created_at ensures newest customers appear first in lists
        ordering = ['-created_at']
        # Add an index on (name, is_active) for fast search and active filtering
        indexes = [
            models.Index(fields=['name', 'is_active']),
            models.Index(fields=['email', 'is_active']),
        ]

    def __str__(self):
        """
        Returns the string representation of this Customer.

        Django uses __str__() to display the object in the admin site, dropdowns,
        debugging output, and form choices. Showing the name makes it human-readable.

        Returns:
            str: The customer's name.
        """
        return self.name

    def set_password(self, raw_password):
        """
        Securely hashes and stores the customer's password.

        NEVER store raw passwords in the database. This method uses Django's built-in
        make_password() which applies a strong one-way hash (PBKDF2 by default).
        The hash includes a salt and multiple iterations, making brute-force attacks
        computationally infeasible.

        Args:
            raw_password (str): The plain-text password entered by the customer.

        Business Logic:
            When a customer creates a portal account or resets their password,
            the admin or the customer themselves enters a plain password. This
            method converts it to a secure hash before saving to the database.
        """
        # make_password() returns a hashed string like "pbkdf2_sha256$..."
        # This hash is what gets stored in the database.
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        """
        Verifies whether a given raw password matches the stored hash.

        Args:
            raw_password (str): The plain-text password to verify.

        Returns:
            bool: True if the raw password matches the stored hash, False otherwise.

        Business Logic:
            Used during customer login to the portal. The customer enters their password;
            this method checks it against the securely stored hash without ever revealing
            the original password.
        """
        # check_password() hashes the raw_password using the same algorithm and salt
        # as the stored hash, then compares them. Returns True if they match.
        return check_password(raw_password, self.password)

    @property
    def has_portal_access(self):
        """
        A computed (read-only) property that checks if this customer can use the portal.

        The @property decorator lets us access this like an attribute:
        customer.has_portal_access instead of customer.has_portal_access()

        Returns:
            bool: True if the customer is active, has an email, AND has a password set.

        Business Logic:
            Not all customers need portal access. A customer must have:
            1. An active account (is_active = True)
            2. An email address (used as login ID)
            3. A password set (they have registered or been given portal access)
            This property is used in views to decide whether to show the login option
            or redirect them to contact the admin.
        """
        # All three conditions must be true for portal access to be granted.
        # If any is missing, the customer cannot log in.
        return self.is_active and self.email and self.password


class CustomerProduct(models.Model):
    """
    Links a Customer to a Product they are allowed to order.

    In this logistics business, a single logistics company may source products for many customers.
    Some products are "private" — only visible to a specific customer. This model creates
    an assignment relationship: "Customer X is allowed to see and order Product Y."

    Attributes:
        customer (Customer): The customer who owns or has access to this product.
        product (Product): The product from the products app that is being assigned.
        note (str, optional): Admin notes about this assignment (e.g., special pricing, sourcing instructions).
        assigned_at (datetime): When this assignment was created (auto-set on creation).

    Database Design:
        - unique_together ensures a customer can only be assigned a product once (no duplicates).
        - The related_name on both FKs allows reverse lookups:
          customer.assigned_products gives all CustomerProduct entries for that customer.
          product.customer_assignments gives all CustomerProduct entries for that product.

    Business Logic:
        If a product is marked as "private" (is_private=True in Product model), it will only
        appear in the portal for customers who have a CustomerProduct link. This prevents
        Customer A from seeing Customer B's exclusive product listings.
    """

    # ForeignKey: Creates a many-to-one relationship. Many CustomerProduct rows can belong to one Customer.
    # on_delete=models.CASCADE means if the Customer is deleted, all their CustomerProduct rows are also deleted.
    # related_name='assigned_products' lets us write: customer.assigned_products.all() to get all products assigned to this customer.
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='assigned_products')

    # ForeignKey to Product in the products app. The string 'products.Product' is used instead of
    # importing the class directly to avoid circular import issues between apps.
    # on_delete=models.CASCADE: if a Product is deleted, remove this assignment.
    # related_name='customer_assignments': lets us write: product.customer_assignments.all()
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE, related_name='customer_assignments')

    # Optional note for the admin about why this product was assigned to this customer.
    # blank=True means the admin form allows leaving this field empty.
    note = models.CharField(max_length=255, blank=True)

    # auto_now_add=True: Django automatically sets this field to the current time when the row is FIRST created.
    # It will never change after that. Used to track when the assignment was made.
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """
        Meta options for the CustomerProduct model.

        These are Django's internal settings that control how the model behaves at the
        database level and in the admin interface.
        """
        # unique_together is a database constraint: it prevents the same customer from being
        # assigned the same product twice. This keeps the data clean and prevents duplicate entries.
        unique_together = ('customer', 'product')

        # ordering = ['-assigned_at'] means when you query CustomerProduct.objects.all(),
        # the results are sorted by assigned_at in descending order (newest first).
        # The minus sign (-) means descending. Useful in admin lists and recent assignments views.
        ordering = ['-assigned_at']

    def __str__(self):
        """
        Returns a human-readable string showing which customer is assigned to which product.

        Returns:
            str: A string like "ABC Trading — Wireless Headphones" showing the relationship.
        """
        # f-string (formatted string literal) allows embedding variables directly in the string.
        # The em dash (—) is used as a separator for readability.
        return f'{self.customer.name} — {self.product.name}'
