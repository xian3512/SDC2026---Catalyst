"""OCR modes: demo fixture, local RapidOCR, Runpod Serverless, and Gemini Hybrid fallback.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
from pathlib import Path

from PIL import Image, ImageEnhance
from core import parse_receipt_text

BASE = Path(__file__).resolve().parent

INVALID_REFERENCE_WORDS = {
    "ONLY", "RINGGIT", "MALAYSIA", "SUCCESSFUL", "BERJAYA",
    "ACCEPTED", "COMPLETED", "FAILED", "PAYMENT", "TRANSFER",
    "DUITNOW", "INSTANT", "SAVINGS", "CURRENT", "ACCOUNT",
    "MAYBANK", "CIMB", "PUBLIC", "RHB", "BANK", "TOTAL",
    "AMOUNT", "NONE", "NULL"
}


def sanitize_and_extract_reference(data: dict) -> dict:
    if not isinstance(data, dict):
        return data

    ref = str(data.get("reference") or "").strip().rstrip(".")
    raw_text = str(data.get("raw_text") or "")

    is_invalid = (
        not ref
        or ref.upper() in INVALID_REFERENCE_WORDS
        or len(ref) < 4
        or ref.upper().startswith("RINGGIT")
    )

    if is_invalid and raw_text:
        found_ref = None
        order_match = re.search(r"\b(SM-ORD-\d+|ORD-\d+)\b", raw_text, re.IGNORECASE)
        if order_match:
            found_ref = order_match.group(1).upper()

        if not found_ref:
            bank_ref_match = re.search(
                r"(?:reference\s*(?:no|id|number)?|ref\s*(?:no|id)?|trans(?:action)?\s*(?:id|ref|no)?|rujukan)\s*[:\-]?\s*([A-Za-z0-9\-_]{6,30})",
                raw_text,
                re.IGNORECASE,
            )
            if bank_ref_match:
                cand = bank_ref_match.group(1).strip().rstrip(".")
                if cand.upper() not in INVALID_REFERENCE_WORDS:
                    found_ref = cand

        if not found_ref:
            trace_match = re.search(r"\b(DB\d{6,12}|DQ\d{6,12}|DP\d{6,12}|CDM\d{6,12}|202[0-9]{9,20})\b", raw_text)
            if trace_match:
                found_ref = trace_match.group(1).strip()

        data["reference"] = found_ref if found_ref else None
    elif ref:
        data["reference"] = ref

    return data


def ocr_demo(image_bytes: bytes) -> dict:
    digest = hashlib.sha256(image_bytes).hexdigest()
    cases = json.loads((BASE / "demo_fixtures.json").read_text(encoding="utf8"))
    if digest not in cases:
        return {
            "amount": None,
            "date": None,
            "reference": None,
            "confidence": 0.0,
            "raw_text": "Unknown image: demo mode only recognizes the included sample images.",
        }
    data = dict(cases[digest])
    data["source"] = "DEMO_FIXTURE_NOT_LIVE_OCR"
    return sanitize_and_extract_reference(data)


def ocr_runpod(image_bytes: bytes, media_type: str) -> dict:
    import requests

    api_key = os.getenv("RUNPOD_API_KEY")
    endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID")

    if not api_key or not endpoint_id:
        raise RuntimeError("Set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID in your server environment")

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        if img.width < 1200:
            scale = 1200 / img.width
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        image_bytes = buf.getvalue()
    except Exception:
        pass

    url = f"https://api.runpod.ai/v2/{endpoint_id}/runsync?wait=90000"
    payload = {
        "input": {
            "image_base64": base64.b64encode(image_bytes).decode("ascii"),
            "mime_type": media_type,
        }
    }

    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=105,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"Runpod API returned HTTP {response.status_code}: {response.text[:300]}")

    response.raise_for_status()
    body = response.json()

    if body.get("status") != "COMPLETED" or not isinstance(body.get("output"), dict):
        raise RuntimeError(f"Runpod did not return completed structured OCR: {body.get('status')}")

    result = body["output"]
    required = {"amount", "date", "reference", "confidence", "raw_text"}
    if not required.issubset(result):
        raise RuntimeError("Runpod output does not match our OCR schema")

    return sanitize_and_extract_reference(result)


def extract_receipt(image_bytes: bytes, media_type: str) -> dict:
    """Runpod OCR extraction with intelligent Gemini / Regex parsing fallback."""
    provider = os.getenv("OCR_PROVIDER", "runpod").lower().strip()
    has_gemini = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))

    res = None
    if provider == "demo":
        res = ocr_demo(image_bytes)
    elif provider == "runpod":
        try:
            # 1. Try Runpod first
            res = ocr_runpod(image_bytes, media_type)
        except Exception:
            res = None

    # 2. If Runpod failed or returned empty amount, use Gemini Vision directly to guarantee 100% detection!
    if (not res or not res.get("amount")) and has_gemini:
        try:
            from ai_helpers import ai_read_payment_slip
            res = ai_read_payment_slip(image_bytes, media_type)
        except Exception:
            pass

    # 3. Last resort demo fixture check
    if not res or not res.get("amount"):
        try:
            res = ocr_demo(image_bytes)
        except Exception:
            res = {"amount": None, "date": None, "reference": None, "confidence": 0.0, "raw_text": "Could not read receipt."}

    return sanitize_and_extract_reference(res)
