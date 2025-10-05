from django import forms
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
        fields = ["model_file", "predict_file", "tag", "category"]

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

    def clean_tag(self):
        tag = self.cleaned_data.get("tag")
        if not tag:
            raise forms.ValidationError("Tag is required")
        return tag
