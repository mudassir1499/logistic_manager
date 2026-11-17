"""
Fill in the slug for every product that predates the field.

Without this, existing products have slug=NULL and are unreachable on the public
catalogue — which is every product currently in the database. The slug is only
generated when missing, so re-running this is a no-op.

Uniqueness is settled with a counter suffix, matching Product._build_slug. The
logic is duplicated here rather than imported because a migration must keep
working against the model as it was, not as it later becomes.
"""

from django.db import migrations
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):
    Product = apps.get_model('products', 'Product')

    # Seed with the slugs already present so a partially-migrated database does
    # not generate a duplicate.
    taken = set(
        Product.objects.exclude(slug=None).exclude(slug='').values_list('slug', flat=True)
    )

    for product in Product.objects.filter(slug__isnull=True).iterator():
        base = slugify(product.name)[:180] or 'product'
        slug = base
        counter = 2
        while slug in taken:
            suffix = f'-{counter}'
            slug = base[:180 - len(suffix)] + suffix
            counter += 1
        taken.add(slug)
        product.slug = slug
        product.save(update_fields=['slug'])


def clear_slugs(apps, schema_editor):
    """Reverse: blank them again so the field can be dropped cleanly."""
    Product = apps.get_model('products', 'Product')
    Product.objects.update(slug=None)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0019_product_slug'),
    ]

    operations = [
        migrations.RunPython(backfill_slugs, clear_slugs),
    ]
