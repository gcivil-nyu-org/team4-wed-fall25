import os
import json
import importlib
import importlib.util
import inspect

from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django import forms
from django.db import transaction, IntegrityError, models

# for admin stats
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count

from django.conf import settings
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from .forms import UploadForm, VersionForm
from .models import ModelUpload, ModelVersion, Profile, ModelComment, CommentReaction
from .utils import (
    validate_model,
    test_model_on_cpu,
    sha256_uploaded_file,
    sha256_file_path,
    delete_version_files_and_dir,
    delete_model_media_tree,
)
from .decorators import role_required
from openai import OpenAI


# ---------------------------------------------------------
# AUTH
# ---------------------------------------------------------
def signup_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password1 = request.POST.get("password1")
        password2 = request.POST.get("password2")

        errors = []
        if not username or not password1 or not password2:
            errors.append("All fields are required.")
        if password1 and password2 and password1 != password2:
            errors.append("Passwords do not match.")
        if User.objects.filter(username=username).exists():
            errors.append("Username already exists.")
        if password1 and len(password1) < 8:
            errors.append("Password must be at least 8 characters long.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, "note2webapp/login.html")

        try:
            with transaction.atomic():
                user = User.objects.create_user(username=username, password=password1)

                # If a signal already created Profile, this will just fetch it.
                profile, created = Profile.objects.get_or_create(
                    user=user, defaults={"role": "uploader"}
                )
                # Ensure normal signups end up as uploader (unless something else set it)
                if profile.role != "uploader" and not user.is_superuser:
                    profile.role = "uploader"
                    profile.save(update_fields=["role"])

                group, _ = Group.objects.get_or_create(name="ModelUploader")
                user.groups.add(group)

            messages.success(request, "Account created successfully! Please login.")
            return redirect("login")

        except IntegrityError:
            # Handles any rare race (double post / parallel signal, etc.)
            messages.error(
                request,
                "Account created but there was a profile setup conflict; please try logging in.",
            )
            return render(request, "note2webapp/login.html")

        except Exception as e:
            messages.error(request, f"Error creating account: {str(e)}")
            return render(request, "note2webapp/login.html")

    return render(request, "note2webapp/login.html")


def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            # Ensure superusers have admin role
            if user.is_superuser:
                prof, _ = Profile.objects.get_or_create(user=user)
                if prof.role != "admin":
                    prof.role = "admin"
                    prof.save()

                # Use different session key for admin
                request.session.set_expiry(3600)  # 1 hour for admins

            # Redirect based on role
            if hasattr(user, "profile") and user.profile.role == "reviewer":
                return redirect("reviewer_dashboard")
            return redirect("dashboard")
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "note2webapp/login.html")


def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect("login")


# ---------------------------------------------------------
# MAIN DASHBOARD ROUTER
# ---------------------------------------------------------
@login_required
def dashboard(request):
    """
    Decide where to send the user.
    - Django staff/superuser: our nice stats page
    - uploader: uploader dashboard
    - reviewer: reviewer dashboard
    """
    if request.user.is_staff:
        return redirect("admin_stats")

    role = getattr(request.user.profile, "role", "uploader")
    if role == "uploader":
        return model_uploader_dashboard(request)
    elif role == "reviewer":
        return reviewer_dashboard(request)

    # fallback
    return model_uploader_dashboard(request)


@login_required
def validation_failed(request, version_id):
    version = get_object_or_404(ModelVersion, id=version_id, upload__user=request.user)
    if version.status != "FAIL":
        return redirect("model_versions", model_id=version.upload.id)
    return render(request, "note2webapp/validation_failed.html", {"version": version})


