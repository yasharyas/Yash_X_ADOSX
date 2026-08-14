from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from reconcile.importer import import_all


class Command(BaseCommand):
    help = "Import locations.csv, system_a.csv, and system_b.csv into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data-dir",
            type=str,
            default=None,
            help="Directory containing the three CSV files (default: settings.DATA_DIR).",
        )

    def handle(self, *args, **options):
        data_dir = Path(options["data_dir"]) if options["data_dir"] else Path(settings.DATA_DIR)
        if not data_dir.is_dir():
            raise CommandError(f"Data directory not found: {data_dir}")

        for name in ("locations.csv", "system_a.csv", "system_b.csv"):
            path = data_dir / name
            if not path.is_file():
                raise CommandError(f"Missing file: {path}")

        counts = import_all(data_dir)
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported locations={counts['locations']} "
                f"system_a={counts['system_a']} system_b={counts['system_b']}"
            )
        )
