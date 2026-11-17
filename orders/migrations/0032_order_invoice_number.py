"""
Adds Order.invoice_number — a stable, sequential invoice reference.

Invoices previously identified themselves by the raw primary key ("#33"), which
is neither sequential nor gapless. This field holds a proper reference such as
"INV-0042", allocated from CompanySettings the first time an invoice is generated
for an order and never regenerated afterwards.

Nullable and unique: existing orders keep NULL (and fall back to "#<id>" until an
invoice is next produced for them), while NULLs do not collide under a unique
constraint in either SQLite or MySQL.

Hand-written — `makemigrations` on this project also emits phantom BigAutoField
alterations for unrelated models.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0031_alter_notification_id_alter_order_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='invoice_number',
            field=models.CharField(
                blank=True,
                null=True,
                unique=True,
                db_index=True,
                # 40 chars is ample for "PREFIX-0000" style references and keeps the
                # unique index far inside the 767-byte InnoDB prefix limit under
                # utf8mb4 (40 x 4 = 160 bytes).
                max_length=40,
                help_text='Assigned automatically when the first invoice is generated. Never changes afterwards.',
                verbose_name='Invoice Number',
            ),
        ),
    ]