# ---------------------------------------------------------
# UPLOADER DASHBOARD
# ---------------------------------------------------------
@login_required
def model_uploader_dashboard(request):
    """
    Handles:
      - /dashboard/?page=list
      - /dashboard/?page=create
      - /dashboard/?page=detail&pk=...
      - /dashboard/?page=add_version&pk=...
    """
    page = request.GET.get("page", "list")
    pk = request.GET.get("pk")

    uploads = ModelUpload.objects.filter(user=request.user).order_by("-created_at")
    for upload in uploads:
        upload.active_versions_count = upload.versions.filter(
            is_deleted=False, status="PASS"
        ).count()

    context = {"uploads": uploads, "page": page}

    # 1) CREATE MODEL
    if page == "create":
        if request.method == "POST":
            form = UploadForm(request.POST)
            if form.is_valid():
                model_name = form.cleaned_data["name"]
                if ModelUpload.objects.filter(
                    user=request.user, name=model_name
                ).exists():
                    messages.error(
                        request,
                        f"A model with the name '{model_name}' already exists. Please choose a different name.",
                    )
                    context["form"] = form
                    return render(request, "note2webapp/home.html", context)
                upload = form.save(commit=False)
                upload.user = request.user
                upload.save()
                messages.success(request, f"Model '{model_name}' created successfully!")
                return redirect(f"/dashboard/?page=detail&pk={upload.pk}")
        else:
            form = UploadForm()
        context["form"] = form

    # 2) MODEL DETAIL
    elif page == "detail" and pk:
        upload = get_object_or_404(ModelUpload, pk=pk, user=request.user)
        versions = upload.versions.all().order_by("-created_at")
        version_counts = {
            "total": versions.count(),
            "active": versions.filter(
                is_active=True, is_deleted=False, status="PASS"
            ).count(),
            "available": versions.filter(is_deleted=False, status="PASS").count(),
            "failed": versions.filter(is_deleted=False, status="FAIL").count(),
            "deleted": versions.filter(is_deleted=True).count(),
        }
        context.update(
            {"upload": upload, "versions": versions, "version_counts": version_counts}
        )

    # 3) ADD VERSION
    elif page == "add_version" and pk:
        upload = get_object_or_404(ModelUpload, pk=pk, user=request.user)
        retry_version_id = request.GET.get("retry")

        if request.method == "POST":
            # quick missing file check
            missing_files = []
            if not request.FILES.get("model_file"):
                missing_files.append("Model file (.pt)")
            if not request.FILES.get("predict_file"):
                missing_files.append("Predict file (.py)")
            if not request.FILES.get("schema_file"):
                missing_files.append("Schema file (.json)")
            if missing_files:
                messages.error(
                    request, f"Missing required files: {', '.join(missing_files)}"
                )
                form = VersionForm(
                    initial={
                        "tag": request.POST.get("tag", ""),
                        "category": request.POST.get("category", "sentiment"),
                    }
                )
                context.update(
                    {
                        "form": form,
                        "upload": upload,
                        "retry_version_id": (
                            retry_version_id if retry_version_id else None
                        ),
                        "page": "add_version",
                        "pk": pk,
                    }
                )
                return render(request, "note2webapp/home.html", context)

            form = VersionForm(request.POST, request.FILES)
            if form.is_valid():
                # 1. Hash incoming files
                incoming_model_hash = sha256_uploaded_file(request.FILES["model_file"])
                incoming_predict_hash = sha256_uploaded_file(
                    request.FILES["predict_file"]
                )
                incoming_schema_hash = sha256_uploaded_file(
                    request.FILES["schema_file"]
                )

                # 2. Compare to every non-deleted version's stored files
                duplicate_found = False
                for v in ModelVersion.objects.filter(is_deleted=False):
                    try:
                        if (
                            v.model_file
                            and v.predict_file
                            and v.schema_file
                            and os.path.isfile(v.model_file.path)
                            and os.path.isfile(v.predict_file.path)
                            and os.path.isfile(v.schema_file.path)
                        ):
                            if (
                                sha256_file_path(v.model_file.path)
                                == incoming_model_hash
                                and sha256_file_path(v.predict_file.path)
                                == incoming_predict_hash
                                and sha256_file_path(v.schema_file.path)
                                == incoming_schema_hash
                            ):
                                duplicate_found = True
                                break
                    except Exception:
                        continue

                if duplicate_found:
                    msg_text = (
                        "An identical model/predict/schema bundle is already present. "
                        "Please upload a new version or change the files."
                    )
                    messages.error(request, msg_text)
                    context.update(
                        {
                            "form": form,
                            "upload": upload,
                            "duplicate_error": msg_text,
                        }
                    )
                    return render(request, "note2webapp/home.html", context)

                # 3. Create or retry the version
                if retry_version_id:
                    try:
                        version = ModelVersion.objects.get(
                            id=retry_version_id,
                            upload=upload,
                            status="FAIL",
                            is_deleted=False,
                        )
                        version.model_file = form.cleaned_data["model_file"]
                        version.predict_file = form.cleaned_data["predict_file"]
                        version.schema_file = form.cleaned_data["schema_file"]
                        version.category = form.cleaned_data["category"]
                        version.information = form.cleaned_data["information"]
                        version.status = "PENDING"
                        version.log = ""
                        version.save()
                        messages.info(
                            request, f"Retrying upload for version '{version.tag}'"
                        )
                    except ModelVersion.DoesNotExist:
                        messages.error(request, "Invalid version to retry")
                        return redirect(f"/dashboard/?page=detail&pk={upload.pk}")
                else:
                    version = form.save(commit=False)
                    version.upload = upload
                    version.save()

                # 4. validate
                validate_model(version)

                if version.status == "FAIL":
                    return redirect("validation_failed", version_id=version.id)

                if not retry_version_id:
                    messages.success(
                        request, f"Version '{version.tag}' uploaded successfully!"
                    )
                return redirect(f"/dashboard/?page=detail&pk={upload.pk}")

            else:
                messages.error(request, "Please correct the errors below.")
        else:
            # GET
            initial = {}
            if retry_version_id:
                try:
                    retry_version = ModelVersion.objects.get(
                        id=retry_version_id,
                        upload=upload,
                        status="FAIL",
                        is_deleted=False,
                    )
                    initial = {
                        "tag": retry_version.tag,
                        "category": retry_version.category,
                    }
                    context["retrying"] = True
                except ModelVersion.DoesNotExist:
                    messages.error(request, "Invalid version to retry")
                    return redirect(f"/dashboard/?page=detail&pk={upload.pk}")
            form = VersionForm(initial=initial)

        context.update(
            {
                "form": form,
                "upload": upload,
                "retry_version_id": retry_version_id if retry_version_id else None,
            }
        )

    return render(request, "note2webapp/home.html", context)


