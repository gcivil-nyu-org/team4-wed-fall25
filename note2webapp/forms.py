# note2webapp/forms.py
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
    information = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "Enter information about this model version...",
            }
        ),
        required=True,
        label="Model Information",
        help_text="Required: Add relevant information about this version",
    )

    class Meta:
        model = ModelVersion
        fields = [
            "model_file",
            "predict_file",
            "schema_file",
            "tag",
            "category",
            "information",
        ]
        widgets = {
            "model_file": forms.FileInput(attrs={"required": False}),
            "predict_file": forms.FileInput(attrs={"required": False}),
            "schema_file": forms.FileInput(attrs={"required": False}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # enforce the 3 categories you decided
        self.fields["category"].choices = [
            ("sentiment", "Sentiment"),
            ("recommendation", "Recommendation"),
            ("text-classification", "Text Classification"),
        ]
        if not self.initial.get("category"):
            self.fields["category"].initial = "sentiment"

        # we’ll do backend checks, so keep these False here
        self.fields["model_file"].required = False
        self.fields["predict_file"].required = False
        self.fields["schema_file"].required = False

        self.fields["model_file"].help_text = "Required: Upload your .pt model file"
        self.fields["predict_file"].help_text = "Required: Upload your .py prediction script"
        self.fields["schema_file"].help_text = "Required: Upload your .json schema file"

    def clean(self):
        cleaned_data = super().clean()
        model_file = cleaned_data.get("model_file")
        predict_file = cleaned_data.get("predict_file")
        schema_file = cleaned_data.get("schema_file")
        information = cleaned_data.get("information")

        if not model_file:
            raise forms.ValidationError("Model file (.pt) is required")
        if not predict_file:
            raise forms.ValidationError("Predict file (.py) is required")
        if not schema_file:
            raise forms.ValidationError("Schema file (.json) is required")
        if not information or not information.strip():
            raise forms.ValidationError("Model Information is required")

        return cleaned_data

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
