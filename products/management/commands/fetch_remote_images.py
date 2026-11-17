"""
Download product images that are currently only linked to the supplier's CDN.

WHY THESE EXIST AT ALL
    Every product photo must be a file in MEDIA_ROOT. NOTHING is ever served
    from the supplier's CDN: alicdn is unreachable or heavily throttled from
    Pakistan and much of the region this catalogue sells into, so a hotlinked
    photo is a broken frame for the customer while looking fine to staff on a
    connection that can reach it. ``ProductImage.src`` therefore returns the
    local file or nothing at all.

    Rows with a ``source_url`` and no file are leftovers from when the importer
    did fall back to linking, plus variations whose bytes did not arrive. They
    render nothing. This command turns them into real files.

    A download can fail for reasons that have nothing to do with the URL: a
    machine behind a VPN whose DNS resolves every host into a private range (the
    SSRF guard then refuses it), no outbound network, or a temporary CDN error.
    Those all leave a perfectly good URL that will work from a different machine,
    which is why the address is kept rather than discarded at import time.

THE 1x1 PROBLEM
    alicdn does not 404 a dead image. It answers 200 with a 1x1 pixel, so a
    naive fetch "succeeds" and stores a single white dot that then stretches to
    fill the product page. Anything below MIN_USABLE_PX is treated as the
    placeholder it is and reported rather than saved.

Usage::

    python manage.py fetch_remote_images            # report only, changes nothing
    python manage.py fetch_remote_images --apply    # actually download and save
    python manage.py fetch_remote_images --apply --limit 50

    # Download what can be downloaded, then delete the image rows that still
    # have no file so they stop counting as photos the product does not have.
    python manage.py fetch_remote_images --apply --purge-failed
"""

import re

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from products.api import _fetch_image
from products.models import ProductImage, ProductVariant

# No product photo is 8px square. Smaller than this is a CDN placeholder.
MIN_USABLE_PX = 8


def _looks_like_placeholder(data):
    """
    True when the downloaded bytes are a tiny image rather than a photo.

    Reads the dimensions out of the file header rather than decoding the image,
    so this needs no Pillow call per candidate. Only PNG, JPEG and GIF are
    inspected — those are what the marketplace CDNs serve — and anything else is
    accepted rather than rejected on a guess.
    """
    if len(data) < 24:
        return True

    try:
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            width = int.from_bytes(data[16:20], 'big')
            height = int.from_bytes(data[20:24], 'big')
        elif data[:3] == b'GIF':
            width = int.from_bytes(data[6:8], 'little')
            height = int.from_bytes(data[8:10], 'little')
        elif data[:2] == b'\xff\xd8':
            # Walk the JPEG segments to the frame header that carries the size.
            index = 2
            width = height = 0
            while index < len(data) - 9:
                if data[index] != 0xFF:
                    index += 1
                    continue
                marker = data[index + 1]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    height = int.from_bytes(data[index + 5:index + 7], 'big')
                    width = int.from_bytes(data[index + 7:index + 9], 'big')
                    break
                index += 2 + int.from_bytes(data[index + 2:index + 4], 'big')
        else:
            return False
    except (ValueError, IndexError):
        return False

    return width < MIN_USABLE_PX or height < MIN_USABLE_PX


