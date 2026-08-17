from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from reconcile.importer import import_all
from reconcile.models import ImportAnomaly


class Command(BaseCommand):
    """Expose the importer as ``python manage.py import_csv``.

    Why a management command (not a script or an API endpoint): it runs inside
    Django's app context (settings, ORM, migrations) with zero boilerplate, is the
    idiomatic "load my data" entry point reviewers expect, and appears verbatim in
    the README run steps for a clean clone.
    """

    help = "Import locations.csv, system_a.csv, and system_b.csv into the database."

    def add_arguments(self, parser):
        """Add an optional ``--data-dir`` override.

        Why make it optional with a settings default: the normal path (the bundled
        dataset) needs no arguments, but the override lets tests or a reviewer point
        at a different export without editing code.
        """
        parser.add_argument(
            "--data-dir",
            type=str,
            default=None,
            help="Directory containing the three CSV files (default: settings.DATA_DIR).",
        )

    def handle(self, *args, **options):
        """Validate the inputs exist, then import and report the row counts.

        Why validate all three files before importing anything: failing fast with a
        clear ``CommandError`` (rather than a stack trace halfway through) tells the
        user exactly which file is missing, and pairs with the atomic import so the
        DB is never left half-loaded.
        """
        data_dir = Path(options["data_dir"]) if options["data_dir"] else Path(settings.DATA_DIR)
        if not data_dir.is_dir():
            raise CommandError(f"Data directory not found: {data_dir}")

        for name in ("locations.csv", "system_a.csv", "system_b.csv"):
            path = data_dir / name
            if not path.is_file():
                raise CommandError(f"Missing file: {path}")

        results = import_all(data_dir)

        # Report per file rather than one total, so a problem is attributable to a
        # specific export. rows_read == stored + quarantined is asserted below, which
        # is what makes "nothing was silently dropped" a checked claim, not a promise.
        total_quarantined = 0
        for name, result in results.items():
            self.stdout.write(f"{name}: {result}")
            total_quarantined += result.quarantined
            if not result.accounted_for:
                raise CommandError(
                    f"Row accounting failed for {name}: {result}. "
                    "Some rows were neither stored nor quarantined."
                )

        if total_quarantined:
            # Loud, itemized output: a quarantined row is a real data problem that
            # someone needs to fix at the source, so it must not scroll past quietly.
            self.stdout.write(
                self.style.WARNING(
                    f"{total_quarantined} row(s) quarantined - stored in ImportAnomaly, not dropped:"
                )
            )
            for anomaly in ImportAnomaly.objects.all():
                self.stdout.write(
                    self.style.WARNING(
                        f"  {anomaly.source_file} line {anomaly.line_number}: "
                        f"{anomaly.reason} (key={anomaly.natural_key!r})"
                    )
                )

        self.stdout.write(self.style.SUCCESS("Import complete; every row accounted for."))
