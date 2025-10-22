# predict.py
import json, sys
import torch
import torch.nn as nn


# Same model definition
class TinyRegressor(nn.Module):
    def __init__(self, in_features=4):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_features, 16), nn.ReLU(), nn.Linear(16, 1)
        )

    def forward(self, x):
        return self.net(x).squeeze(-1)


# Load model once
_model = None


def _load_model():
    global _model
    if _model is None:
        m = TinyRegressor(in_features=4)
        m.load_state_dict(torch.load("model.pt", map_location="cpu"))
        m.eval()
        _model = m
    return _model


def predict(input_data):
    """input_data: {"x1":1, "x2":2, "x3":3, "x4":4}"""
    model = _load_model()
    x = torch.tensor(
        [[input_data["x1"], input_data["x2"], input_data["x3"], input_data["x4"]]],
        dtype=torch.float32,
    )
    with torch.no_grad():
        y = model(x).item()
    return {"prediction": y}


# Allow CLI usage
if __name__ == "__main__":
    payload = json.loads(sys.stdin.read())
    print(json.dumps(predict(payload)))
