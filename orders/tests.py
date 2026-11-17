"""
Tests for the shipment pipeline: bulk status moves, and finding stuck shipments.

WHY THESE IN PARTICULAR

Moving shipments is the most repeated action in the back office and the one with
the widest blast radius — a single click can rewrite the state of thirty orders
and send thirty customers a notification saying their goods have moved. The
tests below pin the three behaviours that make that safe: delivered shipments are
never dragged backwards, every block of an order moves together, and each
customer hears about it exactly once.
"""

import base64
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from customers.models import Customer
from orders.models import Order, OrderItem, ShipmentStatus
from products.models import Product
from settings_manager.models import CompanySettings


class ShipmentPipelineTestCase(TestCase):
    """Shared staff login and a couple of orders to move around."""

    def setUp(self):
        self.staff = User.objects.create_user('ops', 'ops@example.com', 'pw')
        profile = self.staff.profile
        profile.role = 'admin'
        profile.save()
        self.client.force_login(self.staff)

        self.customer = Customer.objects.create(name='Acme Imports', email='acme@example.com')
        # OrderItem.product is PROTECT and non-null, so the lines need something real.
        self.product = Product.objects.create(name='Test Widget', price=10, moq=1)

    def make_order(self, blocks=(1,)):
        """An order with one OrderItem per shipment block."""
        order = Order.objects.create(customer=self.customer, total=100)
        for block in blocks:
            OrderItem.objects.create(order=order, product=self.product,
                                     quantity=1, price=100, shipment_no=block)
        return order

    def bulk(self, orders, status):
        return self.client.post('/orders/bulk-action/', {
            'order_ids': [str(o.id) for o in orders],
            'action': 'set_shipment_status',
            'shipment_status': status,
            'next': '/orders/',
        }, follow=True)


class BulkShipmentStatusTests(ShipmentPipelineTestCase):

    def test_one_click_moves_every_selected_order(self):
        orders = [self.make_order() for _ in range(3)]
        self.bulk(orders, ShipmentStatus.STATUS_ON_THE_WAY)

        for order in orders:
            with self.subTest(order=order.id):
                status = ShipmentStatus.objects.get(order=order, shipment_no=1)
                self.assertEqual(status.status, ShipmentStatus.STATUS_ON_THE_WAY)

    def test_every_block_of_a_split_order_moves(self):
        """
        An order shipped in three cartons has three blocks.

        Moving only block 1 would leave the customer's timeline showing two
        cartons still in the warehouse after the container had sailed.
        """
        order = self.make_order(blocks=(1, 2, 3))
        self.bulk([order], ShipmentStatus.STATUS_DISPATCHED)

        statuses = ShipmentStatus.objects.filter(order=order)
        self.assertEqual(statuses.count(), 3)
        self.assertTrue(all(s.status == ShipmentStatus.STATUS_DISPATCHED for s in statuses))

    def test_a_delivered_shipment_is_never_dragged_backwards(self):
        """
        The safety rule for a control that changes what you cannot see.

        Bulk selection routinely includes a finished order. Pulling it back into
        "At Customs" tells that customer their completed delivery is in transit
        again.
        """
        order = self.make_order()
        ShipmentStatus.objects.create(
            order=order, shipment_no=1, status=ShipmentStatus.STATUS_DELIVERED)

        self.bulk([order], ShipmentStatus.STATUS_AT_CUSTOMS)

        self.assertEqual(
            ShipmentStatus.objects.get(order=order, shipment_no=1).status,
            ShipmentStatus.STATUS_DELIVERED)

    def test_skipping_delivered_is_reported_not_silent(self):
        """Nothing happened must never be the whole story."""
        order = self.make_order()
        ShipmentStatus.objects.create(
            order=order, shipment_no=1, status=ShipmentStatus.STATUS_DELIVERED)

        response = self.bulk([order], ShipmentStatus.STATUS_AT_CUSTOMS)
        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('delivered', text.lower())

    def test_each_customer_is_notified_once_per_order_not_once_per_block(self):
        """A three-carton order is one event to its customer, not three."""
        from orders.models import Notification

        order = self.make_order(blocks=(1, 2, 3))
        self.bulk([order], ShipmentStatus.STATUS_ON_THE_WAY)

        self.assertEqual(
            Notification.objects.filter(customer=self.customer, order=order).count(), 1)

    def test_an_unknown_status_changes_nothing(self):
        order = self.make_order()
        self.bulk([order], 'teleported')
        self.assertFalse(ShipmentStatus.objects.filter(order=order).exists())

    def test_selecting_nothing_changes_nothing(self):
        order = self.make_order()
        self.client.post('/orders/bulk-action/', {
            'action': 'set_shipment_status',
            'shipment_status': ShipmentStatus.STATUS_DISPATCHED,
            'next': '/orders/',
        }, follow=True)
        self.assertFalse(ShipmentStatus.objects.filter(order=order).exists())

    def test_the_existing_bulk_actions_still_work(self):
        """The new branch must not have swallowed the flag updates."""
        orders = [self.make_order() for _ in range(2)]
        self.client.post('/orders/bulk-action/', {
            'order_ids': [str(o.id) for o in orders],
            'action': 'mark_placed',
            'next': '/orders/',
        }, follow=True)
        for order in orders:
            order.refresh_from_db()
            self.assertTrue(order.is_placed)


