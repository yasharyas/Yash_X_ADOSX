from django.contrib import admin

from .models import ImportAnomaly, Location, SystemARecord, SystemBEntry

admin.site.register(Location)
admin.site.register(SystemARecord)
admin.site.register(SystemBEntry)
# Registered so quarantined rows are browsable without writing a query.
admin.site.register(ImportAnomaly)
