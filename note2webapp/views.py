from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.shortcuts import render, redirect, get_object_or_404
from .forms import UploadForm, VersionForm
from .models import ModelUpload, ModelVersion
from .utils import validate_model


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
        return model_uploader_dashboard(request)   # goes to home.html
    elif role == "reviewer":
        return reviewer_dashboard(request)
    else:
        return render(request, "note2webapp/other_dashboard.html")


# -------------------
# MODEL UPLOADER DASHBOARD
# -------------------
@login_required
def model_uploader_dashboard(request):
    page = request.GET.get("page", "list")
    pk = request.GET.get("pk")

    # 👇 only show this uploader’s models
    uploads = ModelUpload.objects.filter(user=request.user).order_by("-created_at")

    context = {"uploads": uploads, "page": page}

    # Create new upload
    if page == "create":
        if request.method == "POST":
            form = UploadForm(request.POST)
            if form.is_valid():
                upload = form.save(commit=False)
                upload.user = request.user  # 👈 assign uploader
                upload.save()
                return redirect(f"/dashboard/?page=detail&pk={upload.pk}")
        else:
            form = UploadForm()
        context["form"] = form

    # Upload details + versions
    elif page == "detail" and pk:
        upload = get_object_or_404(ModelUpload, pk=pk, user=request.user) 
        versions = upload.versions.all().order_by("-created_at")
        context["upload"] = upload
        context["versions"] = versions

    # Add version
    elif page == "add_version" and pk:
        upload = get_object_or_404(ModelUpload, pk=pk, user=request.user)
        if request.method == "POST":
            form = VersionForm(request.POST, request.FILES)
            if form.is_valid():
                version = form.save(commit=False)
                version.upload = upload
                version.save()
                validate_model(version)
                return redirect(f"/dashboard/?page=detail&pk={upload.pk}")
        else:
            form = VersionForm()
        context["form"] = form
        context["upload"] = upload

    return render(request, "note2webapp/home.html", context)



# -------------------
# REVIEWER DASHBOARD
# -------------------
@login_required
def reviewer_dashboard(request):
    """Simple placeholder for now, will expand later"""
    versions = ModelVersion.objects.all().order_by("-created_at")
    return render(request, "note2webapp/reviewer_dashboard.html", {"versions": versions})
