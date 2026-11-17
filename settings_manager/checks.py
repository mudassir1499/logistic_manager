"""
settings_manager/checks.py

Deployment checks that run under ``manage.py check``.

These exist because of a failure that cost real time to find: on the cPanel
deployment ``DJANGO_MEDIA_ROOT`` was not set, so MEDIA_ROOT fell back to
``BASE_DIR / 'media'`` — a directory outside the Apache document root.

Nothing complained. The site started, every page rendered, and the product
images that had been copied into ``public_html/media`` by hand kept loading.
Only files uploaded THROUGH the app were affected, because only those are
written by Django, and they landed somewhere the web server cannot serve. The
symptom therefore appeared days after the deploy, on a screen unrelated to the
setting, as "new product images are broken".

A check that fails loudly at deploy time is worth more than a comment in a
deployment guide that was already correct and still got missed.

REGISTERING A CHECK AS DEPLOY-ONLY

Both checks here are registered with ``deploy=True``, which is the keyword that
makes Django run them only under ``manage.py check --deploy``.

They were previously registered as ``@register('deploy')``, which looks like it
does the same thing and does not: that passes "deploy" as a TAG, and a tagged
check still runs on every single management command. The consequence was that
E001 below — an Error, so fatal — fired on ``migrate``, on ``collectstatic``,
and on ``manage.py test``, because the test runner forces DEBUG to False before
running checks and so walked straight past the DEBUG guard. The whole test suite
was unrunnable on a machine whose .env has DEBUG off.

The DEBUG guards inside each function are kept as a second line of defence, for
anyone who runs ``check --deploy`` against a development configuration.
"""

from pathlib import Path

from django.conf import settings
from django.core.checks import Error, Warning, register


@register(deploy=True)
def check_media_root_is_servable(app_configs, **kwargs):
    """
    With DEBUG off, MEDIA_ROOT must be somewhere the web server can reach.

    Django refuses to serve media when DEBUG is False (see the project URLConf),
    so uploads are only reachable if the web server is serving MEDIA_ROOT
    directly. On shared hosting that means it has to sit inside the document
    root — typically ``public_html``.

    We cannot know the document root for certain, so the test is the one signal
    that is reliably wrong: MEDIA_ROOT sitting inside the project directory,
    which is exactly what the fallback produces when the setting is missing.
    """
    if settings.DEBUG:
        # In development the URLConf serves media itself, so any path works.
        return []

    media_root = Path(settings.MEDIA_ROOT).resolve()
    base_dir = Path(settings.BASE_DIR).resolve()

    problems = []

    if base_dir == media_root or base_dir in media_root.parents:
        problems.append(Error(
            'MEDIA_ROOT is inside the project directory, where the web server '
            'cannot serve it.',
            hint=(
                f'MEDIA_ROOT is currently {media_root}. With DEBUG=False Django '
                'does not serve uploaded files, so anything uploaded through the '
                'app will 404 while files placed in the document root by hand '
                'keep working — which makes this look like an image bug rather '
                'than a configuration one. Set DJANGO_MEDIA_ROOT in .env to a '
                'directory inside the document root, e.g. '
                '/home/<user>/public_html/media, then move the existing files '
                'there and restart.'
            ),
            id='settings_manager.E001',
        ))
    elif not media_root.exists():
        problems.append(Warning(
            f'MEDIA_ROOT does not exist: {media_root}',
            hint='Create the directory and make sure the application user can '
                 'write to it, or uploads will fail at save time.',
            id='settings_manager.W001',
        ))

    static_root = Path(settings.STATIC_ROOT).resolve()
    if base_dir == static_root or base_dir in static_root.parents:
        problems.append(Warning(
            'STATIC_ROOT is inside the project directory.',
            hint=(
                f'STATIC_ROOT is currently {static_root}. WhiteNoise serves static '
                'files from the application, so this is survivable — but Apache '
                'serving them directly from the document root is faster. Set '
                'DJANGO_STATIC_ROOT alongside DJANGO_MEDIA_ROOT.'
            ),
            id='settings_manager.W002',
        ))

    return problems


