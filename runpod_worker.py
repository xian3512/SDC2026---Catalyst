"""Example custom Runpod Serverless worker. OCR is RapidOCR on Runpod.
For a vision-LLM upgrade, replace ocr_local with your model call while keeping the output schema.
"""
import base64
import runpod
from ocr import ocr_local
 

def handler(event):
    job_input = event.get("input", {})
    raw = job_input.get("image_base64", "")
    if not raw:
        return {"amount": None, "date": None, "reference": None,
                "confidence": 0.0, "raw_text": "Missing image_base64"}
    image = base64.b64decode(raw, validate=True)
    if len(image) > 5 * 1024 * 1024:
        raise ValueError("Image too large")
    return ocr_local(image)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
