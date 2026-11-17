"""
Give existing products a SKU.

    python manage.py generate_skus              # report only, writes nothing
    python manage.py generate_skus --apply      # fill in the blanks
    python manage.py generate_skus --apply --replace-supplier-codes

WHAT IT LEAVES ALONE, AND WHY

By default only products with NO SKU are touched. The ones that already have a
code carried it over from the 1688 listing - "1103", "RS550", "17promax" - and
that code is how the supplier identifies the item. Overwriting it would break
the link back to where the goods are bought, which is worth more than a tidy
numbering scheme.

--replace-supplier-codes says to renumber those too, for a catalogue where one
consistent scheme matters more. It is not the default because it is the option
that destroys information, and a mistaken run cannot be undone from here - the
old codes are gone once written over.

Either way, a SKU this command already generated is never reassigned. The
command is safe to re-run: it only ever fills gaps.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from products.models import Category, Product
from products.sku import derive_prefix, looks_generated, next_sku, prefix_for


class Command(BaseCommand):
    help = 'Generate SKUs for products that do not have one.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually write the SKUs. Without this the command only reports.',
        )
        parser.add_argument(
            '--replace-supplier-codes', action='store_true',
            help='Also renumber products whose SKU came from the supplier. '
                 'This DISCARDS those codes and cannot be undone.',
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']
        replace = options['replace_supplier_codes']

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                'DRY RUN - nothing will be written. Re-run with --apply.\n'))

        # ------------------------------------------------------------------
        # Category prefixes first: a product's SKU depends on its category
        # having one, so any category still missing a prefix is filled in
        # before a single product is numbered.
        # ------------------------------------------------------------------
        taken = set(
            Category.objects
            .exclude(sku_prefix__isnull=True).exclude(sku_prefix='')
            .values_list('sku_prefix', flat=True)
        )
        assigned_prefixes = []
        for category in Category.objects.order_by('name'):
            if category.sku_prefix:
                continue
            prefix = derive_prefix(category.name, taken)
            taken.add(prefix)
            assigned_prefixes.append((category.name, prefix))
            if apply_changes:
                category.sku_prefix = prefix
                category.save(update_fields=['sku_prefix'])

        if assigned_prefixes:
            self.stdout.write('Category prefixes:')
            for name, prefix in assigned_prefixes:
                self.stdout.write('   %-32s %s' % (name[:32], prefix))
            self.stdout.write('')
        else:
            self.stdout.write('Every category already has a prefix.\n')

        # In a dry run the prefixes above were never saved, so hold them in
        # memory - otherwise the preview would show every product as GEN.
        preview_prefixes = dict(
            Category.objects.values_list('id', 'sku_prefix')
        )
        if not apply_changes:
            by_name = dict(assigned_prefixes)
            for category in Category.objects.all():
                if not preview_prefixes.get(category.id):
                    preview_prefixes[category.id] = by_name.get(category.name)

        # ------------------------------------------------------------------
        # Products
        # ------------------------------------------------------------------
        products = Product.objects.select_related('category').order_by('id')

        blank, supplier, generated = [], [], []
        for product in products:
            sku = (product.sku or '').strip()
            if not sku:
                blank.append(product)
            elif looks_generated(sku):
                generated.append(product)
            else:
                supplier.append(product)

        self.stdout.write('Products: %d total' % products.count())
        self.stdout.write('   %4d with no SKU        -> will be generated' % len(blank))
        self.stdout.write('   %4d with a supplier code-> %s'
                          % (len(supplier),
                             'WILL BE REPLACED' if replace else 'left as they are'))
        self.stdout.write('   %4d already generated   -> left as they are' % len(generated))
        self.stdout.write('')

        targets = blank + (supplier if replace else [])
        if not targets:
            self.stdout.write(self.style.SUCCESS('Nothing to do.'))
            return

        # Everything issued in this run, so two products in the same category do
        # not both get -0001. next_sku() only sees the database, and nothing is
        # written until the end.
        issued = set()
        planned = []
        for product in targets:
            if apply_changes:
                new_sku = next_sku(product, issued)
            else:
                # Dry run: mirror next_sku's arithmetic against the prefix the
                # category WOULD get, since none of it is saved yet.
                prefix = (preview_prefixes.get(product.category_id)
                          or prefix_for(product))
                start = max(
                    [int(s[len(prefix) + 1:])
                     for s in list(Product.objects.filter(sku__startswith=prefix + '-')
                                   .values_list('sku', flat=True)) + list(issued)
                     if s.startswith(prefix + '-') and s[len(prefix) + 1:].isdigit()]
                    or [0]
                )
                new_sku = '%s-%04d' % (prefix, start + 1)
            issued.add(new_sku)
            planned.append((product, new_sku))

        self.stdout.write('First 15 of %d:' % len(planned))
        for product, new_sku in planned[:15]:
            old = (product.sku or '').strip() or '(none)'
            self.stdout.write('   %-12s -> %-12s %s'
                              % (old, new_sku, (product.name or '')[:40]))
        self.stdout.write('')

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                'Dry run complete. Re-run with --apply to write these.'))
            return

        # One transaction: a half-numbered catalogue, where nobody can tell which
        # products were done, is worse than none.
        with transaction.atomic():
            for product, new_sku in planned:
                product.sku = new_sku
            Product.objects.bulk_update(
                [p for p, _ in planned], ['sku'], batch_size=200)

        self.stdout.write(self.style.SUCCESS(
            'Done. %d product(s) given a SKU.' % len(planned)))

        remaining = Product.objects.filter(sku='').count()
        if remaining:
            self.stdout.write(self.style.ERROR(
                '%d product(s) still have no SKU - investigate.' % remaining))
