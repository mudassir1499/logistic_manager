"""
Tests for the product list's filters and its bulk actions.

WHY THESE IN PARTICULAR

The product list offers to act on "all N matching the current filter". That
sentence is a promise, and the only thing that keeps it honest is the list and
the bulk endpoint deriving N from identical logic. They used to disagree: the
list counted public and private products, while the endpoint excluded private
ones outright, so a bulk action on "all 30" silently landed on 24 with nothing
to show that it had.

The first class below pins that agreement. The second covers tagging, which is
the reason the whole-filter scope matters — labelling forty products is the job
that never gets done one dialog at a time.
"""

import csv
import io as _io
import shutil
import tempfile
import xml.etree.ElementTree as ET

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from decimal import Decimal

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from customers.models import Customer

from products.models import (Category, Product, ProductImage, ProductTag,
                             ProductVariant)
from settings_manager.models import CompanySettings


class ProductListScopeTestCase(TestCase):
    """
    The list and the bulk endpoint must describe the same set of products.
    """

    def setUp(self):
        self.staff = User.objects.create_user('ops', 'ops@example.com', 'pw')
        profile = self.staff.profile
        profile.role = 'admin'
        profile.save()
        self.client.force_login(self.staff)

        self.category = Category.objects.create(name='Power Tools')

        # A deliberately mixed catalogue: the bug only shows up when the three
        # visibility bands hold different numbers of products.
        self.public = [
            Product.objects.create(name=f'Public {i}', price=10, moq=1,
                                   category=self.category)
            for i in range(5)
        ]
        self.private = [
            Product.objects.create(name=f'Private {i}', price=10, moq=1,
                                   category=self.category, is_private=True)
            for i in range(3)
        ]
        self.drafts = [
            Product.objects.create(name=f'Draft {i}', price=10, moq=1,
                                   category=self.category, is_draft=True)
            for i in range(2)
        ]

    def bulk(self, **payload):
        return self.client.post('/products/bulk-action/', payload,
                                content_type='application/json').json()

    def test_default_list_shows_every_visibility_band(self):
        """
        The list is one queryset, not a public grid plus a private annexe.
        """
        response = self.client.get('/products/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 10)
        self.assertEqual(response.context['visible_counts']['private'], 3)
        self.assertEqual(response.context['visible_counts']['draft'], 2)
        # 'public' means a customer can actually see it, so a draft does not
        # count towards it even though the draft is not private.
        self.assertEqual(response.context['visible_counts']['public'], 5)

    def test_visibility_filter_narrows_the_list(self):
        for band, expected in [('private', 3), ('draft', 2), ('public', 5), ('all', 10)]:
            with self.subTest(band=band):
                response = self.client.get('/products/', {'visibility': band})
                self.assertEqual(response.context['total_count'], expected)

    def test_unknown_visibility_widens_rather_than_crashing(self):
        """A hand-edited URL should not 500."""
        response = self.client.get('/products/', {'visibility': 'nonsense'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['visibility'], 'all')
        self.assertEqual(response.context['total_count'], 10)

    def test_whole_filter_action_reaches_private_products(self):
        """
        THE REGRESSION THIS FILE EXISTS FOR.

        The endpoint used to force the filtered scope to public-only, so a bulk
        action offered as covering all ten products touched five of them.
        """
        result = self.bulk(action='draft', ids=[], scope='filtered',
                           q='', visibility='all')
        self.assertTrue(result['success'], result)
        self.assertEqual(
            Product.objects.filter(is_draft=True).count(), 10,
            'a whole-filter action skipped the private or draft products',
        )

    def test_whole_filter_action_honours_the_band_on_screen(self):
        """Filtering to private must not act on public rows."""
        result = self.bulk(action='draft', ids=[], scope='filtered',
                           q='', visibility='private')
        self.assertTrue(result['success'], result)
        self.assertEqual(Product.objects.filter(is_private=True, is_draft=True).count(), 3)
        self.assertEqual(Product.objects.filter(is_private=False, is_draft=True).count(), 2,
                         'only the two pre-existing drafts should still be drafts')

    def test_list_count_matches_what_the_endpoint_acts_on(self):
        """
        Whatever number the page puts in front of the operator is the number of
        products the action touches.
        """
        for band in ('all', 'public', 'private', 'draft'):
            with self.subTest(band=band):
                shown = self.client.get(
                    '/products/', {'visibility': band}).context['total_count']
                acted = self.bulk(action='add_tags', ids=[], scope='filtered',
                                  q='', visibility=band,
                                  new_tags=[f'count-probe-{band}'])
                self.assertIn(str(shown), acted['message'])

    def test_delete_is_still_barred_from_the_whole_filter_scope(self):
        """
        Every other action here is reversible; this one is not, so it stays
        behind an explicit selection.
        """
        result = self.bulk(action='delete', ids=[], scope='filtered',
                           q='', visibility='all')
        self.assertFalse(result['success'])
        self.assertEqual(Product.objects.count(), 10)


class ProductTagTestCase(TestCase):
    """Bulk tagging, and the guarantees that make tags safe to use."""

    def setUp(self):
        self.staff = User.objects.create_user('ops2', 'ops2@example.com', 'pw')
        profile = self.staff.profile
        profile.role = 'admin'
        profile.save()
        self.client.force_login(self.staff)
        self.products = [
            Product.objects.create(name=f'Item {i}', price=10, moq=1)
            for i in range(6)
        ]

    def bulk(self, **payload):
        return self.client.post('/products/bulk-action/', payload,
                                content_type='application/json').json()

    def test_typing_a_new_tag_creates_it(self):
        ids = [p.id for p in self.products[:3]]
        result = self.bulk(action='add_tags', ids=ids, new_tags=['Needs photos'])
        self.assertTrue(result['success'], result)
        tag = ProductTag.objects.get(name='Needs photos')
        self.assertEqual(tag.products.count(), 3)

    def test_new_tag_names_are_matched_case_insensitively(self):
        """"needs photos" must not become a second tag beside "Needs Photos"."""
        self.bulk(action='add_tags', ids=[self.products[0].id], new_tags=['Needs Photos'])
        self.bulk(action='add_tags', ids=[self.products[1].id], new_tags=['needs photos'])
        self.assertEqual(ProductTag.objects.filter(name__iexact='needs photos').count(), 1)
        self.assertEqual(ProductTag.objects.get(name='Needs Photos').products.count(), 2)

    def test_re_adding_an_existing_tag_is_a_no_op(self):
        ids = [p.id for p in self.products[:3]]
        self.bulk(action='add_tags', ids=ids, new_tags=['Ramadan'])
        tag = ProductTag.objects.get(name='Ramadan')
        result = self.bulk(action='add_tags', ids=ids, tag_ids=[tag.id])
        self.assertTrue(result['success'], result)
        self.assertEqual(tag.products.count(), 3)

    def test_remove_only_touches_the_tags_it_was_given(self):
        ids = [p.id for p in self.products[:2]]
        self.bulk(action='add_tags', ids=ids, new_tags=['Keep', 'Drop'])
        keep = ProductTag.objects.get(name='Keep')
        drop = ProductTag.objects.get(name='Drop')
        self.bulk(action='remove_tags', ids=ids, tag_ids=[drop.id])
        self.assertEqual(drop.products.count(), 0)
        self.assertEqual(keep.products.count(), 2, 'removing one tag took another with it')

    def test_tag_filter_requires_every_tag_not_any(self):
        """
        Chaining chips must narrow. If it widened, a second chip would be a
        strange way to ask for more results.
        """
        both = [p.id for p in self.products[:2]]
        one = [self.products[2].id]
        self.bulk(action='add_tags', ids=both + one, new_tags=['Alpha'])
        self.bulk(action='add_tags', ids=both, new_tags=['Beta'])
        alpha = ProductTag.objects.get(name='Alpha')
        beta = ProductTag.objects.get(name='Beta')

        response = self.client.get('/products/', {'tag': alpha.slug})
        self.assertEqual(response.context['total_count'], 3)
        response = self.client.get('/products/', {'tag': [alpha.slug, beta.slug]})
        self.assertEqual(response.context['total_count'], 2)

    def test_renaming_a_tag_keeps_its_slug(self):
        """
        The slug is what the ?tag= filter carries, so a bookmarked filtered view
        has to survive somebody fixing a typo in the label.
        """
        self.bulk(action='add_tags', ids=[self.products[0].id], new_tags=['Reddy to ship'])
        tag = ProductTag.objects.get(name='Reddy to ship')
        original_slug = tag.slug
        response = self.client.post(
            '/products/tags/save/',
            {'id': tag.id, 'name': 'Ready to ship', 'colour': '#15803d'},
            content_type='application/json').json()
        self.assertTrue(response['success'], response)
        tag.refresh_from_db()
        self.assertEqual(tag.name, 'Ready to ship')
        self.assertEqual(tag.slug, original_slug)

    def test_renaming_onto_an_existing_name_is_refused(self):
        self.bulk(action='add_tags', ids=[self.products[0].id], new_tags=['One', 'Two'])
        one = ProductTag.objects.get(name='One')
        response = self.client.post(
            '/products/tags/save/', {'id': one.id, 'name': 'two'},
            content_type='application/json').json()
        self.assertFalse(response['success'])
        one.refresh_from_db()
        self.assertEqual(one.name, 'One')

    def test_deleting_a_tag_leaves_the_products_alone(self):
        """What makes tags safe to experiment with."""
        ids = [p.id for p in self.products[:4]]
        self.bulk(action='add_tags', ids=ids, new_tags=['Temporary'])
        tag = ProductTag.objects.get(name='Temporary')
        response = self.client.post(
            '/products/tags/delete/', {'id': tag.id},
            content_type='application/json').json()
        self.assertTrue(response['success'], response)
        self.assertFalse(ProductTag.objects.filter(id=tag.id).exists())
        self.assertEqual(Product.objects.count(), 6)

    def test_clear_strips_every_tag_from_the_selection_only(self):
        kept, cleared = self.products[0].id, self.products[1].id
        self.bulk(action='add_tags', ids=[kept, cleared], new_tags=['A', 'B'])
        self.bulk(action='clear_tags', ids=[cleared])
        self.assertEqual(Product.objects.get(id=cleared).tags.count(), 0)
        self.assertEqual(Product.objects.get(id=kept).tags.count(), 2)

    def test_an_action_naming_no_tag_is_refused(self):
        result = self.bulk(action='add_tags', ids=[self.products[0].id],
                           tag_ids=[], new_tags=[])
        self.assertFalse(result['success'])


# Uploads happen here, and the Django test runner isolates the database but NOT
# MEDIA_ROOT - without this the test images land next to real product photos.
_FEED_MEDIA = tempfile.mkdtemp(prefix='feed-tests-')


@override_settings(MEDIA_ROOT=_FEED_MEDIA)
class ProductFeedTests(TestCase):
    """
    The advertising catalogue served to Meta and TikTok.

    WHY THESE IN PARTICULAR

    This feed is a PUBLIC, UNAUTHENTICATED URL. It has to be — Meta's crawler
    arrives with no session and no token, so a login wall means an empty
    catalogue and no ads. That makes it the one endpoint where a filtering
    mistake is not a bug on a staff screen but a disclosure to anybody who
    guesses the address.

    Two things therefore matter more than the formatting: that `source_url`
    never appears, because the supplier's listing IS the agency's margin, and
    that private and draft products stay out.
    """

    PIXEL = (b'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_FEED_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        settings = CompanySettings.get_settings()
        settings.site_url = 'https://example.test'
        settings.company_name = 'Test Sourcing'
        settings.currency = 'AED'
        settings.save()

        self.category = Category.objects.create(name='Power Tools')
        self.product = self.make_product('Impact Drill', price=100)

    def photo(self, name='p.gif'):
        import base64
        return SimpleUploadedFile(name, base64.b64decode(self.PIXEL),
                                  content_type='image/gif')

    def make_product(self, name, price=100, with_image=True, **kwargs):
        product = Product.objects.create(
            name=name, price=price, moq=10, category=self.category, **kwargs)
        if with_image:
            ProductImage.objects.create(product=product, image=self.photo())
        return product

    def csv_rows(self):
        response = self.client.get('/products/feed.csv')
        self.assertEqual(response.status_code, 200)
        return list(csv.DictReader(_io.StringIO(response.content.decode())))

    # --- the disclosure guarantees -----------------------------------------

    def test_the_feed_is_reachable_without_logging_in(self):
        """
        Meta and TikTok fetch this with no credentials. If it ever starts
        requiring auth the catalogue silently empties.
        """
        self.assertEqual(self.client.get('/products/feed.csv').status_code, 200)
        self.assertEqual(self.client.get('/products/feed.xml').status_code, 200)

    def test_the_supplier_link_never_appears(self):
        """
        THE ONE THAT MATTERS MOST.

        source_url points at the 1688 or Alibaba listing this was sourced from.
        Anyone holding it can go straight to the factory and cut the agency out
        entirely. It belongs on staff screens and nowhere else.
        """
        self.product.source_url = 'https://detail.1688.com/offer/9999.html'
        self.product.save(update_fields=['source_url'])

        for url in ('/products/feed.csv', '/products/feed.xml'):
            with self.subTest(feed=url):
                body = self.client.get(url).content.decode().lower()
                self.assertNotIn('1688', body)
                self.assertNotIn('alibaba', body)
                self.assertNotIn('detail.1688.com', body)

    def test_private_products_are_not_advertised(self):
        hidden = self.make_product('Customer Exclusive', is_private=True)
        ids = [r['title'] for r in self.csv_rows()]
        self.assertNotIn(hidden.name, ids)
        self.assertIn(self.product.name, ids)

    def test_draft_products_are_not_advertised(self):
        draft = self.make_product('Half Finished', is_draft=True)
        titles = [r['title'] for r in self.csv_rows()]
        self.assertNotIn(draft.name, titles)

    def test_a_product_with_no_photo_is_left_out(self):
        """Meta rejects any item without an image, so emitting one buys nothing."""
        naked = self.make_product('No Photo Here', with_image=False)
        titles = [r['title'] for r in self.csv_rows()]
        self.assertNotIn(naked.name, titles)

    # --- the format Meta actually accepts ----------------------------------

    def test_prices_use_metas_amount_and_currency_format(self):
        """
        '100.00 AED'. A malformed price is the commonest reason a whole feed is
        rejected, and the rejection is reported inside Commerce Manager rather
        than to us.
        """
        import re
        for row in self.csv_rows():
            self.assertRegex(row['price'], r'^\d+\.\d{2} [A-Z]{3}$')

    def test_links_and_images_are_absolute(self):
        """A crawler on Meta's infrastructure cannot resolve a relative path."""
        for row in self.csv_rows():
            self.assertTrue(row['link'].startswith('https://example.test/'))
            self.assertTrue(row['image_link'].startswith('https://example.test/'))

    def test_every_row_has_the_fields_meta_requires(self):
        required = ['id', 'title', 'description', 'availability',
                    'condition', 'price', 'link', 'image_link', 'brand']
        for row in self.csv_rows():
            for field in required:
                self.assertTrue(row[field], f'{field} is empty for {row["id"]}')

    def test_the_description_is_more_than_a_repeat_of_the_title(self):
        """
        Product has no description field, so one is synthesised. Meta penalises
        a description that merely restates the title.
        """
        row = self.csv_rows()[0]
        self.assertGreater(len(row['description']), len(row['title']))
        self.assertIn('Minimum order', row['description'])

    def test_the_xml_is_well_formed_and_uses_the_google_namespace(self):
        body = self.client.get('/products/feed.xml').content
        root = ET.fromstring(body)          # raises on malformed XML
        items = root.findall('.//item')
        self.assertTrue(items)
        ns = {'g': 'http://base.google.com/ns/1.0'}
        self.assertIsNotNone(items[0].find('g:id', ns))
        self.assertIsNotNone(items[0].find('g:price', ns))

    def test_a_name_with_xml_special_characters_does_not_break_the_feed(self):
        self.make_product('Drill <Pro> & "Max"')
        ET.fromstring(self.client.get('/products/feed.xml').content)

    # --- variations ---------------------------------------------------------

    def test_each_variation_is_its_own_row_sharing_an_item_group(self):
        """
        The customer buys a specific colour at a specific price, so that is what
        the ad must show and link to. Collapsing variations into one parent row
        is why dynamic ads so often quote a price the visitor never saw.
        """
        self.product.sku = 'DRILL-1'
        self.product.save(update_fields=['sku'])
        ProductVariant.objects.create(product=self.product, name='Blue', price=110)
        ProductVariant.objects.create(product=self.product, name='Red', price=120)

        rows = [r for r in self.csv_rows() if r['item_group_id'] == 'DRILL-1']
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['price'] for r in rows}, {'110.00 AED', '120.00 AED'})
        self.assertEqual(len({r['id'] for r in rows}), 2, 'variation ids must be unique')

    def test_a_variation_with_zero_stock_is_marked_out_of_stock(self):
        """
        stock is nullable and null means "not tracked", which is not the same as
        none left. Only an explicit 0 may mark something unavailable.
        """
        ProductVariant.objects.create(product=self.product, name='Gone', price=1, stock=0)
        ProductVariant.objects.create(product=self.product, name='Untracked', price=2, stock=None)

        rows = {r['title']: r for r in self.csv_rows()}
        self.assertEqual(rows[f'{self.product.name} — Gone']['availability'], 'out of stock')
        self.assertEqual(rows[f'{self.product.name} — Untracked']['availability'], 'in stock')

    # --- the staff-facing health page --------------------------------------

    def test_the_health_page_reports_what_is_being_dropped(self):
        self.make_product('No Photo Here', with_image=False)
        staff = User.objects.create_user('feedops', 'f@example.com', 'pw')
        profile = staff.profile
        profile.role = 'admin'
        profile.save()
        self.client.force_login(staff)

        response = self.client.get('/products/feed-health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['skipped_no_image'], 1)
        self.assertIn('No Photo Here',
                      [p.name for p in response.context['missing_image_products']])

    def test_the_health_page_is_staff_only(self):
        """The feeds are public; the page describing the catalogue is not."""
        response = self.client.get('/products/feed-health/')
        self.assertIn(response.status_code, (302, 403))


class AdminApiTests(TestCase):
    """
    The endpoints the back-office mobile app runs on.

    WHY THESE

    The dashboard is one call that returns figures from six different modules,
    which makes it the easiest place in the codebase to leak something. A
    coordinator who can only see orders must not learn the ledger balance
    because a phone screen wanted a tidy layout.
    """

    def setUp(self):
        self.admin = User.objects.create_user('apiadmin', 'a@example.com', 'pw')
        profile = self.admin.profile
        profile.role = 'admin'
        for field in profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, True)
        profile.save()

        # Deliberately narrow: orders only.
        self.coordinator = User.objects.create_user('apicoord', 'c@example.com', 'pw')
        coord = self.coordinator.profile
        coord.role = 'staff'
        for field in coord.MODULE_FIELD_MAP.values():
            setattr(coord, field, False)
        coord.perm_orders = True
        coord.save()

    def test_the_dashboard_needs_a_login(self):
        response = self.client.get('/api/v1/dashboard/')
        self.assertIn(response.status_code, (401, 403))

    def test_an_admin_sees_every_block(self):
        self.client.force_login(self.admin)
        data = self.client.get('/api/v1/dashboard/').json()
        for block in ('orders', 'products', 'customers', 'support', 'ledger'):
            self.assertIn(block, data, f'{block} missing for an admin')

    def test_a_coordinator_sees_only_their_module(self):
        """
        Absent, not zeroed. A zero says "nothing to do"; the truth is "not your
        department", and the difference matters when somebody is deciding
        whether to chase something.
        """
        self.client.force_login(self.coordinator)
        data = self.client.get('/api/v1/dashboard/').json()
        self.assertIn('orders', data)
        for block in ('ledger', 'customers', 'support', 'products'):
            self.assertNotIn(block, data, f'{block} leaked to an orders-only account')

    def test_ledger_totals_are_numbers_not_nulls(self):
        """
        Sum() returns None over an empty table. A dashboard rendering
        "None outstanding" reads as a broken screen.
        """
        self.client.force_login(self.admin)
        ledger = self.client.get('/api/v1/dashboard/').json()['ledger']
        for key in ('credit', 'debit', 'outstanding'):
            self.assertIsNotNone(ledger[key])
            float(ledger[key])          # raises if it is not a number

    def test_tags_are_back_office_only(self):
        self.assertIn(self.client.get('/api/v1/tags/').status_code, (401, 403))

    def test_a_tag_slug_cannot_be_rewritten_through_the_api(self):
        """
        The slug is what the ?tag= filter carries, so a bookmarked filtered view
        has to survive a rename. Same rule as products.views.tag_save.
        """
        tag = ProductTag.objects.create(name='Needs Photos')
        original = tag.slug
        self.client.force_login(self.admin)
        response = self.client.patch(
            f'/api/v1/tags/{tag.id}/',
            {'name': 'Needs Photography', 'slug': 'something-else'},
            content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        tag.refresh_from_db()
        self.assertEqual(tag.name, 'Needs Photography')
        self.assertEqual(tag.slug, original)


class InstallableAppTests(TestCase):
    """
    The plumbing that makes the back-office installable on a phone.

    The scope rule is the whole reason there is a route for this. A service
    worker may only control URLs at or below the path it is SERVED from, so
    /static/sw.js registers happily and then controls nothing but /static/ —
    a failure that looks exactly like success.
    """

    def test_the_service_worker_is_served_from_the_root(self):
        response = self.client.get('/sw.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/javascript')

    def test_the_service_worker_is_not_cached(self):
        """A stale worker keeps an old cache version alive on every device."""
        self.assertEqual(self.client.get('/sw.js')['Cache-Control'], 'no-cache')

    def test_the_worker_never_caches_anything_outside_static(self):
        """
        This runs on a staff site behind a login, and a service-worker cache
        survives logout on a shared handset. Caching a page would leave customer
        data readable by whoever picks the phone up next.
        """
        body = self.client.get('/sw.js').content.decode()
        self.assertIn("url.pathname.startsWith('/static/')", body)
        self.assertIn("request.method !== 'GET'", body)

    @staticmethod
    def _manifest():
        """
        Read the manifest off disk rather than over HTTP.

        The test runner sets DEBUG=False, where Django serves no static files at
        all, so a request for /static/manifest.json is a 404 that says nothing
        about production. The file on disk is what collectstatic ships and what
        the browser is eventually handed.
        """
        import json
        from pathlib import Path
        from django.conf import settings as dj_settings
        path = Path(dj_settings.STATICFILES_DIRS[0]) / 'manifest.json'
        return json.loads(path.read_text(encoding='utf-8'))

    def test_the_manifest_is_valid_json_and_named_json(self):
        """
        .json, not .webmanifest: WhiteNoise serves the latter as
        application/octet-stream, Safari refuses it, and the install prompt
        never appears.
        """
        from pathlib import Path
        from django.conf import settings as dj_settings
        static_dir = Path(dj_settings.STATICFILES_DIRS[0])
        self.assertTrue((static_dir / 'manifest.json').exists())
        self.assertFalse((static_dir / 'manifest.webmanifest').exists(),
                         'the .webmanifest copy would be served as octet-stream')
        self.assertTrue(self._manifest())

    def test_the_manifest_meets_androids_install_requirements(self):
        manifest = self._manifest()
        self.assertEqual(manifest['display'], 'standalone')
        self.assertTrue(manifest['start_url'])
        sizes = {icon['sizes'] for icon in manifest['icons']}
        # Android requires both, and a maskable icon is what stops the launcher
        # drawing a white box behind the logo.
        self.assertIn('192x192', sizes)
        self.assertIn('512x512', sizes)
        self.assertTrue(any(i.get('purpose') == 'maskable' for i in manifest['icons']))


class BulkUploadRoundTripTests(TestCase):
    """
    The downloadable template, and what happens when it comes back.

    WHY THESE

    The template used to carry its two example rows inside the data region the
    importer reads, and nothing in the file distinguished them from anything a
    user had typed. Downloading the template and uploading it unchanged added
    "Red Widget Pro" and "Blue Water Bottle" to the live catalogue - silently,
    and reported as a success. Every template issued before the fix still has
    them, so both halves are tested: the new file must not carry examples into
    the data region, and the importer must refuse them wherever they appear.
    """

    XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

    def setUp(self):
        self.admin = User.objects.create_user('xadmin', 'x@example.com', 'pw')
        profile = self.admin.profile
        profile.role = 'admin'
        for field in profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, True)
        profile.save()
        self.client.force_login(self.admin)

    def template_bytes(self):
        response = self.client.get('/products/bulk-upload-template/')
        self.assertEqual(response.status_code, 200)
        return response.content

    def upload(self, body, name='products_template.xlsx'):
        import json
        upload = SimpleUploadedFile(name, body, content_type=self.XLSX)
        response = self.client.post('/products/bulk-upload/', {'csv_file': upload})
        return json.loads(response.content.decode())

    # -- the template itself ---------------------------------------------

    def test_the_data_sheet_ships_empty(self):
        """The sheet the importer reads must contain nothing but the header."""
        import openpyxl
        workbook = openpyxl.load_workbook(_io.BytesIO(self.template_bytes()))
        self.assertEqual(workbook.active.title, 'Products')
        data_rows = [
            row for row in workbook['Products'].iter_rows(min_row=8, values_only=True)
            if any(value not in (None, '') for value in row)
        ]
        self.assertEqual(data_rows, [], 'the Products tab still ships sample data')

    def test_the_examples_are_still_shown_somewhere(self):
        """
        They moved, they were not deleted. Someone filling this in by hand needs
        to see what a good row looks like.
        """
        import openpyxl
        workbook = openpyxl.load_workbook(_io.BytesIO(self.template_bytes()))
        self.assertIn('Example', workbook.sheetnames)
        text = ' '.join(
            str(cell)
            for row in workbook['Example'].iter_rows(values_only=True)
            for cell in row if cell
        )
        self.assertIn('Red Widget Pro', text)

    # -- the round trip ----------------------------------------------------

    def test_an_untouched_template_imports_nothing(self):
        before = Product.objects.count()
        result = self.upload(self.template_bytes())
        self.assertEqual(Product.objects.count(), before)
        self.assertEqual(result.get('created'), 0)

    def test_an_untouched_template_says_what_to_do(self):
        """
        "0 product(s) uploaded successfully" reported doing nothing as a win.
        """
        result = self.upload(self.template_bytes())
        self.assertFalse(result.get('success'))
        self.assertIn('Products', result.get('message', ''))

    # -- templates already in circulation ---------------------------------

    def old_style_workbook(self):
        """The pre-fix layout: header on row 7, examples on 8-9, real row on 10."""
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Products'
        for index, header in enumerate(['name', 'image', 'price', 'moq'], start=1):
            sheet.cell(row=7, column=index, value=header)
        rows = [
            (8,  ['Red Widget Pro', '', '12.50', '100']),
            (9,  ['Blue Water Bottle', '', '8.00', '50']),
            (10, ['Genuine Lamp 40W', '', '19.99', '25']),
        ]
        for row_number, values in rows:
            for index, value in enumerate(values, start=1):
                sheet.cell(row=row_number, column=index, value=value)
        buffer = _io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def test_example_rows_are_skipped_wherever_they_appear(self):
        result = self.upload(self.old_style_workbook(), name='old_template.xlsx')
        self.assertEqual(result.get('created'), 1, 'only the genuine row should import')
        self.assertFalse(Product.objects.filter(name='Red Widget Pro').exists())
        self.assertFalse(Product.objects.filter(name='Blue Water Bottle').exists())
        self.assertTrue(Product.objects.filter(name='Genuine Lamp 40W').exists())

    def test_a_real_product_sharing_an_example_name_still_imports(self):
        """
        The guard matches name, price AND moq. A genuine product called "Red
        Widget Pro" at a different price is a product, not the sample.
        """
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        for index, header in enumerate(['name', 'image', 'price', 'moq'], start=1):
            sheet.cell(row=1, column=index, value=header)
        for index, value in enumerate(['Red Widget Pro', '', '44.00', '5'], start=1):
            sheet.cell(row=2, column=index, value=value)
        buffer = _io.BytesIO()
        workbook.save(buffer)

        result = self.upload(buffer.getvalue(), name='mine.xlsx')
        self.assertEqual(result.get('created'), 1)
        self.assertTrue(Product.objects.filter(name='Red Widget Pro', moq=5).exists())

    # -- error reporting ---------------------------------------------------

    def test_errors_quote_the_row_number_in_the_file(self):
        """
        Messages were numbered from the first DATA row, while the template puts
        its header on row 7 - so a problem on row 9 was reported as "Row 3" and
        sent whoever was fixing it to the wrong line.
        """
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        for index, header in enumerate(['name', 'image', 'price', 'moq'], start=1):
            sheet.cell(row=7, column=index, value=header)
        for index, value in enumerate(['Bad Price Lamp', '', 'not-a-number', '25'], start=1):
            sheet.cell(row=9, column=index, value=value)
        buffer = _io.BytesIO()
        workbook.save(buffer)

        result = self.upload(buffer.getvalue(), name='rows.xlsx')
        self.assertTrue(any('Row 9' in e for e in result.get('errors', [])),
                        'expected the real sheet row, got %r' % result.get('errors'))

    def test_a_file_that_is_not_a_workbook_explains_itself(self):
        """
        openpyxl says "File is not a zip file", which is true and useless: a
        .xlsx IS a zip. The person holding the file needs to be told to re-save
        it.
        """
        result = self.upload(b'name,price,moq\nLamp,5,10', name='renamed.xlsx')
        self.assertFalse(result.get('success'))
        self.assertNotIn('zip', result.get('message', '').lower())
        self.assertIn('.xlsx', result.get('message', ''))


class CatalogueExportQueryTests(TestCase):
    """
    The catalogue export has to stay flat in the number of products.

    It asked for prefetch_related('images') and then called .first() on the
    related manager, which builds a fresh queryset with its own LIMIT 1 and
    ignores the prefetch entirely - one extra query per product. Measured
    before the fix: 38 queries for 32 products, 156 for 150, 406 for 400.
    """

    def setUp(self):
        self.admin = User.objects.create_user('qadmin', 'q@example.com', 'pw')
        profile = self.admin.profile
        profile.role = 'admin'
        for field in profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, True)
        profile.save()
        self.client.force_login(self.admin)

    def export_query_count(self, product_count):
        Product.objects.all().delete()
        Product.objects.bulk_create([
            Product(name='Probe %d' % i, price=10, moq=10, is_draft=False)
            for i in range(product_count)
        ])
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/products/catalogue-export/')
        self.assertEqual(response.status_code, 200)
        return len(queries)

    def test_the_query_count_does_not_follow_the_catalogue_size(self):
        # Warm-up first. The first export in a test also pays one-off costs -
        # the session and user lookups, and CompanySettings.get_settings()
        # filling its cache - which made a 5-product run cost MORE than a
        # 60-product one and read like an N+1 in reverse. Measuring only after
        # those are paid leaves the per-product cost, which is the thing under
        # test.
        self.export_query_count(1)
        small = self.export_query_count(5)
        large = self.export_query_count(60)
        self.assertEqual(
            small, large,
            'export issues %d queries for 5 products and %d for 60 - the '
            'prefetch is being bypassed again' % (small, large))


