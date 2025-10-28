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

    # ADD THESE NEW FIELDS FOR SOFT DELETE
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def get_version_number(self):
        if not self.pk:
            existing_count = (
                ModelVersion.objects.filter(
                    upload=self.upload, is_deleted=False
                ).count()
                if self.upload_id
                else 0
            )
            return existing_count + 1

        return (
            ModelVersion.objects.filter(
                upload=self.upload, is_deleted=False, pk__lt=self.pk
            ).count()
            + 1
        )

    def __str__(self):
        try:
            version_num = self.get_version_number()
            version_str = f"v{version_num}" if version_num else "v?"
            upload_name = getattr(self.upload, "name", "Unknown Upload")
            return f"{upload_name} - {version_str} ({self.status})"
        except Exception as e:
            return f"ModelVersion (unsaved) - {self.status}"