# ---------------------------------------------------------
# REVIEWER DASHBOARD
# ---------------------------------------------------------
@role_required("reviewer")
def reviewer_dashboard(request):
    page = request.GET.get("page", "list")
    pk = request.GET.get("pk")
    context = {"page": page}

    if page == "list":
        uploads = (
            ModelUpload.objects.filter(
                versions__is_active=True,
                versions__status="PASS",
                versions__is_deleted=False,
            )
            .distinct()
            .order_by("-created_at")
        )
        for upload in uploads:
            upload.active_version = upload.versions.filter(
                is_active=True, status="PASS", is_deleted=False
            ).first()
        context["uploads"] = uploads
        return render(request, "note2webapp/reviewer.html", context)

    if page == "detail" and pk:
        upload = get_object_or_404(ModelUpload, pk=pk)
        active_version = upload.versions.filter(
            is_active=True, status="PASS", is_deleted=False
        ).first()
        if not active_version:
            messages.warning(request, "This model has no active version.")
            return redirect("/reviewer/?page=list")
        context.update({"upload": upload, "active_version": active_version})
        return render(request, "note2webapp/reviewer.html", context)

    if page == "add_feedback" and pk:
        version = get_object_or_404(ModelVersion, pk=pk)
        if request.method == "POST":
            comment = request.POST.get("comment", "").strip()
            if comment:
                messages.success(request, "Feedback submitted successfully!")
                return redirect(f"/reviewer/?page=detail&pk={version.upload.pk}")
            else:
                messages.error(request, "Please provide feedback comment.")
        context["version"] = version
        return render(request, "note2webapp/reviewer.html", context)

    return redirect("/reviewer/?page=list")


# ---------------------------------------------------------
# VERSION SOFT DELETE
# ---------------------------------------------------------
@login_required
def soft_delete_version(request, version_id):
    version = get_object_or_404(ModelVersion, id=version_id)

    # permissions
    if request.user != version.upload.user and not request.user.is_staff:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Permission denied"}, status=403
            )
        messages.error(request, "You don't have permission to delete this version.")
        return redirect("dashboard")

    # if it's active and there are other versions -> block
    if version.is_active:
        other_versions = ModelVersion.objects.filter(
            upload=version.upload, is_deleted=False
        ).exclude(id=version_id)
        if other_versions.exists():
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Cannot delete active version. Please activate another version first.",
                    },
                    status=400,
                )
            messages.error(
                request,
                "Cannot delete active version. Please activate another version first.",
            )
            return redirect("dashboard")

    if request.method == "POST":
        version.is_deleted = True
        version.deleted_at = timezone.now()
        version.is_active = False
        version.save()

        # physically remove files + folder
        delete_version_files_and_dir(version)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "success": True,
                    "message": f"Version (Tag: {version.tag}) deleted successfully",
                    "reload": True,
                }
            )

        messages.success(
            request, f"Version with tag '{version.tag}' has been deleted successfully."
        )
        return redirect(f"/model-versions/{version.upload.id}/")

    return redirect("dashboard")


