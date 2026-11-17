"""Pagination shared by every list endpoint."""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """
    Page-number pagination with a caller-controlled size.

    A default is enforced rather than left unbounded: this catalogue already has
    products with variants, images and attributes prefetched per row, and an
    unpaginated list of a few thousand would be a slow query, a large response
    and a lot of memory on a shared host - all triggered by a caller who simply
    forgot to page.

    max_page_size caps what a caller can ask for, so ?page_size=100000 is not a
    denial-of-service button.
    """

    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 200
