from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_manager', '0007_companysettings_exchange_rate'),
    ]

    operations = [
        migrations.CreateModel(
            name='ShippingCompany',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='Shipping Company Name')),
                ('website', models.URLField(blank=True, max_length=255, verbose_name='Website URL')),
            ],
            options={
                'verbose_name': 'Shipping Company',
                'verbose_name_plural': 'Shipping Companies',
                'ordering': ['name'],
            },
        ),
    ]
