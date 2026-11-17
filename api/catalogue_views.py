"""
Writing to the catalogue: photos and variations.

WHY THESE ARE NOT IN views.py

ProductViewSet already creates and edits a product row. What it cannot do is
attach a PHOTO or a VARIATION, because both are separate tables and the read
serializers project them read-only — posting into a nested `images` list there
silently does nothing, which is the worst possible failure for an upload.

Until now the only way to get an image into the catalogue was the browser
extension pushing base64 from a 1688 page. That is the right shape for a
scraper and the wrong one for a phone: the phone already has a JPEG on disk, and
base64-ing a 4MB camera photo through a JSON body wastes a third of it on
encoding over a connection that may be a hotel wifi. These take multipart.

A product with no image is invisible to Meta and TikTok — both reject an item
without one — so "add a photo from your phone" is not a convenience feature, it
is what makes a listing created on a phone actually sellable.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from products.models import Product, ProductImage, ProductVariant

from .permissions import HasModule
from .serializers import (ProductImageSerializer, ProductVariantSerializer,
                          ProductVariantWriteSerializer)


class ProductImageViewSet(viewsets.ModelViewSet):
    """
    Photos on a product.

    Always filtered by ?product=<id>. Listing every image in the catalogue is
    not a question anybody asks, and answering it would page through thousands
    of rows to no purpose.
    """

    serializer_class = ProductImageSerializer
    permission_classes = [HasModule.for_module('products')]
    parser_classes = [MultiPartParser, FormParser]
    throttle_scope = 'write'

    def get_queryset(self):
        qs = ProductImage.objects.select_related('product').order_by('id')
        # LIST only. Applying this to every action would 404 the detail routes:
        # a DELETE carries no query string, so the filter would empty the
        # queryset and the object could never be found.
        if self.action != 'list':
            return qs
        product = self.request.query_params.get('product')
        return qs.filter(product_id=product) if product else qs.none()

    @extend_schema(
        summary='Attach a photo to a product',
        description='multipart/form-data with `product` (id) and `image` (file).',
    )
    def create(self, request, *args, **kwargs):
        product_id = request.data.get('product')
        upload = request.FILES.get('image')

        if not product_id or upload is None:
            return Response(
                {'detail': 'Send a product id and an image file.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        product = Product.objects.filter(pk=product_id).first()
        if product is None:
            return Response({'detail': 'No such product.'},
                            status=status.HTTP_404_NOT_FOUND)

        # A phone camera produces 3-8MB files and the storefront never renders
        # them above ~1000px. The cap is here rather than in the client because
        # the client is the thing that cannot be trusted about it.
        if upload.size > 10 * 1024 * 1024:
            return Response({'detail': 'Image is too large (10MB maximum).'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Three is what the storefront and the ad feed both render. Silently
        # accepting a fourth would let somebody upload photos that are never
        # displayed anywhere and wonder why.
        if product.images.count() >= 3:
            return Response(
                {'detail': 'This product already has three photos. '
                           'Remove one before adding another.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        image = ProductImage.objects.create(product=product, image=upload)
        return Response(self.get_serializer(image).data,
                        status=status.HTTP_201_CREATED)


class ProductVariantViewSet(viewsets.ModelViewSet):
    """
    Variations of a product — the colours and sizes a customer actually buys.

    Filtered by ?product=<id> for the same reason as images above.

    Deleting is a soft retire rather than a row delete: a variation may be
    referenced by an OrderItem, and removing it would either cascade into
    somebody's order history or fail with a foreign-key error. `is_active=False`
    hides it from the storefront and the ad feed while leaving past orders
    intact and readable.
    """

    permission_classes = [HasModule.for_module('products')]
    throttle_scope = 'write'

    def get_serializer_class(self):
        # Reads project `image` as a URL, which cannot be written to; writes
        # take `product`, which reads omit. One serializer cannot do both
        # without one half being a lie.
        if self.request.method in ('GET', 'HEAD'):
            return ProductVariantSerializer
        return ProductVariantWriteSerializer

    def get_queryset(self):
        qs = ProductVariant.objects.select_related('product').order_by('sort_order', 'id')
        if self.action != 'list':      # see ProductImageViewSet.get_queryset
            return qs
        product = self.request.query_params.get('product')
        return qs.filter(product_id=product) if product else qs.none()

    def destroy(self, request, *args, **kwargs):
        variant = self.get_object()
        variant.is_active = False
        variant.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)
