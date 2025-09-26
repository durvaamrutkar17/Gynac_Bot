# main/urls.py

from django.urls import path
from . import views
from django.views.generic import TemplateView # Import this

urlpatterns = [
    path('', views.home, name='home'),
    path('details/', views.pregnancy_details_view, name='pregnancy_details'), # New
    path('chat/', views.chat, name='chat'),
    path('save-report/', views.save_report, name='save_report'),
    path('analyze-session-report/', views.analyze_session_report, name='analyze_session_report'),
    path('get-chat-history/', views.get_chat_history, name='get_chat_history'), 
    path('clear-all-chat-history/', views.clear_all_chat_history, name='clear_all_chat_history'), 
    path('localAnalyze/', views.localAnalyze, name='local_analyze'),
]