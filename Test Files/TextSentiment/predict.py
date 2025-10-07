import json, sys, re, torch, torch.nn.functional as F
import torch.nn as nn

VOCAB_SIZE = 1000
LABELS = ["negative", "positive"]

class BoWSentiment(nn.Module):
    def __init__(self, vocab_size=VOCAB_SIZE, num_classes=2):
        super().__init__()
        self.linear = nn.Linear(vocab_size, num_classes)
    def forward(self, bow): return self.linear(bow)

def _tokenize(s):
    return re.findall(r"[a-zA-Z']+", s.lower())

def _bow_vector(tokens):
    v = torch.zeros(VOCAB_SIZE, dtype=torch.float32)
    for t in tokens:
        idx = hash(t) % VOCAB_SIZE
        v[idx] += 1
    return v

_model = None
def _load_model():
    global _model
    if _model is None:
        m = BoWSentiment()
        m.load_state_dict(torch.load("model.pt", map_location="cpu"))
        m.eval()
        _model = m
    return _model

def predict(input_data):
    text = input_data["text"]
    bow = _bow_vector(_tokenize(text)).unsqueeze(0)
    model = _load_model()
    with torch.no_grad():
        probs = F.softmax(model(bow), dim=-1).squeeze()
    idx = int(torch.argmax(probs))
    return {
        "label": LABELS[idx],
        "confidence": float(probs[idx]),
        "probs": {LABELS[i]: float(probs[i]) for i in range(2)}
    }

# Test
if __name__ == "__main__":
    payload = json.loads(sys.stdin.read())
    print(json.dumps(predict(payload)))
