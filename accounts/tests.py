"""
Tests for Google sign-in.

WHAT IS WORTH TESTING HERE

``decode_id_token`` is the trust boundary. Everything before it is a redirect;
everything after it treats the returned email as proof of identity and will
create or sign into an account with it. Each check in that function is the only
thing standing between a crafted token and someone else's account, and a check
that silently stops working looks exactly like one that works.

The token is not signed in these tests because the code deliberately does not
verify signatures - it trusts the TLS back-channel to the token endpoint (see
the module docstring in accounts/google_oauth.py). That makes the claim checks
load-bearing rather than belt-and-braces, which is precisely why they are
tested here.
"""

import base64
import json
import time

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts import google_oauth
from accounts.google_oauth import GoogleAuthError

CLIENT_ID = '871993913086-test.apps.googleusercontent.com'
OTHER_CLIENT_ID = '999999999999-someoneelse.apps.googleusercontent.com'


def make_id_token(**overrides):
    """
    Build an unsigned ID token with the claims Google would send.

    Args:
        **overrides: claims to replace or, when set to None, remove.

    Returns:
        str: a three-part JWT-shaped string.

    The signature segment is filler on purpose - nothing reads it.
    """
    claims = {
        'iss': 'https://accounts.google.com',
        'aud': CLIENT_ID,
        'sub': '1234567890',
        'email': 'buyer@example.com',
        'email_verified': True,
        'name': 'Test Buyer',
        'given_name': 'Test',
        'family_name': 'Buyer',
        'exp': int(time.time()) + 3600,
        'nonce': 'the-expected-nonce',
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}

    def segment(data):
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip('=')

    return f"{segment({'alg': 'RS256'})}.{segment(claims)}.signature-not-checked"


@override_settings(GOOGLE_OAUTH_CLIENT_ID=CLIENT_ID,
                   GOOGLE_OAUTH_CLIENT_SECRET='test-secret')
class DecodeIdTokenTests(TestCase):

    def test_a_valid_token_yields_the_identity(self):
        identity = google_oauth.decode_id_token(make_id_token(), 'the-expected-nonce')
        self.assertEqual(identity['email'], 'buyer@example.com')
        self.assertEqual(identity['sub'], '1234567890')
        self.assertTrue(identity['email_verified'])

    def test_a_token_for_another_application_is_refused(self):
        """
        The audience check, and the most valuable one here.

        Without it, anyone running any other Google OAuth client could take an
        ID token their own site legitimately received and present it here to
        sign in as that person. The token is genuinely Google's and genuinely
        the user's - it was simply never meant for us.
        """
        with self.assertRaises(GoogleAuthError):
            google_oauth.decode_id_token(
                make_id_token(aud=OTHER_CLIENT_ID), 'the-expected-nonce')

    def test_a_token_from_another_issuer_is_refused(self):
        with self.assertRaises(GoogleAuthError):
            google_oauth.decode_id_token(
                make_id_token(iss='https://evil.example.com'), 'the-expected-nonce')

    def test_an_expired_token_is_refused(self):
        with self.assertRaises(GoogleAuthError):
            google_oauth.decode_id_token(
                make_id_token(exp=int(time.time()) - 3600), 'the-expected-nonce')

    def test_clock_skew_is_tolerated(self):
        """A token that expired two seconds ago is this host's clock, not an attack."""
        identity = google_oauth.decode_id_token(
            make_id_token(exp=int(time.time()) - 2), 'the-expected-nonce')
        self.assertEqual(identity['email'], 'buyer@example.com')

    def test_a_replayed_token_from_another_session_is_refused(self):
        """The nonce ties the token to the browser that started the sign-in."""
        with self.assertRaises(GoogleAuthError):
            google_oauth.decode_id_token(
                make_id_token(nonce='a-different-sessions-nonce'), 'the-expected-nonce')

    def test_a_token_with_no_nonce_is_refused_when_one_was_expected(self):
        with self.assertRaises(GoogleAuthError):
            google_oauth.decode_id_token(make_id_token(nonce=None), 'the-expected-nonce')

    def test_an_unverified_email_is_refused(self):
        """
        Accounts are matched by email, so this is what stops impersonation.

        Anyone can put any address on a Google profile. Only Google's
        verification makes it evidence of control, and without this check
        someone could claim an existing customer's account by typing their
        address into a fresh Google profile.
        """
        with self.assertRaises(GoogleAuthError):
            google_oauth.decode_id_token(
                make_id_token(email_verified=False), 'the-expected-nonce')

    def test_the_workspace_string_true_counts_as_verified(self):
        """Workspace tokens have historically sent "true" rather than true."""
        identity = google_oauth.decode_id_token(
            make_id_token(email_verified='true'), 'the-expected-nonce')
        self.assertTrue(identity['email_verified'])

    def test_a_token_with_no_email_is_refused(self):
        with self.assertRaises(GoogleAuthError):
            google_oauth.decode_id_token(make_id_token(email=None), 'the-expected-nonce')

    def test_a_malformed_token_is_refused(self):
        for bad in ('', 'not-a-jwt', 'only.two', 'a.b.c.d'):
            with self.subTest(token=bad):
                with self.assertRaises(GoogleAuthError):
                    google_oauth.decode_id_token(bad, 'the-expected-nonce')

    def test_the_email_is_normalised(self):
        identity = google_oauth.decode_id_token(
            make_id_token(email='  Buyer@Example.COM  '), 'the-expected-nonce')
        self.assertEqual(identity['email'], 'buyer@example.com')


