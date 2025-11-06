# note2webapp/views.py
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
from django.utils import timezone
from django import forms

from .forms import UploadForm, VersionForm
from .models import ModelUpload, ModelVersion, Profile
from .utils import (
    validate_model,
    test_model_on_cpu,
    sha256_uploaded_file,
    sha256_file_path,
    delete_version_files_and_dir,
    delete_model_media_tree,
)


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
            user = User.objects.create_user(username=username, password=password1)
            Profile.objects.create(user=user, role="uploader")
            group, _ = Group.objects.get_or_create(name="ModelUploader")
            user.groups.add(group)
            messages.success(request, "Account created successfully! Please login.")
            return redirect("login")
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
    role = getattr(request.user.profile, "role", "uploader")
    if role == "uploader":
        return model_uploader_dashboard(request)
    elif role == "reviewer":
        return reviewer_dashboard(request)
    return render(request, "note2webapp/other_dashboard.html")


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
                        "retry_version_id": retry_version_id if retry_version_id else None,
                        "page": "add_version",
                        "pk": pk,
                    }
                )
                return render(request, "note2webapp/home.html", context)

            form = VersionForm(request.POST, request.FILES)
            if form.is_valid():
                # 1. Hash incoming files
                incoming_model_hash = sha256_uploaded_file(
                    request.FILES["model_file"]
                )
                incoming_predict_hash = sha256_uploaded_file(
                    request.FILES["predict_file"]
                )
                incoming_schema_hash = sha256_uploaded_file(
                    request.FILES["schema_file"]
                )

                # 2. Compare to every non-deleted version’s stored files
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
                        # if any file is missing, just skip that version
                        continue

                if duplicate_found:
                    # we set both a Django message and a context flag
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
@login_required
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
            return JsonResponse({"success": False, "error": "Permission denied"}, status=403)
        messages.error(request, "You don't have permission to delete this version.")
        return redirect("dashboard")

    # if it's active and there are other versions -> block
    if version.is_active:
        other_versions = (
            ModelVersion.objects.filter(upload=version.upload, is_deleted=False)
            .exclude(id=version_id)
        )
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
            "pending validation" if version.status == "PENDING" else "that failed validation"
        )
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": f"Cannot activate a version that is {status_msg}."},
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
            return JsonResponse({"success": False, "error": "Permission denied"}, status=403)
        messages.error(request, "You don't have permission to deprecate this version.")
        return redirect("dashboard")

    if version.is_deleted:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "Cannot deprecate deleted version"}, status=400)
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
            return JsonResponse({"success": False, "error": "Permission denied"}, status=403)
        messages.error(request, "You don't have permission to delete this model.")
        return redirect("dashboard")

    # only count non-deleted versions
    remaining = ModelVersion.objects.filter(upload=model_upload, is_deleted=False).count()

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
                {"success": True, "message": f'Model "{model_name}" has been permanently deleted.'}
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
        "active_count": versions.filter(is_active=True, is_deleted=False, status="PASS").count(),
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
                attrs={"rows": 6, "placeholder": "Enter information about this model version..."}
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
    """
    Show test UI and let user run inference on a version.
    Keeps textarea content after POST.
    Supports:
      - single object: {"text": "..."}
      - list of objects: [{"text": "..."}, {"text": "..."}]
    """
    version = get_object_or_404(ModelVersion, id=version_id)

    # try to prefill from schema
    schema_json = None
    if version.schema_file:
        try:
            with open(version.schema_file.path, "r") as f:
                schema_json = json.load(f)
        except Exception:
            schema_json = None

    result = None
    parse_error = None

    # default textarea content
    if schema_json and isinstance(schema_json, dict):
        if "input" in schema_json and isinstance(schema_json["input"], dict):
            last_input = json.dumps(schema_json["input"], indent=2)
        else:
            last_input = json.dumps(schema_json, indent=2)
    else:
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
                                    "error": "Each item in the list must be a JSON object",
                                }
                            )
                        else:
                            outputs.append(test_model_on_cpu(version, item))
                    result = {
                        "status": "ok",
                        "batch": True,
                        "outputs": outputs,
                    }
                elif isinstance(parsed, dict):
                    result = test_model_on_cpu(version, parsed)
                else:
                    parse_error = "Top-level JSON must be an object or a list of objects."
            except json.JSONDecodeError as e:
                parse_error = f"Invalid JSON: {str(e)}"

    return render(
        request,
        "note2webapp/test_model.html",
        {
            "version": version,
            "schema_json": schema_json,
            "result": result,
            "last_input": last_input,
            "parse_error": parse_error,
        },
    )


# ---------------------------------------------------------
# SIMPLE API HOOKS
# ---------------------------------------------------------
@login_required
def run_model_from_path(request):
    """
    Very small endpoint: POST model_path, predict_path, input_data
    and we'll load predict.py dynamically and run it.
    """
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
    """
    POST input_data, look up version, run test_model_on_cpu
    """
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