# ---------------------------------------------------------
# ACTIVATE / DEPRECATE VERSION
# ---------------------------------------------------------
@login_required
def activate_version(request, version_id):
    version = get_object_or_404(ModelVersion, id=version_id)
    if request.user != version.upload.user and not request.user.is_staff:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "success": False,
                    "error": "You don't have permission to activate this version.",
                },
                status=403,
            )
        messages.error(request, "You don't have permission to activate this version.")
        return redirect("dashboard")

    if version.is_deleted:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Cannot activate a deleted version."},
                status=400,
            )
        messages.error(request, "Cannot activate a deleted version.")
        return redirect("model_versions", model_id=version.upload.id)

    if version.status != "PASS":
        status_msg = (
            "pending validation"
            if version.status == "PENDING"
            else "that failed validation"
        )
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "success": False,
                    "error": f"Cannot activate a version that is {status_msg}.",
                },
                status=400,
            )
        messages.error(
            request,
            f"Cannot activate a version that is {status_msg}. Please wait for validation to complete or upload a new version.",
        )
        return redirect("model_versions", model_id=version.upload.id)

    # deactivate all versions of this model, then activate this one
    ModelVersion.objects.filter(upload=version.upload).update(is_active=False)
    version.is_active = True
    version.save()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {"success": True, "message": f"Version '{version.tag}' is now active."}
        )

    messages.success(
        request,
        f"Version '{version.tag}' is now active. Other versions have been deactivated.",
    )
    return redirect("model_versions", model_id=version.upload.id)


@login_required
def deprecate_version(request, version_id):
    version = get_object_or_404(ModelVersion, id=version_id)
    if request.user != version.upload.user and not request.user.is_staff:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Permission denied"}, status=403
            )
        messages.error(request, "You don't have permission to deprecate this version.")
        return redirect("dashboard")

    if version.is_deleted:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Cannot deprecate deleted version"},
                status=400,
            )
        messages.error(request, "Cannot deprecate a deleted version.")
        return redirect("dashboard")

    if request.method == "POST":
        version.is_active = False
        version.save()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "success": True,
                    "message": f'Version with tag "{version.tag}" has been deprecated (deactivated)',
                    "version_id": version.id,
                }
            )
        messages.success(
            request, f"Version with tag '{version.tag}' has been deprecated."
        )
        return redirect(f"/model-versions/{version.upload.id}/")

    return redirect("dashboard")


# ---------------------------------------------------------
# DELETE MODEL
# ---------------------------------------------------------
@login_required
def delete_model(request, model_id):
    model_upload = get_object_or_404(ModelUpload, id=model_id)

    if request.user != model_upload.user and not request.user.is_staff:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Permission denied"}, status=403
            )
        messages.error(request, "You don't have permission to delete this model.")
        return redirect("dashboard")

    # only count non-deleted versions
    remaining = ModelVersion.objects.filter(
        upload=model_upload, is_deleted=False
    ).count()

    if remaining > 0:
        msg = f"Cannot delete model with {remaining} active versions. Please delete all versions first."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": msg}, status=400)
        messages.error(request, msg)
        return redirect("dashboard")

    if request.method == "POST":
        model_name = model_upload.name
        delete_model_media_tree(model_upload)
        model_upload.delete()

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "success": True,
                    "message": f'Model "{model_name}" has been permanently deleted.',
                }
            )
        messages.success(request, f'Model "{model_name}" has been permanently deleted.')
        return redirect("dashboard")

    return redirect("dashboard")


# ---------------------------------------------------------
# MODEL VERSIONS PAGE
# ---------------------------------------------------------
@login_required
def model_versions(request, model_id):
    model_upload = get_object_or_404(ModelUpload, pk=model_id, user=request.user)
    versions = model_upload.versions.all().order_by("-created_at")

    context = {
        "model_upload": model_upload,
        "versions": versions,
        "total_count": versions.count(),
        "active_count": versions.filter(
            is_active=True, is_deleted=False, status="PASS"
        ).count(),
        "available_count": versions.filter(is_deleted=False, status="PASS").count(),
        "failed_count": versions.filter(is_deleted=False, status="FAIL").count(),
        "deleted_count": versions.filter(is_deleted=True).count(),
    }
    return render(request, "note2webapp/model_versions.html", context)


