"""
Tests for the public shipping calculator endpoint.

The arithmetic itself is covered in settings_manager/tests.py. What is tested
here is the part a browser touches: what the view accepts, what it refuses, and
- most importantly - what it puts in the response body.
"""

import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from settings_manager.models import (CargoType, CompanySettings,
                                     ShippingCompany, ShippingDestination,
                                     ShippingRate)


class ShippingCalculatorViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('shipping_calculator_page')

        settings = CompanySettings.get_settings()
        settings.currency = 'AED'
        # House rates, used only when no company prices a lane.
        settings.air_shipping_rate = Decimal('28')
        settings.sea_shipping_rate = Decimal('480')
        settings.volumetric_divisor = Decimal('6000')
        settings.min_cbm = Decimal('1')
        settings.min_chargeable_kg = Decimal('0')
        settings.save()

        # Seeded by settings_manager migration 0025.
        cls.uae = ShippingDestination.objects.get(code='AE')
        cls.general = CargoType.objects.get(slug='general')
        cls.battery = CargoType.objects.get(slug='non-branded-battery')
        cls.beauty = CargoType.objects.get(slug='beauty')

        # A cheaper rate per KG on a harsher divisor...
        cls.falcon = ShippingCompany.objects.create(
            name='Falcon Air Cargo', volumetric_divisor=Decimal('5000'))
        # ...against a dearer rate on the IATA divisor, which wins on cost.
        cls.gulf = ShippingCompany.objects.create(
            name='Gulf Line Consolidators', volumetric_divisor=Decimal('6000'),
            min_cbm=Decimal('1'))

        ShippingRate.objects.create(
            company=cls.falcon, destination=cls.uae, cargo_type=cls.general,
            method='air', rate=Decimal('22'))
        ShippingRate.objects.create(
            company=cls.gulf, destination=cls.uae, cargo_type=cls.general,
            method='air', rate=Decimal('26'))
        ShippingRate.objects.create(
            company=cls.gulf, destination=cls.uae, cargo_type=cls.general,
            method='sea', rate=Decimal('420'))
        ShippingRate.objects.create(
            company=cls.gulf, destination=cls.uae, cargo_type=cls.battery,
            method='air', rate=Decimal('52'))

    # A 60x40x40 cm carton at 8 kg: 16 kg volumetric against 8 kg actual.
    BULKY = {'length_cm': '60', 'width_cm': '40', 'height_cm': '40',
             'weight_kg': '8', 'quantity': '1'}

    def quote(self, **overrides):
        body = {'method': 'air', 'destination': 'AE', 'cargo_type': 'general',
                'lines': [dict(self.BULKY)]}
        body.update(overrides)
        return self.client.post(self.url, body, content_type='application/json')

    # -- the page ---------------------------------------------------------

    def test_page_is_public(self):
        """No login. The question is asked before anyone registers."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'portal/shipping_calculator.html')

    # -- quoting ----------------------------------------------------------

    def test_air_quote_uses_volumetric_weight_and_the_cheapest_company(self):
        data = self.quote().json()
        self.assertTrue(data['success'])
        self.assertEqual(data['actual_kg'], '8.000')
        self.assertEqual(data['volumetric_kg'], '16.000')
        self.assertEqual(data['billed'], '16.000')
        # Gulf Line at 26/kg on 16 kg = 416.00 beats Falcon at 22/kg on
        # 19.2 kg = 422.40, despite the lower headline rate.
        self.assertEqual(data['rate'], '26.00')
        self.assertEqual(data['total'], '416.00')
        self.assertTrue(data['volumetric_applied'])

    def test_sea_quote_is_priced_on_cbm_with_the_minimum_applied(self):
        data = self.quote(method='sea').json()
        self.assertEqual(data['cbm'], '0.096')
        self.assertEqual(data['billed'], '1.000')       # charged up to the minimum
        self.assertTrue(data['minimum_applied'])
        self.assertEqual(data['total'], '420.00')
        self.assertEqual(data['unit'], 'CBM')

    def test_battery_cargo_is_priced_separately(self):
        """
        Batteries cost more, and only the company that quoted them appears.

        Falcon has no battery rate on file, so it is absent from the comparison
        entirely rather than being quoted at its general-cargo price. Gulf Line's
        52/kg on 16 kg = 832.00 is the only quote, and it is dearer than the
        416.00 general-cargo answer - which is the point.
        """
        standard = self.quote().json()
        battery = self.quote(cargo_type='non-branded-battery').json()
        self.assertEqual(battery['rate'], '52.00')
        self.assertEqual(battery['total'], '832.00')
        self.assertGreater(Decimal(battery['total']), Decimal(standard['total']))

    def test_a_cargo_type_nobody_prices_asks_for_a_manual_quote(self):
        """
        Beauty products have a category but no rates yet.

        The honest answer is that we do not have one - not a general-cargo price
        dressed up as a cosmetics quote.
        """
        data = self.quote(cargo_type='beauty').json()
        self.assertFalse(data['success'])
        self.assertTrue(data['needs_manual_quote'])

    def test_an_unknown_cargo_type_falls_back_to_general(self):
        """A stale bookmark should still get the commonest price, not an error."""
        data = self.quote(cargo_type='no-such-category').json()
        self.assertTrue(data['success'])
        self.assertEqual(data['cargo_type'], 'general')

    def test_quantity_scales_the_quote(self):
        line = dict(self.BULKY, quantity='10')
        data = self.quote(lines=[line]).json()
        self.assertEqual(data['cartons'], 10)
        self.assertEqual(data['billed'], '160.000')
        self.assertEqual(data['total'], '4160.00')

    def test_mixed_shipment_charges_each_line_on_its_own_worse_case(self):
        """
        One bulky-light carton plus one small-dense one.

        The winning company here is Falcon, on its 5000 divisor: the bulky
        carton bills 19.2 kg of volume and the dense one bills its 40 kg of
        weight, giving 59.2 kg x 22 = 1302.40 against Gulf Line's
        (16 + 40) x 26 = 1456.00.

        Note that the chargeable weight reported is the WINNER's, which is the
        only figure consistent with the price shown beside it. The rule that
        each line is charged on its own worse case - rather than the shipment
        being averaged - is asserted directly in settings_manager's tests.
        """
        dense = {'length_cm': '20', 'width_cm': '20', 'height_cm': '25',
                 'weight_kg': '40', 'quantity': '1'}
        data = self.quote(lines=[dict(self.BULKY), dense]).json()
        self.assertEqual(data['cartons'], 2)
        self.assertEqual(data['actual_kg'], '48.000')
        self.assertEqual(data['billed'], '59.200')
        self.assertEqual(data['rate'], '22.00')
        self.assertEqual(data['total'], '1302.40')
        # Never the naive max() across shipment totals, which would be 48 kg.
        self.assertNotEqual(data['billed'], '48.000')

    # -- what the response must NOT contain --------------------------------

    def test_the_response_never_names_a_shipping_company(self):
        """
        Which forwarder gives which rate is a supplier relationship.

        The losing quotes have to be ABSENT from the body, not merely unused by
        the template - anything in the JSON is readable by anyone who opens the
        network tab, whatever the page chooses to draw.
        """
        body = self.quote().content.decode()
        for name in ('Falcon', 'Gulf Line', 'company', 'quotes'):
            self.assertNotIn(name, body)

    def test_money_is_returned_as_strings(self):
        """
        JSON numbers are IEEE-754 doubles in every browser.

        A price sent as a number can come back out of JSON.parse as
        1234.5600000000001, so the figures are strings all the way to the DOM.
        """
        data = self.quote().json()
        for key in ('total', 'rate', 'actual_kg', 'volumetric_kg', 'cbm', 'billed'):
            self.assertIsInstance(data[key], str, key)

    # -- refusals ----------------------------------------------------------

    def test_missing_dimensions_are_reported_not_priced(self):
        line = dict(self.BULKY, height_cm='')
        response = self.quote(lines=[line])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])

    def test_an_entirely_empty_form_is_refused(self):
        response = self.quote(lines=[{'length_cm': '', 'width_cm': '', 'height_cm': '',
                                      'weight_kg': '', 'quantity': ''}])
        self.assertEqual(response.status_code, 400)

    def test_negative_dimensions_are_refused(self):
        """A negative height would otherwise produce a negative volume."""
        response = self.quote(lines=[dict(self.BULKY, height_cm='-40')])
        self.assertEqual(response.status_code, 400)

    def test_an_unserved_destination_is_refused(self):
        response = self.quote(destination='ZZ')
        self.assertEqual(response.status_code, 400)

    def test_malformed_json_does_not_raise(self):
        response = self.client.post(self.url, 'not json at all',
                                    content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])

    def test_line_count_is_capped(self):
        """
        A crafted body must not be able to make the server price 10,000 lines.

        The cap truncates rather than rejecting, so a legitimate oversized paste
        still gets an answer for what fits.
        """
        from portal.views import MAX_QUOTE_LINES

        data = self.quote(lines=[dict(self.BULKY)] * (MAX_QUOTE_LINES + 40)).json()
        self.assertEqual(data['cartons'], MAX_QUOTE_LINES)

    def test_no_configured_rate_asks_for_a_manual_quote(self):
        """
        Never a confident 0.00.

        With no company pricing the route the honest answer is that we do not
        have one, plus a way to reach a human.
        """
        ShippingRate.objects.all().delete()
        settings = CompanySettings.get_settings()
        settings.air_shipping_rate = Decimal('0')
        settings.sea_shipping_rate = Decimal('0')
        settings.save()

        data = self.quote().json()
        self.assertFalse(data['success'])
        self.assertTrue(data['needs_manual_quote'])
        self.assertNotIn('total', data)

    def test_the_house_rate_answers_when_no_company_prices_the_lane(self):
        """
        The safety net that predates per-company rates.

        Before rates were rows, a company with a rate of 0 fell through to a
        global default, so a site with nothing entered still quoted. Losing that
        would have made the calculator go silent for anyone who had not yet
        filled in a forwarder.
        """
        ShippingRate.objects.all().delete()
        data = self.quote().json()
        self.assertTrue(data['success'])
        self.assertEqual(data['rate'], '28.00')      # the global air rate
        self.assertEqual(data['total'], '448.00')    # 16 kg x 28


class StylesheetIntegrityTests(TestCase):
    """
    Guard against a stray brace silently deleting a rule.

    WHY THIS EXISTS

    portal.css is 4,000+ lines and edited by hand. CSS has no compiler and fails
    QUIETLY: an unbalanced '}' does not raise, it makes the parser discard the
    rule that follows and carry on. The page still renders, so nothing looks
    broken until somebody notices one specific thing has lost its styling.

    That shipped twice while moving a media query. Both times the visible
    symptom was the header nav links going black — the rule holding
    `color: rgba(255,255,255,0.85)` had been dropped, while its `:hover`
    partner, sitting after the point where the parser resynchronised, still
    worked. "Only the hover is visible" is a very indirect way to be told about
    a punctuation error.
    """

    @staticmethod
    def _strip(css):
        """Blank out comments and strings, keeping newlines so lines still map."""
        def blank(match):
            return re.sub(r'[^\n]', ' ', match.group(0))
        css = re.sub(r'/\*.*?\*/', blank, css, flags=re.S)
        return re.sub(r'"[^"\n]*"|\'[^\'\n]*\'', blank, css)

    def _stylesheets(self):
        root = Path(settings.BASE_DIR) / 'static'
        sheets = sorted(root.glob('*.css'))
        self.assertTrue(sheets, 'no stylesheets found to check')
        return sheets

    def test_braces_are_balanced_with_no_stray_closers(self):
        for path in self._stylesheets():
            with self.subTest(stylesheet=path.name):
                text = self._strip(path.read_text(encoding='utf-8'))
                depth = 0
                line = 1
                strays = []
                for char in text:
                    if char == '\n':
                        line += 1
                    elif char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        # Deliberately NOT reset to 0 here. Resetting is what
                        # made an earlier hand-rolled version of this check
                        # report "balanced" on a file that had a stray brace.
                        if depth < 0:
                            strays.append(line)
                # Only the FIRST stray is reported. One misplaced brace throws
                # the depth off for the rest of the file, so every later '}'
                # looks stray too - printing all of them buries the one line
                # that actually needs editing under a thousand that do not.
                self.assertEqual(
                    strays[:1], [],
                    f'{path.name}: stray closing brace at line {strays[0] if strays else None} '
                    f'({len(strays)} knock-on positions after it) — the rule '
                    f'following it is being silently discarded by the browser',
                )
                self.assertEqual(
                    depth, 0,
                    f'{path.name}: {abs(depth)} unclosed block(s); everything '
                    f'after is nested inside the wrong rule',
                )

    def test_the_header_nav_links_keep_their_colour_rule(self):
        """
        The specific rule both regressions destroyed.

        The nav sits on a near-black bar, so losing this rule drops the links to
        Bootstrap's default near-black and they vanish into the background.
        """
        css = (Path(settings.BASE_DIR) / 'static' / 'portal.css').read_text(encoding='utf-8')
        match = re.search(
            r'\.portal-navbar\s+\.nav-link\s*\{[^}]*?color\s*:\s*([^;]+);',
            css, flags=re.S,
        )
        self.assertIsNotNone(
            match, '.portal-navbar .nav-link lost its colour declaration',
        )
        self.assertIn(
            '255,255,255', match.group(1).replace(' ', ''),
            'header nav links must stay light — they sit on a near-black bar',
        )


class EnquirySpamFilterTests(TestCase):
    """
    The public enquiry forms, which were running at 84% spam.

    31 of 37 messages were bots, and each one also fired a notification email —
    so the alert that exists to catch a waiting customer was mostly announcing
    bots, which is how people learn to ignore the alert.

    The two properties worth protecting are opposites, and the second matters
    more: spam must not reach the inbox, and a real enquiry must never be lost
    to the filter.
    """

    SPAM_BODY = ('Read the news and xpress confidence in $50,000,000 per month '
                 'https://telegra.ph/Read-the-latest-news-and-earn-50000000-in-a-month')

    def stamp(self, seconds_ago=20):
        """
        A signed form timestamp, backdated to model a human filling it in.

        Generating one and posting instantly is precisely what a bot looks
        like, so a "genuine enquiry" test that did that would be testing the
        wrong thing.
        """
        from django.core import signing
        from django.utils import timezone

        return signing.dumps(
            {'t': timezone.now().timestamp() - seconds_ago}, salt='enquiry-form')

    def captcha_fields(self):
        """A fresh, correctly answered CAPTCHA - what a person submits."""
        from portal import captcha

        challenge = captcha.new_challenge()
        return {'captcha_token': challenge['token'],
                'captcha_answer': str(challenge['a'] + challenge['b'])}

    def post(self, **overrides):
        payload = {
            'name': 'Ahmed Hassan',
            'email': 'ahmed@tradingco.ae',
            'message': 'We want to source 2000 USB-C cables for Dubai. Please quote.',
            'form_started_at': self.stamp(),
            **self.captcha_fields(),
        }
        payload.update(overrides)
        return self.client.post('/contact/', payload)

    def latest(self):
        from portal.models import ContactMessage
        return ContactMessage.objects.latest('id')

    # -- the forms carry the defences ------------------------------------

    def test_both_forms_render_the_honeypot_and_timestamp(self):
        """
        The homepage form posts to the same view, so it needs them too.

        Protecting only /contact/ would leave the form actually producing the
        spam wide open - the live messages are tagged
        "Product sourcing request - Homepage".
        """
        for path in ('/contact/', '/'):
            with self.subTest(path=path):
                html = self.client.get(path).content.decode()
                self.assertIn('company_website', html)
                self.assertIn('form_started_at', html)

    def test_the_honeypot_is_hidden_from_people(self):
        html = self.client.get('/contact/').content.decode()
        index = html.find('company_website')
        window = html[max(0, index - 400):index]
        self.assertIn('aria-hidden', window)
        self.assertIn('-9999px', window)

    # -- spam is caught ---------------------------------------------------

    def test_the_spam_actually_received_is_flagged(self):
        self.post(name='RichardCaste', email='fraziera1449@yahoo.com',
                  message=self.SPAM_BODY)
        lead = self.latest()
        self.assertTrue(lead.is_spam)
        self.assertGreaterEqual(lead.spam_score, 5)

    def test_a_filled_honeypot_is_enough_on_its_own(self):
        self.post(company_website='http://spam.example')
        self.assertTrue(self.latest().is_spam)

    def test_an_instant_submission_is_flagged(self):
        """
        Nobody reads a form and writes an enquiry in under three seconds.

        Timing alone scores below the threshold on purpose, so this pairs it
        with spam content - which is how it behaves in the wild.
        """
        self.post(message=self.SPAM_BODY, form_started_at=self.stamp(seconds_ago=0))
        self.assertTrue(self.latest().is_spam)

    def test_speed_alone_does_not_flag_a_genuine_enquiry(self):
        """
        The guard against the filter's riskiest inference.

        A fast submission of an otherwise unremarkable enquiry must survive:
        only the honeypot is decisive on its own.
        """
        self.post(form_started_at=self.stamp(seconds_ago=0))
        self.assertFalse(self.latest().is_spam)

    def test_flagged_messages_send_no_notification(self):
        """
        The whole point. An alert that fires for bots trains people to ignore
        the alert, which is how a real enquiry then gets missed.
        """
        from django.core import mail

        mail.outbox = []
        self.post(name='RichardCaste', message=self.SPAM_BODY,
                  company_website='http://spam.example')
        self.assertTrue(self.latest().is_spam)
        self.assertEqual(len(mail.outbox), 0)

    # -- real enquiries survive -------------------------------------------

    def test_a_genuine_enquiry_is_not_flagged(self):
        self.post()
        self.assertFalse(self.latest().is_spam)

    def test_a_product_link_counts_in_the_senders_favour(self):
        """
        "Send us the product link" is behaviour this business wants to
        encourage, so a 1688 or Alibaba URL must not read as spam.
        """
        self.post(message='Please quote https://detail.1688.com/offer/77123.html '
                          'for 500 pieces delivered to Dubai.')
        self.assertFalse(self.latest().is_spam)

    def test_shouting_alone_does_not_flag_an_enquiry(self):
        """Urgency in capitals is a customer in a hurry, not a bot."""
        self.post(message='URGENT - NEED 5000 UNITS ASAP FOR AMAZON FBA UAE')
        self.assertFalse(self.latest().is_spam)

    def test_a_missing_timestamp_does_not_flag_anyone(self):
        """
        A cached page, or an extension that strips hidden inputs, must not be
        mistaken for a bot. Absent evidence is not evidence.
        """
        self.post(form_started_at='')
        self.assertFalse(self.latest().is_spam)

    def test_a_flagged_sender_still_sees_the_normal_thank_you(self):
        """
        Telling a bot it was caught invites tuning around the filter, and a
        wrongly-flagged human should not be left looking at an error.
        """
        response = self.post(message=self.SPAM_BODY, company_website='x')
        self.assertRedirects(response, '/thank-you/', fetch_redirect_response=False)

    # -- CAPTCHA ------------------------------------------------------------

    def count(self):
        from portal.models import ContactMessage
        return ContactMessage.objects.count()

    def test_every_enquiry_form_shows_a_captcha(self):
        """All three forms post to the same view, so all three need it."""
        for path in ('/contact/', '/', '/ar/'):
            with self.subTest(path=path):
                html = self.client.get(path).content.decode()
                self.assertIn('name="captcha_token"', html)
                self.assertIn('name="captcha_answer"', html)

    def test_a_correct_answer_is_accepted(self):
        response = self.post()
        self.assertRedirects(response, '/thank-you/', fetch_redirect_response=False)
        self.assertEqual(self.count(), 1)

    def test_a_missing_answer_is_rejected_and_nothing_is_saved(self):
        response = self.post(captcha_answer='')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.count(), 0)
        self.assertIn('captcha', response.context['field_errors'])

    def test_a_wrong_answer_is_rejected(self):
        fields = self.captcha_fields()
        wrong = str(int(fields['captcha_answer']) + 1)
        self.post(captcha_token=fields['captcha_token'], captcha_answer=wrong)
        self.assertEqual(self.count(), 0)

    def test_a_missing_token_is_rejected(self):
        """A bot posting straight to the URL never loaded a form."""
        self.post(captcha_token='', captcha_answer='5')
        self.assertEqual(self.count(), 0)

    def test_a_tampered_token_is_rejected(self):
        fields = self.captcha_fields()
        self.post(captcha_token=fields['captcha_token'][:-2] + 'xx',
                  captcha_answer=fields['captcha_answer'])
        self.assertEqual(self.count(), 0)

    def test_a_solved_token_cannot_be_replayed(self):
        """Solve once by hand, then reuse it thousands of times - not allowed."""
        fields = self.captcha_fields()
        self.post(**fields)
        self.post(**fields)
        self.assertEqual(self.count(), 1)

    def test_the_answer_is_not_readable_from_the_token(self):
        """The token is signed, not encrypted, so the answer must not be in it."""
        from django.core import signing
        from portal import captcha

        challenge = captcha.new_challenge()
        payload = signing.loads(challenge['token'], salt=captcha.SALT)
        self.assertEqual(set(payload), {'n', 'h'})

    def test_a_failed_attempt_keeps_what_was_typed(self):
        """
        A homepage submission that fails comes back on /contact/, which has no
        link/quantity inputs - they must survive inside the message.
        """
        response = self.post(captcha_answer='', quantity='500 pcs',
                             product_link='https://detail.1688.com/offer/1.html')
        message = response.context['form_data']['message']
        self.assertIn('USB-C cables', message)
        self.assertIn('Quantity needed: 500 pcs', message)
        self.assertIn('detail.1688.com', message)
        # And a NEW question is shown, since the old token is no longer usable.
        self.assertIn('captcha_token', response.content.decode())

    def test_the_api_no_longer_accepts_anonymous_enquiries(self):
        """Otherwise the API would be a way straight around the CAPTCHA."""
        response = self.client.post('/api/v1/contact/', {
            'name': 'Bot', 'email': 'bot@example.com', 'message': 'hello'})
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(self.count(), 0)


class LeadDeleteTests(TestCase):
    """Deleting enquiries from the back-office inbox."""

    def setUp(self):
        from django.contrib.auth.models import User
        from portal.models import ContactMessage

        staff = User.objects.create_user('leadsdel', 'leadsdel@example.com', 'pw')
        staff.profile.role = 'admin'
        staff.profile.save()
        self.client.force_login(staff)

        self.a = ContactMessage.objects.create(name='Alpha', email='a@x.com', message='one')
        self.b = ContactMessage.objects.create(name='Bravo', email='b@x.com', message='two')
        self.c = ContactMessage.objects.create(name='Charlie', email='c@x.com', message='three')

    def ids(self):
        from portal.models import ContactMessage
        return set(ContactMessage.objects.values_list('id', flat=True))

    def test_the_inbox_offers_delete(self):
        response = self.client.get('/portal/admin/leads/')
        self.assertContains(response, 'admin/leads/delete/')
        self.assertContains(response, 'Delete selected')

    def test_deleting_one_leaves_the_others(self):
        response = self.client.post('/portal/admin/leads/delete/',
                                    {'lead_ids': [self.a.id], 'status': 'all'})
        self.assertEqual(self.ids(), {self.b.id, self.c.id})
        self.assertRedirects(response, '/portal/admin/leads/?status=all',
                             fetch_redirect_response=False)

    def test_deleting_a_selection(self):
        self.client.post('/portal/admin/leads/delete/',
                         {'lead_ids': [self.a.id, self.c.id], 'status': 'new', 'page': '2'})
        self.assertEqual(self.ids(), {self.b.id})

    def test_a_get_request_deletes_nothing(self):
        """A link, prefetch or crawler must never be able to delete."""
        self.client.get('/portal/admin/leads/delete/', {'lead_ids': self.a.id})
        self.assertEqual(len(self.ids()), 3)

    def test_an_empty_selection_deletes_nothing(self):
        self.client.post('/portal/admin/leads/delete/', {'status': 'new'})
        self.assertEqual(len(self.ids()), 3)

    def test_a_customer_cannot_delete(self):
        from django.contrib.auth.models import User

        buyer = User.objects.create_user('buyerdel', 'bd@example.com', 'pw')
        buyer.profile.role = 'customer'
        buyer.profile.save()
        self.client.force_login(buyer)

        response = self.client.post('/portal/admin/leads/delete/', {'lead_ids': [self.a.id]})
        self.assertNotEqual(response.status_code, 302)
        self.assertEqual(len(self.ids()), 3)


class LeadInboxSpamTests(TestCase):
    """How flagged messages behave in the back office."""

    def setUp(self):
        from django.contrib.auth.models import User
        from portal.models import ContactMessage

        staff = User.objects.create_user('leads', 'leads@example.com', 'pw')
        profile = staff.profile
        profile.role = 'admin'
        profile.save()
        self.client.force_login(staff)

        self.real = ContactMessage.objects.create(
            name='Ahmed', email='a@co.ae', message='Need a quote for cables.')
        self.spam = ContactMessage.objects.create(
            name='RichardCaste', email='x@y.com', message='earn money per month',
            is_spam=True, spam_score=20, spam_reason='link to telegra.ph')

    def test_spam_is_hidden_from_the_default_inbox(self):
        response = self.client.get('/portal/admin/leads/')
        self.assertContains(response, 'Ahmed')
        self.assertNotContains(response, 'RichardCaste')

    def test_spam_is_hidden_from_the_all_tab_too(self):
        """All means all real enquiries; spam has its own tab."""
        response = self.client.get('/portal/admin/leads/?status=all')
        self.assertNotContains(response, 'RichardCaste')

    def test_the_spam_tab_shows_it_with_the_reason(self):
        response = self.client.get('/portal/admin/leads/?status=spam')
        self.assertContains(response, 'RichardCaste')
        self.assertContains(response, 'telegra.ph')

    def test_the_unread_badge_ignores_spam(self):
        """A badge showing 31 when 31 are bots stops meaning anything."""
        response = self.client.get('/portal/admin/leads/')
        self.assertEqual(response.context['new_count'], 1)

    def test_clearing_spam_leaves_real_enquiries_alone(self):
        from portal.models import ContactMessage

        self.client.post('/portal/admin/leads/spam-action/', {'action': 'delete_all'})
        self.assertFalse(ContactMessage.objects.filter(is_spam=True).exists())
        self.assertTrue(ContactMessage.objects.filter(id=self.real.id).exists())

    def test_releasing_a_message_returns_it_and_sends_the_held_alert(self):
        """
        The notification never fired while it was flagged, so releasing has to
        send it - otherwise a rescued enquiry lands in a list nobody watches.
        """
        from django.core import mail

        mail.outbox = []
        self.client.post('/portal/admin/leads/spam-action/',
                         {'action': 'not_spam', 'lead_id': self.spam.id})
        self.spam.refresh_from_db()
        self.assertFalse(self.spam.is_spam)
        self.assertEqual(len(mail.outbox), 1)

    def test_a_customer_cannot_reach_the_spam_controls(self):
        from django.contrib.auth.models import User
        from portal.models import ContactMessage

        buyer = User.objects.create_user('buyer9', 'b9@example.com', 'pw')
        buyer.profile.role = 'customer'
        buyer.profile.save()
        self.client.force_login(buyer)

        response = self.client.post('/portal/admin/leads/spam-action/',
                                    {'action': 'delete_all'})
        self.assertNotEqual(response.status_code, 200)
        self.assertTrue(ContactMessage.objects.filter(is_spam=True).exists())
