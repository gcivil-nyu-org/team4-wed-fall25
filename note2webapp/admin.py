from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin
from .models import Profile, ModelUpload, ModelVersion


# Extend User admin to show Profile inline
class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "Profile"


class CustomUserAdmin(UserAdmin):
    inlines = (ProfileInline,)


# Unregister default User admin, register our custom one
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


# Register your existing models
@admin.register(ModelUpload)
class ModelUploadAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at")


@admin.register(ModelVersion)
class ModelVersionAdmin(admin.ModelAdmin):
    list_display = ("id", "upload", "tag", "status", "created_at")
    list_filter = ("status", "is_active", "created_at")


# Register Profile standalone (optional, since it's inline too)
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