class StaleShipmentTests(ShipmentPipelineTestCase):
    """Finding shipments that have stopped moving."""

    def setUp(self):
        super().setUp()
        settings = CompanySettings.get_settings()
        settings.stale_shipment_days = 10
        settings.save()

    def age(self, status, days):
        """Backdate updated_at, which auto_now would otherwise keep at today."""
        ShipmentStatus.objects.filter(pk=status.pk).update(
            updated_at=timezone.now() - timedelta(days=days))

    def test_a_shipment_that_has_not_moved_is_flagged(self):
        order = self.make_order()
        status = ShipmentStatus.objects.create(
            order=order, shipment_no=1, status=ShipmentStatus.STATUS_WAITING_PRODUCT)
        self.age(status, 30)

        response = self.client.get('/orders/?stale=1')
        self.assertIn(order, response.context['page_obj'].object_list)

    def test_a_recently_updated_shipment_is_not_flagged(self):
        order = self.make_order()
        ShipmentStatus.objects.create(
            order=order, shipment_no=1, status=ShipmentStatus.STATUS_WAITING_PRODUCT)

        response = self.client.get('/orders/?stale=1')
        self.assertNotIn(order, response.context['page_obj'].object_list)

    def test_a_delivered_shipment_is_never_stale(self):
        """
        Finished is not neglected.

        A delivered consignment sitting untouched for a year is the correct
        outcome; listing it as needing attention would bury the ones that do.
        """
        order = self.make_order()
        status = ShipmentStatus.objects.create(
            order=order, shipment_no=1, status=ShipmentStatus.STATUS_DELIVERED)
        self.age(status, 365)

        response = self.client.get('/orders/?stale=1')
        self.assertNotIn(order, response.context['page_obj'].object_list)

    def test_the_dashboard_count_matches_the_list_it_links_to(self):
        """
        A count that disagrees with its own link is worse than no count.

        Both read the same helper, and this is what keeps them doing so.
        """
        for _ in range(3):
            order = self.make_order()
            status = ShipmentStatus.objects.create(
                order=order, shipment_no=1, status=ShipmentStatus.STATUS_AT_WAREHOUSE)
            self.age(status, 20)

        dashboard = self.client.get('/dashboard/')
        stale_item = [i for i in dashboard.context['attention_items']
                      if i['key'] == 'stale_shipments']
        self.assertEqual(len(stale_item), 1)

        listed = self.client.get('/orders/?stale=1').context['page_obj'].object_list
        self.assertEqual(stale_item[0]['count'], len(listed))

    def test_setting_the_threshold_to_zero_switches_the_warning_off(self):
        settings = CompanySettings.get_settings()
        settings.stale_shipment_days = 0
        settings.save()

        order = self.make_order()
        status = ShipmentStatus.objects.create(
            order=order, shipment_no=1, status=ShipmentStatus.STATUS_AT_CUSTOMS)
        self.age(status, 365)

        dashboard = self.client.get('/dashboard/')
        keys = [i['key'] for i in dashboard.context['attention_items']]
        self.assertNotIn('stale_shipments', keys)


