| Property                            | Description                                                                                |
| ----------------------------------- | ------------------------------------------------------------------------------------------ |
| **Expected input (Python / JSON)**  | `{"text": string}`                                                                         |
| **Example input**                   | `{"text": "I love this app!"}`                                                             |
| **Expected output (Python / JSON)** | `{"label": string, "confidence": float, "probs": {"negative": float, "positive": float}}`  |
| **Example output**                  | `{"label": "positive", "confidence": 0.87, "probs": {"negative": 0.13, "positive": 0.87}}` |
| **Use case**                        | Text input → classify as positive or negative with confidence scores.                      |
