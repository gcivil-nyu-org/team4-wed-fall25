import json, sys, torch, torch.nn.functional as F
import torch.nn as nn

LABELS = ["class_a","class_b","class_c","class_d","class_e"]

class TinyClassifier(nn.Module):
    def __init__(self, in_features=3, num_classes=len(LABELS)):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_features, 32),
            nn.ReLU(),
            nn.Linear(32, num_classes)
        )
    def forward(self, x): return self.net(x)

_model = None
def _load_model():
    global _model
    if _model is None:
        m = TinyClassifier()
        m.load_state_dict(torch.load("model.pt", map_location="cpu"))
        m.eval()
        _model = m
    return _model

def predict(input_data):
    if not isinstance(input_data, list):
        raise ValueError("Expected a list of dicts.")
    X = torch.tensor([[r["f1"], r["f2"], r["f3"]] for r in input_data], dtype=torch.float32)
    model = _load_model()
    with torch.no_grad():
        probs = F.softmax(model(X), dim=-1)
    results = []
    for p in probs:
        top = torch.topk(p, 3)
        results.append({
            "label": LABELS[int(top.indices[0])],
            "top3": [(LABELS[int(i)], float(p[i])) for i in top.indices]
        })
    return results

if __name__ == "__main__":
    payload = json.loads(sys.stdin.read())
    print(json.dumps(predict(payload)))
