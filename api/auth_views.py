"""
Registration, login and logout for API clients.

A mobile app cannot use the website's session login: there is no browser to hold
a cookie and no page to POST a form to. Without these three endpoints the only
way to get a token is to open the site in a browser and mint one by hand, which
is not a signup flow anybody would ship.

WHAT LOGIN ACTUALLY DOES

It exchanges a password for a bearer token. The password is used once, on that
call, and never stored by the client - the app keeps the token instead. That is
the point: a leaked token is revocable from /accounts/api-tokens/ without
changing the password, and it carries only the permissions of its owner.

WHY BACK-OFFICE ACCOUNTS CANNOT LOG IN HERE

Staff logins go through the website, which has the one-time-code step. Handing
out an admin bearer token in exchange for a password would route around that,
and an admin token is a far more valuable thing to lose than a customer one.
Same reasoning as the Google sign-in restriction.
"""

import logging

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import ApiToken, Profile
from accounts.validators import validate_password_strength
from customers.models import Customer

logger = logging.getLogger(__name__)

# A token minted by an app, so it is identifiable in the token list later and a
# person can tell "my phone" apart from "the 1688 extension" when revoking.
MOBILE_TOKEN_NAME = 'Mobile app'


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    address = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_email(self, value):
        email = value.strip().lower()
        if (Customer.objects.filter(email__iexact=email).exists()
                or User.objects.filter(username__iexact=email).exists()):
            # Deliberately the same wording the website uses. It does reveal that
            # an account exists, which is a real trade-off - but a registration
            # form that accepts a duplicate and then fails silently is worse, and
            # the address is one the caller already claims to own.
            raise serializers.ValidationError('An account with this email already exists.')
        return email

    def validate_password(self, value):
        error = validate_password_strength(value)
        if error:
            raise serializers.ValidationError(error)
        return value


class LoginSerializer(serializers.Serializer):
    email = serializers.CharField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})


class TokenSerializer(serializers.Serializer):
    """The response shape for register and login."""

    token = serializers.CharField(help_text='Send as: Authorization: Bearer <token>')
    token_prefix = serializers.CharField(help_text='Identifies this token in the token list.')
    username = serializers.CharField()
    role = serializers.CharField()
    customer_id = serializers.IntegerField(allow_null=True)


def _issue(user, name=MOBILE_TOKEN_NAME):
    """Mint a token and shape the response. The raw value exists only here."""
    token, raw = ApiToken.issue(user=user, name=name)
    profile = getattr(user, 'profile', None)
    return {
        'token': raw,
        'token_prefix': token.prefix,
        'username': user.get_username(),
        'role': getattr(profile, 'role', ''),
        'customer_id': getattr(profile, 'customer_id', None),
    }


class RegisterView(APIView):
    """Create a customer account and return a token for it."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'auth'

    @extend_schema(
        summary='Register a customer account',
        request=RegisterSerializer,
        responses={201: TokenSerializer,
                   400: OpenApiResponse(description='Validation failed')},
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # One transaction for all three rows. A Customer without its User, or a
        # User whose Profile was never pointed at its Customer, is an account
        # that exists and cannot be used - and nothing would report it.
        with transaction.atomic():
            customer = Customer.objects.create(
                name=data['name'], phone=data.get('phone', ''),
                email=data['email'], address=data.get('address', ''),
                is_active=True,
            )
            # Keep the legacy mirrored hash in step with the website's own
            # registration path.
            customer.set_password(data['password'])
            customer.save(update_fields=['password'])

            user = User.objects.create_user(
                username=data['email'], email=data['email'], password=data['password'],
            )
            profile = user.profile          # created by the post_save signal
            profile.role = Profile.ROLE_CUSTOMER
            profile.customer = customer
            profile.save()

        return Response(_issue(user), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """Exchange an email and password for a bearer token."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'auth'

    @extend_schema(
        summary='Log in and receive a token',
        request=LoginSerializer,
        responses={200: TokenSerializer,
                   401: OpenApiResponse(description='Invalid credentials')},
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data['email'].strip()
        password = serializer.validated_data['password']

        # Accounts are created with the email as the username, but staff-created
        # ones may not be, so try both. authenticate() is what applies the
        # password hasher's constant-time comparison.
        user = authenticate(request, username=identifier, password=password)
        if user is None:
            match = User.objects.filter(email__iexact=identifier).first()
            if match is not None:
                user = authenticate(request, username=match.get_username(), password=password)

        # One message for "no such account" and "wrong password". Distinguishing
        # them turns this endpoint into a way to test which addresses are
        # registered.
        if user is None or not user.is_active:
            logger.info('API login failed for %r', identifier)
            return Response({'detail': 'Invalid email or password.'},
                            status=status.HTTP_401_UNAUTHORIZED)

        profile = getattr(user, 'profile', None)
        if profile is None or profile.role != Profile.ROLE_CUSTOMER:
            return Response(
                {'detail': 'Staff accounts sign in on the website. '
                           'Issue an API token there instead.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(_issue(user))


class StaffLoginView(APIView):
    """
    Sign a BACK-OFFICE account in and mint a token for the admin app.

    Separate from LoginView, which serves customers and deliberately refuses
    staff. The two are kept apart rather than merged behind a role check
    because they are different products with different risks: a customer login
    reaches a catalogue and their own orders, while this one reaches every
    order, every customer and the ledger.

    WHY THIS EXISTS AT ALL

    Staff could already mint a token at /accounts/api-tokens/ and paste it in.
    That is a reasonable flow for the 1688 browser extension, which is set up
    once on a desktop; it is a poor one on a phone, where the person is holding
    the device that needs the token and cannot easily copy a 40-character
    secret onto it.

    The account must be back-office. A customer hitting this endpoint is
    refused with the same message a wrong password gets, so it cannot be used
    to discover which addresses are staff.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'auth'

    @extend_schema(
        summary='Staff sign-in for the admin app',
        request=LoginSerializer,
        responses={200: TokenSerializer,
                   401: OpenApiResponse(description='Invalid credentials')},
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data['email'].strip()
        password = serializer.validated_data['password']

        # Staff usernames are not always emails - accounts created by an admin
        # often use a short name - so both are accepted.
        user = authenticate(username=identifier, password=password)
        if user is None:
            match = User.objects.filter(email__iexact=identifier).first()
            if match is not None:
                user = authenticate(username=match.get_username(), password=password)

        profile = getattr(user, 'profile', None) if user else None

        # One message for "no such account", "wrong password" and "not staff".
        # Distinguishing them would turn this into a way to enumerate which
        # addresses belong to employees.
        if user is None or profile is None or not profile.is_back_office:
            return Response({'detail': 'Invalid credentials.'},
                            status=status.HTTP_401_UNAUTHORIZED)

        return Response(_issue(user, name='Admin app'))


class LogoutView(APIView):
    """
    Revoke the token that made this request.

    Only that one token. Revoking every token for the account would sign the
    person out of their other devices - and out of the 1688 extension - because
    they closed an app on their phone.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = 'auth'

    @extend_schema(summary='Revoke the current token',
                   request=None,
                   responses={204: OpenApiResponse(description='Token revoked')})
    def post(self, request):
        token = getattr(request, 'auth', None)
        if isinstance(token, ApiToken):
            ApiToken.objects.filter(pk=token.pk).update(is_active=False)
        # 204 either way: a caller logging out with a session cookie rather than
        # a token has nothing to revoke, and telling them so serves no purpose.
        return Response(status=status.HTTP_204_NO_CONTENT)
