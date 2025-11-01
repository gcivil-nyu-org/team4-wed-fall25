from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from .forms import UploadForm, VersionForm
from .models import ModelUpload, ModelVersion
from .utils import validate_model
from .utils import test_model_on_cpu
import os
import json


# -------------------
# SIGNUP
# -------------------
def signup_view(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()

            # By default, add every new user to "ModelUploader"
            group, created = Group.objects.get_or_create(name="ModelUploader")
            user.groups.add(group)

            login(request, user)
            return redirect("dashboard")
    else:
        form = UserCreationForm()
    return render(request, "note2webapp/signup.html", {"form": form})


# -------------------
# LOGIN
# -------------------
def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect("dashboard")
    else:
        form = AuthenticationForm()
    return render(request, "note2webapp/login.html", {"form": form})


# -------------------
# LOGOUT
# -------------------
def logout_view(request):
    logout(request)
    return redirect("login")


# -------------------
# DASHBOARD (Role-based)
# -------------------
@login_required
def dashboard(request):
    """Redirect based on user role"""
    role = getattr(request.user.profile, "role", "uploader")  # fallback uploader
    if role == "uploader":
        return model_uploader_dashboard(request)  # goes to home.html
    elif role == "reviewer":
        return reviewer_dashboard(request)
    else:
        return render(request, "note2webapp/other_dashboard.html")


@login_required
def validation_failed(request, version_id):
    """View for displaying validation failure details"""
    version = get_object_or_404(ModelVersion, id=version_id, upload__user=request.user)
    if version.status != "FAIL":
        return redirect("model_versions", model_id=version.upload.id)

    return render(
        request,
        "note2webapp/validation_failed.html",
        {
            "version": version,
        },
    )


# -------------------
# MODEL UPLOADER DASHBOARD
# -------------------
@login_required
def model_uploader_dashboard(request):
    page = request.GET.get("page", "list")
    pk = request.GET.get("pk")

    # 👇 only show this uploader's models
    uploads = ModelUpload.objects.filter(user=request.user).order_by("-created_at")

    # Add active_versions_count to EVERY upload object (only count PASSing versions)
    for upload in uploads:
        upload.active_versions_count = upload.versions.filter(
            is_deleted=False, status="PASS"
        ).count()

    # ALWAYS add uploads to context first
    context = {"uploads": uploads, "page": page}

    # Create new upload
    if page == "create":
        if request.method == "POST":
            form = UploadForm(request.POST)
            if form.is_valid():
                model_name = form.cleaned_data["name"]

                # Check if model with same name already exists for this user
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

    # Upload details + versions
    elif page == "detail" and pk:
        upload = get_object_or_404(ModelUpload, pk=pk, user=request.user)
        versions = upload.versions.all().order_by("-created_at")

        # Add version status counts
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

    # Add version (or retry failed version)
    elif page == "add_version" and pk:
        upload = get_object_or_404(ModelUpload, pk=pk, user=request.user)
        retry_version_id = request.GET.get("retry")

        if request.method == "POST":
            # Validate all files are present FIRST
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
                # Create form with existing POST data to preserve user input
                form = VersionForm(
                    initial={
                        "tag": request.POST.get("tag", ""),
                        "category": request.POST.get("category", "research"),
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
            # Now validate the form
            form = VersionForm(request.POST, request.FILES)
            if form.is_valid():
                # If retrying, update the existing version
                if retry_version_id:
                    try:
                        version = ModelVersion.objects.get(
                            id=retry_version_id,
                            upload=upload,
                            status="FAIL",
                            is_deleted=False,
                        )
                        # Update the version with new files
                        version.model_file = form.cleaned_data["model_file"]
                        version.predict_file = form.cleaned_data["predict_file"]
                        version.schema_file = form.cleaned_data["schema_file"]
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
                    # Create new version
                    version = form.save(commit=False)
                    version.upload = upload
                    version.save()

                # Run validation in background
                validate_model(version)

                if version.status == "FAIL":
                    return redirect("validation_failed", version_id=version.id)

                if not retry_version_id:
                    messages.success(
                        request, f"Version '{version.tag}' uploaded successfully!"
                    )

                return redirect(f"/dashboard/?page=detail&pk={upload.pk}")
            else:
                # Form validation failed (e.g., invalid tag)
                messages.error(request, "Please correct the errors below.")
        else:
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


# -------------------
# REVIEWER DASHBOARD (multi-mode like uploader)
# -------------------
@login_required
def reviewer_dashboard(request):
    """Unified reviewer dashboard: list, detail, feedback"""
    page = request.GET.get("page", "list")
    pk = request.GET.get("pk")

    context = {"page": page}

    # ---List all uploaded model versions---
    if page == "list":
        versions = ModelVersion.objects.all().order_by("-created_at")
        context["versions"] = versions

    # ---View details of a specific model version---
    elif page == "detail" and pk:
        version = get_object_or_404(ModelVersion, pk=pk)
        context["version"] = version
        # In future, we'll show validation logs, files, predictions, etc.

    # ---Add feedback (integrated, not separate view)---
    elif page == "add_feedback" and pk:
        version = get_object_or_404(ModelVersion, pk=pk)
        if request.method == "POST":
            comment = request.POST.get("comment", "")
            print(f"📝 Feedback for version {version.id}: {comment}")
            # Later, store in DB via Feedback model
            return redirect(f"/dashboard/?page=detail&pk={version.pk}")
        context["version"] = version

    return render(request, "note2webapp/reviewer.html", context)


# -------------------
# VERSION MANAGEMENT
# -------------------
@login_required
def model_versions(request, model_id):
    """View all versions of a model including deleted ones"""
    model_upload = get_object_or_404(ModelUpload, pk=model_id, user=request.user)
    versions = ModelVersion.objects.filter(upload=model_upload).order_by("-created_at")

    # Counts for summary
    total_count = versions.count()
    active_count = versions.filter(
        is_active=True, is_deleted=False, status="PASS"
    ).count()
    available_count = versions.filter(is_deleted=False, status="PASS").count()
    deleted_count = versions.filter(is_deleted=True).count()
    failed_count = versions.filter(is_deleted=False, status="FAIL").count()

    context = {
        "model_upload": model_upload,
        "versions": versions,
        "total_count": total_count,
        "active_count": active_count,
        "available_count": available_count,
        "deleted_count": deleted_count,
        "failed_count": failed_count,
    }
    return render(request, "note2webapp/model_versions.html", context)


@login_required
def soft_delete_version(request, version_id):
    """Soft delete a model version"""
    version = get_object_or_404(ModelVersion, id=version_id)

    # Check permission - only uploader (owner) can delete
    if request.user != version.upload.user and not request.user.is_staff:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Permission denied"}, status=403
            )
        messages.error(request, "You don't have permission to delete this version.")
        return redirect("dashboard")

    # Check if this is the active version
    if version.is_active:
        # Check if there are other non-deleted versions
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
        # Soft delete
        version.is_deleted = True
        version.deleted_at = timezone.now()
        version.is_active = False
        version.save()

        # Delete physical files
        files_to_delete = [
            version.model_file,
            version.predict_file,
            version.schema_file,
        ]

        for file_field in files_to_delete:
            if file_field:
                try:
                    if os.path.isfile(file_field.path):
                        os.remove(file_field.path)
                except Exception as e:
                    print(f"Error deleting file: {e}")

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "success": True,
                    "message": f"Version (Tag: {version.tag}) deleted successfully",
                    "reload": True,  # Add this flag
                }
            )

        messages.success(
            request, f"Version with tag '{version.tag}' has been deleted successfully."
        )
        return redirect(f"/model-versions/{version.upload.id}/")

    return redirect("dashboard")


