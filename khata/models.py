"""
khata/models.py

This module defines the database models for the Khata (Ledger) app in a Django logistics management system.

"Khata" (from Urdu/Hindi/Urdu: खाता/खाते) is a traditional term for a ledger or account book
used in South Asian and Middle Eastern business culture. In this system, it represents the
financial record of transactions between the logistics company and each customer — essentially
a digital ledger that tracks who owes what.

Models:
    - LedgerEntry: A single transaction record (credit or debit) in a customer's account.

Business Concepts:
    - Credit (+): When the customer pays money to the logistics company. This reduces their balance/dues.
    - Debit (-): When the customer owes money to the logistics company (e.g., for an order).
      This increases their balance/dues.
    - Running Balance: The net amount a customer owes is calculated by summing all debits
      and subtracting all credits.
    - Multi-currency: The business operates across multiple countries (UAE, China, Saudi Arabia),
      so transactions can be recorded in different currencies.
"""

# Import Django's ORM models module for defining database fields
from django.db import models

# timezone.now is used as the default for LedgerEntry.date. It is passed as a
# reference (no parentheses) so it is evaluated at insert time, not at import.
from django.utils import timezone

# Import the Customer model from the customers app. Each ledger entry belongs to one customer.
from customers.models import Customer


# CURRENCY_CHOICES defines the currencies supported by the logistics business.
# The business operates across multiple countries, so it handles multiple currencies.
# Each tuple is (database_value, display_label). The database stores the short code (e.g., 'AED').
CURRENCY_CHOICES = [
    ('AED', 'AED'),  # UAE Dirham — primary currency for UAE-based operations
    ('RMB', 'RMB'),  # Chinese Yuan (Renminbi) — used when sourcing from Chinese suppliers
    ('USD', 'USD'),  # US Dollar — commonly used for international trade
    ('EUR', 'EUR'),  # Euro — used for European transactions
    ('GBP', 'GBP'),  # British Pound — used for UK transactions
    ('SAR', 'SAR'),  # Saudi Riyal — used for Saudi Arabia operations
]


class LedgerEntry(models.Model):
    """
    Represents a single financial transaction in a customer's ledger (Khata).

    In traditional South Asian/Middle Eastern business culture, a "Khata" is an account book
    where a merchant records all credit and debit transactions with a customer. This model
    digitizes that concept: every time a customer pays or owes money, a LedgerEntry is created.

    Attributes:
        customer (Customer): The customer whose account this entry belongs to.
        entry_type (str): 'credit' (customer paid) or 'debit' (customer owes).
        amount (Decimal): The monetary value of the transaction.
        currency (str): The currency of the transaction (AED, RMB, USD, etc.).
        date (datetime): When this transaction was recorded.
        description (str, optional): Notes explaining the transaction (e.g., "Payment for Order #42").

    Business Logic:
        - When a customer places an order, the system creates a DEBIT entry for the order total.
          This increases what the customer owes.
        - When a customer makes a payment, the system creates a CREDIT entry for the payment amount.
          This decreases what the customer owes.
        - The "running balance" for a customer is calculated as:
          Total Debits - Total Credits = Amount Owed
        - Multi-currency support means transactions in different currencies are tracked separately
          or converted using the exchange rate from CompanySettings.
    """

    # Class constants for entry types. Using constants prevents typos and makes code readable.
    # CREDIT means money coming IN to the logistics company (customer paid).
    CREDIT = 'credit'

    # DEBIT means money going OUT from the customer's perspective — they now owe more.
    # In accounting terms, a debit increases the customer's liability (amount they owe).
    DEBIT = 'debit'

    # ENTRY_TYPE_CHOICES defines the two possible transaction types.
    # Each LedgerEntry must be either a credit or a debit.
    ENTRY_TYPE_CHOICES = [
        (CREDIT, 'Credit'),  # Customer made a payment
        (DEBIT, 'Debit'),    # Customer incurred a debt (e.g., new order)
    ]

    # ForeignKey: Many ledger entries can belong to one customer.
    # on_delete=models.CASCADE: if a customer is deleted, all their ledger entries are also deleted.
    # This prevents orphaned financial records, though in practice customers should be deactivated rather than deleted.
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)

    # entry_type is a CharField with choices. It must be either 'credit' or 'debit'.
    # max_length=6 is sufficient because the longest value ('credit') is 6 characters.
    # The choices parameter ensures the admin dropdown and forms only show these two options.
    entry_type = models.CharField(max_length=6, choices=ENTRY_TYPE_CHOICES)

    # DecimalField for the transaction amount. max_digits=10 allows up to 99,999,999.99.
    # decimal_places=2 ensures 2 decimal places for currency precision.
    # This stores the absolute value of the transaction (always positive; the entry_type indicates direction).
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    # The currency of this transaction. Default is 'AED' (UAE Dirham) since that's likely
    # the primary operating currency. The choices restrict input to supported currencies.
    currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default='AED')

    # The date the transaction HAPPENED, which is not always the date it was typed in.
    #
    # This was auto_now_add=True, which made the field unwritable: Django ignores
    # any value you assign and stamps the moment the row was inserted. For an
    # account book that is wrong in two ways. A payment received on Tuesday and
    # entered on Friday was filed under Friday, so a statement filtered to a date
    # range reported the wrong figures. And an import of historical entries would
    # have stamped every single one with the import date, collapsing years of
    # ledger history onto one day and destroying the running balance.
    #
    # default=timezone.now keeps the same behaviour when nothing is supplied - a
    # new entry still defaults to now - while allowing a real transaction date to
    # be set. Indexed because every ledger screen and every export filters and
    # orders on it.
    date = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text='When the transaction took place, which may be earlier than when it was entered.',
    )

    # Optional text description explaining the purpose of this transaction.
    # Examples: "Payment for Order #42", "Advance deposit for June shipments", "Refund for cancelled order".
    # blank=True means the field is optional in forms.
    description = models.TextField(blank=True)

    # Optional link to the order this entry pays for. Set by the "Record payment"
    # flow so an order's paid-vs-total progress can be computed directly from the
    # ledger (SET_NULL keeps the accounting row even if the order is deleted).
    order = models.ForeignKey(
        'orders.Order',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ledger_entries',
    )

    def __str__(self):
        """
        Returns a human-readable summary of this ledger entry.

        Returns:
            str: A string like "ABC Trading - credit - 5000.00 AED" showing the customer,
                 transaction type, amount, and currency.

        Business Logic:
            This string format is used in the Django admin and dropdowns so the admin can quickly
            identify a transaction without opening it. It shows all the key info at a glance.
        """
        # f-string combining all key fields: customer name, entry type, amount, and currency.
        return f"{self.customer.name} - {self.entry_type} - {self.amount} {self.currency}"
