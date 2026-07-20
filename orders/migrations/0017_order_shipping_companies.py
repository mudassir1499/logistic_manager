import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0016_order_shipping_company'),
        ('settings_manager', '0008_shippingcompany'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='order',
            name='shipping_company',
        ),
        migrations.AddField(
            model_name='order',
            name='shipping_companies',
            field=models.ManyToManyField(
                blank=True,
                to='settings_manager.shippingcompany',
                verbose_name='Shipping Companies',
            ),
        ),
    ]