class Command(BaseCommand):
    help = 'Download product images that are currently linked to a supplier CDN.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually download and save. Without this the command only reports.',
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Stop after this many images. 0 means no limit.',
        )
        parser.add_argument(
            '--purge-failed', action='store_true',
            help=(
                'After downloading, DELETE the ProductImage rows that still have '
                'no file. Requires --apply. Variation rows are never deleted — '
                'they carry price and stock — only their dead image_url is '
                'cleared.'
            ),
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']
        limit = options['limit']
        purge = options['purge_failed']

        if purge and not apply_changes:
            raise CommandError(
                '--purge-failed deletes rows, so it requires --apply. Run without '
                'it first to see what would be downloaded.'
            )

        pending = (
            ProductImage.objects
            .filter(image='')
            .exclude(source_url='')
            .select_related('product')
            .order_by('product__name', 'id')
        )
        variants = (
            ProductVariant.objects
            .filter(image='')
            .exclude(image_url='')
            .select_related('product')
            .order_by('product__name', 'sort_order')
        )

        total = pending.count() + variants.count()
        if not total:
            self.stdout.write(self.style.SUCCESS(
                'Nothing to do — every product image is already stored locally.'
            ))
            return

        self.stdout.write(
            f'{pending.count()} product image(s) and {variants.count()} variation '
            f'image(s) are linked rather than stored.'
        )
        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                'Reporting only. Re-run with --apply to download them.'
            ))
        self.stdout.write('')

        saved = failed = placeholder = 0
        processed = 0

        for row, url_field, label in (
            [(r, 'source_url', 'image') for r in pending] +
            [(v, 'image_url', 'variation') for v in variants]
        ):
            if limit and processed >= limit:
                break
            processed += 1

            url = getattr(row, url_field)
            name = row.product.name[:44]

            fetched = _fetch_image(url)
            if fetched is None:
                failed += 1
                self.stdout.write(self.style.ERROR(f'  refused/unreachable  {name}  {url[:58]}'))
                continue

            data, extension = fetched
            if _looks_like_placeholder(data):
                placeholder += 1
                self.stdout.write(self.style.WARNING(
                    f'  CDN placeholder      {name}  (needs a real photo)'
                ))
                continue

            if apply_changes:
                safe = re.sub(r'[^\w\-]', '_', row.product.name)[:50] or 'product'
                row.image.save(f'{safe}_{row.pk}.{extension}', ContentFile(data), save=True)
            saved += 1
            self.stdout.write(self.style.SUCCESS(
                f'  {"downloaded" if apply_changes else "would download"}  {label:9} {name}'
            ))

        self.stdout.write('')
        verb = 'Downloaded' if apply_changes else 'Would download'
        self.stdout.write(f'{verb}: {saved}')
        if placeholder:
            self.stdout.write(self.style.WARNING(
                f'CDN placeholders (1x1, no real photo behind the link): {placeholder}'
            ))
        if failed:
            self.stdout.write(self.style.ERROR(f'Refused or unreachable: {failed}'))
        if failed and not apply_changes:
            self.stdout.write(
                'A refusal usually means the host is not on the CDN allowlist, or '
                'this machine resolves it to a private address — a VPN or split-DNS '
                'setup does that. Try again from the server.'
            )

        # ------------------------------------------------------------------
        # PURGE
        # ------------------------------------------------------------------
        # Nothing renders a supplier URL any more (see ProductImage.src): a row
        # holding only an address is invisible, not a fallback. Those rows are
        # therefore dead weight that makes a product look like it has photos it
        # cannot show, and they skew the counts staff use to find products that
        # still need a picture.
        #
        # Deleting is opt-in and comes AFTER the download pass, so a row is only
        # ever removed once fetching it has been attempted and failed.
        if purge:
            dead_images = ProductImage.objects.filter(image='').exclude(source_url='')
            # Variations are NOT deleted — the row carries the variation's price
            # and stock, and orders reference it. Only the dead address is
            # cleared, so nothing keeps pointing at a CDN we will never read.
            dead_variants = ProductVariant.objects.filter(image='').exclude(image_url='')

            image_count = dead_images.count()
            variant_count = dead_variants.count()

            dead_images.delete()
            dead_variants.update(image_url='')

            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'Purged {image_count} image row(s) that had no file, and cleared '
                f'the dead link on {variant_count} variation(s).'
            ))
            if image_count or variant_count:
                self.stdout.write(
                    'Those products now show the "no image" placeholder. Upload a '
                    'photo by hand, or re-push them from the sourcing extension, '
                    'which sends the picture as bytes rather than as a link.'
                )