@override_settings(GOOGLE_OAUTH_CLIENT_ID=CLIENT_ID,
                   GOOGLE_OAUTH_CLIENT_SECRET='test-secret')
class AuthorizationRequestTests(TestCase):

    def test_state_and_nonce_are_stored_and_differ_each_time(self):
        """
        Both are single-use and unguessable.

        state defends the callback against CSRF; nonce ties the returned token
        to this attempt. Reusing either across sign-ins would defeat both.
        """
        from django.test import RequestFactory
        from django.contrib.sessions.backends.db import SessionStore

        seen = set()
        for _ in range(3):
            request = RequestFactory().get('/accounts/login/', HTTP_HOST='127.0.0.1')
            request.session = SessionStore()
            google_oauth.start(request, '')
            state = request.session[google_oauth.SESSION_STATE]
            nonce = request.session[google_oauth.SESSION_NONCE]
            self.assertNotIn(state, seen)
            self.assertNotIn(nonce, seen)
            self.assertNotEqual(state, nonce)
            seen.update({state, nonce})

    def test_a_mismatched_state_is_refused(self):
        from django.test import RequestFactory
        from django.contrib.sessions.backends.db import SessionStore

        request = RequestFactory().get('/accounts/login/', HTTP_HOST='127.0.0.1')
        request.session = SessionStore()
        google_oauth.start(request, '')
        with self.assertRaises(GoogleAuthError):
            google_oauth.consume_state(request, 'a-state-we-never-issued')


