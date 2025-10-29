# your_app/admin.py
from django.contrib import admin
from .models import PatientReport, ChatMessage

@admin.register(PatientReport)
class PatientReportAdmin(admin.ModelAdmin):
    list_display = ("user", "get_report_type", "created_at")
    search_fields = ("user__username",)
    list_filter = ("created_at",)
    readonly_fields = ('data',) # Display data as read-only

    @admin.display(description='Report Type')
    def get_report_type(self, obj):
        return obj.data.get('type', 'N/A')

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'content_snippet', 'timestamp')
    search_fields = ('user__username', 'content')
    list_filter = ('timestamp', 'role')
    
    @admin.display(description='Content')
    def content_snippet(self, obj):
        return (obj.content[:75] + '...') if len(obj.content) > 75 else obj.content