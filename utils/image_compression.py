"""
utils/image_compression.py

Image compression and optimization utilities for the LogisticManager project.

This module provides functions to compress and resize uploaded images,
reducing storage usage and improving page load times while maintaining
visual quality. It uses Pillow (PIL) for image processing.

Functions:
    compress_image: Compresses an image file in-place, optionally resizing.
    process_product_image: Signal handler to compress product images on upload.
    process_portfolio_image: Signal handler to compress portfolio images on upload.

Business Logic:
    Logistics businesses handle many product photos and portfolio images.
    Uncompressed images from modern phones/cameras can be 5-10MB each.
    Compressing them to ~200KB saves disk space and bandwidth for customers.
"""

import os
from io import BytesIO
from PIL import Image, ExifTags
from django.core.files.base import ContentFile


# Maximum dimensions for different image types
MAX_PRODUCT_WIDTH = 1200
MAX_PRODUCT_HEIGHT = 1200
MAX_PORTFOLIO_WIDTH = 1600
MAX_PORTFOLIO_HEIGHT = 1200
MAX_THUMB_WIDTH = 400
MAX_THUMB_HEIGHT = 400

# JPEG quality (0-100). 85 gives good balance of quality and file size.
DEFAULT_QUALITY = 85


def _fix_image_orientation(img: Image.Image) -> Image.Image:
    """
    Correct image orientation based on EXIF data.
    
    Mobile phones often save photos with orientation metadata instead of
    rotating the actual pixels. This function reads the EXIF Orientation tag
    and rotates the image so it displays correctly in browsers.
    
    Args:
        img: PIL Image instance to fix.
        
    Returns:
        PIL Image with correct orientation.
    """
    try:
        exif = img._getexif()
        if exif:
            for tag, value in exif.items():
                if ExifTags.TAGS.get(tag) == 'Orientation':
                    if value == 3:
                        img = img.rotate(180, expand=True)
                    elif value == 6:
                        img = img.rotate(270, expand=True)
                    elif value == 8:
                        img = img.rotate(90, expand=True)
                    break
    except Exception:
        pass
    return img


def compress_image(image_field, max_width=MAX_PRODUCT_WIDTH, max_height=MAX_PRODUCT_HEIGHT,
                   quality=DEFAULT_QUALITY, create_thumbnail=False):
    """
    Compress and resize an uploaded image to reduce file size.
    
    Args:
        image_field: Django ImageFieldFile instance (e.g., product.image)
        max_width: Maximum width in pixels.
        max_height: Maximum height in pixels.
        quality: JPEG quality (0-100). Higher = better quality but larger file.
        create_thumbnail: If True, also create a thumbnail version.
        
    Returns:
        dict: {'saved': bytes_saved, 'original_size': orig_size, 'new_size': new_size}
        
    Business Logic:
        When admins upload product photos from their phones, files can be 5-10MB.
        Compressing to 1200px wide at 85% quality typically reduces them to 150-300KB
        without visible quality loss. This makes the catalog load faster for customers
        on slower internet connections (common in international logistics).
    """
    if not image_field or not image_field.name:
        return None
    
    try:
        img = Image.open(image_field)
    except Exception:
        return None
    
    # Skip if not an image type we can compress
    if img.format not in ('JPEG', 'PNG', 'WEBP', 'TIFF', 'BMP'):
        return None
    
    # Fix orientation from EXIF
    img = _fix_image_orientation(img)
    
    # Convert to RGB if necessary (removes alpha channel for JPEG compatibility)
    if img.mode in ('RGBA', 'P', 'LA'):
        img = img.convert('RGBA')
        # For JPEG output, composite onto white background
        background = Image.new('RGBA', img.size, (255, 255, 255))
        img = Image.alpha_composite(background, img).convert('RGB')
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    
    # Resize if larger than max dimensions
    orig_width, orig_height = img.size
    if orig_width > max_width or orig_height > max_height:
        ratio = min(max_width / orig_width, max_height / orig_height)
        new_size = (int(orig_width * ratio), int(orig_height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    
    # Save compressed image to memory buffer
    buffer = BytesIO()
    img.save(buffer, format='JPEG', quality=quality, optimize=True, progressive=True)
    buffer.seek(0)
    new_size = buffer.tell()
    
    # Get original file size
    try:
        original_size = image_field.size
    except Exception:
        original_size = 0
    
    # Only replace if the new file is smaller
    if new_size < original_size or original_size == 0:
        image_field.save(
            os.path.basename(image_field.name),
            ContentFile(buffer.read()),
            save=False
        )
    
    result = {
        'saved': original_size - new_size if original_size > new_size else 0,
        'original_size': original_size,
        'new_size': new_size,
    }
    
    # Optional thumbnail creation
    if create_thumbnail:
        thumb_buffer = BytesIO()
        thumb = img.copy()
        thumb.thumbnail((MAX_THUMB_WIDTH, MAX_THUMB_HEIGHT), Image.LANCZOS)
        thumb.save(thumb_buffer, format='JPEG', quality=70, optimize=True)
        thumb_buffer.seek(0)
        result['thumbnail_size'] = thumb_buffer.tell()
    
    return result


def process_product_image(image_field):
    """
    Compress a product image using standard product dimensions.
    
    Args:
        image_field: Django ImageFieldFile instance.
        
    Returns:
        dict: Compression statistics or None.
    """
    return compress_image(image_field, max_width=MAX_PRODUCT_WIDTH, max_height=MAX_PRODUCT_HEIGHT)


def process_portfolio_image(image_field):
    """
    Compress a portfolio image using larger dimensions (portfolio images
    may be displayed full-width on the website).
    
    Args:
        image_field: Django ImageFieldFile instance.
        
    Returns:
        dict: Compression statistics or None.
    """
    return compress_image(image_field, max_width=MAX_PORTFOLIO_WIDTH, max_height=MAX_PORTFOLIO_HEIGHT)
