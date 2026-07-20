from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_manager', '0009_shippingcompany_rates'),
    ]

    operations = [
        migrations.AddField(
            model_name='shippingcompany',
            name='shipping_rate_sheet',
            field=models.FileField(blank=True, null=True, upload_to='shipping_rate_sheets/', verbose_name='Shipping Rate Excel Sheet'),
        ),
    ]
