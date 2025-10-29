from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('details/', views.pregnancy_details_view, name='pregnancy_details'),
    path('chat/', views.chat, name='chat'),
    path('get-chat-history/', views.get_chat_history, name='get_chat_history'),
    path('clear-all-chat-history/', views.clear_all_chat_history, name='clear_all_chat_history'),
    path('get-user-profile/', views.get_user_profile, name='get_user_profile'),
    path('log-symptom/', views.log_symptom, name='log_symptom'),

    path('gemini/', views.gemini, name='gemini'),
    path('gemini/send_frame/', views.send_frame, name='send_frame'),
    path('gemini/send_audio/', views.send_audio, name='send_audio'),
]