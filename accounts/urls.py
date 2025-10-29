from django.urls import path
from . import views

urlpatterns = [
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("details/", views.details, name="details"),
    path("logout/", views.logout_view, name="logout"),
]
