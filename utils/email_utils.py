"""
Email utility for sending typed transactional emails.

This module provides a single helper, send_typed_email(), that picks the correct
SMTP profile from CompanySettings based on the email purpose:

  - order_status: order confirmations, shipping updates, delivery notifications
  - security:   registration confirmations, login alerts, password resets
  - news:       new product announcements (Amazon/Noon), catalog updates

If a profile is not fully configured, the helper falls back to Django's default
EMAIL_BACKEND (console in development, SMTP in production) so the site keeps
working during setup.
"""

# EmailMultiAlternatives is used only when a reply_to is requested; send_mail()
# does not expose that header.
from django.core.mail import send_mail, get_connection, EmailMultiAlternatives
from django.conf import settings as django_settings

from settings_manager.models import CompanySettings


VALID_EMAIL_TYPES = {'order_status', 'security', 'news'}


def get_email_connection(email_type='order_status'):
    """
    Build a Django email backend connection for the requested email type.

    Args:
        email_type (str): 'order_status', 'security', or 'news'.

    Returns:
        EmailBackend: A Django email backend configured from CompanySettings,
                      or the default backend if no SMTP host is configured.
    """
    email_type = str(email_type or 'order_status').lower()
    if email_type not in VALID_EMAIL_TYPES:
        email_type = 'order_status'

    profile = CompanySettings.get_settings().get_smtp_profile(email_type)
    host = profile.get('host', '')

    if not host:
        # No SMTP host configured for this profile; return the default backend.
        return get_connection(backend=django_settings.EMAIL_BACKEND)

    return get_connection(
        backend='django.core.mail.backends.smtp.EmailBackend',
        host=host,
        port=profile.get('port', 587),
        username=profile.get('user', ''),
        password=profile.get('password', ''),
        use_tls=profile.get('use_tls', True),
    )


def send_typed_email(email_type, subject, message, recipient_list, html_message=None,
                     from_email=None, fail_silently=True, reply_to=None):
    """
    Send an email using the SMTP profile matching the requested type.

    Args:
        email_type (str): 'order_status', 'security', or 'news'.
        subject (str): Email subject line.
        message (str): Plain-text message body.
        recipient_list (list): List of recipient email addresses.
        html_message (str, optional): HTML version of the message.
        from_email (str, optional): Override the profile's from address.
        fail_silently (bool): If True, suppress email errors. Default True to avoid
                              breaking order flows when SMTP is misconfigured.
        reply_to (list, optional): Addresses that receive replies instead of
                              `from_email`. Used by the new-lead alert so that
                              pressing Reply answers the customer directly rather
                              than the company's own inbox — which turns a
                              three-step follow-up into one.

    Returns:
        int: Number of messages sent (0 or more).
    """
    email_type = str(email_type or 'order_status').lower()
    if email_type not in VALID_EMAIL_TYPES:
        email_type = 'order_status'

    profile = CompanySettings.get_settings().get_smtp_profile(email_type)
    if from_email is None:
        from_email = profile.get('from_address') or django_settings.DEFAULT_FROM_EMAIL

    try:
        connection = get_email_connection(email_type)

        # send_mail() has no reply_to parameter, so the richer EmailMultiAlternatives
        # is used only when one is supplied. Existing callers keep the exact code
        # path they had before.
        if reply_to:
            email = EmailMultiAlternatives(
                subject=subject,
                body=message,
                from_email=from_email,
                to=recipient_list,
                reply_to=reply_to,
                connection=connection,
            )
            if html_message:
                email.attach_alternative(html_message, 'text/html')
            return email.send(fail_silently=fail_silently)

        return send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            html_message=html_message,
            connection=connection,
            fail_silently=fail_silently,
        )
    except Exception:
        if not fail_silently:
            raise
        return 0
