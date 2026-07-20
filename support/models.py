"""
support/models.py

A lightweight support-ticket system that gives customers a way to raise issues
(about an order, a payment, shipping, etc.) and gives the internal Support role a
queue to work through.

Data model:
  - Ticket         : one support conversation, opened by a customer, optionally
                     assigned to a support agent, moving through a status flow.
  - TicketMessage  : an individual reply within a ticket. Messages can be marked
                     ``internal`` so support staff can leave notes the customer
                     never sees.
  - TicketAttachment: a file attached to a message (screenshot, document…).

Everyone here is a Django ``User`` (the unified identity introduced by the
``accounts`` app). ``Ticket.customer`` denormalises the customer link so the
support queue can filter/group by customer without walking through the profile.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Ticket(models.Model):
    """A single support request opened by a customer."""

    # ------- Category: what the ticket is broadly about (drives triage) -------
    CATEGORY_CHOICES = [
        ('general', 'General'),
        ('order', 'Order'),
        ('payment', 'Payment / Ledger'),
        ('shipping', 'Shipping'),
        ('product', 'Product'),
        ('other', 'Other'),
    ]

    # ------- Priority: how urgent, set by the customer, adjustable by staff ----
    PRIORITY_LOW = 'low'
    PRIORITY_NORMAL = 'normal'
    PRIORITY_HIGH = 'high'
    PRIORITY_URGENT = 'urgent'
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, 'Low'),
        (PRIORITY_NORMAL, 'Normal'),
        (PRIORITY_HIGH, 'High'),
        (PRIORITY_URGENT, 'Urgent'),
    ]

    # ------- Status: where the ticket is in its lifecycle ---------------------
    STATUS_OPEN = 'open'          # New / awaiting first response from support.
    STATUS_PENDING = 'pending'    # Waiting on the customer to reply.
    STATUS_RESOLVED = 'resolved'  # Support believes it is solved.
    STATUS_CLOSED = 'closed'      # Done; no further replies expected.
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_PENDING, 'Pending Customer'),
        (STATUS_RESOLVED, 'Resolved'),
        (STATUS_CLOSED, 'Closed'),
    ]
    # Statuses that count as "still needs attention" for the queue badge.
    OPEN_STATUSES = (STATUS_OPEN, STATUS_PENDING)

    # Who opened the ticket. The account is the source of truth; ``customer``
    # below is a convenience denormalisation for filtering.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tickets_created',
    )

    # The customer business record this ticket concerns. Nullable so a staff
    # member could, in principle, open an internal ticket.
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_tickets',
    )

    subject = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True)

    # The support agent responsible for this ticket. NULL = unassigned queue.
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets_assigned',
        limit_choices_to={'is_active': True},
    )

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['status', '-updated_at']),
            models.Index(fields=['assigned_to', 'status']),
        ]

    def __str__(self):
        return f'#{self.pk} {self.subject}'

    @property
    def is_open(self):
        """True while the ticket still needs work (open or pending)."""
        return self.status in self.OPEN_STATUSES

    def status_badge_class(self):
        """CSS suffix used by templates to colour the status badge."""
        return {
            self.STATUS_OPEN: 'open',
            self.STATUS_PENDING: 'pending',
            self.STATUS_RESOLVED: 'resolved',
            self.STATUS_CLOSED: 'closed',
        }.get(self.status, 'open')

    def priority_badge_class(self):
        """CSS suffix used by templates to colour the priority badge."""
        return {
            self.PRIORITY_LOW: 'low',
            self.PRIORITY_NORMAL: 'normal',
            self.PRIORITY_HIGH: 'high',
            self.PRIORITY_URGENT: 'urgent',
        }.get(self.priority, 'normal')

    def touch(self):
        """Bump ``updated_at`` (e.g. after a new reply) so the queue re-sorts."""
        self.save(update_fields=['updated_at'])


class TicketMessage(models.Model):
    """One reply inside a ticket thread."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='messages')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='ticket_messages',
    )
    body = models.TextField()

    # Internal notes are visible only to back-office/support users, never to the
    # customer. Handy for agents to coordinate without exposing chatter.
    is_internal = models.BooleanField(default=False)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Message on ticket #{self.ticket_id} by {self.author_id}'


class TicketAttachment(models.Model):
    """A file attached to a ticket message."""

    message = models.ForeignKey(TicketMessage, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='support_attachments/%Y/%m/')
    uploaded_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f'Attachment for message #{self.message_id}'
