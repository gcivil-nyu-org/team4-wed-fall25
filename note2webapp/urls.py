from django.urls import path
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
]
