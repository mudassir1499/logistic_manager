"""
Prove the whole create-a-listing flow works over the API, exactly as the phone
will drive it: sign in, create the product, upload a photo, add variations, tag
it, publish it, and confirm it reaches the ad feed.

Runs against a throwaway test database via Django's own runner, so nothing here
touches the real catalogue.
"""
import base64
import io as _io
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from products.models import Category, Product, ProductTag

_MEDIA = tempfile.mkdtemp(prefix='listing-tests-')
PIXEL = b'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'


@override_settings(MEDIA_ROOT=_MEDIA)
class CreateListingFromPhoneTests(TestCase):
    """
    The journey the app has to support end to end.

    Each step is a separate request because that is how the phone makes them —
    a product row cannot carry its photo in the same POST, since one is JSON and
    the other is multipart.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.staff = User.objects.create_user('lister', 'l@example.com', 'pw')
        profile = self.staff.profile
        profile.role = 'admin'
        for field in profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, True)
        profile.save()
        self.category = Category.objects.create(name='Power Tools')

    def token_headers(self):
        """Sign in the way the app does, and use the token it gets back."""
        self.staff.set_password('phone-pw')
        self.staff.save()
        r = self.client.post('/api/v1/auth/staff-login/',
                             {'email': 'lister', 'password': 'phone-pw'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        return {'HTTP_AUTHORIZATION': 'Bearer ' + r.json()['token']}

    def test_a_listing_can_be_created_entirely_over_the_api(self):
        auth = self.token_headers()

        # 1. the product row
        r = self.client.post('/api/v1/products/', {
            'name': 'Cordless Impact Drill 21V',
            'sku': 'DRILL-21V',
            'price': '149.00',
            'moq': 10,
            'weight': '2.400',
            'carton_qty': 20,
            'category': self.category.slug,
            'is_draft': True,          # created as a draft, published at the end
        }, content_type='application/json', **auth)
        self.assertEqual(r.status_code, 201, r.content)
        product_id = r.json()['id']
        # ProductViewSet looks up by SLUG, not pk. A client that only kept the
        # id could not address the product it just created.
        slug = r.json()['slug']
        self.assertTrue(slug, 'create must return the slug the detail route needs')

        # 2. a photo, as multipart - the phone has a file, not base64
        photo = SimpleUploadedFile('drill.gif', base64.b64decode(PIXEL),
                                   content_type='image/gif')
        r = self.client.post('/api/v1/product-images/',
                             {'product': product_id, 'image': photo}, **auth)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()['url'], 'the upload returned no URL')

        # 3. variations - what the customer actually buys
        for name, price in [('1 battery', '149.00'), ('2 batteries', '189.00')]:
            r = self.client.post('/api/v1/product-variants/', {
                'product': product_id, 'name': name, 'price': price,
            }, content_type='application/json', **auth)
            self.assertEqual(r.status_code, 201, r.content)

        # 4. a tag
        tag = ProductTag.objects.create(name='Guangzhou supplier')
        r = self.client.patch(f'/api/v1/products/{slug}/',
                              {'tags': [tag.id]},
                              content_type='application/json', **auth)
        self.assertEqual(r.status_code, 200, r.content)

        # 5. publish
        r = self.client.patch(f'/api/v1/products/{slug}/',
                              {'is_draft': False},
                              content_type='application/json', **auth)
        self.assertEqual(r.status_code, 200, r.content)

        product = Product.objects.get(pk=product_id)
        self.assertEqual(product.images.count(), 1)
        self.assertEqual(product.variants.count(), 2)
        self.assertEqual(product.tags.count(), 1)
        self.assertFalse(product.is_draft)

        # 6. and it is actually advertisable - the point of the whole exercise
        feed = self.client.get('/products/feed.csv').content.decode()
        self.assertIn('DRILL-21V', feed,
                      'a listing created on the phone never reached the ad feed')

    def test_a_photo_needs_a_real_product(self):
        auth = self.token_headers()
        photo = SimpleUploadedFile('x.gif', base64.b64decode(PIXEL),
                                   content_type='image/gif')
        r = self.client.post('/api/v1/product-images/',
                             {'product': 999999, 'image': photo}, **auth)
        self.assertEqual(r.status_code, 404)

    def test_the_fourth_photo_is_refused_with_a_reason(self):
        """Only three are ever rendered, so a silent fourth would be a mystery."""
        auth = self.token_headers()
        r = self.client.post('/api/v1/products/',
                             {'name': 'Thing', 'price': '10.00', 'moq': 1},
                             content_type='application/json', **auth)
        pid = r.json()['id']
        for i in range(3):
            photo = SimpleUploadedFile(f'{i}.gif', base64.b64decode(PIXEL),
                                       content_type='image/gif')
            self.assertEqual(
                self.client.post('/api/v1/product-images/',
                                 {'product': pid, 'image': photo}, **auth).status_code,
                201)
        photo = SimpleUploadedFile('four.gif', base64.b64decode(PIXEL),
                                   content_type='image/gif')
        r = self.client.post('/api/v1/product-images/',
                             {'product': pid, 'image': photo}, **auth)
        self.assertEqual(r.status_code, 400)
        self.assertIn('three photos', r.json()['detail'])

    def test_deleting_a_variation_retires_it_rather_than_erasing_it(self):
        """
        A variation may be on somebody's order. Hard-deleting it would either
        cascade into their history or fail on a foreign key.
        """
        auth = self.token_headers()
        pid = self.client.post('/api/v1/products/',
                               {'name': 'Thing', 'price': '10.00', 'moq': 1},
                               content_type='application/json', **auth).json()['id']
        vid = self.client.post('/api/v1/product-variants/',
                               {'product': pid, 'name': 'Blue', 'price': '12.00'},
                               content_type='application/json', **auth).json()['id']

        self.assertEqual(
            self.client.delete(f'/api/v1/product-variants/{vid}/', **auth).status_code, 204)

        from products.models import ProductVariant
        variant = ProductVariant.objects.get(pk=vid)
        self.assertFalse(variant.is_active, 'the row should survive, deactivated')

    def test_a_free_variation_is_refused(self):
        auth = self.token_headers()
        pid = self.client.post('/api/v1/products/',
                               {'name': 'Thing', 'price': '10.00', 'moq': 1},
                               content_type='application/json', **auth).json()['id']
        r = self.client.post('/api/v1/product-variants/',
                             {'product': pid, 'name': 'Free', 'price': '0.00'},
                             content_type='application/json', **auth)
        self.assertEqual(r.status_code, 400)

    def test_catalogue_writes_need_the_products_module(self):
        """A coordinator with only `orders` must not be able to list products."""
        coord = User.objects.create_user('ordersonly', 'o@example.com', 'pw')
        profile = coord.profile
        profile.role = 'staff'
        for field in profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, False)
        profile.can_orders = True
        profile.save()
        coord.set_password('pw2')
        coord.save()

        r = self.client.post('/api/v1/auth/staff-login/',
                             {'email': 'ordersonly', 'password': 'pw2'},
                             content_type='application/json')
        auth = {'HTTP_AUTHORIZATION': 'Bearer ' + r.json()['token']}

        r = self.client.post('/api/v1/products/',
                             {'name': 'Sneaky', 'price': '1.00', 'moq': 1},
                             content_type='application/json', **auth)
        self.assertIn(r.status_code, (403, 401))


class CreateOrderFromPhoneTests(TestCase):
    """
    Building a whole order in one request.

    The total is the figure the customer is billed, so the rule under test is
    that the SERVER computes it from the lines and never takes it from the
    request body.
    """

    def setUp(self):
        from customers.models import Customer
        self.staff = User.objects.create_user('sales', 's@example.com', 'pw')
        profile = self.staff.profile
        profile.role = 'admin'
        for field in profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, True)
        profile.save()
        self.staff.set_password('phone-pw')
        self.staff.save()

        self.customer = Customer.objects.create(name='Gulf Trading')
        self.product = Product.objects.create(name='Drill', price='100.00', moq=1)

        r = self.client.post('/api/v1/auth/staff-login/',
                             {'email': 'sales', 'password': 'phone-pw'},
                             content_type='application/json')
        self.auth = {'HTTP_AUTHORIZATION': 'Bearer ' + r.json()['token']}

    def create(self, payload):
        return self.client.post('/api/v1/order-admin/', payload,
                                content_type='application/json', **self.auth)

    def test_an_order_and_its_lines_are_created_together(self):
        r = self.create({
            'customer': self.customer.id,
            'items': [{'product': self.product.id, 'quantity': 3}],
        })
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body['items'], 1)
        # 3 x 100.00, priced from the catalogue because no price was sent.
        self.assertEqual(body['total'], '300.00')
        self.assertTrue(body['tracking_number'],
                        'the caller needs the tracking number back')

    def test_the_client_cannot_dictate_the_total(self):
        """The one field that must never be taken from the request."""
        r = self.create({
            'customer': self.customer.id,
            'total': '1.00',
            'items': [{'product': self.product.id, 'quantity': 2}],
        })
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['total'], '200.00')

    def test_a_line_price_overrides_the_catalogue_without_changing_it(self):
        """
        A negotiated price on one order must not rewrite the listing — which is
        what editing the product would do.
        """
        r = self.create({
            'customer': self.customer.id,
            'items': [{'product': self.product.id, 'quantity': 1, 'price': '80.00'}],
        })
        self.assertEqual(r.json()['total'], '80.00')
        self.product.refresh_from_db()
        self.assertEqual(str(self.product.price), '100.00')

    def test_shipping_is_added_to_the_total(self):
        r = self.create({
            'customer': self.customer.id,
            'shipping_cost': '25.00',
            'items': [{'product': self.product.id, 'quantity': 1}],
        })
        self.assertEqual(r.json()['total'], '125.00')

    def test_a_variation_prices_the_line(self):
        from products.models import ProductVariant
        variant = ProductVariant.objects.create(
            product=self.product, name='Big', price='150.00')
        r = self.create({
            'customer': self.customer.id,
            'items': [{'product': self.product.id, 'variant': variant.id,
                       'quantity': 2}],
        })
        self.assertEqual(r.json()['total'], '300.00')

    def test_a_variation_of_another_product_is_refused(self):
        from products.models import ProductVariant
        other = Product.objects.create(name='Other', price='5.00', moq=1)
        variant = ProductVariant.objects.create(
            product=other, name='X', price='5.00')
        r = self.create({
            'customer': self.customer.id,
            'items': [{'product': self.product.id, 'variant': variant.id,
                       'quantity': 1}],
        })
        self.assertEqual(r.status_code, 400)

    def test_an_order_with_no_lines_is_refused(self):
        r = self.create({'customer': self.customer.id, 'items': []})
        self.assertEqual(r.status_code, 400)
        from orders.models import Order
        self.assertEqual(Order.objects.count(), 0)

    def test_a_bad_line_leaves_no_half_built_order(self):
        """
        Atomic. An order that exists with half its lines is worse than one that
        failed outright: the half is invisible and the total looks plausible.
        """
        from orders.models import Order
        r = self.create({
            'customer': self.customer.id,
            'items': [
                {'product': self.product.id, 'quantity': 1},
                {'product': 999999, 'quantity': 1},
            ],
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_creating_an_order_needs_the_orders_module(self):
        nobody = User.objects.create_user('nomodule', 'n@example.com', 'pw')
        profile = nobody.profile
        profile.role = 'staff'
        for field in profile.MODULE_FIELD_MAP.values():
            setattr(profile, field, False)
        profile.can_products = True
        profile.save()
        nobody.set_password('pw3')
        nobody.save()
        r = self.client.post('/api/v1/auth/staff-login/',
                             {'email': 'nomodule', 'password': 'pw3'},
                             content_type='application/json')
        auth = {'HTTP_AUTHORIZATION': 'Bearer ' + r.json()['token']}
        r = self.client.post('/api/v1/order-admin/', {
            'customer': self.customer.id,
            'items': [{'product': self.product.id, 'quantity': 1}],
        }, content_type='application/json', **auth)
        self.assertIn(r.status_code, (401, 403))
