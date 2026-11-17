"""
Password reset for API clients.

An app user who forgets their password otherwise has to find the website, which
is a dead end in a mobile flow.

THE RESET LINK STILL POINTS AT THE WEBSITE, and that is deliberate. The email
carries a URL to the existing browser confirmation page rather than a bare token
for the app to consume. Emailing a raw token means it sits in an inbox, in a
mail provider's logs, and in whatever previews the mail client renders - and any
app claiming to be yours could collect it. Sending people to a page on the real
domain is the flow they can verify by looking at the address bar.

The app's job is only to ask for the email. Django's own token generator is used,
so a link works exactly once and stops working the moment the password changes.
"""

import logging

from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.validators import validate_password_strength
from settings_manager.models import CompanySettings
from utils.email_utils import send_typed_email

logger = logging.getLogger(__name__)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    new_password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate_new_password(self, value):
        error = validate_password_strength(value)
        if error:
            raise serializers.ValidationError(error)
        return value


class PasswordResetRequestView(APIView):
    """Email a reset link to an address, if an account has it."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'auth'

    @extend_schema(
        summary='Request a password reset email',
        request=PasswordResetRequestSerializer,
        responses={200: OpenApiResponse(
            description='Always 200, whether or not the address is registered.')},
    )
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()

        user = (User.objects.filter(username__iexact=email).first()
                or User.objects.filter(email__iexact=email).first())

        if user is not None and user.is_active:
            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = request.build_absolute_uri(
                reverse('account_password_reset_confirm',
                        kwargs={'uidb64': uidb64, 'token': token})
            )
            settings_obj = CompanySettings.get_settings()
            send_typed_email(
                email_type='security',
                subject=f'Reset your {settings_obj.company_name} password',
                message=(
                    f'A password reset was requested for this account.\n\n'
                    f'Open this link to choose a new password:\n{link}\n\n'
                    f'The link can be used once and expires. If you did not ask '
                    f'for this, you can ignore this email - nothing has changed.\n\n'
                    f'{settings_obj.company_name}'
                ),
                recipient_list=[user.email or email],
                fail_silently=True,
            )
        else:
            logger.info('Password reset requested for unknown address %r', email)

        # The SAME response either way, and deliberately so. Returning 404 for an
        # unknown address turns this endpoint into a way to enumerate which
        # emails hold accounts - a list worth having if you are about to try
        # credential stuffing.
        return Response({
            'detail': 'If that email has an account, a reset link is on its way.',
        })


class PasswordChangeView(APIView):
    """Change the password of the account making the request."""

    permission_classes = [IsAuthenticated]
    throttle_scope = 'auth'

    @extend_schema(
        summary='Change your password',
        request=PasswordChangeSerializer,
        responses={200: OpenApiResponse(description='Password changed'),
                   400: OpenApiResponse(description='Current password wrong, or new one too weak')},
    )
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user

        # The current password is required even though the caller already holds a
        # valid token. A token can be stolen; requiring the password means a
        # stolen token cannot be used to lock the real owner out of their account.
        if not user.check_password(serializer.validated_data['current_password']):
            return Response({'current_password': ['That is not your current password.']},
                            status=status.HTTP_400_BAD_REQUEST)

        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])

        # Existing tokens are left alone on purpose. Revoking them would sign the
        # person out of every device the moment they tidied up their password,
        # which is not what changing a password means to most people. Anyone who
        # believes a token is compromised revokes it at /accounts/api-tokens/.
        return Response({'detail': 'Password changed.'})