@register(deploy=True)
def check_google_oauth(app_configs, **kwargs):
    """
    Catch the two Google sign-in misconfigurations that fail silently.

    Both of these leave a site that starts, serves every page, and looks
    healthy — which is exactly why they need a check rather than a note in a
    deployment guide.

    HALF-CONFIGURED. The button only renders when BOTH the client ID and the
    secret are present. Set one and forget the other and there is no error
    anywhere: the button simply never appears, and the natural conclusion is
    that the feature was not deployed rather than that a variable is missing.

    HTTP CALLBACK. The redirect URI is built from the incoming request, so with
    HTTPS off it comes out as ``http://...``. Google rejects non-HTTPS redirect
    URIs for anything except localhost, so every sign-in dies at the consent
    screen with redirect_uri_mismatch — a message that points at the Google
    console, not at this setting.
    """
    if settings.DEBUG:
        # Development. A half-finished Google setup is the normal state while
        # someone is in the middle of doing it, and these checks run on EVERY
        # manage.py command - an Error here would block migrate and
        # collectstatic on a developer's machine over an optional feature.
        return []

    client_id = getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')
    client_secret = getattr(settings, 'GOOGLE_OAUTH_CLIENT_SECRET', '')

    if not client_id and not client_secret:
        # Deliberately unconfigured. Password login is unaffected and the button
        # is hidden, so this is a supported state, not a problem.
        return []

    problems = []

    # These are Warnings, not Errors, and that is a deliberate proportionality
    # call. Google sign-in is a convenience on top of password login: a broken
    # one is worth shouting about, but an Error makes manage.py refuse to run,
    # which would block a deploy - or a migration fixing something urgent -
    # over an optional feature that is not even reached by most visitors.
    if bool(client_id) != bool(client_secret):
        missing = 'GOOGLE_OAUTH_CLIENT_SECRET' if client_id else 'GOOGLE_OAUTH_CLIENT_ID'
        problems.append(Warning(
            f'Google sign-in is half-configured: {missing} is not set.',
            hint=(
                'Both values are required before the "Continue with Google" '
                'button will appear. With only one set the button stays hidden '
                'and nothing reports why. Add the missing value to .env and '
                'restart. The client ID is public; the secret must never be '
                'committed to git.'
            ),
            id='settings_manager.W004',
        ))

    if client_id and not client_id.endswith('.apps.googleusercontent.com'):
        problems.append(Warning(
            'GOOGLE_OAUTH_CLIENT_ID does not look like a Google client ID.',
            hint=(
                f'It is currently {client_id[:40]}... A web client ID from the '
                'Google Cloud console always ends in .apps.googleusercontent.com. '
                'A truncated or mistyped value fails at the consent screen with '
                'invalid_client.'
            ),
            id='settings_manager.W003',
        ))

    if client_id and client_secret and not getattr(settings, 'USE_HTTPS', False):
        problems.append(Warning(
            'Google sign-in is enabled but HTTPS is off.',
            hint=(
                'The callback URL is derived from the incoming request, so it '
                'will be built as http://.../accounts/google/callback/ — and '
                'Google only accepts http for localhost. Every sign-in will fail '
                'with redirect_uri_mismatch. Set DJANGO_SECURE_SSL=1 in .env '
                '(and make sure the proxy sends X-Forwarded-Proto).'
            ),
            id='settings_manager.W005',
        ))

    return problems


# The Django release requirements.txt pins. Migrations generated under another
# major version can differ in ways that only show up as a model/migration
# mismatch later - several here were made under 5.2 while the project runs 4.2.
PINNED_DJANGO = (4, 2)


@register()
def check_django_version(app_configs, **kwargs):
    """Warn when the running Django is not the version requirements.txt pins."""
    import django

    if django.VERSION[:2] == PINNED_DJANGO:
        return []
    return [Warning(
        f'Running Django {django.get_version()}, but requirements.txt pins '
        f'{PINNED_DJANGO[0]}.{PINNED_DJANGO[1]}.',
        hint=('Use the project virtualenv (.venv/Scripts/python.exe manage.py ...), '
              'especially for makemigrations. Migrations made under a different '
              'Django version are how the models and migrations drifted apart before.'),
        id='settings_manager.W006',
    )]
