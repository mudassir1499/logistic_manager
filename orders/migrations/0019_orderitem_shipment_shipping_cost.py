from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0018_orderitem_shipment_company'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='shipment_shipping_cost',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Shipment Shipping Cost'),
        ),
    ]
