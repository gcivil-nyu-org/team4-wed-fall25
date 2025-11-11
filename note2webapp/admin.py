# note2webapp/admin.py
from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin
from django.urls import path

from .models import Profile, ModelUpload, ModelVersion
from .utils import delete_model_media_tree, delete_version_files_and_dir
from . import views


# ---------------------------
# Custom Admin Site with Stats
# ---------------------------
class CustomAdminSite(admin.AdminSite):
    site_header = "Note2Web Administration"
    site_title = "Note2Web Admin"
    index_title = "Welcome to Note2Web Administration"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("stats/", self.admin_view(views.admin_stats), name="admin_stats"),
        ]
        return custom_urls + urls

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_stats_button"] = True
        return super().index(request, extra_context)


# Create custom admin site instance
admin_site = CustomAdminSite(name="admin")


# ---------------------------
# User + Profile inline
# ---------------------------
class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "Profile"
    extra = 0


class CustomUserAdmin(UserAdmin):
    inlines = (ProfileInline,)


# Register User with custom admin site
admin_site.register(User, CustomUserAdmin)


# ---------------------------
# ModelUpload admin
# admin delete => also delete media tree
# ---------------------------
@admin.register(ModelUpload, site=admin_site)
class ModelUploadAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("name", "user__username")

    def delete_model(self, request, obj):
        # delete media/<model> folder too
        delete_model_media_tree(obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        # bulk delete cleanup
        for obj in queryset:
            delete_model_media_tree(obj)
        super().delete_queryset(request, queryset)


# ---------------------------
# ModelVersion admin
# admin delete => also delete version files
# ---------------------------
@admin.register(ModelVersion, site=admin_site)
class ModelVersionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "upload",
        "tag",
        "status",
        "is_active",
        "is_deleted",
        "category",
        "created_at",
    )
    list_filter = ("status", "is_active", "is_deleted", "category", "created_at")
    search_fields = ("tag", "upload__name")

    def delete_model(self, request, obj):
        delete_version_files_and_dir(obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            delete_version_files_and_dir(obj)
        super().delete_queryset(request, queryset)


# ---------------------------
# Profile admin
# ---------------------------
@admin.register(Profile, site=admin_site)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    list_filter = ("role",)
    search_fields = ("user__username",)
