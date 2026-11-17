"""
portal/context_processors.py
================================================================================
Global template context for the public website
================================================================================

`portal/templates/portal/base.html` renders the company's SEO surface — title,
meta description, Open Graph tags, JSON-LD structured data, the Google Analytics
tag and the Search Console verification meta. Every one of those reads from the
singleton `CompanySettings` row via a `settings` template variable.

Historically each view had to remember to put `'settings': settings` in its own
context dictionary. Any view that forgot silently rendered a page with a missing
company name, no analytics tag and no verification meta — an SEO regression that
is invisible in local testing and only shows up as missing Search Console data
weeks later.

This context processor makes `settings` available to every template so the head
of the page is always complete, regardless of which view rendered it. Views that
pass their own `settings` still win: view context takes precedence over context
processors in Django, so nothing existing changes behaviour.

Performance note:
    The lookup is wrapped in SimpleLazyObject, so the database is only touched if
    a template actually dereferences `settings`. Requests that render no template
    (AJAX/JSON endpoints, redirects) pay nothing.
"""

from django.utils.functional import SimpleLazyObject

from settings_manager.models import CompanySettings, SiteImage


def site_settings(request):
    """
    Expose the singleton CompanySettings row to every template as `settings`.

    Args:
        request (HttpRequest): The current request (unused — the settings row is
                               global, not per-user — but required by Django's
                               context-processor signature).

    Returns:
        dict: {'settings': <lazy CompanySettings>} — evaluated on first access.
    """
    return {'settings': SimpleLazyObject(CompanySettings.get_settings)}


def site_images(request):
    """
    Expose owner-uploaded photographs to every template as `site_images`.

    Args:
        request (HttpRequest): The current request (unused; imagery is global).

    Returns:
        dict: {'site_images': {slot: SiteImage}} — a lazy dict keyed by slot name.

    Usage in a template:

        {% if site_images.home_feature %}
          <img src="{{ site_images.home_feature.image.url }}"
               alt="{{ site_images.home_feature.alt_text }}">
        {% else %}
          <img src="{% static 'images/stock/china-operations.webp' %}" alt="...">
        {% endif %}

    A slot with no upload simply resolves to nothing in the template, so pages
    fall through to their bundled stock image and never render broken. That means
    the owner can fill the slots one at a time, in any order, with no coordination
    between uploading a photo and deploying a template change.

    Wrapped in SimpleLazyObject so pages that reference no imagery — the customer
    portal, the admin, every JSON endpoint — never run the query.
    """
    return {'site_images': SimpleLazyObject(SiteImage.get_map)}