class ShipmentFilterTests(ShipmentPipelineTestCase):

    def test_filtering_by_transit_status(self):
        at_customs = self.make_order()
        ShipmentStatus.objects.create(
            order=at_customs, shipment_no=1, status=ShipmentStatus.STATUS_AT_CUSTOMS)

        elsewhere = self.make_order()
        ShipmentStatus.objects.create(
            order=elsewhere, shipment_no=1, status=ShipmentStatus.STATUS_PREPARING)

        listed = self.client.get(
            f'/orders/?shipment={ShipmentStatus.STATUS_AT_CUSTOMS}').context['page_obj'].object_list
        self.assertIn(at_customs, listed)
        self.assertNotIn(elsewhere, listed)

    def test_a_split_order_appears_once_not_once_per_block(self):
        """Joining across shipment blocks duplicates rows without a distinct()."""
        order = self.make_order(blocks=(1, 2, 3))
        for block in (1, 2, 3):
            ShipmentStatus.objects.create(
                order=order, shipment_no=block, status=ShipmentStatus.STATUS_DISPATCHED)

        listed = list(self.client.get(
            f'/orders/?shipment={ShipmentStatus.STATUS_DISPATCHED}').context['page_obj'].object_list)
        self.assertEqual(listed.count(order), 1)

    def test_an_unknown_status_is_ignored_rather_than_erroring(self):
        self.make_order()
        response = self.client.get('/orders/?shipment=not-a-real-status')
        self.assertEqual(response.status_code, 200)


