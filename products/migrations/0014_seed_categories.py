"""
Creates the product taxonomy and categorises every product that predates it.

The category/subcategory columns added in 0013 land empty, which would leave the
new portal filter bar showing nothing on a live database. This migration fills
them in so the feature works immediately after deploy rather than requiring the
admin to tag 78 products by hand.

The taxonomy and the matching rules are imported from products/categorization.py
rather than duplicated here. That is a deliberate departure from the usual
"data migrations should be self-contained" guidance: the same rules power the
`categorize_products` management command, and keeping two copies in sync is a
worse failure mode than this migration's results shifting if the rules are later
edited. Nothing downstream depends on this migration reproducing byte-identical
results on a replay — it only needs to leave every product sensibly tagged.
"""

from django.db import migrations

from products.categorization import TAXONOMY, classify


def seed_taxonomy_and_categorise(apps, schema_editor):
    """Create the categories/subcategories, then tag every existing product."""
    Category = apps.get_model('products', 'Category')
    SubCategory = apps.get_model('products', 'SubCategory')
    Product = apps.get_model('products', 'Product')

    # Slugs are set explicitly. Historical models are rebuilt from the migration
    # state without custom methods, so the save() override that would normally
    # derive a slug from the name does not run here.
    category_by_slug = {}
    subcategory_by_slug = {}

    for cat_name, cat_slug, cat_order, subcategories in TAXONOMY:
        category, _ = Category.objects.get_or_create(
            slug=cat_slug,
            defaults={'name': cat_name, 'ordering': cat_order, 'is_active': True},
        )
        category_by_slug[cat_slug] = category

        for sub_name, sub_slug, sub_order in subcategories:
            subcategory, _ = SubCategory.objects.get_or_create(
                category=category,
                slug=sub_slug,
                defaults={'name': sub_name, 'ordering': sub_order, 'is_active': True},
            )
            # Keyed by (category slug, subcategory slug) because subcategory
            # slugs are only unique within their parent category.
            subcategory_by_slug[(cat_slug, sub_slug)] = subcategory

    # Only touch products that have not been categorised already, so re-running
    # this on a database where an admin has hand-tagged something does not
    # overwrite their decision.
    for product in Product.objects.filter(category__isnull=True):
        match = classify(product.name)
        if match is None:
            continue

        cat_slug, sub_slug = match
        category = category_by_slug.get(cat_slug)
        if category is None:
            continue

        product.category = category
        if sub_slug is not None:
            product.subcategory = subcategory_by_slug.get((cat_slug, sub_slug))
        product.save(update_fields=['category', 'subcategory'])


def unseed(apps, schema_editor):
    """
    Reverse: detach products from the taxonomy, then remove it.

    Products are never deleted — only their category links are cleared, which
    returns the catalogue to exactly the state 0013 left it in.
    """
    Category = apps.get_model('products', 'Category')
    SubCategory = apps.get_model('products', 'SubCategory')
    Product = apps.get_model('products', 'Product')

    Product.objects.update(category=None, subcategory=None)
    SubCategory.objects.all().delete()
    Category.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0013_category_subcategory_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_taxonomy_and_categorise, unseed),
    ]