# ---------------------------------------------------------
# EDIT VERSION INFORMATION
# ---------------------------------------------------------
class VersionInformationForm(forms.ModelForm):
    class Meta:
        model = ModelVersion
        fields = ["information"]
        widgets = {
            "information": forms.Textarea(
                attrs={
                    "rows": 6,
                    "placeholder": "Enter information about this model version...",
                }
            )
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["information"].required = True
        self.fields["information"].label = "Model Information"


@login_required
def edit_version_information(request, version_id):
    version = get_object_or_404(ModelVersion, id=version_id)
    if version.upload.user != request.user:
        messages.error(request, "You don't have permission to edit this version.")
        return redirect("dashboard")

    if request.method == "POST":
        form = VersionInformationForm(request.POST, instance=version)
        if form.is_valid():
            form.save()
            messages.success(
                request, f"Information for version {version.tag} updated successfully!"
            )
            return redirect("model_versions", model_id=version.upload.id)
    else:
        form = VersionInformationForm(instance=version)

    return render(
        request,
        "note2webapp/edit_version_information.html",
        {"form": form, "version": version},
    )


# ---------------------------------------------------------
# TEST MODEL (CPU)
# ---------------------------------------------------------
@login_required
def test_model_cpu(request, version_id):
    version = get_object_or_404(ModelVersion, id=version_id)

    result = None
    parse_error = None
    last_input = ""

    if request.method == "POST":
        raw_input = request.POST.get("input_data", "").strip()
        last_input = raw_input

        if raw_input:
            try:
                parsed = json.loads(raw_input)

                if isinstance(parsed, list):
                    outputs = []
                    for item in parsed:
                        if not isinstance(item, dict):
                            outputs.append(
                                {
                                    "status": "error",
                                    "error": 'Each item in the list must be a JSON object like {"text": "..."}',
                                }
                            )
                        else:
                            outputs.append(test_model_on_cpu(version, item))
                    result = {"status": "ok", "batch": True, "outputs": outputs}

                elif isinstance(parsed, dict):
                    result = test_model_on_cpu(version, parsed)

                else:
                    parse_error = (
                        "Top-level JSON must be either an object {...} or a list [...]."
                    )
                # Increment usage counter every time it's tested
                version.usage_count = models.F("usage_count") + 1
                version.save(update_fields=["usage_count"])
                version.refresh_from_db()

            except json.JSONDecodeError as e:
                raw_msg = str(e)
                stripped = raw_input.lstrip()
                friendly = raw_msg

                if raw_msg.startswith("Extra data"):
                    friendly = (
                        "Your JSON has extra data. Did you forget to wrap it in { ... } ? "
                        'Example: {"text": "Party"}'
                    )
                elif raw_msg.startswith(
                    "Expecting property name enclosed in double quotes"
                ):
                    friendly = 'Invalid JSON: Property names must be in double quotes. Example: {"text": "Hello"}'
                elif raw_msg.startswith("Expecting value") and stripped.startswith("{"):
                    friendly = 'Invalid JSON: String values must be in double quotes. Example: {"text": "Hello"}'
                elif (
                    raw_msg.startswith("Expecting value")
                    and not stripped.startswith("{")
                    and not stripped.startswith("[")
                ):
                    friendly = (
                        "JSON must start with { ... } (object) or [ ... ] (list). "
                        'Example: {"text": "Hello"}'
                    )
                elif raw_msg.startswith("Unterminated string starting at"):
                    friendly = "You have an opening quote without a closing quote."
                elif raw_msg.startswith("Expecting ',' delimiter"):
                    friendly = "You may be missing a comma between fields."

                parse_error = friendly

    # Get comments for this version
    comments = ModelComment.objects.filter(
        model_version=version, parent=None
    ).prefetch_related(
        "replies",
        "replies__user__profile",
        "replies__reactions",
        "user__profile",
        "reactions",
    )

    # Check if user is uploader
    is_uploader = version.upload.user == request.user

    # Get user reactions for all comments and replies
    comment_ids = [c.id for c in comments]
    for comment in comments:
        comment_ids.extend([r.id for r in comment.replies.all()])

    user_reactions = {}
    if comment_ids:
        reactions = CommentReaction.objects.filter(
            comment_id__in=comment_ids, user=request.user
        )
        for reaction in reactions:
            user_reactions[reaction.comment_id] = reaction.reaction_type

    # Add UTC timestamps to version and comments/replies for JavaScript conversion
    # Version uploaded timestamp
    if timezone.is_aware(version.created_at):
        version.created_at_utc = version.created_at.isoformat()
    else:
        version.created_at_utc = timezone.make_aware(
            version.created_at, timezone.utc
        ).isoformat()

    # Comments and replies timestamps
    for comment in comments:
        # Ensure timezone-aware datetime
        if timezone.is_aware(comment.created_at):
            comment.created_at_utc = comment.created_at.isoformat()
        else:
            # If naive, assume UTC
            comment.created_at_utc = timezone.make_aware(
                comment.created_at, timezone.utc
            ).isoformat()

        for reply in comment.replies.all():
            if timezone.is_aware(reply.created_at):
                reply.created_at_utc = reply.created_at.isoformat()
            else:
                reply.created_at_utc = timezone.make_aware(
                    reply.created_at, timezone.utc
                ).isoformat()

    return render(
        request,
        "note2webapp/test_model.html",
        {
            "version": version,
            "result": result,
            "last_input": last_input,
            "parse_error": parse_error,
            "comments": comments,
            "is_uploader": is_uploader,
            "user_reactions": json.dumps(user_reactions),
        },
    )


# ---------------------------------------------------------
# SIMPLE API HOOKS
# ---------------------------------------------------------
@login_required
def run_model_from_path(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    model_path = request.POST.get("model_path")
    predict_path = request.POST.get("predict_path")
    raw_input = request.POST.get("input_data", "{}")

    try:
        input_data = json.loads(raw_input)
    except Exception:
        return JsonResponse({"error": "Invalid JSON in input_data"}, status=400)

    spec = importlib.util.spec_from_file_location("predict_module", predict_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "predict"):
        return JsonResponse({"error": "predict() not found in predict.py"}, status=400)

    sig = inspect.signature(module.predict)
    num_params = len(sig.parameters)
    if num_params == 1:
        out = module.predict(input_data)
    else:
        out = module.predict(model_path, input_data)

    return JsonResponse({"output": out})


@login_required
def run_model_by_version_id(request, version_id):
    version = get_object_or_404(ModelVersion, id=version_id)

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    raw_input = request.POST.get("input_data", "{}")
    try:
        input_data = json.loads(raw_input)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    result = test_model_on_cpu(version, input_data)
    return JsonResponse(result)


# ---------------------------------------------------------
# AI-ASSISTED MODEL INFO (ChatGPT integration)
# ---------------------------------------------------------
@login_required
@csrf_exempt
@require_POST
def generate_model_info(request):
    """
    Generate a 'Model Information' text using ONLY the three artifacts:
      - model_file (.pt)
      - predict_file (.py)
      - schema_file (.json)

    Modes:
      1) New upload (Add Version form)
         - uses request.FILES['model_file'], ['predict_file'], ['schema_file']
      2) Existing version (comments/detail screen)
         - POST includes 'version_id'; reads files from ModelVersion fields
    """

    # 1. OpenAI client
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        return JsonResponse(
            {"error": "Server is missing OPENAI_API_KEY configuration."},
            status=500,
        )

    client = OpenAI(api_key=api_key)

    # 2. Collect artifacts (two modes)
    model_summary = ""
    predict_source = ""
    schema_text = ""

    version_id = request.POST.get("version_id")

    # ---------- Mode A: existing version (from DB) ----------
    if version_id:
        version = ModelVersion.objects.filter(id=version_id).first()
        if not version:
            return JsonResponse({"error": "Model version not found."}, status=404)

        model_path = version.model_file.path if version.model_file else None
        predict_path = version.predict_file.path if version.predict_file else None
        schema_path = version.schema_file.path if version.schema_file else None

        if not (model_path and predict_path and schema_path):
            return JsonResponse(
                {
                    "error": (
                        "This version is missing one or more artifacts. "
                        "Please re-upload the model, predict.py, and schema.json."
                    )
                },
                status=400,
            )

        # model.pt -> summarize (don't pass binary to the model)
        try:
            size_mb = os.path.getsize(model_path) / (1024 * 1024)
            model_summary = (
                f"PyTorch model weights file '{os.path.basename(model_path)}', "
                f"approx. {size_mb:.2f} MB."
            )
        except OSError:
            model_summary = "PyTorch model weights file (size unknown)."

        # predict.py (truncated)
        try:
            with open(predict_path, "r", encoding="utf-8", errors="ignore") as f:
                predict_source = f.read(4000)
        except OSError:
            predict_source = ""

        # schema.json (truncated)
        try:
            with open(schema_path, "r", encoding="utf-8", errors="ignore") as f:
                schema_text = f.read(4000)
        except OSError:
            schema_text = ""

    # ---------- Mode B: Add Version form (new upload, from request.FILES) ----------
    else:
        # These are the field names on VersionForm/ModelVersion.
        # The actual filenames are model.pt, predict.py, schema.json – that's fine.
        model_file = request.FILES.get("model_file")
        predict_file = request.FILES.get("predict_file")
        schema_file = request.FILES.get("schema_file")

        if not (model_file and predict_file and schema_file):
            return JsonResponse(
                {
                    "error": (
                        "Could not find all required files. Please make sure you "
                        "have uploaded a .pt, a .py, and a .json file."
                    )
                },
                status=400,
            )

        # model.pt summary (size only)
        try:
            size_mb = model_file.size / (1024 * 1024)
        except Exception:
            size_mb = 0.0
        model_summary = f"PyTorch model file '{model_file.name}' (~{size_mb:.2f} MB)."

        # predict.py content (truncate and rewind so upload still works)
        try:
            predict_bytes = predict_file.read()
            predict_source = predict_bytes.decode("utf-8", errors="ignore")[:4000]
            predict_file.seek(0)
        except Exception:
            predict_source = ""

        # schema.json content (truncate and rewind)
        try:
            schema_bytes = schema_file.read()
            schema_text = schema_bytes.decode("utf-8", errors="ignore")[:4000]
            schema_file.seek(0)
        except Exception:
            schema_text = ""

    # Fallbacks if we couldn't read something
    if not predict_source:
        predict_source = "No usable predict.py content could be read."
    if not schema_text:
        schema_text = "No usable schema.json content could be read."

    # 3. Build prompt for OpenAI
    system_prompt = (
        "You are an ML engineer who writes concise release notes for model versions. "
        "Write for engineers and product managers. Avoid lists; use 3–6 plain sentences."
    )

    user_prompt = f"""You are given information about a model version from three artifacts.

PyTorch model summary:
{model_summary}

predict.py (truncated):
```python
{predict_source}
```

schema.json (truncated):
```json
{schema_text}
```

Using only this information, write a description suitable for a Model Information field in a deployment dashboard.

Explain:
- What the model does and the type of task it solves.
- The kinds of inputs/outputs you can infer from the schema.
- Any important assumptions, limitations, or warnings (e.g. domain coverage, language, bias, need for monitoring).

Write 3–6 sentences of neutral, professional prose.
Do NOT include headings or bullet points.
"""

    # 4. Call OpenAI
    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=300,
        )
        description = completion.choices[0].message.content.strip()
        return JsonResponse({"description": description})

    except Exception as e:
        # Log error to server console for debugging
        print("Error from OpenAI in generate_model_info:", repr(e))
        return JsonResponse(
            {
                "error": (
                    "Network or server issue while generating description. "
                    "Please try again or write it manually."
                )
            },
            status=500,
        )


# ---------------------------------------------------------
# ADMIN STATS VIEW  ( /admin/stats/ )
# ---------------------------------------------------------
@staff_member_required
def admin_stats(request):
    # top counts
    total_uploads = ModelUpload.objects.count()
    total_versions = ModelVersion.objects.count()
    total_users = User.objects.count()

    # version breakdown
    active_versions = ModelVersion.objects.filter(
        is_deleted=False, is_active=True, status="PASS"
    ).count()
    deleted_versions = ModelVersion.objects.filter(is_deleted=True).count()
    inactive_versions = ModelVersion.objects.filter(
        is_deleted=False, status="PASS", is_active=False
    ).count()

    # superusers shown as admin in the pie chart
    superusers_count = User.objects.filter(is_superuser=True).count()

    # roles for non-superusers
    role_rows = list(
        Profile.objects.filter(user__is_superuser=False)
        .values("role")
        .annotate(c=Count("id"))
        .order_by("role")
    )

    # users without profile (non-superuser)
    no_profile_count = User.objects.filter(
        profile__isnull=True, is_superuser=False
    ).count()
    if no_profile_count:
        role_rows.append({"role": "no-profile", "c": no_profile_count})

    # add admin bucket
    if superusers_count:
        role_rows.append({"role": "admin", "c": superusers_count})

    # versions by status
    status_rows = list(
        ModelVersion.objects.values("status").annotate(c=Count("id")).order_by("status")
    )

    # versions by category
    category_rows = list(
        ModelVersion.objects.values("category")
        .annotate(c=Count("id"))
        .order_by("category")
    )

    # top uploaders
    top_uploaders = list(
        ModelUpload.objects.values("user__username")
        .annotate(c=Count("id"))
        .order_by("-c")[:10]
    )

    context = {
        "total_uploads": total_uploads,
        "total_versions": total_versions,
        "total_users": total_users,
        "active_versions": active_versions,
        "deleted_versions": deleted_versions,
        "inactive_versions": inactive_versions,
        "role_counts_json": json.dumps(role_rows),
        "version_status_counts_json": json.dumps(status_rows),
        "version_category_counts_json": json.dumps(category_rows),
        "top_uploaders_json": json.dumps(top_uploaders),
        "top_uploaders": top_uploaders,
    }
    return render(request, "note2webapp/admin_stats.html", context)


# ---------------------------------------------------------
# MODEL COMMENTS VIEW
# ---------------------------------------------------------
@login_required
def model_comments_view(request, version_id):
    """
    Display comments thread for a specific model version.
    Includes:
    - Parent comments and their replies
    - User reaction state (like/dislike)
    - Author badges and role indicators
    - Back button with return_to parameter support
    """
    version = get_object_or_404(ModelVersion, id=version_id)

    comments = (
        ModelComment.objects.filter(model_version=version, parent__isnull=True)
        .select_related("user__profile")
        .prefetch_related("replies__user__profile", "reactions")
    )

    # map: comment_id → 'like' or 'dislike' for the current user
    if request.user.is_authenticated:
        reactions = CommentReaction.objects.filter(
            user=request.user,
            comment__model_version=version,
        )
        user_reactions = {r.comment_id: r.reaction_type for r in reactions}
    else:
        user_reactions = {}

    # Back button target:
    # Constructs proper URL based on user role and return_to parameter
    default_back = reverse("test_model_cpu", args=[version.id])
    return_to_param = request.GET.get("return_to")
    model_id = request.GET.get("model_id", version.upload.id)

    # Build proper back URL based on return_to parameter
    if return_to_param == "reviewer":
        # Go to reviewer dashboard with detail page
        return_to = f"{reverse('reviewer_dashboard')}?page=detail&pk={model_id}"
    elif return_to_param == "uploader":
        # Go to uploader version management
        return_to = reverse("model_versions", args=[model_id])
    elif return_to_param == "dashboard":
        # Go to general dashboard
        return_to = f"{reverse('dashboard')}?page=detail&pk={model_id}"
    elif return_to_param and return_to_param.startswith("/"):
        # Custom URL path
        return_to = return_to_param
    else:
        # Default to test model page
        return_to = default_back

    context = {
        "version": version,
        "comments": comments,
        "user_reactions": user_reactions,
        "is_uploader": request.user.is_authenticated
        and request.user == version.upload.user,
        "back_url": return_to,
    }
    return render(request, "note2webapp/model_comments.html", context)


# ---------------------------------------------------------
# TOGGLE COMMENT REACTION (LIKE/DISLIKE)
# ---------------------------------------------------------
@login_required
@require_POST
def toggle_comment_reaction(request, comment_id):
    """
    Toggle a user's reaction (like/dislike) on a comment or reply.

    Returns:
    - 400 if user tries to react to their own comment
    - 400 if reaction_type is invalid
    - 200 with success=True if reaction was toggled/deleted

    Response includes:
    - likes_count: current like count
    - dislikes_count: current dislike count
    - user_reaction: 'like', 'dislike', or None
    """
    comment = get_object_or_404(ModelComment, id=comment_id)

    # 🔒 Block reacting to your own comment (uploader OR reviewer)
    # This is enforced on frontend AND backend for security
    if comment.user_id == request.user.id:
        return JsonResponse(
            {
                "success": False,
                "error": "You can't like or dislike your own comment.",
                "likes_count": comment.get_likes_count(),
                "dislikes_count": comment.get_dislikes_count(),
                "user_reaction": None,
            },
            status=400,
        )

    reaction_type = request.POST.get("reaction_type")
    if reaction_type not in ("like", "dislike"):
        return JsonResponse(
            {"success": False, "error": "Invalid reaction type."}, status=400
        )

    # Toggle / switch the reaction
    # If the user already has this reaction, delete it.
    # If they have a different reaction, replace it.
    # If they have no reaction, create it.
    reaction, created = CommentReaction.objects.get_or_create(
        user=request.user,
        comment=comment,
        defaults={"reaction_type": reaction_type},
    )

    if not created:
        if reaction.reaction_type == reaction_type:
            # same reaction again → remove it (toggle off)
            reaction.delete()
        else:
            # switch like ↔ dislike
            reaction.reaction_type = reaction_type
            reaction.save()

    likes = comment.get_likes_count()
    dislikes = comment.get_dislikes_count()

    # this user's current reaction (if any)
    try:
        current = CommentReaction.objects.get(user=request.user, comment=comment)
        user_reaction = current.reaction_type
    except CommentReaction.DoesNotExist:
        user_reaction = None

    return JsonResponse(
        {
            "success": True,
            "likes_count": likes,
            "dislikes_count": dislikes,
            "user_reaction": user_reaction,
        }
    )
