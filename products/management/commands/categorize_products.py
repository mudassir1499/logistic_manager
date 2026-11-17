"""
Management command: categorize_products

Applies the keyword rules in products/categorization.py to products that have
no category yet, and creates any taxonomy rows that are missing.

The data migration categorised everything that existed when the feature
shipped. This command is what you run afterwards — after a bulk product import,
or after editing the rules to fix a miscategorised item.

Usage:
    python manage.py categorize_products              # tag uncategorised products
    python manage.py categorize_products --dry-run    # show what would change
    python manage.py categorize_products --all        # also re-tag existing ones
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from products.categorization import TAXONOMY, classify
from products.models import Category, Product, SubCategory


class Command(BaseCommand):
    help = 'Assign categories and subcategories to products using keyword rules.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report the changes that would be made without saving anything.',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help=(
                'Re-categorise every product, including ones already tagged. '
                'Use after editing the rules. This OVERWRITES manual category '
                'assignments made in the admin.'
            ),
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        recategorise_all = options['all']

        # transaction.atomic keeps a failure partway through from leaving the
        # catalogue half-tagged. In dry-run mode we roll back at the end
        # regardless, which lets the same code path do the reporting.
        with transaction.atomic():
            categories, subcategories = self._ensure_taxonomy()

            queryset = Product.objects.all()
            if not recategorise_all:
                queryset = queryset.filter(category__isnull=True)

            changed = 0
            unmatched = []

            for product in queryset.order_by('name'):
                match = classify(product.name)
                if match is None:
                    unmatched.append(product.name)
                    continue

                cat_slug, sub_slug = match
                category = categories.get(cat_slug)
                if category is None:
                    unmatched.append(product.name)
                    continue

                subcategory = (
                    subcategories.get((cat_slug, sub_slug))
                    if sub_slug is not None
                    else None
                )

                # Skip the write when nothing actually differs, so --all does
                # not churn every row on a no-op run.
                if product.category_id == category.id and product.subcategory_id == (
                    subcategory.id if subcategory else None
                ):
                    continue

                label = category.name + (f' / {subcategory.name}' if subcategory else '')
                self.stdout.write(f'  {product.name}  ->  {label}')

                product.category = category
                product.subcategory = subcategory
                if not dry_run:
                    product.save(update_fields=['category', 'subcategory'])
                changed += 1

            if unmatched:
                self.stdout.write('')
                self.stdout.write(self.style.WARNING(
                    f'{len(unmatched)} product(s) matched no rule and were left '
                    f'uncategorised:'
                ))
                for name in unmatched:
                    self.stdout.write(f'  - {name}')
                self.stdout.write(
                    'Add a keyword for these to RULES in products/categorization.py.'
                )

            self.stdout.write('')
            if dry_run:
                self.stdout.write(self.style.NOTICE(
                    f'DRY RUN — {changed} product(s) would be updated. Nothing saved.'
                ))
                # Undo everything this transaction touched, including any
                # taxonomy rows created above.
                transaction.set_rollback(True)
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'Updated {changed} product(s).'
                ))

    def _ensure_taxonomy(self):
        """
        Create any categories/subcategories from TAXONOMY that do not exist yet.

        Returns two lookup dicts: categories keyed by slug, and subcategories
        keyed by (category_slug, subcategory_slug) — subcategory slugs are only
        unique within their parent, so the pair is the real key.
        """
        categories = {}
        subcategories = {}

        for cat_name, cat_slug, cat_order, subs in TAXONOMY:
            category, created = Category.objects.get_or_create(
                slug=cat_slug,
                defaults={'name': cat_name, 'ordering': cat_order},
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created category: {cat_name}'))
            categories[cat_slug] = category

            for sub_name, sub_slug, sub_order in subs:
                subcategory, created = SubCategory.objects.get_or_create(
                    category=category,
                    slug=sub_slug,
                    defaults={'name': sub_name, 'ordering': sub_order},
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(
                        f'Created subcategory: {cat_name} / {sub_name}'
                    ))
                subcategories[(cat_slug, sub_slug)] = subcategory

        return categories, subcategories