class ExportEmptyStateTests(TestCase):
    """
    What an export does when there is nothing to export.

    Both of these answered a download request with a bare sentence - one as
    text/plain under HTTP 200, which the browser saves as a stray file, and one
    as a 400 that reads like a broken link. Neither offered a way forward.
    """

    def setUp(self):
        self.admin = User.objects.create_user('eadmin', 'e@example.com', 'pw')
        profile = self.admin.profile
        profile.role = 'admin'
        for field in profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, True)
        profile.save()
        self.client.force_login(self.admin)

    def test_a_customer_with_no_products_is_sent_somewhere_useful(self):
        customer = Customer.objects.create(name='Empty Co')
        response = self.client.get('/customers/%s/quotation/' % customer.id, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.redirect_chain, 'should redirect, not answer with text')
        self.assertContains(response, 'no products assigned')

    def test_the_admin_shell_renders_messages_at_all(self):
        """
        The guard under the two tests above. templates/base.html had no
        messages block, so every messages.* call from orders, products and
        customers was posted into a template that dropped it - about thirty
        calls, including the two empty states here.
        """
        customer = Customer.objects.create(name='Silent Co')
        response = self.client.get('/customers/%s/quotation/' % customer.id, follow=True)
        self.assertContains(response, 'alert-warning')


