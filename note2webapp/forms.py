from django import forms
from django.contrib.auth.models import User
from .models import ModelUpload, ModelVersion


# -------------------------
# Upload Form (for new upload)
# -------------------------
class UploadForm(forms.ModelForm):
    class Meta:
        model = ModelUpload
        fields = ["name"]


# -------------------------
# Version Form (for new version)
# -------------------------
class VersionForm(forms.ModelForm):
    class Meta:
        model = ModelVersion
        fields = ["model_file", "predict_file", "schema_file", "tag", "category"]

    def clean_model_file(self):
        file = self.cleaned_data.get("model_file")
        if file and not file.name.endswith(".pt"):
            raise forms.ValidationError("Only .pt files are allowed for Model File")
        return file

    def clean_predict_file(self):
        file = self.cleaned_data.get("predict_file")
        if file and not file.name.endswith(".py"):
            raise forms.ValidationError("Only .py files are allowed for Predict File")
        return file

    def clean_schema_file(self):
        file = self.cleaned_data.get("schema_file")
        if file and not file.name.endswith(".json"):
            raise forms.ValidationError("Only .json files allowed for schema")
        return file

    def clean_tag(self):
        tag = self.cleaned_data.get("tag")
        if not tag:
            raise forms.ValidationError("Tag is required")
        return tag


class SignupForm(forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm Password", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["username", "email"]

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return p2

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user
