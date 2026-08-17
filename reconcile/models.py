from django.db import models


class ImportAnomaly(models.Model):
    """A source row that could not become a first-class record, kept verbatim.

    Why this table exists: the other three models use the CSV's natural key as
    their primary key, which is right for identity and idempotent re-imports, but
    it means a duplicate or blank key in a worse export would overwrite (and so
    silently destroy) a previous row. Rather than lose it, such a row is stored
    here with its file, line number, and full raw content.

    This is the standard "dead letter"/quarantine pattern: the main tables stay
    clean and queryable, while every rejected row remains inspectable and counted,
    so the importer can never quietly drop data.
    """

    REASON_DUPLICATE_SOURCE_KEY = "DUPLICATE_SOURCE_KEY"
    REASON_BLANK_PRIMARY_KEY = "BLANK_PRIMARY_KEY"
    REASON_CHOICES = [
        (REASON_DUPLICATE_SOURCE_KEY, "Duplicate natural key within the same file"),
        (REASON_BLANK_PRIMARY_KEY, "Natural key was blank"),
    ]

    source_file = models.CharField(max_length=64, db_index=True)
    # Why store the line number: "row 87 of system_b.csv" is actionable for
    # whoever has to fix the export; a bare copy of the row is not.
    line_number = models.PositiveIntegerField()
    natural_key = models.CharField(max_length=128, blank=True, default="")
    reason = models.CharField(max_length=32, choices=REASON_CHOICES)
    # The entire original row, so nothing about the rejected data is lost.
    raw_row = models.JSONField(default=dict)

    class Meta:
        ordering = ["source_file", "line_number"]
        verbose_name_plural = "import anomalies"

    def __str__(self):
        return f"{self.source_file}:{self.line_number} {self.reason}"


class Location(models.Model):
    """The location -> org mapping; the only place tenancy is defined.

    Why ``location_id`` is the primary key (here and in the other two models):
    the CSVs already carry stable natural keys, so reusing them avoids a
    meaningless surrogate id and makes ``update_or_create`` on re-import trivial.
    ``org_id`` is indexed because every disagreement is scoped by org.
    """

    location_id = models.CharField(max_length=64, primary_key=True)
    org_id = models.CharField(max_length=64, db_index=True)
    location_name = models.CharField(max_length=255)

    class Meta:
        ordering = ["location_id"]

    def __str__(self):
        # Why show the org too: locations are almost always read in a tenant
        # context, so the admin/debug repr is far more useful with it attached.
        return f"{self.location_id} ({self.org_id})"


class SystemARecord(models.Model):
    """One System A event. Raw CSV strings are always kept; parsed fields may be null."""

    record_id = models.CharField(max_length=64, primary_key=True)
    location_id = models.CharField(max_length=64, db_index=True)
    event_date_raw = models.CharField(max_length=64, blank=True, default="")
    category_code = models.CharField(max_length=64, blank=True, default="")
    actor_id = models.CharField(max_length=64, blank=True, default="")
    base_value_raw = models.CharField(max_length=64, blank=True, default="")
    adjustment_raw = models.CharField(max_length=64, blank=True, default="")
    total_value_raw = models.CharField(max_length=64, blank=True, default="")
    state = models.CharField(max_length=64, blank=True, default="")

    event_date = models.DateField(null=True, blank=True)
    base_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    adjustment = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    total_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)

    # Why a JSONField list: the number of parse problems per row is open-ended
    # (a row can be dirty in several columns at once), so a list captures them all
    # without a side table, and it survives a clean clone on SQLite.
    parse_issues = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["record_id"]

    def __str__(self):
        # The record id is the identifier the brief and the reviewers reason about.
        return self.record_id


class SystemBEntry(models.Model):
    """One System B entry. May point at A via a messy record_ref."""

    entry_id = models.CharField(max_length=64, primary_key=True)
    record_ref_raw = models.CharField(max_length=128, blank=True, default="")
    record_id_normalized = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    location_id = models.CharField(max_length=64, db_index=True)
    recorded_on_raw = models.CharField(max_length=64, blank=True, default="")
    value_raw = models.CharField(max_length=64, blank=True, default="")
    label = models.CharField(max_length=255, blank=True, default="")

    recorded_on = models.DateField(null=True, blank=True)
    value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)

    parse_issues = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["entry_id"]
        # Why set this: Django would otherwise pluralize to "system b entrys".
        verbose_name_plural = "system b entries"

    def __str__(self):
        return self.entry_id
