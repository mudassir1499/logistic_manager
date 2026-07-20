from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0001_initial'),
        ('products', '0007_is_private'),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomerProduct',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('note', models.CharField(blank=True, max_length=255)),
                ('assigned_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assigned_products', to='customers.customer')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='customer_assignments', to='products.product')),
            ],
            options={
                'ordering': ['-assigned_at'],
                'unique_together': {('customer', 'product')},
            },
        ),
    ]
