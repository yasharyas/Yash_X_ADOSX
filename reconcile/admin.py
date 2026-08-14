from django.contrib import admin

from .models import Location, SystemARecord, SystemBEntry

admin.site.register(Location)
admin.site.register(SystemARecord)
admin.site.register(SystemBEntry)
