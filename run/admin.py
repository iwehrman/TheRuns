from run.models import Run, Shoe, UserProfile
from django.contrib import admin


class RunAdmin(admin.ModelAdmin):
    fieldsets = [(None, {'fields': ['user', 'date', 'shoe', 'distance']}), 
                 ('Duration', 
                    {'fields': ['duration']}),
                 ('Physiology', {'fields': ['average_heart_rate']}), 
                ]
    list_display = ['date', 'user', 'distance', 'duration']
    list_filter = ['user']

admin.site.register(Run, RunAdmin)
admin.site.register(Shoe)
admin.site.register(UserProfile)