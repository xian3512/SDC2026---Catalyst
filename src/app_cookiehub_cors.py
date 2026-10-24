"""Orbyte proof-of-concept API. Not a production payment verification service."""
import io
import json
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from order_parser import parse_order_message
from PIL import Image, UnidentifiedImageError

from core import analyze_payment
from ocr import extract_receipt
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Orbyte Payment Slip Matcher (DEMO)", version="0.1")
# For a public deployment, set FRONTEND_ORIGIN to your actual Replit frontend origin.
origins = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000,http://localhost:5173,http://localhost:5500,http://127.0.0.1:5500").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])


def load_data(filename):
    return json.loads((ROOT / filename).read_text(encoding="utf8"))


@app.get("/health")
def health():
    return {"ok": True, "ocr_provider": os.getenv("OCR_PROVIDER", "demo"), "app": "Orbyte Role 3 POC"}


@app.get("/orders")
def pending_orders_demo():
    # Synthetic-only demonstration endpoint. Restrict this in real deployments.
    return load_data("pending_orders.json")


@app.post("/analyze")
async def analyze(file: UploadFile = File(...), customer_id: str = Form(...)):
    if file.content_type not in ("image/png", "image/jpeg", "image/jpg"):
        raise HTTPException(status_code=400, detail="Upload PNG or JPEG only")
    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Maximum image size is 5 MB")
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
    except (UnidentifiedImageError, ValueError, OSError):
        raise HTTPException(status_code=400, detail="Not a valid image")
    try:
        extracted = extract_receipt(data, file.content_type)
    except Exception as exc:
        # Never auto-approve when OCR or the GPU service fails.
        extracted = {"amount": None, "date": None, "reference": None,
                     "confidence": 0.0, "raw_text": "OCR unavailable"}
        error_hint = f"OCR provider unavailable: {type(exc).__name__}. Manual review required."
    else:
        error_hint = None
    result = analyze_payment(extracted, customer_id,
                             load_data("pending_orders.json"),
                             set(load_data("used_references.json")))
    if error_hint:
        result["warnings"].append(error_hint)
    result["customer_id"] = customer_id
    result["ocr_provider"] = os.getenv("OCR_PROVIDER", "demo")
    result["is_demo"] = True
    return result


# WhatsApp text -> reviewable order draft. Does NOT save or approve an invoice.
class WhatsAppOrderRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@app.post("/parse-order")
def parse_order(request: WhatsAppOrderRequest):
    return parse_order_message(
        request.message,
        load_data("product_catalog.json")
    )