class GoogleButtonVisibilityTests(TestCase):
    """
    The button appears only when BOTH halves of the client are configured.

    A half-configured deployment shows password login and nothing else, rather
    than a button that leads to an error page.
    """

    @override_settings(GOOGLE_OAUTH_CLIENT_ID='', GOOGLE_OAUTH_CLIENT_SECRET='')
    def test_hidden_when_nothing_is_configured(self):
        response = self.client.get(reverse('account_login'))
        self.assertNotContains(response, '/accounts/google/')

    @override_settings(GOOGLE_OAUTH_CLIENT_ID=CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET='')
    def test_hidden_when_only_the_client_id_is_set(self):
        """The state this deployment is in right now."""
        response = self.client.get(reverse('account_login'))
        self.assertNotContains(response, '/accounts/google/')

    @override_settings(GOOGLE_OAUTH_CLIENT_ID=CLIENT_ID,
                       GOOGLE_OAUTH_CLIENT_SECRET='test-secret')
    def test_shown_when_both_are_set(self):
        response = self.client.get(reverse('account_login'))
        self.assertContains(response, '/accounts/google/')

    @override_settings(GOOGLE_OAUTH_CLIENT_ID=CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET='')
    def test_coming_soon_is_shown_on_login_and_register_until_configured(self):
        """Visible but disabled: it promises the feature without a dead link."""
        for name in ('account_login', 'account_register'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, 'Coming soon')
                self.assertContains(response, 'Continue with Google')
                self.assertContains(response, 'disabled')

    @override_settings(GOOGLE_OAUTH_CLIENT_ID=CLIENT_ID,
                       GOOGLE_OAUTH_CLIENT_SECRET='test-secret')
    def test_coming_soon_disappears_once_configured(self):
        for name in ('account_login', 'account_register'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertNotContains(response, 'Coming soon')
                self.assertContains(response, '/accounts/google/')

    @override_settings(GOOGLE_OAUTH_CLIENT_ID='', GOOGLE_OAUTH_CLIENT_SECRET='')
    def test_starting_the_flow_unconfigured_redirects_rather_than_erroring(self):
        response = self.client.get(reverse('account_google_start'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])


@override_settings(GOOGLE_OAUTH_CLIENT_ID=CLIENT_ID,
                   GOOGLE_OAUTH_CLIENT_SECRET='test-secret')
class AccountMatchingTests(TestCase):
    """Which account a verified Google identity is allowed to become."""

    def identity(self, email='buyer@example.com'):
        return {'sub': '1', 'email': email, 'email_verified': True,
                'name': 'Test Buyer', 'given_name': 'Test', 'family_name': 'Buyer'}

    def test_a_new_email_creates_a_customer(self):
        from accounts.views import _user_from_google

        user, created = _user_from_google(self.identity('brand-new@example.com'))
        self.assertTrue(created)
        self.assertEqual(user.profile.role, 'customer')
        self.assertTrue(user.profile.email_verified)

    def test_an_existing_customer_is_matched_not_duplicated(self):
        from accounts.views import _user_from_google

        first, _ = _user_from_google(self.identity('repeat@example.com'))
        second, created = _user_from_google(self.identity('repeat@example.com'))
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(User.objects.filter(email__iexact='repeat@example.com').count(), 1)

    def test_a_staff_account_may_not_sign_in_with_google(self):
        """
        Back-office accounts keep their password.

        Allowing them through an external provider makes the security of the
        back office the security of somebody's personal Google account,
        including its recovery options, which we do not control.
        """
        from django.core.exceptions import PermissionDenied
        from accounts.views import _user_from_google

        staff = User.objects.create_user('boss@example.com', 'boss@example.com', 'pw')
        profile = staff.profile
        profile.role = 'admin'
        profile.save()

        with self.assertRaises(PermissionDenied):
            _user_from_google(self.identity('boss@example.com'))

    def test_a_deactivated_account_is_refused(self):
        from django.core.exceptions import PermissionDenied
        from accounts.views import _user_from_google

        user, _ = _user_from_google(self.identity('gone@example.com'))
        user.is_active = False
        user.save(update_fields=['is_active'])

        with self.assertRaises(PermissionDenied):
            _user_from_google(self.identity('gone@example.com'))

    def test_google_verification_clears_a_pending_email_check(self):
        """Google has just confirmed the address, so our own email can stop waiting."""
        from accounts.views import _user_from_google

        user, _ = _user_from_google(self.identity('pending@example.com'))
        user.profile.email_verified = False
        user.profile.save(update_fields=['email_verified'])

        again, created = _user_from_google(self.identity('pending@example.com'))
        self.assertFalse(created)
        again.profile.refresh_from_db()
        self.assertTrue(again.profile.email_verified)


class AuthPageThemeTests(TestCase):
    """
    Every auth page wears the customer portal's chrome.

    These pages sit in the middle of a customer's journey — portal, sign in,
    portal — and used to be a standalone document carrying the back-office
    styling. The theme changed twice in the middle of logging in, which was most
    obvious on the 2FA step because it added a second admin-looking page.

    Asserting on the shell rather than on colours: if someone re-bases one of
    these templates on the admin layout again, the portal navigation disappears
    and these fail.
    """

    AUTH_PATHS = ['/accounts/login/', '/accounts/register/', '/accounts/password-reset/']

    def test_auth_pages_carry_the_portal_navigation(self):
        for path in self.AUTH_PATHS:
            with self.subTest(path=path):
                html = self.client.get(path).content.decode()
                self.assertIn('navbar-brand', html)
                self.assertIn('auth-card', html)

    def test_auth_pages_load_no_external_assets(self):
        """
        Everything is served locally, and that is not just tidiness.

        The old shell pulled Bootstrap and Inter from jsdelivr and
        fonts.googleapis.com. Google Fonts is blocked in mainland China, where
        this company works from, so the login page was the one page on the site
        that could render unstyled for its own staff.
        """
        for path in self.AUTH_PATHS:
            with self.subTest(path=path):
                html = self.client.get(path).content.decode()
                self.assertNotIn('fonts.googleapis.com', html)
                self.assertNotIn('cdn.jsdelivr.net', html)

    def test_auth_pages_are_not_indexable(self):
        for path in self.AUTH_PATHS:
            with self.subTest(path=path):
                self.assertContains(self.client.get(path), 'noindex')

    def test_flash_messages_are_not_rendered_twice(self):
        """
        The portal base emits messages above <main>.

        The auth shell used to emit its own copy as well, so every login error
        would have appeared twice once the two were combined.
        """
        response = self.client.post('/accounts/login/',
                                    {'username': 'nobody@example.com', 'password': 'wrong'},
                                    follow=True)
        html = response.content.decode()
        self.assertEqual(html.count('Invalid credentials'), 1)


class TwoFactorFlowTests(TestCase):
    """The 2FA step a customer with two_factor_enabled goes through."""

    def setUp(self):
        from customers.models import Customer

        self.user = User.objects.create_user(
            'twofa-test@example.com', 'twofa-test@example.com', 'pw12345')
        customer = Customer.objects.create(name='Two Fa', email='twofa-test@example.com')
        profile = self.user.profile
        profile.role = 'customer'
        profile.customer = customer
        profile.two_factor_enabled = True
        profile.email_verified = True
        profile.save()

    def login(self):
        return self.client.post(
            '/accounts/login/',
            {'username': 'twofa-test@example.com', 'password': 'pw12345'})

    def test_password_alone_does_not_start_a_session(self):
        """The whole point: the code is a second factor, not a formality."""
        self.login()
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_the_code_page_uses_the_portal_shell(self):
        self.login()
        html = self.client.get('/accounts/otp/').content.decode()
        self.assertIn('navbar-brand', html)
        self.assertIn('auth-card', html)
        self.assertNotIn('cdn.jsdelivr.net', html)

    def test_a_correct_code_lands_the_customer_in_the_portal(self):
        self.login()
        code = self.client.session['otp_code']
        response = self.client.post('/accounts/otp/', {'code': code})
        self.assertRedirects(response, '/portal/dashboard/', fetch_redirect_response=False)
        self.assertIn('_auth_user_id', self.client.session)
        # The legacy key several public portal views still read.
        self.assertTrue(self.client.session.get('customer_id'))

    def test_a_wrong_code_does_not_sign_anyone_in(self):
        self.login()
        self.client.post('/accounts/otp/', {'code': '000000'})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_the_code_is_not_rendered_into_the_page(self):
        """
        A code that appears in the HTML is not a second factor.

        Someone reading the page they were already served would have both
        halves, which defeats the point of emailing it.
        """
        self.login()
        code = self.client.session['otp_code']
        html = self.client.get('/accounts/otp/').content.decode()
        self.assertNotIn(code, html)
