"""
Management command: load the blog archive from portal/blog_content into the database.

Usage
-----
    python manage.py seed_blog_posts            # create anything missing, touch nothing else
    python manage.py seed_blog_posts --update   # also overwrite existing posts from source
    python manage.py seed_blog_posts --dry-run  # report what would happen, change nothing

Why this is a command and not a data migration
----------------------------------------------
A data migration runs once. If the owner later corrects a duty figure or a transit
time through Django admin, a migration cannot help — and re-running one risks
overwriting that correction. This command is idempotent by default: it creates
posts that do not exist and leaves everything else alone, so it is safe to run on
every deploy. `--update` is the explicit opt-in for when the source text here is
genuinely newer than what is in the database.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from portal.blog_content import CATEGORIES, POSTS
from portal.models import BlogCategory, BlogPost


class Command(BaseCommand):
    help = 'Create the blog categories and articles defined in portal/blog_content.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--update',
            action='store_true',
            help='Overwrite existing posts with the content from portal/blog_content. '
                 'This DISCARDS edits made in Django admin — use deliberately.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created or updated without writing anything.',
        )

    def handle(self, *args, **options):
        update = options['update']
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes will be written.\n'))

        # ------------------------------------------------------------------
        # Categories
        # ------------------------------------------------------------------
        category_map = {}
        created_categories = 0

        for spec in CATEGORIES:
            existing = BlogCategory.objects.filter(slug=spec['slug']).first()
            if existing:
                category_map[spec['slug']] = existing
                continue

            if dry_run:
                self.stdout.write(f"  would create category: {spec['name']}")
                continue

            category_map[spec['slug']] = BlogCategory.objects.create(
                name=spec['name'],
                slug=spec['slug'],
                description=spec.get('description', ''),
                display_order=spec.get('display_order', 0),
            )
            created_categories += 1

        # ------------------------------------------------------------------
        # Posts
        # ------------------------------------------------------------------
        # Publication dates are staggered backwards from today, a few days apart,
        # in reverse list order. Stamping every article with the identical
        # timestamp makes the blog index look machine-generated and gives the
        # ordering nothing to sort on.
        now = timezone.now()
        created_posts = 0
        updated_posts = 0
        skipped_posts = 0

        for offset, spec in enumerate(POSTS):
            slug = spec['slug']
            existing = BlogPost.objects.filter(slug=slug).first()

            if existing and not update:
                skipped_posts += 1
                continue

            published_at = now - timedelta(days=offset * 4)

            fields = {
                'title': spec['title'],
                'excerpt': spec['excerpt'].strip(),
                'body': spec['body'].strip(),
                'category': category_map.get(spec.get('category')),
                'meta_description': spec.get('meta_description', ''),
                'keywords': spec.get('keywords', ''),
                'is_featured': spec.get('featured', False),
                'is_published': True,
            }

            if existing:
                if dry_run:
                    self.stdout.write(f'  would update: {slug}')
                    continue
                for key, value in fields.items():
                    setattr(existing, key, value)
                # Force the reading estimate to be recomputed from the new body.
                existing.reading_minutes = 0
                existing.save()
                updated_posts += 1
                self.stdout.write(f'  updated: {slug}')
            else:
                if dry_run:
                    self.stdout.write(f'  would create: {slug}')
                    continue
                BlogPost.objects.create(slug=slug, published_at=published_at, **fields)
                created_posts += 1
                self.stdout.write(f'  created: {slug}')

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        if dry_run:
            self.stdout.write(self.style.WARNING('\nDry run complete — nothing was written.'))
            return

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Categories created: {created_categories}  '
            f'Posts created: {created_posts}  '
            f'Posts updated: {updated_posts}  '
            f'Posts left untouched: {skipped_posts}'
        ))
        if skipped_posts and not update:
            self.stdout.write(
                'Existing posts were left as they are. Pass --update to overwrite them '
                'from portal/blog_content (this discards any admin edits).'
            )