class CatalogueImportTests(TestCase):
    """
    The catalogue export, filled in and sent back.

    WHY THESE

    Re-pricing was being done in Excel and typed back in by hand, which is
    where the typos came from. The round trip is only safe if three things
    hold, and each is a test below: a blank cell must not erase the value it
    was exported from, a row matching nothing must not quietly become a new
    product, and a bad number must name the row it is on.
    """

    XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

    def setUp(self):
        self.admin = User.objects.create_user('catadmin', 'cat@example.com', 'pw')
        profile = self.admin.profile
        profile.role = 'admin'
        for field in profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, True)
        profile.save()
        self.client.force_login(self.admin)

        # get_or_create: the migrations seed a default category set, and
        # creating one with the same name collides on the slug.
        self.category, _ = Category.objects.get_or_create(name='Tools & Machinery')
        self.product = Product.objects.create(
            name='Impact Drill 21V', sku='MLK-5000', price=Decimal('100.00'),
            moq=10, weight=Decimal('2.500'), category=self.category, is_draft=False)

    def export_workbook(self):
        import openpyxl
        response = self.client.get('/products/catalogue-export/')
        self.assertEqual(response.status_code, 200)
        return openpyxl.load_workbook(_io.BytesIO(response.content))

    def header_map(self, sheet):
        for row in range(1, 13):
            texts = {
                str(sheet.cell(row=row, column=c).value or '').strip().lower(): c
                for c in range(1, 20)
            }
            if 'sku' in texts:
                return row, texts
        self.fail('no header row with SKU in the catalogue export')

    def upload(self, workbook):
        import json
        buffer = _io.BytesIO()
        workbook.save(buffer)
        upload = SimpleUploadedFile('catalogue.xlsx', buffer.getvalue(),
                                    content_type=self.XLSX)
        response = self.client.post('/products/catalogue-import/',
                                    {'catalogue_file': upload})
        return json.loads(response.content.decode())

    # -- the export carries what the import needs -------------------------

    def test_the_export_names_the_sku_and_the_category(self):
        """
        Without a SKU there is nothing stable to match a row back to, and the
        sheet was sorted by category while never printing it.
        """
        workbook = self.export_workbook()
        _row, headers = self.header_map(workbook.active)
        self.assertIn('sku', headers)
        self.assertIn('category', headers)

    # -- the round trip ----------------------------------------------------

    def test_a_changed_price_comes_back(self):
        workbook = self.export_workbook()
        sheet = workbook.active
        header_row, headers = self.header_map(sheet)
        sheet.cell(row=header_row + 1, column=headers['price']).value = 88.5

        result = self.upload(workbook)
        self.product.refresh_from_db()
        self.assertTrue(result['success'], result)
        self.assertEqual(self.product.price, Decimal('88.50'))

    def test_an_unchanged_sheet_changes_nothing(self):
        workbook = self.export_workbook()
        result = self.upload(workbook)
        self.product.refresh_from_db()
        self.assertEqual(result['updated'], 0)
        self.assertEqual(self.product.price, Decimal('100.00'))

    def test_a_thousands_separator_is_read_as_a_number(self):
        """What someone gets by formatting the column in Excel."""
        workbook = self.export_workbook()
        sheet = workbook.active
        header_row, headers = self.header_map(sheet)
        sheet.cell(row=header_row + 1, column=headers['price']).value = '1,234.50'

        self.upload(workbook)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal('1234.50'))

    # -- the three safety properties --------------------------------------

    def test_a_blank_cell_does_not_erase_the_value(self):
        """
        The export writes an em dash wherever a product has no value, so
        reading blanks as "set to null" would mean every round trip wiped the
        fields that were empty when the sheet was made.
        """
        workbook = self.export_workbook()
        sheet = workbook.active
        header_row, headers = self.header_map(sheet)
        sheet.cell(row=header_row + 1, column=headers['price']).value = None
        sheet.cell(row=header_row + 1, column=headers['weight (kg)']).value = ''

        self.upload(workbook)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal('100.00'))
        self.assertEqual(self.product.weight, Decimal('2.500'))

    def test_a_row_matching_nothing_is_reported_not_created(self):
        workbook = self.export_workbook()
        sheet = workbook.active
        header_row, headers = self.header_map(sheet)
        sheet.cell(row=header_row + 1, column=headers['sku']).value = 'NOPE-0001'
        sheet.cell(row=header_row + 1, column=headers['product name']).value = 'Ghost'

        before = Product.objects.count()
        result = self.upload(workbook)
        self.assertEqual(Product.objects.count(), before, 'the import created a product')
        self.assertTrue(any('NOPE-0001' in e for e in result['errors']), result['errors'])

    def test_a_bad_number_names_its_row(self):
        workbook = self.export_workbook()
        sheet = workbook.active
        header_row, headers = self.header_map(sheet)
        target = header_row + 1
        sheet.cell(row=target, column=headers['price']).value = 'about twenty'

        result = self.upload(workbook)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal('100.00'), 'the row was applied anyway')
        self.assertTrue(any('Row %d' % target in e for e in result['errors']),
                        result['errors'])

    def test_a_file_that_is_not_a_catalogue_is_turned_away(self):
        from openpyxl import Workbook

        workbook = Workbook()
        workbook.active['A1'] = 'something else entirely'
        result = self.upload(workbook)
        self.assertFalse(result['success'])
        self.assertIn('header row', result['message'].lower())


