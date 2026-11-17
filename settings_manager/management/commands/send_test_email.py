"""
Prove an SMTP profile actually works, and say precisely why when it does not.

WHY THIS COMMAND EXISTS

Every email in this project goes through ``send_typed_email``, which defaults to
``fail_silently=True``. That default is right: a customer placing an order must
not see a 500 because the mail server was briefly unreachable. But it has a
consequence that is easy to miss — a completely unconfigured mail setup behaves
exactly like a working one. Orders go through, tickets get answered, password
resets report success, and nothing arrives. There is no error anywhere, because
the error was deliberately swallowed.

So the only way to know email works is to send one on purpose, with the
swallowing turned off. That is this command.

    python manage.py send_test_email --to you@example.com
    python manage.py send_test_email --to you@example.com --profile security

It reports the resolved configuration first, then attempts a real send, and
exits non-zero on failure so it can gate a deploy script.

Passwords are never printed — only whether one is set.
"""

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings as django_settings

from settings_manager.models import CompanySettings
from utils.email_utils import send_typed_email

PROFILES = ('order_status', 'security', 'news')

# What each profile is actually used for, so the output explains what breaks
# when one of them is down rather than just naming it.
PURPOSE = {
    'order_status': 'order confirmations, shipping and delivery notices',
    'security': 'password resets, sign-in codes, email verification, '
                'support replies and new-enquiry alerts',
    'news': 'new product announcements',
}


class Command(BaseCommand):
    help = 'Send a test email through one or every SMTP profile and report the result.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--to', required=True,
            help='Where to send the test. Use an address on a different provider '
                 'from the sender - a message that never leaves the server looks '
                 'identical to one that was delivered.',
        )
        parser.add_argument(
            '--profile', default='all', choices=PROFILES + ('all',),
            help='Which profile to test. Default: all three.',
        )

    def handle(self, *args, **options):
        recipient = options['to'].strip()
        chosen = PROFILES if options['profile'] == 'all' else (options['profile'],)

        settings = CompanySettings.get_settings()

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Django email backend'))
        self.stdout.write(f'  {django_settings.EMAIL_BACKEND}')

        # The trap worth naming explicitly. With the SMTP backend selected and no
        # host on the profile, Django falls back to its own EMAIL_HOST default of
        # localhost:25 - which on this kind of hosting is nothing at all.
        backend_is_smtp = 'smtp' in django_settings.EMAIL_BACKEND
        if backend_is_smtp:
            fallback_host = getattr(django_settings, 'EMAIL_HOST', '') or 'localhost'
            self.stdout.write(
                f'  Profiles with no host of their own fall back to {fallback_host}:'
                f'{getattr(django_settings, "EMAIL_PORT", 25)}'
            )

        failures = []
        unconfigured = []

        for name in chosen:
            profile = settings.get_smtp_profile(name)
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(f'[{name}]  {PURPOSE[name]}'))
            self.stdout.write(f'  from     : {profile["from_address"] or "(not set)"}')
            self.stdout.write(f'  host     : {profile["host"] or "(not set)"}')
            self.stdout.write(f'  port     : {profile["port"]}   TLS: {profile["use_tls"]}')
            self.stdout.write(f'  username : {profile["user"] or "(not set)"}')
            # Never the value. Whether it exists is the only useful part.
            self.stdout.write(f'  password : {"set" if profile["password"] else "(not set)"}')

            if not profile['host']:
                unconfigured.append(name)
                self.stdout.write(self.style.WARNING(
                    '  No SMTP host. This profile is not configured; mail sent through '
                    'it is being discarded silently.'
                ))
                if name != 'order_status':
                    self.stdout.write(
                        '  (It would inherit the order_status server if that one had a host.)'
                    )

            sent = self._attempt(name, recipient)
            if sent:
                self.stdout.write(self.style.SUCCESS(f'  Sent to {recipient}.'))
            else:
                failures.append(name)

        self._summarise(chosen, failures, unconfigured, recipient)

        if failures:
            raise CommandError(
                f'{len(failures)} of {len(chosen)} profile(s) could not send: '
                f'{", ".join(failures)}'
            )

    def _attempt(self, name, recipient):
        """
        Try one real send with error suppression turned OFF.

        Args:
            name (str): the profile.
            recipient (str): where to send it.

        Returns:
            bool: whether the message was accepted by the server.

        fail_silently=False is the entire point — the application deliberately
        hides these errors, and this is the one place that must not.
        """
        subject = f'[{name}] Test email from {CompanySettings.get_settings().company_name}'
        body = (
            f'This is a test of the "{name}" SMTP profile.\n\n'
            f'It covers: {PURPOSE[name]}.\n\n'
            'If you are reading this, that profile can deliver mail.\n'
        )
        try:
            count = send_typed_email(
                name, subject, body, [recipient], fail_silently=False)
            return bool(count)
        except Exception as error:                              # noqa: BLE001
            # The exception text from smtplib is the genuinely useful part —
            # authentication failed, connection refused, certificate problem —
            # so it is shown verbatim rather than summarised away.
            self.stdout.write(self.style.ERROR(f'  FAILED: {error.__class__.__name__}: {error}'))
            self.stdout.write(self.style.ERROR(f'  {self._hint(error)}'))
            return False

    def _hint(self, error):
        """Turn the common smtplib failures into something actionable."""
        text = f'{error.__class__.__name__}: {error}'.lower()

        if 'authentication' in text or 'username and password' in text or '535' in text:
            return ('The server rejected the username or password. For Gmail and '
                    'Workspace this must be an app password, not the account password.')
        if 'connection refused' in text or 'actively refused' in text or 'timed out' in text:
            return ('Nothing answered on that host and port. Check the hostname, and '
                    'that the host allows outbound SMTP on this port.')
        if 'certificate' in text or 'ssl' in text or 'wrong version' in text:
            return ('TLS mismatch. Port 587 normally needs TLS on; port 465 is '
                    'implicit SSL and usually needs it off.')
        if 'sender' in text or 'from' in text or '553' in text or '550' in text:
            return ('The server refused the From address. It usually has to be a real '
                    'mailbox on that server, matching the username.')
        return 'Check the host, port, username, password and TLS setting for this profile.'

    def _summarise(self, chosen, failures, unconfigured, recipient):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Summary'))

        working = [p for p in chosen if p not in failures]
        if working:
            self.stdout.write(self.style.SUCCESS(f'  Delivering: {", ".join(working)}'))
        if failures:
            self.stdout.write(self.style.ERROR(f'  Failing   : {", ".join(failures)}'))

        if unconfigured and 'order_status' in unconfigured:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                '  Nothing is configured at all. Until order_status has a host, every\n'
                '  email this site sends is being thrown away without an error —\n'
                '  including password resets and sign-in codes.'
            ))

        self.stdout.write('')
        self.stdout.write(
            f'  A send reported here only means {recipient} ACCEPTED the message.\n'
            '  Check the inbox, and the spam folder — a new sending domain with no\n'
            '  SPF or DKIM record is usually delivered straight to spam.'
        )
        self.stdout.write('')
