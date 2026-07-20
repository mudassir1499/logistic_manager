from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_manager', '0008_shippingcompany'),
    ]

    operations = [
        migrations.AddField(
            model_name='shippingcompany',
            name='air_rate',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Air Rate per KG'),
        ),
        migrations.AddField(
            model_name='shippingcompany',
            name='sea_rate',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Sea Rate per CBM'),
        ),
        migrations.AddField(
            model_name='shippingcompany',
            name='ksa_air_rate',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='KSA Air Rate per KG'),
        ),
        migrations.AddField(
            model_name='shippingcompany',
            name='ksa_sea_rate',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='KSA Sea Rate per CBM'),
        ),
        migrations.AddField(
            model_name='shippingcompany',
            name='nbb_air_rate',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='No Brand Battery Air Rate per KG'),
        ),
        migrations.AddField(
            model_name='shippingcompany',
            name='nbb_sea_rate',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='No Brand Battery Sea Rate per CBM'),
        ),
        migrations.AddField(
            model_name='shippingcompany',
            name='nbb_ksa_air_rate',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='No Brand Battery KSA Air Rate per KG'),
        ),
        migrations.AddField(
            model_name='shippingcompany',
            name='nbb_ksa_sea_rate',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='No Brand Battery KSA Sea Rate per CBM'),
        ),
    ]
