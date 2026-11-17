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

from datetime import date

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

    # Force https in the generated <loc> URLs. Without this, Django derives the
    # protocol from the request, so a sitemap fetched over http (or through a
    # proxy that terminates TLS) lists http:// URLs. Google then treats those as a
    # separate, redirecting set of pages and the sitemap reports crawl warnings.
    protocol = 'https'

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
            'shipping_calculator_page',  # Public freight calculator
            'portfolio_page',  # Portfolio
            'testimonials_page',  # Testimonials
            'faq_page',        # FAQ
            'blog_index',      # Blog hub — links out to every article
            'ar_home',         # Arabic homepage
            'ar_services_page',  # Arabic services
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
        # The Arabic pages are a secondary market entry point rather than the
        # primary funnel, so they sit just below the English marketing pages.
        if item.startswith('ar_'):
            return 0.7
        return 0.8

    def lastmod(self, item):
        """
        Returns the last-modified date reported for a page.

        Args:
            item (str): A URL name from the items() list.

        Returns:
            datetime.date: The date to publish as <lastmod> in the sitemap.

        These are hand-built marketing templates with no database record behind
        them, so there is no per-page timestamp to read. Reporting the deployment
        date of the current SEO revision is honest and useful: it tells Google the
        pages changed recently and are worth re-crawling, without pretending they
        change every single day (a sitemap whose lastmod is always "today" gets
        ignored — Google learns the signal is meaningless).

        If you make a substantive edit to the marketing copy, bump this date.
        """
        return date(2026, 7, 27)


class BlogSitemap(Sitemap):
    """
    Sitemap for published blog articles.

    Unlike the static pages, these have a genuine per-record modification
    timestamp, so `lastmod` reports the real `updated_at` value. That is exactly
    what search engines want: correcting a duty rate in an article causes Google
    to see a changed lastmod and re-crawl that one URL, rather than re-crawling
    everything or nothing.

    Drafts are excluded — an unpublished post 404s, and listing 404s in a sitemap
    is reported as an error in Search Console.
    """

    changefreq = 'monthly'
    protocol = 'https'
    # No `priority = 0.7` class attribute here: the priority() method defined below
    # replaces it outright (later definition in the class body wins), so the constant
    # was dead and only misled anyone trying to tune it.

    def items(self):
        """Every published post, newest first."""
        # Imported here rather than at module level: sitemaps.py is imported from
        # the root URLConf, and importing models during URLConf import can run
        # before the app registry is ready.
        from portal.models import BlogPost
        return BlogPost.objects.filter(is_published=True).order_by('-published_at')

    def location(self, obj):
        """Delegates to the model so the URL shape lives in one place."""
        return obj.get_absolute_url()

    def lastmod(self, obj):
        """The article's real last-edited timestamp."""
        return obj.updated_at

    def priority(self, obj):
        """
        Featured articles are the ones written to rank for the highest-volume
        terms, so they get a slightly higher priority than the rest of the archive.
        Priority is a relative hint within this site only — it does not compete
        against other domains.
        """
        return 0.8 if obj.is_featured else 0.6


class ProductSitemap(Sitemap):
    """
    Every publicly visible product.

    This is what actually gets the catalogue indexed. Without it a crawler can
    only reach products by paginating /shop/, which it will do slowly and
    incompletely; the sitemap hands it the full list on the first visit.

    Drafts and private products are excluded because their public URLs 404, and
    listing 404s in a sitemap is reported as an error in Search Console.
    """

    changefreq = 'weekly'
    protocol = 'https'
    priority = 0.7
    limit = 5000

    def items(self):
        # Imported inside the method for the same app-registry reason as BlogSitemap.
        from products.models import Product
        return (
            Product.objects
            .filter(is_draft=False, is_private=False)
            .exclude(slug=None)
            .exclude(slug='')
            .order_by('-id')
        )

    def location(self, obj):
        return obj.get_absolute_url()


class ShopIndexSitemap(Sitemap):
    """
    The catalogue landing page and one entry per active category.

    Category URLs are the ones with a realistic chance of ranking for a
    category-level search ("bulk photo frames uae"), so they are listed
    explicitly rather than left for the crawler to infer from the sidebar.
    """

    changefreq = 'daily'
    protocol = 'https'
    priority = 0.9

    def items(self):
        from products.models import Category
        return ['__index__'] + list(
            Category.objects.filter(is_active=True).values_list('slug', flat=True)
        )

    def location(self, item):
        base = reverse('shop_index')
        return base if item == '__index__' else f'{base}?category={item}'


class MarketSitemap(Sitemap):
    """
    One entry per country landing page.

    These pages exist to be found from a country-specific search, so leaving
    them for the crawler to discover through a footer link would waste them.
    High priority because they are the entry point for every market outside the
    UAE, where the site currently has no ranking at all.
    """

    changefreq = 'weekly'
    protocol = 'https'
    priority = 0.9

    def items(self):
        from portal.markets import MARKETS
        return [m['slug'] for m in MARKETS]

    def location(self, slug):
        return reverse('market_page', args=[slug])
