from django.db import models

class Product(models.Model):
	name = models.CharField(max_length=255)
	price = models.DecimalField(max_digits=10, decimal_places=2)
	moq = models.PositiveIntegerField(verbose_name='Minimum Order Quantity')

	def __str__(self):
		return self.name

class ProductImage(models.Model):
	product = models.ForeignKey(Product, related_name='images', on_delete=models.CASCADE)
	image = models.ImageField(upload_to='product_images/')

	def __str__(self):
		return f"Image for {self.product.name}"
