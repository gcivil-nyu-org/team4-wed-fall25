import importlib.util
import json
import os
from django.conf import settings

ALLOWED_CATEGORIES = {
    "sentiment",
    "recommendation",
    "text-classification",
}


def get_model_version_dir(category: str, model_name: str, version: str) -> str:
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"Unknown category: {category}")
    return os.path.join(settings.MEDIA_ROOT, category, model_name, version)


def load_schema(category: str, model_name: str, version: str):
    model_dir = get_model_version_dir(category, model_name, version)
    schema_path = os.path.join(model_dir, "schema.json")
    with open(schema_path, "r") as f:
        return json.load(f)


def load_predict_module(category: str, model_name: str, version: str):
    model_dir = get_model_version_dir(category, model_name, version)
    predict_path = os.path.join(model_dir, "predict.py")
    spec = importlib.util.spec_from_file_location("predict_module", predict_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, model_dir
