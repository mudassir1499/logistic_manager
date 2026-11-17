"""
DRF authentication backed by the ApiToken rows this project already issues.

WHY NOT DRF's OWN TokenAuthentication

rest_framework.authtoken stores tokens in plaintext, one per user, with no name,
no revocation beyond deletion and no last-used timestamp. This project already
has something better in ``accounts.ApiToken``: the token is stored as a SHA-256
hash so a database leak does not hand over working credentials, several can
exist per user with names, each can be revoked independently, and use is
recorded. Adding a second token system alongside it would mean two places to
revoke and one of them forgotten.

So this class adapts what exists rather than replacing it, and the tokens the
extension already uses work against the new API with no migration.
"""

from django.utils import timezone
from rest_framework import authentication, exceptions

from accounts.models import ApiToken

# Updating a timestamp on every single request is a write per read. A token used
# in a tight loop would otherwise generate one UPDATE per call for information
# nobody needs to the second.
LAST_USED_RESOLUTION_SECONDS = 300


class ApiTokenAuthentication(authentication.BaseAuthentication):
    """
    Authenticate ``Authorization: Bearer <token>`` against accounts.ApiToken.

    Returns:
        tuple[User, ApiToken] | None: None when there is no bearer header at
        all, which lets DRF fall through to session authentication so the
        browsable API works for a logged-in staff user.
    """

    keyword = 'Bearer'

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode('latin-1')
        if not header:
            return None

        parts = header.split()
        if parts[0] != self.keyword:
            # Some other scheme (Basic, session). Not ours to judge.
            return None
        if len(parts) == 1:
            raise exceptions.AuthenticationFailed('Bearer token missing after the scheme.')
        if len(parts) > 2:
            raise exceptions.AuthenticationFailed('Bearer token must not contain spaces.')

        raw = parts[1].strip()
        if not raw:
            raise exceptions.AuthenticationFailed('Empty bearer token.')

        token = (
            ApiToken.objects
            .select_related('user', 'user__profile')
            .filter(token_hash=ApiToken.hash_token(raw), is_active=True)
            .first()
        )

        # One message for "no such token", "revoked" and "owner disabled".
        # Distinguishing them would confirm to someone guessing that a token
        # exists, which is exactly the thing worth not confirming.
        if token is None or not token.user.is_active:
            raise exceptions.AuthenticationFailed('Token is invalid or has been revoked.')

        self._touch(token)
        return (token.user, token)

    @staticmethod
    def _touch(token):
        """Record use, but no more often than LAST_USED_RESOLUTION_SECONDS."""
        now = timezone.now()
        if (token.last_used_at is None
                or (now - token.last_used_at).total_seconds() > LAST_USED_RESOLUTION_SECONDS):
            # update_fields so this never races with an unrelated edit to the row.
            ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)
            token.last_used_at = now

    def authenticate_header(self, request):
        """
        The WWW-Authenticate value.

        Returning this is what makes DRF answer an unauthenticated request with
        401 rather than 403 - without it, a caller with no credentials at all is
        told "forbidden", which reads as "your token is wrong" and sends people
        looking in the wrong place.
        """
        return self.keyword
