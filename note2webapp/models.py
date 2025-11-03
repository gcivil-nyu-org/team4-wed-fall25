from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


# -----------------------
# USER PROFILE WITH ROLE
# -----------------------
class Profile(models.Model):
    ROLE_CHOICES = [
        ("uploader", "Model Uploader"),
        ("reviewer", "Model Reviewer"),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="uploader")

    def __str__(self):
        return f"{self.user.username} ({self.role})"


@receiver(post_save, sender=User)
def create_or_update_profile(sender, instance, created, **kwargs):
    """Automatically create or update Profile when User is created/updated"""
    if created:
        Profile.objects.create(user=instance)
    else:
        instance.profile.save()


# -----------------------
# MODEL UPLOAD + VERSION
# -----------------------
class ModelUpload(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="uploads")
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ModelVersion(models.Model):
    upload = models.ForeignKey(
        ModelUpload, on_delete=models.CASCADE, related_name="versions"
    )
    model_file = models.FileField(upload_to="models/")
    predict_file = models.FileField(upload_to="predict/")
    schema_file = models.FileField(
        upload_to="schemas/", blank=True, null=True
    )  # for test data generation
    tag = models.CharField(max_length=100)
    # ADD THIS: Model information field
    information = models.TextField(blank=True, null=True)

    category = models.CharField(
        max_length=50,
        choices=[
            ("research", "Research"),
            ("production", "Production"),
            ("testing", "Testing"),
        ],
        default="research",
    )

    status = models.CharField(
        max_length=20,
        choices=[("PENDING", "Pending"), ("PASS", "Pass"), ("FAIL", "Fail")],
        default="PENDING",
    )
    is_active = models.BooleanField(default=False)
    log = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Soft delete fields
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    # Store version number permanently
    version_number = models.IntegerField(default=1)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        # Auto-generate version number for new versions only
        if not self.pk:  # Only for new objects
            from django.db.models import Max

            # Get the highest version number for this upload
            last_version = ModelVersion.objects.filter(upload=self.upload).aggregate(
                Max("version_number")
            )["version_number__max"]
            self.version_number = (last_version or 0) + 1
        super().save(*args, **kwargs)

    def get_version_number(self):
        """Keep this method for backwards compatibility"""
        return self.version_number

    def __str__(self):
        try:
            version_str = f"v{self.version_number}"
            upload_name = getattr(self.upload, "name", "Unknown Upload")
            return f"{upload_name} - {version_str} ({self.status})"
        except Exception:
            return f"ModelVersion (unsaved) - {self.status}"
