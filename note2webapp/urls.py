# note2webapp/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.login_view, name="root"),
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("reviewer/", views.reviewer_dashboard, name="reviewer_dashboard"),
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
    path(
        "validation-failed/<int:version_id>/",
        views.validation_failed,
        name="validation_failed",
    ),
    path("delete-model/<int:model_id>/", views.delete_model, name="delete_model"),
    path("test-model/<int:version_id>/", views.test_model_cpu, name="test_model_cpu"),
    path(
        "version/<int:version_id>/edit-information/",
        views.edit_version_information,
        name="edit_version_information",
    ),
    # NEW API endpoints
    path("api/run-model/", views.run_model_from_path, name="run_model_from_path"),
    path(
        "api/run-model/<int:version_id>/",
        views.run_model_by_version_id,
        name="run_model_by_version_id",
    ),
    path("admin/stats/", views.admin_stats, name="admin_stats"),
    path(
        "model/<int:version_id>/comments/",
        views.model_comments_view,
        name="model_comments",
    ),
    path(
        "api/generate-model-info/",
        views.generate_model_info,
        name="generate_model_info",
    ),
    path(
        "api/comment/<int:comment_id>/reaction/",
        views.toggle_comment_reaction,
        name="toggle_comment_reaction",
    ),
    path("api/notifications/", views.list_notifications, name="list_notifications"),
    path(
        "api/notifications/mark-all-read/",
        views.mark_all_notifications_read,
        name="mark_all_notifications_read",
    ),
]
