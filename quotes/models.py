"""
Quotations — the record of a price offered to a customer.

WHY THIS APP EXISTS

Quoting already happened, twice, and left nothing behind:

  * ``orders.generate_quotation_excel`` builds a spreadsheet from a customer id
    and a list of product ids posted from a form, and
  * ``orders.import_quotation_excel`` reads that file back once the customer has
    filled in the quantity column, and turns it into an order.

That round trip works, but the quote itself is never stored. If the customer
does not return the file — which is most of them, most of the time — there is
no evidence the quote was ever made: not what was offered, not at what price,
not when, not why it was lost. "How many quotes did we send last month and how
many closed?" has no answer, and the figure that matters most to a sourcing
business is its conversion rate.

A Quotation makes the offer a thing: it is created when the price is worked
out, it carries its own lifecycle, and the spreadsheet becomes a rendering of
it rather than the only trace of it.

WHY ITS OWN APP

``orders.views`` is already 4,300 lines and ``orders.models`` 985. This is a
distinct lifecycle with its own screens, and it follows the pattern the newer
apps here use (``support``, ``khata``, ``noon_labels``): small, focused, with
its own urls, admin and tests.
"""

from decimal import Decimal

from django.conf import settings as django_settings
from django.db import models, transaction
from django.utils import timezone


class QuotationSequence(models.Model):
    """
    The highest quotation number ever issued for a year.

    Exists so a reference is never reused. Deriving the next number from the
    highest one currently in the table looks equivalent and is not: delete the
    newest quotation and the maximum drops, so the next one is handed a
    reference that is already sitting in a customer's inbox. They then have two
    different documents carrying the same number, and no way to say which one
    is being discussed.

    This counter only ever goes up - the same reasoning, and the same shape, as
    products.SkuSequence.
    """

    year = models.PositiveIntegerField(
        unique=True, help_text='Calendar year this counter belongs to.')
    last_number = models.PositiveIntegerField(
        default=0, help_text='Highest number issued so far. Never decreases.')

    class Meta:
        verbose_name = 'Quotation sequence'
        ordering = ['-year']

    def __str__(self):
        return '%d (last %d)' % (self.year, self.last_number)


