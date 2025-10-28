from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("", views.login_view, name="root"),
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("model-versions/<int:model_id>/", views.model_versions, name="model_versions"),
    path(
        "delete-version/<int:version_id>/",
        views.soft_delete_version,
        name="delete_version",
    ),
    path(
        "activate-version/<int:version_id>/",
        views.activate_version,
        name="activate_version",
    ),
    path(
        "deprecate-version/<int:version_id>/",
        views.deprecate_version,
        name="deprecate_version",
    ),
    path("delete-model/<int:model_id>/", views.delete_model, name="delete_model"),
    path("reviewer/", views.reviewer_dashboard, name="reviewer_dashboard"),
    # Password reset routes
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="note2webapp/password_reset_form.html",
            email_template_name="note2webapp/password_reset_email.html",
            subject_template_name="note2webapp/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="note2webapp/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="note2webapp/password_reset_confirm.html"
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="note2webapp/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]
