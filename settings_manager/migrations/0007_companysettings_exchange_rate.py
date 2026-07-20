from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_manager', '0006_companysettings_no_brand_battery_air_shipping_rate_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='companysettings',
            name='exchange_rate_enabled',
            field=models.BooleanField(default=False, verbose_name='Show Exchange Rate on Invoice'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='exchange_rate_from',
            field=models.CharField(
                choices=[('AED', 'AED — UAE Dirham'), ('RMB', 'RMB — Chinese Yuan'),
                         ('USD', 'USD — US Dollar'), ('EUR', 'EUR — Euro'),
                         ('GBP', 'GBP — British Pound'), ('SAR', 'SAR — Saudi Riyal')],
                default='AED', max_length=10, verbose_name='Exchange Rate: From Currency'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='exchange_rate_to',
            field=models.CharField(
                choices=[('AED', 'AED — UAE Dirham'), ('RMB', 'RMB — Chinese Yuan'),
                         ('USD', 'USD — US Dollar'), ('EUR', 'EUR — Euro'),
                         ('GBP', 'GBP — British Pound'), ('SAR', 'SAR — Saudi Riyal')],
                default='RMB', max_length=10, verbose_name='Exchange Rate: To Currency'),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='exchange_rate',
            field=models.DecimalField(decimal_places=6, default=0, max_digits=12,
                                      verbose_name='Exchange Rate (1 FROM = ? TO)'),
        ),
    ]
