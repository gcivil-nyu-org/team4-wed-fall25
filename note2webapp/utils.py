import importlib.util
import traceback
import json
import os

TYPE_MAP = {"float": float, "int": int, "str": str, "bool": bool}


def generate_dummy_input(schema_path):
    with open(schema_path, "r") as f:
        schema = json.load(f)

    input_schema = schema.get("input", {})
    dummy = {}
    for key, typ in input_schema.items():
        py_type = TYPE_MAP.get(typ)
        if py_type == float:
            dummy[key] = 1.0
        elif py_type == int:
            dummy[key] = 42
        elif py_type == str:
            dummy[key] = "example"
        elif py_type == bool:
            dummy[key] = True
        else:
            raise ValueError(f"Unsupported type: {typ}")
    return dummy, schema.get("output", {})


def validate_model(version):
    try:
        # 🔁 Change to directory containing model.pt
        model_dir = os.path.dirname(version.model_file.path)
        os.chdir(model_dir)

        # ✅ Dynamically import predict.py
        spec = importlib.util.spec_from_file_location(
            "predict", version.predict_file.path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "predict"):
            raise Exception("predict() function missing in predict.py")

        # Load schema + generate dummy input
        if not version.schema_file:
            raise Exception("No schema file provided")
        dummy_input, expected_output = generate_dummy_input(version.schema_file.path)

        # Call predict with ONLY dummy input
        output = module.predict(dummy_input)

        # Validate output
        if not isinstance(output, dict):
            raise Exception("predict() must return a dict")

        for key, typ in expected_output.items():
            if key not in output:
                raise Exception(f"Missing key in output: {key}")
            if not isinstance(output[key], TYPE_MAP.get(typ)):
                raise Exception(
                    f"Wrong type for '{key}': expected {typ}, got {type(output[key]).__name__}"
                )

        version.status = "PASS"
        version.log = f"Validation successful ✅\nInput: {json.dumps(dummy_input)}\nOutput: {json.dumps(output, indent=2)}"

    except Exception:
        version.status = "FAIL"
        version.log = traceback.format_exc()

    version.save()
    return version
