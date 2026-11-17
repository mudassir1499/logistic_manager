"""
Teaching drf-spectacular about this project's own authentication.

Without this the generated schema describes every endpoint perfectly and says
nothing about how to authenticate to any of them - so /api/v1/docs/ renders with
no Authorize button and a reader has no way to try a call. The endpoints look
documented and are unusable, which is worse than obviously missing docs.

Imported for its side effect: defining the class registers it. api/apps.py does
the import in ready().
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ApiTokenScheme(OpenApiAuthenticationExtension):
    """Describe ApiTokenAuthentication as HTTP bearer auth in the OpenAPI schema."""

    target_class = 'api.authentication.ApiTokenAuthentication'
    name = 'ApiToken'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'description': (
                'Issue a token at /accounts/api-tokens/ and send it as '
                '`Authorization: Bearer <token>`. A token carries exactly the '
                'permissions of the account that owns it - a customer account '
                'produces a customer-scoped token, and revoking the token or '
                'disabling the account revokes API access immediately.'
            ),
        }