# Django's test runner gives every run a throwaway DATABASE but leaves
# MEDIA_ROOT pointing at the live media folder, so an ImageField upload inside a
# test is written next to real product photos and survives the run. The tests
# below upload deliberately, so they get their own directory and remove it
# afterwards.
_TEST_MEDIA = tempfile.mkdtemp(prefix='tracking-tests-')


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class PublicTrackingTestCase(TestCase):
    """
    What the public tracking page shows, for both kinds of job.

    WHY THESE

    The page answers one question — "where are my goods" — and for freight jobs
    it had stopped answering it. _build_logistics_tracking_view's docstring
    claimed "deliberately the SAME contract" as the order builder, but the order
    builder returns block['status'] as a dict of label and steps while the
    freight one returned a bare status string. Django templates resolve a
    missing attribute to the empty string, so nothing failed loudly: the badge
    and the timeline simply rendered blank.

    Two shapes that a template reads by attribute name will drift, and these
    tests are what makes the drift fail out loud rather than silently.
    """

    # A one-pixel GIF: enough for ImageField to accept, validate and store.
    PIXEL = b'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'

    @classmethod
    def tearDownClass(cls):
        # ignore_errors so a locked file on Windows cannot fail an otherwise
        # green run; the directory is under the OS temp path either way.
        shutil.rmtree(_TEST_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.customer = Customer.objects.create(name='Gulf Trading', email='gulf@example.com')
        self.product = Product.objects.create(name='LED Strip Lights', price=25, moq=10)

    def track(self, number):
        return self.client.get('/track/', {'number': number})

    def upload(self, name):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, base64.b64decode(self.PIXEL),
                                  content_type='image/gif')

    def make_freight_job(self, **kwargs):
        from orders.models import LogisticsOrder
        defaults = dict(
            customer=self.customer,
            description='3 cartons LED strip lights',
            weight_kg='42.5',
            status=ShipmentStatus.STATUS_DISPATCHED,
        )
        defaults.update(kwargs)
        return LogisticsOrder.objects.create(**defaults)

    def make_order(self, **item_kwargs):
        order = Order.objects.create(customer=self.customer, total=100)
        fields = dict(quantity=1, price=25, shipment_no=1)
        fields.update(item_kwargs)
        OrderItem.objects.create(order=order, product=self.product, **fields)
        return order

    # --- the regression -----------------------------------------------------

    def test_freight_job_renders_a_real_status_and_timeline(self):
        job = self.make_freight_job()
        block = self.track(job.tracking_number).context['result']['blocks'][0]

        self.assertIsInstance(
            block['status'], dict,
            'the freight builder must produce the same status shape as the order '
            'builder, or the template renders an empty badge and empty timeline',
        )
        self.assertEqual(block['status']['label'], 'Dispatched')
        self.assertEqual(len(block['status']['steps']), len(ShipmentStatus.STATUS_CHOICES))
        self.assertTrue(block['status']['confirmed'])

    def test_the_badge_and_timeline_actually_reach_the_html(self):
        """The symptom the customer reported, not just the context behind it."""
        job = self.make_freight_job()
        body = self.track(job.tracking_number).content.decode()
        self.assertIn('Dispatched', body)
        self.assertIn('ship-step', body)

    def test_the_timeline_marks_progress_up_to_the_current_step(self):
        job = self.make_freight_job(status=ShipmentStatus.STATUS_DISPATCHED)
        steps = self.track(job.tracking_number).context['result']['blocks'][0]['status']['steps']
        done = [s['label'] for s in steps if s['done']]
        self.assertEqual(done[-1], 'Dispatched')
        self.assertEqual(len(done), ShipmentStatus.STATUS_ORDER.index(
            ShipmentStatus.STATUS_DISPATCHED) + 1)
        self.assertFalse(steps[-1]['done'],
                         'nothing past the current step may be marked done')

    def test_both_builders_agree_on_the_status_keys(self):
        """The contract itself, not one example of it."""
        job = self.make_freight_job()
        freight = self.track(job.tracking_number).context['result']['blocks'][0]
        product_block = self.track(self.make_order().tracking_number).context['result']['blocks'][0]

        self.assertEqual(
            set(freight['status'].keys()), set(product_block['status'].keys()),
            'the two tracking builders have drifted apart again',
        )

    def test_a_delivered_job_is_flagged_as_such(self):
        job = self.make_freight_job(status=ShipmentStatus.STATUS_DELIVERED)
        result = self.track(job.tracking_number).context['result']
        self.assertTrue(result['blocks'][0]['status']['is_delivered'])
        self.assertTrue(result['all_delivered'])

    def test_an_unrecognised_status_degrades_instead_of_erroring(self):
        """The page is public and unauthenticated; it must not 500."""
        from orders.models import LogisticsOrder
        job = self.make_freight_job()
        LogisticsOrder.objects.filter(pk=job.pk).update(status='something-invented')
        response = self.track(job.tracking_number)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['result']['blocks'][0]['status']['step_index'], 0)

    # --- pictures -----------------------------------------------------------

    def test_a_freight_job_without_a_photo_reports_no_image(self):
        """'' rather than a broken <img>. The template guards on this."""
        job = self.make_freight_job()
        block = self.track(job.tracking_number).context['result']['blocks'][0]
        self.assertEqual(block['image'], '')

    def test_a_freight_job_passes_its_photo_through(self):
        job = self.make_freight_job(photo=self.upload('crate.gif'))
        block = self.track(job.tracking_number).context['result']['blocks'][0]
        self.assertTrue(block['image'], 'the uploaded photo never reached the page')
        self.assertEqual(block['image'], block['items'][0]['image'])

    def test_order_items_carry_their_product_image(self):
        from products.models import ProductImage
        ProductImage.objects.create(product=self.product, image=self.upload('p.gif'))
        block = self.track(self.make_order(quantity=2).tracking_number).context['result']['blocks'][0]
        self.assertTrue(block['items'][0]['image'], 'the product photo never reached the page')
        self.assertEqual(block['image'], block['items'][0]['image'],
                         'the block lead image should be the first item that has one')

    def test_an_item_whose_product_has_no_image_still_renders(self):
        response = self.track(self.make_order().tracking_number)
        self.assertEqual(response.status_code, 200)
        block = response.context['result']['blocks'][0]
        self.assertEqual(block['items'][0]['image'], '')
        self.assertEqual(block['image'], '')

    # --- the privacy contract still holds -----------------------------------

    def test_no_price_or_customer_detail_leaks_onto_the_page(self):
        """
        The reference is shareable, so anyone holding it sees this page. Adding
        pictures must not have widened what it discloses.
        """
        order = Order.objects.create(customer=self.customer, total=999)
        OrderItem.objects.create(order=order, product=self.product, quantity=1,
                                 price=777, shipment_no=1)
        body = self.track(order.tracking_number).content.decode()
        self.assertNotIn('777', body)
        self.assertNotIn('999', body)
        self.assertNotIn('Gulf Trading', body)
        self.assertNotIn('gulf@example.com', body)


