# main/models.py

from django.db import models
from django.contrib.auth.models import User

class PatientReport(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        report_type = self.data.get('type', 'general')
        return f"Report ({report_type}) for {self.user.username} at {self.created_at.strftime('%Y-%m-%d')}"

class ChatMessage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=10)  # 'user' or 'bot'
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"[{self.user.username}] {self.role}: {self.content[:50]}..."

# NEW MODEL FOR DAILY TRACKING
class DailyLog(models.Model):
    """
    Stores daily user-reported data like symptoms, mood, vitals, etc.
    This is the foundation for tracking progress over time.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    log_date = models.DateField(auto_now_add=True)
    # Flexible JSONField to store various types of logs (symptoms, mood, etc.)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Ensure one log per user per day to avoid duplicates, can be adjusted
        unique_together = ('user', 'log_date')
        ordering = ['-log_date']

    def __str__(self):
        log_type = self.data.get('type', 'generic')
        return f"{log_type.title()} log for {self.user.username} on {self.log_date}"