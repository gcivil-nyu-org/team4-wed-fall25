import importlib.util
import torch
import traceback

def validate_model(version):
    try:
        # Load model file
        model = torch.load(version.model_file.path, map_location="cpu")

        # Import predict.py dynamically
        spec = importlib.util.spec_from_file_location("predict", version.predict_file.path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "predict"):
            raise Exception("predict() function missing in predict.py")

        # Dummy inference
        dummy_input = torch.randn(1, 3, 224, 224)
        _ = module.predict(model, dummy_input)

        version.status = "PASS"
        version.log = "Validation successful"
    except Exception:
        version.status = "FAIL"
        version.log = traceback.format_exc()

    version.save()
    return version