class ProductLookupTests(ShipmentPipelineTestCase):
    """
    The catalogue search behind the order builder and quotation picker.

    The order list used to embed every product in its HTML so the picker could
    filter client-side, which made the busiest page in the back office grow with
    the catalogue — 169 KB at 30 products, 810 KB at 500. These cover the
    endpoint that replaced it.
    """

    def setUp(self):
        super().setUp()
        from products.models import Product
        self.extra = [
            Product.objects.create(name='Blue Widget', sku='BW-1', price=5, moq=1),
            Product.objects.create(name='Red Widget', sku='RW-2', price=6, moq=1),
            Product.objects.create(name='Draft Thing', sku='DT-3', price=7, moq=1, is_draft=True),
        ]

    def lookup(self, **params):
        return self.client.get('/orders/product-lookup/', params).json()

    def test_it_searches_by_name(self):
        names = [p['name'] for p in self.lookup(q='Blue')['products']]
        self.assertIn('Blue Widget', names)
        self.assertNotIn('Red Widget', names)

    def test_it_searches_by_sku(self):
        names = [p['name'] for p in self.lookup(q='RW-2')['products']]
        self.assertEqual(names, ['Red Widget'])

    def test_words_match_in_any_order_and_spacing(self):
        """Typing "widget red" or doubled spaces must still find "Red Widget"."""
        for query in ('widget red', 'red  widget', ' Red Widget '):
            names = [p['name'] for p in self.lookup(q=query)['products']]
            self.assertEqual(names, ['Red Widget'], query)

    def test_words_can_mix_name_and_sku(self):
        names = [p['name'] for p in self.lookup(q='widget RW-2')['products']]
        self.assertEqual(names, ['Red Widget'])

    def test_a_product_beyond_the_first_page_is_found(self):
        """
        The order builder's dropdown only has the first page of products in the
        browser, so this endpoint is the only way to reach the rest. A product
        that sorts after a full page of others must still come back by name.
        """
        from products.models import Product
        from orders.views import ORDER_BUILDER_PAGE_SIZE

        Product.objects.bulk_create([
            Product(name='Aaa Filler %03d' % i, price=1, moq=1)
            for i in range(ORDER_BUILDER_PAGE_SIZE + 10)])
        Product.objects.create(name='Zebra Lamp', sku='ZL-9', price=3, moq=1)

        self.assertNotIn('Zebra Lamp', [p['name'] for p in self.lookup()['products']])
        names = [p['name'] for p in self.lookup(q='zebra')['products']]
        self.assertEqual(names, ['Zebra Lamp'])

    def test_drafts_are_never_offered(self):
        """A draft is not ready to sell, so it must not reach a quotation."""
        names = [p['name'] for p in self.lookup(q='Draft')['products']]
        self.assertEqual(names, [])

    def test_it_returns_the_fields_the_builder_needs(self):
        row = self.lookup(q='Blue')['products'][0]
        for field in ('id', 'name', 'sku', 'price', 'weight',
                      'carton_qty', 'carton_length', 'carton_width',
                      'carton_height', 'image'):
            self.assertIn(field, row)

    def test_it_does_not_leak_internal_fields(self):
        """
        An explicit field list, not the whole model.

        This response is read by the browser; serialising the model wholesale
        would hand cost prices and supplier notes to anyone with the page open.
        """
        row = self.lookup(q='Blue')['products'][0]
        for leaked in ('source_url', 'cost', 'cost_price', 'supplier', 'is_private'):
            self.assertNotIn(leaked, row)

    def test_fetching_by_ids_ignores_the_search(self):
        """
        How a selection survives a new search, and how the edit modal gets a
        product that falls outside the first page.
        """
        wanted = [self.extra[0].id, self.extra[1].id]
        ids = ','.join(str(i) for i in wanted)
        returned = {p['id'] for p in self.lookup(ids=ids)['products']}
        self.assertEqual(returned, set(wanted))

    def test_results_are_capped_and_say_so(self):
        from products.models import Product
        from orders.views import ORDER_BUILDER_PAGE_SIZE

        Product.objects.bulk_create([
            Product(name='Bulk Item %03d' % i, price=1, moq=1)
            for i in range(ORDER_BUILDER_PAGE_SIZE + 25)])

        data = self.lookup(q='Bulk Item')
        self.assertEqual(len(data['products']), ORDER_BUILDER_PAGE_SIZE)
        self.assertTrue(data['truncated'])
        self.assertGreater(data['total'], ORDER_BUILDER_PAGE_SIZE)

    def test_a_customer_cannot_read_the_catalogue_lookup(self):
        """Cost-adjacent data: staff only, like every other orders endpoint."""
        from django.contrib.auth.models import User

        buyer = User.objects.create_user('buyer2', 'buyer2@example.com', 'pw')
        buyer.profile.role = 'customer'
        buyer.profile.save()
        self.client.force_login(buyer)

        response = self.client.get('/orders/product-lookup/')
        self.assertNotEqual(response.status_code, 200)