class Quotation(models.Model):
    """
    One priced offer to one customer.

    Attributes:
        number (str): Human reference, e.g. ``QT-2026-0007``. Assigned on first
            save and never reused — it is what the customer quotes back at us.
        customer (Customer): Who it was offered to.
        request (ProductRequest): The enquiry it answers, when it came from one.
        status (str): Where it is in its life. See the constants below.
        valid_until (date): After this the price is not held. Advisory, not
            enforced — expiry is a decision, not a cron job. See ``is_overdue``.
        order (Order): Set when an accepted quote is turned into an order, so
            the two are linked in both directions.

    THE STATUS FLOW

        draft ──send──> sent ──accept──> accepted ──convert──> (order created)
                          │
                          ├──decline──> declined   (with a reason)
                          └──expire───> expired

    Backwards moves are deliberately not offered. A quote that was sent and
    declined is a fact about what happened; editing it into something else
    destroys the only record of the loss, which is the half of the data that
    makes a conversion rate mean anything.
    """

    STATUS_DRAFT = 'draft'          # Being prepared; the customer has not seen it.
    STATUS_SENT = 'sent'            # Offered. The clock on valid_until starts here.
    STATUS_ACCEPTED = 'accepted'    # Customer agreed. Ready to become an order.
    STATUS_DECLINED = 'declined'    # Lost. decline_reason says why.
    STATUS_EXPIRED = 'expired'      # Went stale without an answer.

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SENT, 'Sent'),
        (STATUS_ACCEPTED, 'Accepted'),
        (STATUS_DECLINED, 'Declined'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    # The statuses that count as "finished" — no further action is expected.
    CLOSED_STATUSES = (STATUS_ACCEPTED, STATUS_DECLINED, STATUS_EXPIRED)

    number = models.CharField(
        max_length=20, unique=True, editable=False, db_index=True,
        help_text='Assigned automatically, e.g. QT-2026-0007.',
    )
    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.PROTECT, related_name='quotations',
        help_text='Who this was quoted to.',
    )
    # String reference rather than an import: portal already imports from
    # orders, and keeping this lazy avoids adding another edge to that graph.
    request = models.ForeignKey(
        'portal.ProductRequest', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='quotations',
        help_text='The sourcing request this answers, if it came from one.',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True,
    )

    currency = models.CharField(
        max_length=8, default='AED',
        help_text='Currency the prices below are in.',
    )
    valid_until = models.DateField(
        null=True, blank=True,
        help_text='How long the price is held. Blank means no stated expiry.',
    )

    notes = models.TextField(
        blank=True, default='',
        help_text='Shown to the customer on the quotation.',
    )
    internal_notes = models.TextField(
        blank=True, default='',
        help_text='Never shown to the customer. Margin thinking, supplier options, risks.',
    )
    decline_reason = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Why it was lost. The most useful field on this model and the '
                  'one most likely to be left blank.',
    )

    order = models.ForeignKey(
        'orders.Order', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='source_quotations',
        help_text='The order this became, once accepted and converted.',
    )

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='quotations_created',
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When it was accepted, declined or expired.',
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Quotation'
        verbose_name_plural = 'Quotations'
        indexes = [
            # The list screen filters on status and sorts by date; the reporting
            # query groups by status over a date range. This serves both.
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return '%s — %s' % (self.number, self.customer)

    # ------------------------------------------------------------------ money

    @property
    def subtotal(self):
        """
        Sum of the line totals, as a Decimal.

        Reads ``self.items.all()``, so a caller that has already prefetched the
        items pays nothing extra — which the list screen relies on.
        """
        return sum((item.line_total for item in self.items.all()), Decimal('0.00'))

    @property
    def item_count(self):
        return len(self.items.all())

    # ----------------------------------------------------------- lifecycle

    @property
    def is_open(self):
        """Still awaiting an outcome."""
        return self.status not in self.CLOSED_STATUSES

    @property
    def is_overdue(self):
        """
        Past its validity date while still waiting for an answer.

        Deliberately computed rather than stored. A nightly job that flipped
        quotes to `expired` would overwrite the status while someone was in the
        middle of a conversation about one; showing it as overdue in the list
        tells the owner the same thing and leaves the decision with them.
        """
        return bool(
            self.valid_until
            and self.status == self.STATUS_SENT
            and self.valid_until < timezone.localdate()
        )

    def mark_sent(self, when=None):
        """Move a draft to sent, stamping the time."""
        self.status = self.STATUS_SENT
        self.sent_at = when or timezone.now()
        self.save(update_fields=['status', 'sent_at', 'updated_at'])

    def mark_accepted(self, when=None):
        self.status = self.STATUS_ACCEPTED
        self.decided_at = when or timezone.now()
        self.save(update_fields=['status', 'decided_at', 'updated_at'])

    def mark_declined(self, reason='', when=None):
        self.status = self.STATUS_DECLINED
        self.decline_reason = (reason or '')[:255]
        self.decided_at = when or timezone.now()
        self.save(update_fields=['status', 'decline_reason', 'decided_at', 'updated_at'])

    def mark_expired(self, when=None):
        self.status = self.STATUS_EXPIRED
        self.decided_at = when or timezone.now()
        self.save(update_fields=['status', 'decided_at', 'updated_at'])

    # ------------------------------------------------------------ numbering

    @classmethod
    def next_number(cls):
        """
        Reserve and return the next reference, as QT-<year>-<sequence>.

        Reads and bumps QuotationSequence under select_for_update, so two
        requests arriving together cannot be handed the same number, and a
        deleted quotation never frees its reference for reuse.
        """
        year = timezone.localdate().year
        with transaction.atomic():
            sequence, _created = (QuotationSequence.objects
                                  .select_for_update()
                                  .get_or_create(year=year))
            sequence.last_number += 1
            sequence.save(update_fields=['last_number'])
            return 'QT-%d-%04d' % (year, sequence.last_number)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.next_number()
        return super().save(*args, **kwargs)


class QuotationItem(models.Model):
    """
    One priced line on a quotation.

    ``product`` is optional on purpose. A sourcing quote frequently covers
    something that is not in the catalogue yet — that is the whole business —
    so a line can carry a free-text description instead, and be linked to a
    real Product later if it becomes one.
    """

    quotation = models.ForeignKey(
        Quotation, on_delete=models.CASCADE, related_name='items',
    )
    product = models.ForeignKey(
        'products.Product', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='quotation_items',
        help_text='The catalogue product, when the line is for one.',
    )
    description = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Used when there is no catalogue product, or to override its name.',
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # What we expect to pay the factory. Optional, internal, and never rendered
    # on anything the customer sees - it is here so a quote can be checked for
    # margin before it goes out rather than after the order lands.
    unit_cost = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Internal only. Expected factory price per unit.',
    )

    position = models.PositiveIntegerField(
        default=0, help_text='Manual ordering on the quotation.',
    )

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return '%s x%d' % (self.label, self.quantity)

    @property
    def label(self):
        """What to print: the override, else the product name, else a placeholder."""
        if self.description:
            return self.description
        if self.product_id and self.product:
            return self.product.name
        return 'Unnamed item'

    @property
    def line_total(self):
        return (self.unit_price or Decimal('0.00')) * self.quantity

    @property
    def line_margin(self):
        """Expected margin for the line, or None when no cost was entered."""
        if self.unit_cost is None:
            return None
        return ((self.unit_price or Decimal('0.00')) - self.unit_cost) * self.quantity
