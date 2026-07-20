"""
portal/sitemaps.py
================================================================================
Django Sitemap Framework for the Public Portal
================================================================================

This module defines sitemap classes used by Django's built-in sitemap framework
to automatically generate a sitemap.xml file for search engines.

The sitemap.xml tells Google, Bing, and other search engines:
  - Which pages exist on the site
  - How often they change (change frequency)
  - How important they are relative to other pages (priority)
  - When they were last modified

Business Purpose:
    A sitemap.xml improves SEO by ensuring search engines discover all public
    pages on the site. Without a sitemap, search engines rely on crawling links,
    which may miss pages that are not well-linked (e.g., the contact page, FAQ).

For more information:
    https://docs.djangoproject.com/en/4.2/ref/contrib/sitemaps/
"""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticViewSitemap(Sitemap):
    """
    Sitemap for all static public pages in the portal.

    Django's sitemap framework works by creating a subclass of Sitemap and
    defining the items() and location() methods. items() returns a list of
    objects (here, URL names), and location() returns the URL for each item.

    Attributes:
        changefreq (str): How often the content changes. 'weekly' is appropriate
                          for marketing pages that are updated occasionally.
        priority (float): Relative importance (0.0 to 1.0). 0.5 is the default.
                          The homepage gets 1.0, other pages 0.8.

    The protocol is automatically determined by Django based on whether the
    request is HTTP or HTTPS. In production (mudassirllc.com), HTTPS is used.
    """
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        """
        Returns a list of named URL patterns for all public pages.

        These are the URL names defined in logistic_manager/urls.py and portal/urls.py.
        Each name corresponds to a public-facing page that should be indexed by
        search engines. Only static pages are included here; dynamic pages like
        customer dashboards or admin pages are excluded because they require login.

        Returns:
            list[str]: A list of URL names (e.g., ['front_page', 'about_page', ...]).
        """
        return [
            'front_page',      # Homepage — the most important page
            'about_page',      # About Us
            'services_page',   # Services
            'contact_page',    # Contact
            'portfolio_page',  # Portfolio
            'testimonials_page',  # Testimonials (new)
            'faq_page',        # FAQ (new)
        ]

    def location(self, item):
        """
        Returns the absolute URL path for a given URL name.

        Args:
            item (str): A URL name from the items() list.

        Returns:
            str: The URL path (e.g., '/' for front_page, '/about/' for about_page).

        Uses Django's reverse URL resolver, which looks up the URL pattern by name.
        This is the same mechanism used by the {% url %} template tag.
        """
        return reverse(item)

    def priority(self, item):
        """
        Returns the priority for a specific page.

        The homepage is the most important page (1.0). Other pages are slightly
        lower (0.8) to indicate they are important but secondary to the homepage.

        Args:
            item (str): A URL name from the items() list.

        Returns:
            float: Priority value between 0.0 and 1.0.
        """
        # The homepage is the landing page for most visitors — give it top priority.
        if item == 'front_page':
            return 1.0
        return 0.8