@login_required
def activate_version(request, version_id):
    """Activate a specific version and deactivate others"""
    version = get_object_or_404(ModelVersion, id=version_id)

    # Check permission
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

    # Don't allow activating deleted versions
    if version.is_deleted:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Cannot activate a deleted version."},
                status=400,
            )
        messages.error(request, "Cannot activate a deleted version.")
        return redirect("model_versions", model_id=version.upload.id)

    # Don't allow activating if validation failed or is pending
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
            f"Cannot activate a version that is {status_msg}. "
            f"Please wait for validation to complete or upload a new version.",
        )
        return redirect("model_versions", model_id=version.upload.id)

    # Set all versions of this model to inactive first
    ModelVersion.objects.filter(upload=version.upload).update(is_active=False)

    # Activate this version
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
def delete_model(request, model_id):
    """Permanently delete a model if it has no non-deleted versions"""
    model_upload = get_object_or_404(ModelUpload, id=model_id)

    # Check permission - only owner or staff
    if request.user != model_upload.user and not request.user.is_staff:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Permission denied"}, status=403
            )
        messages.error(request, "You don't have permission to delete this model.")
        return redirect("dashboard")

    # Check if model has any NON-DELETED versions
    active_version_count = ModelVersion.objects.filter(
        upload=model_upload, is_deleted=False
    ).count()

    if active_version_count > 0:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "success": False,
                    "error": "Cannot delete model with active versions. Please delete all versions first.",
                },
                status=400,
            )
        messages.error(
            request,
            "Cannot delete model with active versions. Please delete all versions first.",
        )
        return redirect("dashboard")

    if request.method == "POST":
        model_name = model_upload.name
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


@login_required
def deprecate_version(request, version_id):
    """Deprecate (deactivate) a version"""
    version = get_object_or_404(ModelVersion, id=version_id)

    # Check permission - only uploader (owner) can deprecate
    if request.user != version.upload.user and not request.user.is_staff:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Permission denied"}, status=403
            )
        messages.error(request, "You don't have permission to deprecate this version.")
        return redirect("dashboard")

    # Check if version is deleted
    if version.is_deleted:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Cannot deprecate deleted version"},
                status=400,
            )
        messages.error(request, "Cannot deprecate a deleted version.")
        return redirect("dashboard")

    if request.method == "POST":
        # Deactivate this version
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


@login_required
def test_model_cpu(request, version_id):
    """
    Allow uploaders and reviewers to test a specific version on CPU.
    """
    version = get_object_or_404(ModelVersion, id=version_id)
    user_role = getattr(request.user.profile, "role", None)
    if user_role not in ["uploader", "reviewer"]:
        return JsonResponse({"error": "Permission denied"}, status=403)

    # Load schema to prefill JSON
    schema_json = None
    if version.schema_file:
        try:
            with open(version.schema_file.path, "r") as f:
                schema_json = json.load(f)
        except Exception as e:
            schema_json = {"error": str(e)}

    result = None
    if request.method == "POST":
        try:
            input_json = json.loads(request.POST.get("input_data", "{}"))
            result = test_model_on_cpu(version, input_json)
        except json.JSONDecodeError:
            result = {"status": "error", "error": "Invalid JSON format"}

    return render(
        request,
        "note2webapp/test_model.html",
        {
            "version": version,
            "schema_json": json.dumps(schema_json, indent=2) if schema_json else None,
            "result": result,
        },
    )
