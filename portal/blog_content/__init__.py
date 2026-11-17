"""
portal/blog_content
================================================================================
Seed content for the public blog.
================================================================================

Why the articles live in Python instead of a data migration:

  A data migration runs exactly once. If the owner later edits an article in
  Django admin — fixes a duty rate, updates a transit time — a re-run of the
  migration would either do nothing or silently overwrite the correction. Keeping
  the content here and loading it through the idempotent `seed_blog_posts`
  management command means:

    * a fresh deploy gets the full archive with one command,
    * re-running the command never touches a post that already exists,
    * `--update` is available when the source text here is genuinely newer.

Each entry is a plain dict. `body` is HTML, rendered with `|safe` in the
template — see the security note in the BlogPost model docstring.

Editorial rules these articles follow:

  * Answer the search query in the first two paragraphs. A reader who has to dig
    for the answer leaves, and the resulting short visit is a ranking signal.
  * Never invent a precise figure that moves. Freight rates, exchange rates and
    factory lead times change constantly; stating them as fact makes the article
    wrong within weeks and destroys trust. Give the structure of the cost and the
    method to work it out, then invite a live quote.
  * Regulatory detail is described in general terms with a pointer to the
    authority (UAE customs / MOIAT), because rules change and only the authority
    is current.
"""

from .sourcing import CATEGORY as SOURCING_CATEGORY, POSTS as SOURCING_POSTS
from .shipping import CATEGORY as SHIPPING_CATEGORY, POSTS as SHIPPING_POSTS
from .customs import CATEGORY as CUSTOMS_CATEGORY, POSTS as CUSTOMS_POSTS
from .costs import CATEGORY as COSTS_CATEGORY, POSTS as COSTS_POSTS
from .selling import CATEGORY as SELLING_CATEGORY, POSTS as SELLING_POSTS

# Ordered so the categories appear in a sensible reading sequence on the blog
# index: find a supplier, ship the goods, clear customs, work out the cost, sell.
CATEGORIES = [
    SOURCING_CATEGORY,
    SHIPPING_CATEGORY,
    CUSTOMS_CATEGORY,
    COSTS_CATEGORY,
    SELLING_CATEGORY,
]

POSTS = (
    SOURCING_POSTS
    + SHIPPING_POSTS
    + CUSTOMS_POSTS
    + COSTS_POSTS
    + SELLING_POSTS
)

__all__ = ['CATEGORIES', 'POSTS']
