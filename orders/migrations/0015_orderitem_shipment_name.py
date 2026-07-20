from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0014_shipment_weight'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='shipment_name',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='Shipment Name'),
        ),
    ]
