"""
Convert the MySQL database to utf8mb4 so text comparisons stop failing.

THE SYMPTOM

    Error processing file: (1267, "Illegal mix of collations
    (latin1_swedish_ci,IMPLICIT) and (utf8mb4_general_ci,COERCIBLE)
    for operation 'like'")

THE CAUSE

    Django connects with ``charset: utf8mb4`` (see settings.DATABASES), so every
    string it sends is utf8mb4. The database itself was created with the MySQL
    server default, which on most cPanel hosts is latin1. Comparing a latin1
    column against a utf8mb4 value is something MySQL refuses to guess at, so any
    query using LIKE errors out.

    The bulk importer checks ``Product.objects.filter(name__iexact=name)`` for
    every row, and ``iexact`` compiles to LIKE — which is why an upload dies on
    the duplicate check rather than on anything to do with the file. The same
    fault affects product search and category matching; the import is simply
    where it shows up first.

    It is not a data problem. latin1 columns cannot even store the Chinese
    product names this catalogue is full of, so converting is needed regardless.

USAGE

    python manage.py fix_db_collation            # report only, changes nothing
    python manage.py fix_db_collation --apply    # convert

BACK UP FIRST. This rewrites every table. `CONVERT TO CHARACTER SET` is a
standard, well-trodden operation, but it is not free and it is not instant on a
large table.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

TARGET_CHARSET = 'utf8mb4'
# unicode_ci sorts non-English text correctly, where general_ci is a faster but
# cruder approximation. Every table gets the SAME collation: two different
# utf8mb4 collations in one JOIN raises the identical 1267 error this fixes.
TARGET_COLLATION = 'utf8mb4_unicode_ci'


class Command(BaseCommand):
    help = 'Convert the MySQL database and all its tables to utf8mb4.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually convert. Without this the command only reports.',
        )

    def handle(self, *args, **options):
        if connection.vendor != 'mysql':
            raise CommandError(
                f'This database is {connection.vendor}, not MySQL — there is '
                f'nothing to convert. Run it against production.'
            )

        apply_changes = options['apply']
        db_name = connection.settings_dict['NAME']

        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT default_character_set_name, default_collation_name '
                'FROM information_schema.SCHEMATA WHERE schema_name = %s',
                [db_name],
            )
            row = cursor.fetchone()
            db_charset, db_collation = row if row else ('?', '?')

            self.stdout.write(f'Database : {db_name}')
            self.stdout.write(f'Charset  : {db_charset} / {db_collation}')
            self.stdout.write('')

            cursor.execute(
                'SELECT t.table_name, c.character_set_name, t.table_collation '
                'FROM information_schema.TABLES t '
                'JOIN information_schema.COLLATION_CHARACTER_SET_APPLICABILITY c '
                '  ON c.collation_name = t.table_collation '
                'WHERE t.table_schema = %s AND t.table_type = %s '
                'ORDER BY t.table_name',
                [db_name, 'BASE TABLE'],
            )
            tables = cursor.fetchall()

            # Compare the COLLATION, not just the charset.
            #
            # Checking charset alone reported "nothing to do" on a database whose
            # tables were utf8mb4 but whose collations differed - and two
            # different utf8mb4 collations in one JOIN raise the same 1267 error
            # as latin1 vs utf8mb4. The charset test only ever caught the
            # latin1 case.
            wrong = [(name, charset, collation) for name, charset, collation in tables
                     if charset != TARGET_CHARSET or collation != TARGET_COLLATION]

            self.stdout.write(
                f'{len(tables)} table(s), {len(wrong)} not {TARGET_COLLATION}:')
            for name, charset, collation in wrong:
                self.stdout.write(self.style.WARNING(f'   {name:44} {charset} / {collation}'))
            if not wrong:
                self.stdout.write(self.style.SUCCESS(
                    f'   none - every table is already {TARGET_COLLATION}'))

            # The database default decides what a NEWLY created table gets. Left
            # on a different collation, the next migration to add a table plants
            # a future 1267 error even though every existing table is correct.
            needs_db = (db_charset != TARGET_CHARSET
                        or db_collation != TARGET_COLLATION)
            if needs_db:
                self.stdout.write('')
                self.stdout.write(self.style.WARNING(
                    f'   database default is {db_charset}/{db_collation}, '
                    f'so new tables would be created wrong'))
            if not wrong and not needs_db:
                self.stdout.write('')
                self.stdout.write(self.style.SUCCESS('Nothing to do.'))
                return

            if not apply_changes:
                self.stdout.write('')
                self.stdout.write(self.style.WARNING(
                    'Reporting only. Re-run with --apply to convert. '
                    'BACK UP THE DATABASE FIRST.'
                ))
                return

            # The database default only affects tables created later; existing
            # tables are converted individually below.
            if needs_db:
                cursor.execute(
                    f'ALTER DATABASE `{db_name}` '
                    f'CHARACTER SET {TARGET_CHARSET} COLLATE {TARGET_COLLATION}'
                )
                self.stdout.write(self.style.SUCCESS(
                    f'\nDatabase default set to {TARGET_CHARSET}.'
                ))

            self.stdout.write('')
            # Foreign keys are checked on ALTER; a mid-conversion state has
            # parent and child on different charsets, which the checker rejects.
            # They are re-enabled in the finally block so an error cannot leave
            # the session with checking off.
            cursor.execute('SET FOREIGN_KEY_CHECKS = 0')
            converted, failed = 0, 0
            try:
                for name, charset, collation in wrong:
                    try:
                        cursor.execute(
                            f'ALTER TABLE `{name}` CONVERT TO '
                            f'CHARACTER SET {TARGET_CHARSET} COLLATE {TARGET_COLLATION}'
                        )
                        converted += 1
                        self.stdout.write(self.style.SUCCESS(f'   converted  {name}'))
                    except Exception as exc:
                        failed += 1
                        self.stdout.write(self.style.ERROR(f'   FAILED     {name}: {exc}'))
            finally:
                cursor.execute('SET FOREIGN_KEY_CHECKS = 1')

        self.stdout.write('')
        self.stdout.write(f'Converted: {converted}')
        if failed:
            self.stdout.write(self.style.ERROR(f'Failed: {failed}'))
            self.stdout.write(
                'A failure is usually an index too long for utf8mb4 — four bytes '
                'per character against the old 767-byte key limit. Setting the '
                "table's ROW_FORMAT to DYNAMIC lifts that to 3072 bytes."
            )
        else:
            self.stdout.write(self.style.SUCCESS(
                'Done. Re-run the CSV upload — the collation error should be gone.'
            ))
