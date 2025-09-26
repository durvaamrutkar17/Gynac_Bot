# main/models.py

from django.db import models
from django.contrib.auth.models import User

# NOTE: These models have been updated to persist chat and report data
# in the database. This ensures data is not lost on logout and is tied to the user account.
# The ephemeral session-based storage is being replaced by this database-backed approach.

class PatientReport(models.Model):
    # Link reports to an authenticated user.
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # A flexible JSONField to store the varied structure of 'general' and 'pregnancy' reports.
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Order descending by creation to easily get the latest one with .first()
        ordering = ['-created_at']

    def __str__(self):
        report_type = self.data.get('type', 'general')
        return f"Report ({report_type}) for {self.user.username} at {self.created_at.strftime('%Y-%m-%d')}"

class ChatMessage(models.Model):
    # Link messages to an authenticated user, making it non-nullable.
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # session_key is no longer needed as we are dealing with authenticated users.
    role = models.CharField(max_length=10)  # 'user' or 'bot'
    content = models.TextField()

    # These fields are kept from the original model definition for potential future use.
    meta_type = models.CharField(
        max_length=32,
        default='chat',                 # 'chat' | 'quick_analyze' | 'summary' | 'medication'
    )
    payload = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        owner = self.user.username
        return f"[{owner}] {self.meta_type}/{self.role}: {self.content[:50]}..."