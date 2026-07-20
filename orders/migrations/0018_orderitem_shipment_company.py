from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0017_order_shipping_companies'),
        ('settings_manager', '0008_shippingcompany'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='shipment_company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='settings_manager.shippingcompany',
                verbose_name='Shipment Company',
            ),
        ),
    ]
