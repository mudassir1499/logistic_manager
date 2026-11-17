"""
Tests for quotations.

The properties worth protecting are the ones that make the record trustworthy:
a reference is never reused, a sent quote cannot be edited underneath the
customer, a conversion rate counts the right denominator, and converting to an
order never silently drops a line.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from customers.models import Customer
from orders.models import Order
from products.models import Product
from quotes.models import Quotation, QuotationItem


class QuotationTestCase(TestCase):
    """Shared admin login, a customer and a product to quote."""

    def setUp(self):
        self.admin = User.objects.create_user('quoter', 'q@example.com', 'pw')
        profile = self.admin.profile
        profile.role = 'admin'
        for field in profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, True)
        profile.save()
        self.client.force_login(self.admin)

        self.customer = Customer.objects.create(name='Acme Imports')
        self.product = Product.objects.create(name='Quoted Widget', price=10, moq=1)

    def make_quote(self, **kwargs):
        kwargs.setdefault('customer', self.customer)
        return Quotation.objects.create(**kwargs)

    def add_line(self, quote, **kwargs):
        kwargs.setdefault('quantity', 10)
        kwargs.setdefault('unit_price', Decimal('5.00'))
        return QuotationItem.objects.create(quotation=quote, **kwargs)


class NumberingTests(QuotationTestCase):

    def test_numbers_are_sequential_within_a_year(self):
        first = self.make_quote()
        second = self.make_quote()
        year = timezone.localdate().year
        self.assertEqual(first.number, 'QT-%d-0001' % year)
        self.assertEqual(second.number, 'QT-%d-0002' % year)

    def test_a_deleted_quotation_does_not_free_its_number(self):
        """
        The reference may already be in a customer's inbox. Deriving the next
        one from a COUNT rather than the highest issued would hand the same
        reference to a different quotation.
        """
        first = self.make_quote()
        second = self.make_quote()
        second.delete()
        third = self.make_quote()
        self.assertNotEqual(third.number, first.number)
        self.assertEqual(third.number, 'QT-%d-0003' % timezone.localdate().year)


class MoneyTests(QuotationTestCase):

    def test_subtotal_sums_the_lines(self):
        quote = self.make_quote()
        self.add_line(quote, product=self.product, quantity=100, unit_price=Decimal('2.50'))
        self.add_line(quote, description='Carton', quantity=100, unit_price=Decimal('0.40'))
        self.assertEqual(quote.subtotal, Decimal('290.00'))

    def test_margin_is_none_when_no_cost_was_entered(self):
        """Not zero. Zero margin and unknown margin are different answers."""
        quote = self.make_quote()
        line = self.add_line(quote, description='Unknown cost', unit_price=Decimal('5.00'))
        self.assertIsNone(line.line_margin)

    def test_margin_uses_the_cost_when_it_is_there(self):
        quote = self.make_quote()
        line = self.add_line(quote, description='Known', quantity=10,
                             unit_price=Decimal('5.00'), unit_cost=Decimal('3.00'))
        self.assertEqual(line.line_margin, Decimal('20.00'))

    def test_a_line_with_no_product_still_has_a_label(self):
        quote = self.make_quote()
        self.assertEqual(self.add_line(quote, description='Tooling').label, 'Tooling')
        self.assertEqual(self.add_line(quote, product=self.product).label, 'Quoted Widget')


class LifecycleTests(QuotationTestCase):

    def test_a_draft_cannot_be_sent_empty(self):
        quote = self.make_quote()
        self.client.post('/quotes/%d/action/' % quote.id, {'action': 'send'})
        quote.refresh_from_db()
        self.assertEqual(quote.status, Quotation.STATUS_DRAFT)

    def test_sending_stamps_the_time(self):
        quote = self.make_quote()
        self.add_line(quote, product=self.product)
        self.client.post('/quotes/%d/action/' % quote.id, {'action': 'send'})
        quote.refresh_from_db()
        self.assertEqual(quote.status, Quotation.STATUS_SENT)
        self.assertIsNotNone(quote.sent_at)

    def test_a_sent_quotation_cannot_be_edited(self):
        """
        The customer is holding this. Changing the lines would alter what they
        were offered with no record of the original.
        """
        quote = self.make_quote()
        self.add_line(quote, product=self.product)
        quote.mark_sent()
        self.client.post('/quotes/%d/items/add/' % quote.id,
                         {'description': 'added later', 'quantity': 1, 'unit_price': '1'})
        self.assertEqual(quote.items.count(), 1)

    def test_only_a_sent_quotation_can_be_accepted(self):
        quote = self.make_quote()
        self.add_line(quote, product=self.product)
        self.client.post('/quotes/%d/action/' % quote.id, {'action': 'accept'})
        quote.refresh_from_db()
        self.assertEqual(quote.status, Quotation.STATUS_DRAFT)

    def test_declining_keeps_the_reason(self):
        quote = self.make_quote()
        self.add_line(quote, product=self.product)
        quote.mark_sent()
        self.client.post('/quotes/%d/action/' % quote.id,
                         {'action': 'decline', 'reason': 'Lead time too long'})
        quote.refresh_from_db()
        self.assertEqual(quote.status, Quotation.STATUS_DECLINED)
        self.assertEqual(quote.decline_reason, 'Lead time too long')

    def test_overdue_is_computed_not_stored(self):
        quote = self.make_quote(valid_until=timezone.localdate() - timedelta(days=1))
        self.add_line(quote, product=self.product)
        quote.mark_sent()
        self.assertTrue(quote.is_overdue)
        # Still 'sent' - nothing flipped the status behind the owner's back.
        self.assertEqual(quote.status, Quotation.STATUS_SENT)

    def test_a_decided_quotation_is_not_overdue(self):
        quote = self.make_quote(valid_until=timezone.localdate() - timedelta(days=10))
        quote.mark_accepted()
        self.assertFalse(quote.is_overdue)


class ConversionTests(QuotationTestCase):

    def accepted_quote(self):
        quote = self.make_quote()
        self.add_line(quote, product=self.product, quantity=100, unit_price=Decimal('3.00'))
        quote.mark_sent()
        quote.mark_accepted()
        return quote

    def test_converting_creates_an_order_with_the_lines(self):
        quote = self.accepted_quote()
        self.client.post('/quotes/%d/convert/' % quote.id)
        quote.refresh_from_db()
        self.assertIsNotNone(quote.order_id)
        order = Order.objects.get(id=quote.order_id)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.total, Decimal('300.00'))

    def test_an_unaccepted_quotation_does_not_convert(self):
        quote = self.make_quote()
        self.add_line(quote, product=self.product)
        self.client.post('/quotes/%d/convert/' % quote.id)
        quote.refresh_from_db()
        self.assertIsNone(quote.order_id)
        self.assertEqual(Order.objects.count(), 0)

    def test_converting_twice_does_not_make_a_second_order(self):
        quote = self.accepted_quote()
        self.client.post('/quotes/%d/convert/' % quote.id)
        self.client.post('/quotes/%d/convert/' % quote.id)
        self.assertEqual(Order.objects.count(), 1)

    def test_free_text_lines_are_reported_not_silently_dropped(self):
        """
        OrderItem.product is non-null, so a line with no catalogue product
        cannot go on the order. Whoever converts has to be told which ones, or
        the tooling charge quietly disappears.
        """
        quote = self.make_quote()
        self.add_line(quote, product=self.product, quantity=10, unit_price=Decimal('1.00'))
        self.add_line(quote, description='Tooling charge', quantity=1, unit_price=Decimal('250.00'))
        quote.mark_sent()
        quote.mark_accepted()

        response = self.client.post('/quotes/%d/convert/' % quote.id, follow=True)
        quote.refresh_from_db()
        order = Order.objects.get(id=quote.order_id)
        self.assertEqual(order.items.count(), 1)
        self.assertContains(response, 'Tooling charge')

    def test_a_quotation_of_only_free_text_refuses_to_convert(self):
        quote = self.make_quote()
        self.add_line(quote, description='Consultancy', quantity=1, unit_price=Decimal('500.00'))
        quote.mark_sent()
        quote.mark_accepted()
        self.client.post('/quotes/%d/convert/' % quote.id)
        quote.refresh_from_db()
        self.assertIsNone(quote.order_id)
        self.assertEqual(Order.objects.count(), 0)


class ListScreenTests(QuotationTestCase):

    def test_conversion_counts_decided_quotations_only(self):
        """
        An open quote is not a loss. If the denominator were every quotation,
        the rate would fall every time one was sent, which is backwards.
        """
        for _ in range(3):
            q = self.make_quote()
            self.add_line(q, product=self.product)
            q.mark_sent()
            q.mark_accepted()
        q = self.make_quote()
        self.add_line(q, product=self.product)
        q.mark_sent()
        q.mark_declined('too slow')
        # Two still open - these must not count against the rate.
        self.make_quote()
        self.make_quote()

        context = self.client.get('/quotes/').context
        self.assertEqual(context['accepted_count'], 3)
        self.assertEqual(context['decided_count'], 4)
        self.assertEqual(context['conversion_rate'], 75.0)

    def test_the_rate_is_none_rather_than_zero_before_anything_is_decided(self):
        self.make_quote()
        self.assertIsNone(self.client.get('/quotes/').context['conversion_rate'])

    def test_the_list_does_not_query_once_per_row(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for _ in range(3):
            q = self.make_quote()
            self.add_line(q, product=self.product)
        self.client.get('/quotes/')                      # warm-up
        with CaptureQueriesContext(connection) as small:
            self.client.get('/quotes/')
        for _ in range(12):
            q = self.make_quote()
            self.add_line(q, product=self.product)
        with CaptureQueriesContext(connection) as large:
            self.client.get('/quotes/')
        self.assertEqual(
            len(small), len(large),
            'list went from %d to %d queries after adding 12 quotations'
            % (len(small), len(large)))


class PermissionTests(QuotationTestCase):

    def test_a_customer_cannot_reach_quotations(self):
        buyer = User.objects.create_user('buyerq', 'b@example.com', 'pw')
        buyer.profile.role = 'customer'
        buyer.profile.save()
        self.client.force_login(buyer)
        self.assertNotEqual(self.client.get('/quotes/').status_code, 200)

    def test_staff_without_the_module_cannot_reach_quotations(self):
        staff = User.objects.create_user('staffq', 's@example.com', 'pw')
        profile = staff.profile
        profile.role = 'staff'
        for field in profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, False)
        profile.save()
        self.client.force_login(staff)
        self.assertNotEqual(self.client.get('/quotes/').status_code, 200)