class PrintableCatalogueTests(TestCase):
    """The catalogue people actually print and send to buyers."""

    def setUp(self):
        self.admin = User.objects.create_user('pcadmin', 'pc@example.com', 'pw')
        profile = self.admin.profile
        profile.role = 'admin'
        for field in profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, True)
        profile.save()
        self.client.force_login(self.admin)

        tools, _ = Category.objects.get_or_create(name='Tools & Machinery')
        kitchen, _ = Category.objects.get_or_create(name='Home & Kitchen')
        for name, category in (('Drill', tools), ('Grinder', tools), ('Kettle', kitchen)):
            Product.objects.create(name=name, price=10, moq=1,
                                   category=category, is_draft=False)

    def test_products_are_grouped_under_category_headings(self):
        response = self.client.get('/products/catalogue/')
        self.assertContains(response, 'category-heading')
        self.assertContains(response, 'Tools &amp; Machinery')
        self.assertContains(response, 'Home &amp; Kitchen')

    def test_a_product_with_no_category_still_appears(self):
        """It gets a heading of its own rather than falling off the page."""
        Product.objects.create(name='Orphan Widget', price=5, moq=1, is_draft=False)
        response = self.client.get('/products/catalogue/')
        self.assertContains(response, 'Uncategorised')
        self.assertContains(response, 'Orphan Widget')

    def test_the_page_does_not_query_once_per_product(self):
        self.client.get('/products/catalogue/')  # warm-up: sessions, settings
        with CaptureQueriesContext(connection) as first:
            self.client.get('/products/catalogue/')
        for i in range(25):
            Product.objects.create(name='Filler %d' % i, price=5, moq=1, is_draft=False)
        with CaptureQueriesContext(connection) as second:
            self.client.get('/products/catalogue/')
        self.assertEqual(
            len(first), len(second),
            'catalogue went from %d to %d queries after adding 25 products'
            % (len(first), len(second)))
