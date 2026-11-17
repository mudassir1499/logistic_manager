"""
Seed the destination and cargo-type lists, then move the existing rates into
ShippingRate rows.

The eight rate columns on ShippingCompany are NOT dropped. Order pricing still
reads them (orders/views.py, three places), so they are kept and mirrored - see
sync_legacy_rate_columns. This migration only copies the values forward so the
new rate sheets start populated instead of blank.

Only non-zero rates become rows. Zero meant "this company does not quote this
lane", and creating a row for it would put a forwarder into a comparison at a
price of nothing.
"""

from decimal import Decimal

from django.db import migrations


# (code, name, sort order). The two the schema already priced.
DESTINATIONS = [
    ('AE', 'United Arab Emirates', 10),
    ('SA', 'Saudi Arabia', 20),
]

# (slug, name, sort order, customer selectable, description)
#
# 'general' and 'non-branded-battery' are the two the old columns encoded -
# "No Brand Battery" is a non-branded product containing a cell. The rest are
# the categories forwarders quote separately and there was previously nowhere
# to record.
CARGO_TYPES = [
    ('general', 'General Goods', 10, True,
     'Ordinary unbranded goods with no batteries and no special handling.'),
    ('branded', 'Branded Goods', 20, True,
     'Carries a trademark. Held longer at customs, so most forwarders price it apart.'),
    ('non-branded', 'Non-Branded Goods', 30, True,
     'Plain or own-label goods with no trademark on the product or packaging.'),
    ('branded-battery', 'Branded with Battery', 40, True,
     'Trademarked goods containing a lithium cell. Dangerous goods.'),
    ('non-branded-battery', 'Non-Branded with Battery', 50, True,
     'Plain goods containing a lithium cell - power banks, cordless tools, lit toys.'),
    ('beauty', 'Beauty & Cosmetics', 60, True,
     'Liquids, creams and aerosols. Restricted by air and subject to extra checks.'),
]

# legacy column -> (destination code, cargo slug, method)
LEGACY_COLUMNS = {
    'air_rate': ('AE', 'general', 'air'),
    'sea_rate': ('AE', 'general', 'sea'),
    'ksa_air_rate': ('SA', 'general', 'air'),
    'ksa_sea_rate': ('SA', 'general', 'sea'),
    'nbb_air_rate': ('AE', 'non-branded-battery', 'air'),
    'nbb_sea_rate': ('AE', 'non-branded-battery', 'sea'),
    'nbb_ksa_air_rate': ('SA', 'non-branded-battery', 'air'),
    'nbb_ksa_sea_rate': ('SA', 'non-branded-battery', 'sea'),
}


def seed_forward(apps, schema_editor):
    ShippingDestination = apps.get_model('settings_manager', 'ShippingDestination')
    CargoType = apps.get_model('settings_manager', 'CargoType')
    ShippingCompany = apps.get_model('settings_manager', 'ShippingCompany')
    ShippingRate = apps.get_model('settings_manager', 'ShippingRate')

    destinations = {}
    for code, name, order in DESTINATIONS:
        obj, _ = ShippingDestination.objects.get_or_create(
            code=code, defaults={'name': name, 'sort_order': order, 'is_active': True})
        destinations[code] = obj

    cargo_types = {}
    for slug, name, order, selectable, description in CARGO_TYPES:
        obj, _ = CargoType.objects.get_or_create(
            slug=slug,
            defaults={'name': name, 'sort_order': order, 'is_active': True,
                      'customer_selectable': selectable, 'description': description})
        cargo_types[slug] = obj

    for company in ShippingCompany.objects.all():
        for column, (dest_code, cargo_slug, method) in LEGACY_COLUMNS.items():
            rate = getattr(company, column, None) or Decimal('0')
            if rate <= 0:
                continue  # not quoted - see the module docstring
            ShippingRate.objects.update_or_create(
                company=company,
                destination=destinations[dest_code],
                cargo_type=cargo_types[cargo_slug],
                method=method,
                defaults={
                    'rate': rate,
                    # The divisor and minimums were per-company, not per-lane.
                    # Leaving these at 0 makes each lane inherit them, which is
                    # what was in force before this migration ran.
                    'volumetric_divisor': Decimal('0'),
                    'minimum': Decimal('0'),
                },
            )


def seed_backward(apps, schema_editor):
    """
    Drop the seeded rows.

    The legacy columns were never modified, so reversing loses nothing that was
    not already recorded there - except rates entered for lanes the columns
    cannot represent (a third country, or the four new cargo types). Those are
    genuinely lost on reverse, which is why this is worth stating rather than
    leaving as a silent noop.
    """
    ShippingRate = apps.get_model('settings_manager', 'ShippingRate')
    ShippingDestination = apps.get_model('settings_manager', 'ShippingDestination')
    CargoType = apps.get_model('settings_manager', 'CargoType')

    ShippingRate.objects.all().delete()
    ShippingDestination.objects.filter(
        code__in=[code for code, _, _ in DESTINATIONS]).delete()
    CargoType.objects.filter(
        slug__in=[slug for slug, _, _, _, _ in CARGO_TYPES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('settings_manager', '0024_cargotype_shippingdestination_shippingratesheet_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_forward, seed_backward),
    ]
