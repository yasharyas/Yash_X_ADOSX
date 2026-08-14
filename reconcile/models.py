from django.db import models


class Location(models.Model):
    location_id = models.CharField(max_length=64, primary_key=True)
    org_id = models.CharField(max_length=64, db_index=True)
    location_name = models.CharField(max_length=255)

    class Meta:
        ordering = ["location_id"]

    def __str__(self):
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

    parse_issues = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["record_id"]

    def __str__(self):
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
        verbose_name_plural = "system b entries"

    def __str__(self):
        return self.entry_id
