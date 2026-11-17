"""
Rewrite existing Product.source_url values into their canonical form.

Without this the new duplicate check only works for products imported from now
on. Everything already in the catalogue carries the URL exactly as it was
scraped - with the ?spm= tracking parameters and whichever 1688 host the
operator happened to be on - so re-scraping one of those offers would not match
its own row and would import a second copy.

Reversible in the sense that matters: it never deletes anything and never
touches a row whose URL is already canonical. It cannot restore the discarded
tracking parameters, but those carried no information about the product.
"""

from django.db import migrations


def canonicalise(apps, schema_editor):
    # Imported inside the function, not at module scope: a migration must keep
    # working even if this helper is later moved or renamed, and failing at
    # import time would break the whole migration graph rather than one step.
    from products.source_url import canonical_source_url

    Product = apps.get_model('products', 'Product')

    updated = []
    for product in Product.objects.exclude(source_url='').exclude(source_url=None).iterator():
        canonical = canonical_source_url(product.source_url)[:500]
        if canonical and canonical != product.source_url:
            product.source_url = canonical
            updated.append(product)

    if updated:
        Product.objects.bulk_update(updated, ['source_url'], batch_size=200)


def noop(apps, schema_editor):
    """
    Nothing to undo.

    The canonical URL points at the same listing as the original, so leaving it
    in place on a rollback is correct - and the tracking parameters that were
    dropped cannot be reconstructed anyway.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0021_price_adjustment'),
    ]

    operations = [
        migrations.RunPython(canonicalise, noop),
    ]
