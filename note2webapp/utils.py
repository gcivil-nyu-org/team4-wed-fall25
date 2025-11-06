# note2webapp/utils.py
import os
import json
import shutil
import hashlib
import traceback
import importlib.util
import inspect

import torch
from django.conf import settings

# primitive types we can strictly validate for "custom" schemas
TYPE_MAP = {"float": float, "int": int, "str": str, "bool": bool}


# ---------------------------------------------------------------------
# 1. HASHING + MATERIALIZING + DELETING DIRECTORIES
# ---------------------------------------------------------------------
def sha256_uploaded_file(django_file):
    """
    Compute sha256 for an uploaded file (InMemory/Temporary) by streaming chunks.
    Used in views to detect duplicate uploads.
    """
    h = hashlib.sha256()
    for chunk in django_file.chunks():
        h.update(chunk)
    return h.hexdigest()


def sha256_file_path(path):
    """
    Same as above but for an existing file on disk.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def materialize_version_to_media(version):
    """
    After a version PASSes validation, copy its files into:
      media/<category>/<model-name>/v<version_number>/
    with consistent filenames.
    """
    target_dir = os.path.join(
        settings.MEDIA_ROOT,
        version.category,
        version.upload.name,
        f"v{version.version_number}",
    )
    os.makedirs(target_dir, exist_ok=True)

    # model.pt
    if version.model_file and os.path.isfile(version.model_file.path):
        shutil.copy(version.model_file.path, os.path.join(target_dir, "model.pt"))

    # predict.py
    if version.predict_file and os.path.isfile(version.predict_file.path):
        shutil.copy(version.predict_file.path, os.path.join(target_dir, "predict.py"))

    # schema.json
    if version.schema_file and os.path.isfile(version.schema_file.path):
        shutil.copy(version.schema_file.path, os.path.join(target_dir, "schema.json"))


def delete_version_files_and_dir(version):
    """
    Delete the uploaded files (the ones stored by FileField)
    AND the materialized media/<category>/<model-name>/vX/ folder for this version.
    """
    # 1) delete uploaded files
    for f in [version.model_file, version.predict_file, version.schema_file]:
        if f and getattr(f, "path", None):
            try:
                if os.path.isfile(f.path):
                    os.remove(f.path)
            except Exception:
                # don't crash deletion
                pass

    # 2) delete materialized dir
    version_dir = os.path.join(
        settings.MEDIA_ROOT,
        version.category,
        version.upload.name,
        f"v{version.version_number}",
    )
    if os.path.isdir(version_dir):
        try:
            shutil.rmtree(version_dir)
        except Exception:
            pass


def delete_model_media_tree(model_upload):
    """
    Delete the whole dir for this model:
        media/<category>/<model-name>/
    We try known categories and the category of any existing version.
    """
    # try to read category from an existing version
    any_version = model_upload.versions.first()
    possible_categories = []
    if any_version:
        possible_categories.append(any_version.category)

    # also try your 3 fixed categories
    possible_categories.extend(["sentiment", "recommendation", "text-classification"])

    for cat in possible_categories:
        candidate = os.path.join(settings.MEDIA_ROOT, cat, model_upload.name)
        if os.path.isdir(candidate):
            try:
                shutil.rmtree(candidate)
            except Exception:
                pass


# ---------------------------------------------------------------------
# 2. SCHEMA BUILDERS
# ---------------------------------------------------------------------
def _make_value_from_simple_type(typ: str):
    """Used for the old/custom schema style."""
    if typ == "float":
        return 1.0
    if typ == "int":
        return 42
    if typ == "str":
        return "example"
    if typ == "bool":
        return True
    if typ == "object":
        return {}
    return None


def _build_from_custom_schema(schema: dict):
    """
    Handle schema like:
    {
      "input": { "text": "str", "age": "int" },
      "output": { "prediction": "float" }
    }
    """
    input_schema = schema.get("input", {})
    dummy = {}
    for key, typ in input_schema.items():
        if isinstance(typ, str):
            dummy[key] = _make_value_from_simple_type(typ)
        elif isinstance(typ, dict):
            nested = {}
            for k2, t2 in typ.items():
                if isinstance(t2, str):
                    nested[k2] = _make_value_from_simple_type(t2)
                else:
                    nested[k2] = None
            dummy[key] = nested
        else:
            dummy[key] = None
    return dummy, schema.get("output", {})


def _build_from_json_schema(schema: dict):
    """
    Handle real JSON Schema style:
    {
      "type": "object",
      "required": ["text"],
      "properties": {
        "text": { "type": "string", "example": "This is great!" }
      }
    }
    We:
      - use example if present
      - else fill a reasonable default from "type"
    """
    props = schema.get("properties", {}) or {}
    data = {}
    for name, prop in props.items():
        if not isinstance(prop, dict):
            data[name] = "example"
            continue

        if "example" in prop and prop["example"] is not None:
            data[name] = prop["example"]
            continue

        ptype = prop.get("type")
        if ptype == "string":
            data[name] = "example text"
        elif ptype == "number":
            data[name] = 1.0
        elif ptype == "integer":
            data[name] = 1
        elif ptype == "boolean":
            data[name] = True
        elif ptype == "object":
            data[name] = {}
        elif ptype == "array":
            data[name] = []
        else:
            data[name] = "example"

    return data, None


def generate_input_and_output_schema(schema_path: str):
    """
    Decide which schema style we got and build an input dict from it.
    Returns (input_data: dict, output_schema: dict|None)
    """
    with open(schema_path, "r") as f:
        schema = json.load(f)

    # 1) wrapped format: { "input": {...}, "output": {...} }
    if "input" in schema:
        input_schema = schema["input"]

        # maybe they put JSON Schema INSIDE "input"
        if isinstance(input_schema, dict) and "properties" in input_schema:
            return _build_from_json_schema(input_schema)
        else:
            return _build_from_custom_schema(schema)

    # 2) direct JSON Schema
    if "properties" in schema or schema.get("type") == "object":
        return _build_from_json_schema(schema)

    # 3) fallback
    return {}, None


# ---------------------------------------------------------------------
# 3. MODEL LOADING HELPERS
# ---------------------------------------------------------------------
def _load_model_for_version(module, model_path):
    """
    Best-effort loader for validation.
    1) try torch.load
    2) try user's _load_model(...)
    """
    # 1) try torch.load
    try:
        return torch.load(model_path, map_location="cpu")
    except Exception:
        pass

    # 2) try user's loader
    if hasattr(module, "_load_model") and callable(module._load_model):
        try:
            sig = inspect.signature(module._load_model)
            n = len(sig.parameters)
            if n == 0:
                return module._load_model()
            elif n == 1:
                return module._load_model(model_path)
        except Exception:
            pass

    return None


def _is_seek_error(out):
    """
    Detect that PyTorch "dict has no attribute 'seek'" message.
    """
    return (
        isinstance(out, dict)
        and "error" in out
        and "no attribute 'seek'" in str(out["error"])
    )


# ---------------------------------------------------------------------
# 4. VALIDATION
# ---------------------------------------------------------------------
def validate_model(version):
    """
    1. import version's predict.py
    2. build input from uploaded schema (custom or JSON Schema)
    3. call predict(...) with correct number of args
    4. if PASS: materialize to media/<cat>/<model>/vX/
    5. if FAIL: store traceback
    """
    original_cwd = os.getcwd()
    try:
        model_dir = os.path.dirname(version.model_file.path)
        os.chdir(model_dir)

        # import predict.py
        spec = importlib.util.spec_from_file_location(
            "predict", version.predict_file.path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "predict"):
            raise Exception("predict() function missing in predict.py")

        if not version.schema_file:
            raise Exception("No schema file provided")

        # build input from schema
        input_data, output_schema = generate_input_and_output_schema(
            version.schema_file.path
        )

        # inspect signature
        sig = inspect.signature(module.predict)
        num_params = len(sig.parameters)

        # call predict
        if num_params == 1:
            result = module.predict(input_data)
        elif num_params == 2:
            result = module.predict(version.model_file.path, input_data)
        else:
            raise Exception(
                f"predict() has {num_params} parameters, expected 1 or 2."
            )

        # try to fix common torch.load seek error
        if _is_seek_error(result):
            try:
                if num_params == 1:
                    result = module.predict(version.model_file.path)
                elif num_params == 2:
                    model_obj = _load_model_for_version(
                        module, version.model_file.path
                    )
                    if model_obj is not None:
                        result = module.predict(model_obj, input_data)
            except Exception:
                pass

        if not isinstance(result, dict):
            raise Exception("predict() must return a dict")

        # If result says error, we mark FAIL
        if "error" in result and result.get("prediction") is None:
            raise Exception(f"Prediction error: {result['error']}")

        # Strict output checking only for simple custom schema
        do_strict = (
            isinstance(output_schema, dict)
            and output_schema
            and all(
                isinstance(v, str) and v in TYPE_MAP for v in output_schema.values()
            )
        )
        if do_strict:
            for key, typ in output_schema.items():
                if key not in result:
                    raise Exception(f"Missing key in output: {key}")
                if not isinstance(result[key], TYPE_MAP[typ]):
                    raise Exception(
                        f"Wrong type for '{key}': expected {typ}, got {type(result[key]).__name__}"
                    )

        # success
        version.status = "PASS"
        version.log = (
            "✅ Validation Successful\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "INPUT (from schema):\n"
            f"{json.dumps(input_data, indent=2)}\n\n"
            "OUTPUT (from predict()):\n"
            f"{json.dumps(result, indent=2)}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        # materialize now
        materialize_version_to_media(version)

    except Exception:
        version.status = "FAIL"
        version.log = (
            "❌ Validation Failed\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{traceback.format_exc()}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
    finally:
        os.chdir(original_cwd)

    version.save()
    return version


# ---------------------------------------------------------------------
# 5. TEST MODEL ON CPU (manual testing from UI)
# ---------------------------------------------------------------------
def test_model_on_cpu(version, input_data):
    """
    Called from the test page.
    Handles predict(input) and predict(model_path, input).
    """
    original_cwd = os.getcwd()
    try:
        model_dir = os.path.dirname(version.model_file.path)
        os.chdir(model_dir)

        predict_path = version.predict_file.path
        model_path = version.model_file.path

        spec = importlib.util.spec_from_file_location("predict_module", predict_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "predict"):
            raise Exception("predict() function missing in predict.py")

        sig = inspect.signature(module.predict)
        num_params = len(sig.parameters)

        if num_params == 1:
            output = module.predict(input_data)
        elif num_params == 2:
            output = module.predict(model_path, input_data)
        else:
            raise Exception(f"predict() has {num_params} parameters, expected 1 or 2")

        if _is_seek_error(output):
            if num_params == 1:
                output = module.predict(model_path)
            else:
                model_obj = _load_model_for_version(module, model_path)
                if model_obj:
                    output = module.predict(model_obj, input_data)

        return {"status": "ok", "output": output}

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "trace": traceback.format_exc(),
        }
    finally:
        os.chdir(original_cwd)
