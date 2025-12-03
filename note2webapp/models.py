from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Max


# -----------------------
# USER PROFILE WITH ROLE
# -----------------------
class Profile(models.Model):
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("uploader", "Model Uploader"),
        ("reviewer", "Model Reviewer"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    # default stays "uploader" for normal signups
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="uploader")

    def __str__(self):
        return f"{self.user.username} ({self.role})"


@receiver(post_save, sender=User)
def create_or_update_profile(sender, instance, created, **kwargs):
    """
    Ensure every User has a Profile.
    If the user is staff/superuser, force role="admin".
    """
    if created:
        profile = Profile.objects.create(user=instance)
    else:
        profile, _ = Profile.objects.get_or_create(user=instance)

    # force admin role for Django admins
    if instance.is_superuser or instance.is_staff:
        if profile.role != "admin":
            profile.role = "admin"
            profile.save()
    else:
        # just save whatever non-admin role it has
        profile.save()


# -----------------------
# MODEL UPLOAD
# -----------------------
class ModelUpload(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="uploads")
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


# -----------------------
# MODEL VERSION
# -----------------------
class ModelVersion(models.Model):
    upload = models.ForeignKey(
        ModelUpload,
        on_delete=models.CASCADE,
        related_name="versions",
    )

    # uploaded files
    model_file = models.FileField(upload_to="models/")
    predict_file = models.FileField(upload_to="predict/")
    schema_file = models.FileField(upload_to="schemas/", blank=True, null=True)

    tag = models.CharField(max_length=100)
    information = models.TextField(blank=True, null=True)

    CATEGORY_CHOICES = [
        ("sentiment", "Sentiment"),
        ("recommendation", "Recommendation"),
        ("text-classification", "Text Classification"),
    ]
    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        default="sentiment",
    )

    status = models.CharField(
        max_length=20,
        choices=[
            ("PENDING", "Pending"),
            ("PASS", "Pass"),
            ("FAIL", "Fail"),
        ],
        default="PENDING",
    )

    is_active = models.BooleanField(default=False)
    log = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    usage_count = models.PositiveIntegerField(
        default=0, help_text="Number of times this version has been tested."
    )

    # soft delete
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # per-upload version number
    version_number = models.IntegerField(default=1)

    # hashes for dedupe
    model_hash = models.CharField(max_length=64, blank=True, null=True)
    predict_hash = models.CharField(max_length=64, blank=True, null=True)
    schema_hash = models.CharField(max_length=64, blank=True, null=True)
    bundle_hash = models.CharField(max_length=64, blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        # assign next version number only on first save
        if not self.pk:
            last_version = ModelVersion.objects.filter(upload=self.upload).aggregate(
                Max("version_number")
            )["version_number__max"]
            self.version_number = (last_version or 0) + 1
        super().save(*args, **kwargs)

    def __str__(self):
        try:
            return f"{self.upload.name} - v{self.version_number} ({self.status})"
        except Exception:
            return f"ModelVersion (unsaved) - {self.status}"

    def get_version_number(self):
        return self.version_number

    def get_media_dir(self):
        """
        media/<category>/<upload.name>/v<version_number>/
        """
        safe_name = getattr(self.upload, "name", f"upload-{self.upload_id}")
        return f"{self.category}/{safe_name}/v{self.version_number}/"


# -----------------------
# MODEL FEEDBACK/COMMENT SYSTEM
# -----------------------
class ModelComment(models.Model):
    model_version = models.ForeignKey(
        ModelVersion, on_delete=models.CASCADE, related_name="comments"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user.username} on {self.model_version.tag}: {self.content[:50]}"

    def is_reply(self):
        return self.parent is not None

    def get_likes_count(self):
        return self.reactions.filter(reaction_type="like").count()

    def get_dislikes_count(self):
        return self.reactions.filter(reaction_type="dislike").count()

    def get_user_reaction(self, user):
        try:
            reaction = self.reactions.get(user=user)
            return reaction.reaction_type
        except CommentReaction.DoesNotExist:
            return None


class CommentReaction(models.Model):
    REACTION_CHOICES = [
        ("like", "Like"),
        ("dislike", "Dislike"),
    ]

    comment = models.ForeignKey(
        ModelComment, on_delete=models.CASCADE, related_name="reactions"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    reaction_type = models.CharField(max_length=10, choices=REACTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["comment", "user"]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} {self.reaction_type}s comment {self.comment.id}"
