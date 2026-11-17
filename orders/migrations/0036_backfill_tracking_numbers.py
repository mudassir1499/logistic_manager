"""
Give every order that predates tracking a tracking number.

The field is added as NULL-able by 0035, so existing rows arrive here with no
number and would be untrackable forever — the number is only assigned on save,
and nobody re-saves a delivered order.

Numbers are generated the same way Order._new_tracking_number does, but the
alphabet is repeated here rather than imported. A data migration must keep
working against the model as it was AT THIS POINT IN HISTORY; importing from
orders.models would silently change behaviour the day that constant is edited,
and re-running this migration on a fresh database would then produce different
values from the ones already in production.
"""
import secrets

from django.db import migrations

ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
PREFIX = 'MLK'


def _candidate():
    groups = [''.join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(3)]
    return f'{PREFIX}-' + '-'.join(groups)


def backfill(apps, schema_editor):
    Order = apps.get_model('orders', 'Order')

    # Held in memory so uniqueness is checked without a query per candidate. The
    # order book is thousands of rows, not millions.
    taken = set(
        Order.objects.exclude(tracking_number=None)
        .values_list('tracking_number', flat=True)
    )

    pending = Order.objects.filter(tracking_number=None).only('id')
    updated = []
    for order in pending.iterator():
        for _ in range(20):
            candidate = _candidate()
            if candidate not in taken:
                taken.add(candidate)
                order.tracking_number = candidate
                updated.append(order)
                break
        else:
            raise RuntimeError(f'Could not allocate a tracking number for order {order.pk}')

    if updated:
        Order.objects.bulk_update(updated, ['tracking_number'], batch_size=500)


def unbackfill(apps, schema_editor):
    """
    Reverse deliberately does nothing.

    Clearing the numbers would break every tracking link already shared with a
    customer, and 0035 drops the column on a full reverse anyway.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0035_order_tracking_number'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