class OrderListWeightTests(ShipmentPipelineTestCase):
    """The order list must not grow with the catalogue."""

    def test_only_one_page_of_products_is_embedded(self):
        from products.models import Product
        from orders.views import ORDER_BUILDER_PAGE_SIZE

        Product.objects.bulk_create([
            Product(name='Catalogue %03d' % i, price=1, moq=1)
            for i in range(ORDER_BUILDER_PAGE_SIZE + 120)])

        context = self.client.get('/orders/').context
        self.assertLessEqual(len(context['products']), ORDER_BUILDER_PAGE_SIZE)
        self.assertGreater(context['product_total'], ORDER_BUILDER_PAGE_SIZE)

    def test_the_page_stops_growing_once_the_cap_is_reached(self):
        """
        The regression this whole change exists to prevent.

        Measured from ABOVE the cap, not from an empty catalogue: going from 1
        product to 50 legitimately adds 49 rows. What must not happen is the
        page continuing to grow after that, which is what took it from 169 KB at
        30 products to 810 KB at 500.
        """
        from products.models import Product
        from orders.views import ORDER_BUILDER_PAGE_SIZE

        Product.objects.bulk_create([
            Product(name='Base %03d' % i, price=1, moq=1)
            for i in range(ORDER_BUILDER_PAGE_SIZE + 10)])
        before = len(self.client.get('/orders/').content)

        Product.objects.bulk_create([
            Product(name='More %03d' % i, price=1, moq=1) for i in range(300)])
        after = len(self.client.get('/orders/').content)

        self.assertLess(abs(after - before), 2_000,
                        'order list changed by %d bytes for 300 more products'
                        % (after - before))


