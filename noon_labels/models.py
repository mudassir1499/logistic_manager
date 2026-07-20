"""
noon_labels/models.py

This module defines the database models for the Noon Labels app in a Django logistics management system.

The Noon Labels app generates carton/shipping labels for products sold on Noon.com,
which is a major e-commerce marketplace in the Middle East (UAE, Saudi Arabia, Egypt).
Noon has specific labeling requirements for cartons, including ASN (Amazon-style but Noon-specific)
numbers, label marks, and quantity information. This model stores the data needed to print
compliant carton labels.

Models:
    - LabelBatch: Represents a batch of carton labels with marks, ASN numbers, and quantities.

Business Context:
    Noon.com is one of the largest e-commerce platforms in the Middle East. When a seller
    (like the logistics company's customer) sends inventory to Noon's fulfillment center, each carton
    must have a label with specific markings. The logistics company prepares these labels based on
    the shipment details provided by the customer or extracted from Noon seller portal.
"""

# Import Django's ORM models module to define database fields
from django.db import models


class LabelBatch(models.Model):
    """
    Represents a batch of carton labels for a Noon.com shipment.

    In Noon's fulfillment system, sellers send products in cartons, and each carton needs
    a label with identifying marks. A LabelBatch groups together all the information needed
    to print one set of labels (e.g., for one shipment to Noon's warehouse).

    Attributes:
        label_mark (str): Primary identifier/mark printed on the label (e.g., a seller ID or batch code).
        label_mark_2 (str, optional): Secondary label mark for additional categorization.
        label_mark_3 (str, optional): Tertiary label mark for additional categorization.
        carton_mark (str): The mark printed on the carton itself (may differ from label mark).
        carton_asn (str, optional): ASN (Advanced Shipping Notice) number — a Noon-specific tracking number.
        quantity (int): Total number of individual items in this label batch.
        carton_quantity (int): Number of cartons in this batch. Default is 1 carton.
        created_at (datetime): When this label batch was created in the system.

    Business Logic:
        When a customer sells products on Noon.com, they need to send inventory to Noon's
        fulfillment center. The logistics company prepares the cartons and prints labels.
        Each LabelBatch stores the data for one label run. The label_mark is typically a
        seller identifier or batch code that Noon uses to route the cartons. The carton_asn
        is an advance shipping notice number that Noon requires for inbound tracking.
    """

    # CharField for the primary label mark. This is the main identifier printed on the label.
    # Example values might be a seller code, a SKU prefix, or a customer-specific batch code.
    # Max length 100 allows for reasonably long codes.
    label_mark = models.CharField(max_length=100)

    # Optional secondary label mark. Some Noon labels require multiple marks for different sorting levels.
    # blank=True, null=True means the field is completely optional (both in forms and in the database).
    label_mark_2 = models.CharField(max_length=100, blank=True, null=True)

    # Optional tertiary label mark. Provides flexibility for complex labeling requirements.
    label_mark_3 = models.CharField(max_length=100, blank=True, null=True)

    # The mark printed on the physical carton. This may differ from the label mark
    # because the carton itself might have a different code (e.g., a customer carton code
    # while the label has a Noon-specific code).
    carton_mark = models.CharField(max_length=100)

    # ASN = Advanced Shipping Notice. Noon uses ASN numbers to track incoming shipments.
    # This is optional because some label batches may not have an ASN assigned yet,
    # or they may be for internal use rather than Noon fulfillment.
    carton_asn = models.CharField(max_length=100, blank=True, null=True)

    # Total number of individual product pieces in this batch.
    # For example, if a customer is sending 500 pieces of a product, quantity = 500.
    # PositiveIntegerField ensures the value is always >= 0 (no negative quantities).
    quantity = models.PositiveIntegerField()

    # Number of cartons in this batch. Default is 1.
    # If the customer sends 500 pieces in 10 cartons, carton_quantity = 10 and quantity = 500.
    # This helps calculate pieces per carton: 500 / 10 = 50 pieces per carton.
    carton_quantity = models.PositiveIntegerField(default=1)

    # auto_now_add=True: Automatically records the current date and time when this LabelBatch
    # is first created. This helps track when labels were generated and allows sorting by recency.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """
        Meta options for the LabelBatch model.

        These settings control how the model behaves in the Django admin and in database queries.
        """
        # ordering = ['-created_at'] means label batches are sorted by creation date,
        # with the newest batches first. The minus sign (-) indicates descending order.
        # This is useful because the admin typically wants to see the most recent label batches.
        ordering = ['-created_at']

        # verbose_name_plural is the human-readable plural name shown in the Django admin sidebar.
        # By default, Django would pluralize "LabelBatch" as "LabelBatchs" (incorrect).
        # Setting it to 'Label Batches' makes the admin interface look professional and correct.
        verbose_name_plural = 'Label Batches'

    def __str__(self):
        """
        Returns a human-readable summary of this label batch.

        Returns:
            str: A string like "SELLER123 — Qty: 500" showing the label mark and total quantity.

        Business Logic:
            This format is used in Django admin dropdowns and lists so the admin can quickly
            identify which label batch they're looking at without opening each record.
        """
        # f-string combining the label mark and quantity for quick identification.
        # The em dash (—) makes the output visually clear and easy to read.
        return f"{self.label_mark} — Qty: {self.quantity}"
