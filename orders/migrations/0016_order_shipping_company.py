import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0015_orderitem_shipment_name'),
        ('settings_manager', '0008_shippingcompany'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='shipping_company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='settings_manager.shippingcompany',
                verbose_name='Shipping Company',
            ),
        ),
    ]