class ReportCategoryTests(ShipmentPipelineTestCase):
    """
    Categories in the two report exports.

    WHY THESE

    The report answered "what sold" without ever saying what KIND of thing
    sold, which is the question a sourcing business asks before deciding what
    to go and buy more of. Both formats are tested together because they are
    one report: the PDF gaining a section the Excel lacked would be the sort of
    difference that gets noticed in a meeting rather than in a test.
    """

    def setUp(self):
        super().setUp()
        from products.models import Category

        # get_or_create: the migrations seed a default category set.
        tools, _ = Category.objects.get_or_create(name='Tools & Machinery')
        kitchen, _ = Category.objects.get_or_create(name='Home & Kitchen')
        self.drill = Product.objects.create(name='Report Drill', price=50, moq=1,
                                            category=tools)
        self.kettle = Product.objects.create(name='Report Kettle', price=20, moq=1,
                                             category=kitchen)

        order = Order.objects.create(customer=self.customer, total=300)
        OrderItem.objects.create(order=order, product=self.drill,
                                 quantity=4, price=50, shipment_no=1)
        OrderItem.objects.create(order=order, product=self.kettle,
                                 quantity=5, price=20, shipment_no=1)

    def workbook(self):
        import io as _io

        import openpyxl
        response = self.client.get('/orders/reports/export-excel/')
        self.assertEqual(response.status_code, 200)
        return openpyxl.load_workbook(_io.BytesIO(response.content))

    def pdf_text(self):
        import io as _io

        try:
            import pypdf
        except ImportError:  # pragma: no cover - depends on the environment
            self.skipTest('pypdf is not installed')
        response = self.client.get('/orders/reports/export-pdf/')
        self.assertEqual(response.status_code, 200)
        reader = pypdf.PdfReader(_io.BytesIO(response.content))
        return '\n'.join(page.extract_text() for page in reader.pages)

    # -- Excel -------------------------------------------------------------

    def test_top_products_names_the_category(self):
        sheet = self.workbook()['Top Products']
        headers = [cell.value for cell in sheet[1]]
        self.assertIn('Category', headers)
        column = headers.index('Category') + 1
        values = {sheet.cell(row=r, column=column).value
                  for r in range(2, sheet.max_row + 1)}
        self.assertIn('Tools & Machinery', values)
        self.assertIn('Home & Kitchen', values)

    def test_the_workbook_has_a_revenue_by_category_sheet(self):
        self.assertIn('Revenue by Category', self.workbook().sheetnames)

    def test_the_category_totals_add_up(self):
        sheet = self.workbook()['Revenue by Category']
        totals = {
            sheet.cell(row=r, column=1).value: sheet.cell(row=r, column=3).value
            for r in range(2, sheet.max_row + 1)
            if sheet.cell(row=r, column=1).value
        }
        self.assertEqual(totals['Tools & Machinery'], 200)   # 4 x 50
        self.assertEqual(totals['Home & Kitchen'], 100)      # 5 x 20

    def test_share_is_a_real_percentage_not_a_string(self):
        """
        Written as a number under a 0.0% format so the column can be summed and
        charted, rather than as text that only looks like a percentage.
        """
        sheet = self.workbook()['Revenue by Category']
        self.assertEqual(sheet.cell(row=2, column=4).number_format, '0.0%')
        self.assertAlmostEqual(sheet.cell(row=2, column=4).value, 200 / 300, places=4)

    def test_an_uncategorised_product_is_labelled_not_blank(self):
        loose = Product.objects.create(name='Report Orphan', price=10, moq=1)
        order = Order.objects.create(customer=self.customer, total=10)
        OrderItem.objects.create(order=order, product=loose,
                                 quantity=1, price=10, shipment_no=1)
        sheet = self.workbook()['Revenue by Category']
        names = {sheet.cell(row=r, column=1).value for r in range(2, sheet.max_row + 1)}
        self.assertIn('Uncategorised', names)

    # -- PDF ---------------------------------------------------------------

    def test_the_pdf_says_the_same_thing(self):
        text = self.pdf_text()
        self.assertIn('Revenue by Category', text)
        self.assertIn('Tools & Machinery', text)
        self.assertIn('Home & Kitchen', text)

    # -- the division guard ------------------------------------------------

    def test_a_period_with_no_revenue_does_not_divide_by_zero(self):
        """
        Everything given away, or priced at zero: the share column would
        otherwise take the report down rather than print a dash.
        """
        OrderItem.objects.all().update(price=0)
        Order.objects.all().update(total=0)
        self.assertEqual(self.client.get('/orders/reports/export-excel/').status_code, 200)
        self.assertEqual(self.client.get('/orders/reports/export-pdf/').status_code, 200)


class ChartDataEscapingTests(ShipmentPipelineTestCase):
    """
    Names printed into chart <script> blocks must not be able to end the tag.

    Customers register themselves and product names come from supplier pages,
    so either could carry ``</script><script>...``. Printed with plain
    ``json.dumps`` + ``|safe`` that ran code in the admin's browser.
    """

    HOSTILE = '</script><script>alert(1)</script>'

    def setUp(self):
        super().setUp()
        self.customer.name = self.HOSTILE
        self.customer.save()
        self.product.name = 'Widget ' + self.HOSTILE
        self.product.save()
        self.make_order()

    def assert_no_breakout(self, path):
        html = self.client.get(path).content.decode()
        self.assertNotIn('<script>alert(1)', html)

    def test_reports_page(self):
        self.assert_no_breakout('/orders/reports/')

    def test_dashboard(self):
        self.assert_no_breakout('/dashboard/')

    def test_the_names_still_reach_the_chart(self):
        """Escaped, not removed: the chart must still show the real name."""
        html = self.client.get('/orders/reports/').content.decode()
        self.assertIn('\u003C/script\u003E', html)
