"""Master FastAPI server for Orbyte SlipMatch.
Automates receipt OCR parsing, fraud verification, dynamic order matching,
and serves catalyst_orbyte_dashboard.html at http://localhost:8000/.
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import sqlite3
import uuid
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

# Base directories & automatic .env loading
BASE_DIR = Path(__file__).resolve().parent


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
    except ImportError:
        pass
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
os.environ.setdefault("SLIPMATCH_OWNER_KEY", "demo-owner-123")

from ocr import extract_receipt

DB_FILE = BASE_DIR / "data" / "slipmatch.db"
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Orbyte SlipMatch - AI Receipt & Billing Engine",
    description="Automated DuitNow Receipt Verification & Conversational Billing for SMEs",
    version="1.0"
)

# CORS configuration
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")
origins = [o.strip() for o in FRONTEND_ORIGIN.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if "*" in origins else origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static folder for uploaded receipt viewing in dashboard
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# Include modular feature routers
try:
    from billing_routes import router as billing_router
    app.include_router(billing_router)
except ImportError:
    pass

try:
    from approval_routes import router as approval_router
    app.include_router(approval_router)
except ImportError:
    pass

try:
    from products_routes import router as products_router
    app.include_router(products_router)
except ImportError:
    pass


# -------------------------------------------------------------
# SERVE YOUR DASHBOARD AT /
# -------------------------------------------------------------
@app.get("/")
def serve_dashboard():
    """Automatically serves catalyst_orbyte_dashboard.html at http://localhost:8000/."""
    preferred_files = [
        BASE_DIR / "catalyst_orbyte_dashboard_complete_fixed_v3.html",
        BASE_DIR / "catalyst_orbyte_dashboard.html",
    ]
    for preferred in preferred_files:
        if preferred.exists():
            return FileResponse(preferred)

    html_files = sorted(BASE_DIR.glob("*.html"))
    if html_files:
        return FileResponse(html_files[0])

    for sub in ("static", "templates", "frontend", "../orbyte_dashboard"):
        sub_dir = (BASE_DIR / sub).resolve()
        if sub_dir.exists() and sub_dir.is_dir():
            sub_htmls = sorted(sub_dir.glob("*.html"))
            if sub_htmls:
                return FileResponse(sub_htmls[0])

    return HTMLResponse(
        "<h2>Dashboard HTML file not found in folder. Open <a href='/docs'>/docs</a> for API.</h2>",
        status_code=404
    )


# -------------------------------------------------------------
# DATABASE CONNECTION & STARTUP CLEANUP
# -------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def cleanup_corrupted_references():
    """Automatically removes false 'ONLY.' references from SQLite and used_references.json."""
    if DB_FILE.exists():
        try:
            conn = get_db()
            conn.execute("DELETE FROM payment_slips WHERE UPPER(reference_number) LIKE 'ONLY%'")
            conn.commit()
            conn.close()
        except Exception:
            pass

    used_json = BASE_DIR / "used_references.json"
    if used_json.exists():
        try:
            refs = json.loads(used_json.read_text(encoding="utf-8"))
            cleaned = [r for r in refs if not str(r).upper().startswith("ONLY")]
            used_json.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
        except Exception:
            pass


cleanup_corrupted_references()


def amount_to_cents(value: str | int | float | None) -> int:
    if value is None:
        raise ValueError("Amount is required")
    clean = str(value).replace(",", "").replace("RM", "").strip()
    return int(Decimal(clean).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def cents_to_amount(cents: int) -> str:
    return f"{Decimal(cents) / Decimal(100):.2f}"


# -------------------------------------------------------------
# MULTI-LINE SMART METADATA EXTRACTION (RapidOCR / RunPod)
# -------------------------------------------------------------
STOP_WORDS = {
    "ONLY", "ONLY.", "SAHAJA", "TIADA", "NIL", "NONE", "PAYMENT", "TRANSFER",
    "DUITNOW", "QR", "COOKIES", "ORDER", "ORDERS", "SUCCESSFUL", "COMPLETED",
    "BERJAYA", "FAVOURITE", "INSTANT", "FUND", "FUNDS", "RECEIPT", "RESIT",
    "BAKES", "CATALYST", "RECIPIENT", "SENDER", "BENEFICIARY", "ACCOUNT", "DEMO",
    "DETAILS", "TRANSACTION", "NO", "NUMBER", "ID", "METHOD", "WALLET"
}

NAME_LABELS = {
    "paid from", "transfer from", "transferred from", "received from",
    "sender name", "sender", "payer name", "payer", "from account",
    "account holder", "customer name", "paid by", "from"
}

NOT_A_NAME = {
    "CATALYST", "KITAPAY", "DUITNOW", "DUITNOW QR", "GREENBANK", "MAYBANK",
    "CIMB", "PUBLIC BANK", "RHB", "HONG LEONG", "AMBANK", "BANK ISLAM",
    "SAVINGS ACCOUNT", "CURRENT ACCOUNT", "E-WALLET", "WALLET NO", "WALLET NO.",
    "PAID TO", "PAYMENT METHOD", "TRANSACTION DETAILS", "SUCCESSFUL", "BERJAYA",
    "DEMO / SYNTHETIC DATA", "PAYMENT SUCCESSFUL", "DUITNOW QR PAYMENT"
}


def extract_reference_smart(raw_text: str, candidate_ref: str | None = None) -> str | None:
    """Extracts genuine Malaysian bank transaction reference, handling multi-line RapidOCR output."""
    if candidate_ref:
        cand = str(candidate_ref).strip(" .:#-,")
        clean = cand.rstrip(".")
        if cand.upper() not in STOP_WORDS and clean.upper() not in STOP_WORDS:
            if re.search(r"\d{3,}", cand):
                return cand

    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

    for i, line in enumerate(lines):
        low = line.lower()
        if "reference only" in low or "rujukan sahaja" in low:
            continue
        if re.match(r"(?i)^(?:transaction\s*(?:no|number|id)|ref(?:erence)?\s*(?:no|number)?|duitnow\s*ref|no\.?\s*rujukan)\s*[:.]?$", low):
            if i + 1 < len(lines):
                cand = lines[i + 1].strip(" .:#-,")
                if cand.upper() not in STOP_WORDS and re.search(r"\d{3,}", cand):
                    return cand
        m = re.search(
            r"(?i)(?:transaction\s*(?:no|number|id)|ref(?:erence)?\s*(?:no|number)?|duitnow\s*ref|no\.?\s*rujukan)\s*[:.]?\s*([A-Z0-9_-]{5,30})",
            line
        )
        if m:
            cand = m.group(1).strip(" .:#-,")
            clean = cand.rstrip(".")
            if cand.upper() not in STOP_WORDS and clean.upper() not in STOP_WORDS and re.search(r"\d{3,}", cand):
                return cand

    m = re.search(
        r"\b(DQ\d{6,}|DB\d{6,}|DP\d{6,}|CDM\d{6,}|REF-?\d+|TXN-?\d+|USED-?\d+|[A-Z]{2,4}-?\d{5,20}|\d{10,24})\b",
        raw_text,
        re.I
    )
    if m:
        cand = m.group(1).strip(" .:#-,")
        if cand.upper() not in STOP_WORDS:
            return cand

    return None


def clean_person_name(raw_val: str) -> str | None:
    if not raw_val:
        return None
    val = re.split(r"(\+60|\b\d{3,}[- ]?\d{3,}|account|wallet|date|merchant|ctl-)", raw_val, flags=re.I)[0]
    val = val.strip(" .:-,#")
    if len(val) < 2 or val.upper() in NOT_A_NAME or "CATALYST" in val.upper():
        return None
    if re.search(r"\d{3,}", val):
        return None
    return val


def get_short_given_name(full_name: str) -> str:
    """Extracts primary given name before bin/binti/a/l/a/p so 'Farah binti Kamal' -> 'Farah'."""
    if not full_name:
        return ""
    parts = re.split(r"\b(bin|binti|bt|bte|anak|a/l|a/p)\b", full_name, flags=re.I)
    first_part = parts[0].strip()
    return first_part if first_part else full_name.strip()


def extract_customer_name(raw_text: str) -> tuple[str | None, str | None]:
    """Returns (short_given_name, full_name) from either multi-line or single-line OCR text."""
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        low = line.lower().strip(" :.-")
        if low in NAME_LABELS:
            if i + 1 < len(lines):
                cand = clean_person_name(lines[i + 1])
                if cand:
                    return get_short_given_name(cand), cand
        m = re.match(
            r"(?i)^(?:paid\s+from|transfer(?:red)?\s+from|received\s+from|sender(?:\s+name)?|payer(?:\s+name)?|from\s+account|account\s+holder|customer\s+name|paid\s+by|from)\s*[:.-]\s*(.+)$",
            line
        )
        if m:
            cand = clean_person_name(m.group(1))
            if cand:
                return get_short_given_name(cand), cand
    return None, None


def match_malaysian_names(order_name: str, slip_name: str) -> bool:
    """Matches Malaysian names properly, accounting for 'bin', 'binti', 'bt', 'a/l', etc."""
    if not order_name or not slip_name:
        return False

    o = get_short_given_name(order_name).lower().strip()
    s = get_short_given_name(slip_name).lower().strip()

    if o and s and (o in s or s in o):
        return True

    o_clean = re.sub(r"\b(bin|binti|bt|bte|anak|a/l|a/p|puan|cik|encik|mr|mrs|ms)\b", " ", order_name.lower())
    s_clean = re.sub(r"\b(bin|binti|bt|bte|anak|a/l|a/p|puan|cik|encik|mr|mrs|ms)\b", " ", slip_name.lower())

    o_tokens = {tok for tok in o_clean.split() if len(tok) >= 3}
    s_tokens = {tok for tok in s_clean.split() if len(tok) >= 3}

    return len(o_tokens & s_tokens) > 0


# -------------------------------------------------------------
# CORE API ENDPOINTS
# -------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "ok": True,
        "ocr_provider": os.getenv("OCR_PROVIDER", "demo"),
        "app": "Orbyte SlipMatch API"
    }


@app.get("/orders")
def list_orders():
    """Return database orders in the response shape consumed by the dashboard."""
    if DB_FILE.exists():
        conn = get_db()
        try:
            rows = conn.execute("""
                SELECT order_id, customer_name, amount_due_cents, payment_status,
                       order_reference, created_at
                FROM orders
                ORDER BY created_at DESC, order_id DESC
            """).fetchall()
            return {
                "total_orders": len(rows),
                "orders": [
                    {
                        "order_id": r["order_id"],
                        "customer_name": r["customer_name"],
                        "amount_due": cents_to_amount(r["amount_due_cents"]),
                        "amount_rm": float(cents_to_amount(r["amount_due_cents"])),
                        "payment_status": r["payment_status"],
                        "status": r["payment_status"],
                        "order_reference": r["order_reference"] or "",
                        "created_at": r["created_at"] or "",
                    }
                    for r in rows
                ],
            }
        finally:
            conn.close()

    json_path = BASE_DIR / "pending_orders.json"
    fallback = json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else []
    return {"total_orders": len(fallback), "orders": fallback}


@app.delete("/orders/{order_id}")
def delete_order(order_id: str, x_owner_key: str | None = Header(default=None)):
    """Delete one order and its dependent order items/matches; owner-key protected."""
    expected = os.getenv("SLIPMATCH_OWNER_KEY") or "demo-owner-123"
    if not x_owner_key or not secrets.compare_digest(x_owner_key, expected):
        raise HTTPException(status_code=403, detail="Owner authorization required")
    conn = get_db()
    try:
        exists = conn.execute("SELECT order_id FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Order not found")
        conn.execute("DELETE FROM payment_matches WHERE order_id = ?", (order_id,))
        conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
        conn.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
        conn.execute(
            """INSERT INTO audit_logs (entity_type, entity_id, actor_name, actor_role, action, details)
               VALUES ('order', ?, 'Owner', 'OWNER', 'DELETE', ?)""",
            (order_id, json.dumps({"reason": "Deleted from dashboard order history"})),
        )
        conn.commit()
        return {"message": f"Order {order_id} deleted successfully", "order_id": order_id}
    finally:
        conn.close()


@app.delete("/orders")
def delete_order_history(x_owner_key: str | None = Header(default=None)):
    """Delete all order history, preserving slips and product catalogue."""
    expected = os.getenv("SLIPMATCH_OWNER_KEY") or "demo-owner-123"
    if not x_owner_key or not secrets.compare_digest(x_owner_key, expected):
        raise HTTPException(status_code=403, detail="Owner authorization required")
    conn = get_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        conn.execute("DELETE FROM payment_matches")
        conn.execute("DELETE FROM order_items")
        conn.execute("DELETE FROM orders")
        conn.execute(
            """INSERT INTO audit_logs (entity_type, entity_id, actor_name, actor_role, action, details)
               VALUES ('order_history', 'ALL', 'Owner', 'OWNER', 'DELETE_ALL', ?)""",
            (json.dumps({"deleted_orders": count}),),
        )
        conn.commit()
        return {"message": f"Deleted {count} order(s). Payment slips and products were kept.", "deleted_orders": count}
    finally:
        conn.close()


def _amount_integrity_check(raw_text: str, extracted_amount) -> dict:
    """Flag conflicting amounts printed on receipt text; this cannot prove image editing."""
    labeled_values = []
    for line in (raw_text or "").splitlines():
        if re.search(r"\b(amount|total|paid|transfer(?:red)? amount|transaction amount|jumlah|amaun)\b", line, re.I):
            values = re.findall(r"(?i)(?:RM|MYR)\s*([0-9][0-9,]*\.\d{2})|\b([0-9][0-9,]*\.\d{2})\b", line)
            for pair in values:
                value = (pair[0] or pair[1]).replace(",", "")
                try:
                    labeled_values.append(int((Decimal(value) * 100).quantize(Decimal("1"))))
                except Exception:
                    pass
    unique_values = sorted(set(labeled_values))
    try:
        extracted_cents = int((Decimal(str(extracted_amount).replace(",", "")) * 100).quantize(Decimal("1")))
    except Exception:
        extracted_cents = None
    conflicting = len(unique_values) > 1 and (extracted_cents is None or extracted_cents in unique_values)
    if conflicting:
        return {
            "status": "SUSPICIOUS",
            "possible_amount_tampering": True,
            "amounts_found_rm": [f"{value / 100:.2f}" for value in unique_values],
            "message": "Different amounts appear beside payment amount/total labels. The receipt may be edited or OCR may have misread it. Verify the original receipt and bank credit manually."
        }
    return {
        "status": "NO_CONFLICT_FOUND",
        "possible_amount_tampering": False,
        "amounts_found_rm": [f"{value / 100:.2f}" for value in unique_values],
        "message": "No conflicting labelled amounts were detected. This does not prove the image is genuine or unedited."
    }


@app.post("/analyze")
async def analyze_receipt(file: UploadFile = File(...)):
    """
    Automated payment slip analysis (Zero manual customer_id input required).
    Extracts amount, genuine reference (e.g. DQ2610003), customer given name, and matches to open orders.
    """
    if file.content_type not in ("image/png", "image/jpeg", "image/jpg"):
        raise HTTPException(status_code=400, detail="Upload PNG or JPEG only")

    image_bytes = await file.read(5 * 1024 * 1024 + 1)
    if len(image_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Maximum image size is 5 MB")

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()
    except (UnidentifiedImageError, ValueError, OSError):
        raise HTTPException(status_code=400, detail="Not a valid image")

    # Save uploaded image to /uploads for frontend preview
    filename_hash = uuid.uuid4().hex[:10]
    ext = ".png" if "png" in file.content_type else ".jpg"
    image_rel_path = f"/uploads/{filename_hash}{ext}"
    local_image_path = UPLOADS_DIR / f"{filename_hash}{ext}"
    local_image_path.write_bytes(image_bytes)

    # 1. OCR Extraction (RunPod Serverless or RapidOCR)
    try:
        extracted = extract_receipt(image_bytes, file.content_type)
    except Exception as exc:
        extracted = {
            "amount": None,
            "date": None,
            "reference": None,
            "confidence": 0.0,
            "raw_text": f"OCR Error: {exc}"
        }

    raw_text = extracted.get("raw_text") or ""
    amount_str = extracted.get("amount")
    integrity_check = _amount_integrity_check(raw_text, amount_str)

    if extracted.get("is_payment_receipt") is False:
        slip_id = f"SLIP-{uuid.uuid4().hex[:8].upper()}"
        result = {
            "traffic_light": "RED", "risk_level": "RED",
            "reason_code": "NOT_A_SLIP",
            "message": "AI could not identify this image as a payment receipt. Manual review required.",
            "extracted": {"amount": None, "reference": None, "date": None},
            "matched_orders": [], "slip_id": slip_id, "customer_name": "Unknown",
            "ocr_provider": extracted.get("provider", os.getenv("OCR_PROVIDER", "demo")),
            "image_url": image_rel_path, "bank_payment_verified": False,
            "integrity_check": integrity_check
        }
        _record_slip(slip_id, image_rel_path, None, "Unknown", None, "RED", result["message"], [])
        return result

    # Check for non-receipt images (e.g. cat photo)
    if re.search(r"\b(CAT PHOTO|FELINE|DEMO CAT IMAGE|NOT A PAYMENT SLIP|KUCING)\b", raw_text, re.I):
        slip_id = f"SLIP-{uuid.uuid4().hex[:8].upper()}"
        result = {
            "traffic_light": "RED",
            "risk_level": "RED",
            "reason_code": "NOT_A_SLIP",
            "message": "Uploaded image does not appear to be a valid payment receipt. Manual review required.",
            "extracted": {"amount": None, "reference": None, "date": None},
            "matched_orders": [],
            "slip_id": slip_id,
            "customer_name": "Unknown",
            "ocr_provider": extracted.get("provider", os.getenv("OCR_PROVIDER", "demo")),
            "image_url": image_rel_path,
            "bank_payment_verified": False,
            "integrity_check": integrity_check
        }
        _record_slip(slip_id, image_rel_path, None, "Unknown", None, "RED", result["message"], [])
        return result

    # Smart multi-line reference extraction: Captures DQ2610003, ignores 'ONLY.'
    clean_ref = extract_reference_smart(raw_text, extracted.get("reference"))
    extracted["reference"] = clean_ref

    # Smart multi-line customer name extraction
    slip_sender = extracted.get("sender_name")
    short_name, full_name = extract_customer_name(raw_text)
    display_slip_name = slip_sender or short_name or full_name
    if not full_name and slip_sender:
        full_name = slip_sender

    # 2. Load pending orders (only UNPAID / pending)
    orders_payload = list_orders()
    if isinstance(orders_payload, dict):
        all_orders = orders_payload.get("orders", [])
    elif isinstance(orders_payload, list):
        all_orders = orders_payload
    else:
        all_orders = []
    pending_orders = [
        o for o in all_orders
        if isinstance(o, dict) and str(o.get("status", "UNPAID")).upper() in ("UNPAID", "PENDING")
    ]

    # 3. Load previously used references to detect duplicate fraud
    known_references = set()
    used_json = BASE_DIR / "used_references.json"
    if used_json.exists():
        try:
            for r in json.loads(used_json.read_text(encoding="utf-8")):
                cleaned = extract_reference_smart("", r)
                if cleaned:
                    known_references.add(cleaned.upper())
        except Exception:
            pass

    if DB_FILE.exists():
        try:
            conn = get_db()
            db_refs = conn.execute("SELECT reference_number FROM payment_slips WHERE reference_number IS NOT NULL").fetchall()
            conn.close()
            for r in db_refs:
                cleaned = extract_reference_smart("", r["reference_number"])
                if cleaned:
                    known_references.add(cleaned.upper())
        except Exception:
            pass

    # 4. FRAUD CHECK: Reused Reference
    slip_id = f"SLIP-{uuid.uuid4().hex[:8].upper()}"

    if clean_ref and clean_ref.upper() in known_references:
        result = {
            "traffic_light": "RED",
            "risk_level": "RED",
            "reason_code": "REUSED_REFERENCE",
            "message": f"Reference {clean_ref} was already used in a previous transaction! Potential double-spend fraud.",
            "extracted": {
                "amount": amount_str,
                "reference": clean_ref,
                "date": extracted.get("date") or "20/10/2026"
            },
            "matched_orders": [],
            "slip_id": slip_id,
            "customer_name": display_slip_name or "Unknown",
            "ocr_provider": extracted.get("provider", os.getenv("OCR_PROVIDER", "demo")),
            "image_url": image_rel_path,
            "bank_payment_verified": False,
            "integrity_check": integrity_check
        }
        _record_slip(slip_id, image_rel_path, None, result["customer_name"], clean_ref, "RED", result["message"], [])
        return result

    # 5. AMOUNT VALIDATION
    try:
        slip_cents = amount_to_cents(amount_str)
    except Exception:
        result = {
            "traffic_light": "YELLOW",
            "risk_level": "YELLOW",
            "reason_code": "INVALID_AMOUNT",
            "message": "Unreadable or missing payment amount on slip. Manual review required.",
            "extracted": {
                "amount": amount_str,
                "reference": clean_ref,
                "date": extracted.get("date") or "20/10/2026"
            },
            "matched_orders": [],
            "slip_id": slip_id,
            "customer_name": display_slip_name or "Unknown",
            "ocr_provider": extracted.get("provider", os.getenv("OCR_PROVIDER", "demo")),
            "image_url": image_rel_path,
            "bank_payment_verified": False,
            "integrity_check": integrity_check
        }
        _record_slip(slip_id, image_rel_path, None, result["customer_name"], clean_ref, "YELLOW", result["message"], [])
        return result

    if integrity_check.get("possible_amount_tampering"):
        cust = display_slip_name or "Unknown"
        result = {
            "traffic_light": "YELLOW",
            "risk_level": "YELLOW",
            "reason_code": "POSSIBLE_AMOUNT_TAMPERING",
            "message": integrity_check["message"],
            "extracted": {"amount": amount_str, "reference": clean_ref, "date": extracted.get("date")},
            "matched_orders": [],
            "slip_id": slip_id,
            "customer_name": cust,
            "ocr_provider": extracted.get("provider", os.getenv("OCR_PROVIDER", "demo")),
            "image_url": image_rel_path,
            "bank_payment_verified": False,
            "integrity_check": integrity_check
        }
        _record_slip(slip_id, image_rel_path, slip_cents, cust, clean_ref, "YELLOW", result["message"], [])
        return result

    # 6. AUTOMATED ORDER MATCHING
    candidate_orders = []

    mentioned_numbers = set(re.findall(r"\b(?:ORD-)?(\d{3,6})\b", raw_text, re.I))
    for o in pending_orders:
        oid = str(o.get("order_id", "")).upper()
        oid_nums = "".join(filter(str.isdigit, oid))
        if oid in raw_text.upper() or oid_nums in mentioned_numbers:
            if o not in candidate_orders:
                candidate_orders.append(o)

    if not candidate_orders and full_name:
        candidate_orders = [
            o for o in pending_orders
            if match_malaysian_names(o.get("customer_name", ""), full_name)
        ]

    if not candidate_orders and not full_name:
        for o in pending_orders:
            c_name = get_short_given_name(o.get("customer_name", "")).strip()
            if len(c_name) >= 3 and re.search(rf"\b{re.escape(c_name)}\b", raw_text, re.I):
                candidate_orders.append(o)

    amount_only_orders = [
        o for o in pending_orders
        if amount_to_cents(o.get("amount_due", 0)) == slip_cents
    ]

    # 7. EVALUATE MATCHES & TRAFFIC LIGHT
    matched_exact = [o for o in candidate_orders if amount_to_cents(o.get("amount_due", 0)) == slip_cents]

    combos = []
    if len(candidate_orders) >= 2:
        for size in range(2, min(4, len(candidate_orders)) + 1):
            for combo in combinations(candidate_orders, size):
                if sum(amount_to_cents(o.get("amount_due", 0)) for o in combo) == slip_cents:
                    combos.append(list(combo))

    if len(matched_exact) == 1 and len(combos) == 1:
        possible = [matched_exact[0], *combos[0]]
        seen_ids = set()
        possible = [o for o in possible if not (o.get("order_id") in seen_ids or seen_ids.add(o.get("order_id")))]
        cust = display_slip_name or possible[0].get("customer_name") or "Unknown"
        result = {
            "traffic_light": "YELLOW",
            "risk_level": "YELLOW",
            "reason_code": "AMBIGUOUS_SINGLE_OR_COMBO_MATCH",
            "message": "The receipt amount matches one order individually and also matches a combination of multiple orders. Owner review is required.",
            "extracted": {"amount": amount_str, "reference": clean_ref, "date": extracted.get("date")},
            "matched_orders": possible,
            "slip_id": slip_id,
            "customer_name": cust,
            "ocr_provider": extracted.get("provider", os.getenv("OCR_PROVIDER", "demo")),
            "image_url": image_rel_path,
            "bank_payment_verified": False,
            "integrity_check": integrity_check
        }
        _record_slip(slip_id, image_rel_path, slip_cents, cust, clean_ref, "YELLOW", result["message"], possible)
        return result

    if len(matched_exact) == 1:
        matched_order = matched_exact[0]
        cust = matched_order.get("customer_name") or display_slip_name or "Customer"
        result = {
            "traffic_light": "GREEN",
            "risk_level": "GREEN",
            "reason_code": "EXACT_AMOUNT_MATCH",
            "message": f"Payment matched order {matched_order['order_id']} ({cust}) for RM {cents_to_amount(slip_cents)}.",
            "extracted": {
                "amount": amount_str,
                "reference": clean_ref,
                "date": extracted.get("date") or "20/10/2026"
            },
            "matched_orders": [matched_order],
            "slip_id": slip_id,
            "customer_name": cust,
            "ocr_provider": extracted.get("provider", os.getenv("OCR_PROVIDER", "demo")),
            "image_url": image_rel_path,
            "bank_payment_verified": False,
            "integrity_check": integrity_check
        }
        _record_slip(slip_id, image_rel_path, slip_cents, cust, clean_ref, "GREEN", result["message"], [matched_order])
        return result

    elif len(combos) == 1:
        combo_orders = combos[0]
        cust = combo_orders[0].get("customer_name") or display_slip_name or "Customer"
        order_ids = ", ".join(o["order_id"] for o in combo_orders)
        result = {
            "traffic_light": "GREEN",
            "risk_level": "GREEN",
            "reason_code": "COMBO_AMOUNT_MATCH",
            "message": f"Combo payment matched orders {order_ids} ({cust}) totalling RM {cents_to_amount(slip_cents)}.",
            "extracted": {
                "amount": amount_str,
                "reference": clean_ref,
                "date": extracted.get("date") or "20/10/2026"
            },
            "matched_orders": combo_orders,
            "slip_id": slip_id,
            "customer_name": cust,
            "ocr_provider": extracted.get("provider", os.getenv("OCR_PROVIDER", "demo")),
            "image_url": image_rel_path,
            "bank_payment_verified": False,
            "integrity_check": integrity_check
        }
        _record_slip(slip_id, image_rel_path, slip_cents, cust, clean_ref, "GREEN", result["message"], combo_orders)
        return result

    elif len(candidate_orders) == 1 and slip_cents < amount_to_cents(candidate_orders[0].get("amount_due", 0)):
        due = amount_to_cents(candidate_orders[0].get("amount_due", 0))
        shortfall = cents_to_amount(due - slip_cents)
        cust = candidate_orders[0].get("customer_name") or display_slip_name or "Customer"
        result = {
            "traffic_light": "YELLOW",
            "risk_level": "YELLOW",
            "reason_code": "SHORT_PAY",
            "message": f"Underpayment detected! Paid RM {cents_to_amount(slip_cents)}, but order {candidate_orders[0]['order_id']} requires RM {cents_to_amount(due)} (Short by RM {shortfall}).",
            "extracted": {
                "amount": amount_str,
                "reference": clean_ref,
                "date": extracted.get("date") or "20/10/2026"
            },
            "matched_orders": [candidate_orders[0]],
            "short_pay_remaining": shortfall,
            "slip_id": slip_id,
            "customer_name": cust,
            "ocr_provider": extracted.get("provider", os.getenv("OCR_PROVIDER", "demo")),
            "image_url": image_rel_path,
            "bank_payment_verified": False,
            "integrity_check": integrity_check
        }
        _record_slip(slip_id, image_rel_path, slip_cents, cust, clean_ref, "YELLOW", result["message"], [candidate_orders[0]])
        return result

    elif not candidate_orders and len(amount_only_orders) == 1 and not display_slip_name:
        matched_order = amount_only_orders[0]
        cust = matched_order.get("customer_name") or "Unknown"
        result = {
            "traffic_light": "YELLOW",
            "risk_level": "YELLOW",
            "reason_code": "AMOUNT_ONLY_MATCH",
            "message": f"Amount RM {cents_to_amount(slip_cents)} matches order {matched_order['order_id']} ({cust}), but no order ID or payer name was found on slip. Owner review required.",
            "extracted": {
                "amount": amount_str,
                "reference": clean_ref,
                "date": extracted.get("date") or "20/10/2026"
            },
            "matched_orders": [matched_order],
            "slip_id": slip_id,
            "customer_name": cust,
            "ocr_provider": extracted.get("provider", os.getenv("OCR_PROVIDER", "demo")),
            "image_url": image_rel_path,
            "bank_payment_verified": False,
            "integrity_check": integrity_check
        }
        _record_slip(slip_id, image_rel_path, slip_cents, cust, clean_ref, "YELLOW", result["message"], [matched_order])
        return result

    else:
        cust = display_slip_name or "Unknown"
        result = {
            "traffic_light": "YELLOW",
            "risk_level": "YELLOW",
            "reason_code": "MANUAL_REVIEW_NEEDED",
            "message": f"Receipt from '{cust}' (RM {cents_to_amount(slip_cents)}) could not be automatically matched to an open order for '{cust}'. Owner review required.",
            "extracted": {
                "amount": amount_str,
                "reference": clean_ref,
                "date": extracted.get("date") or "20/10/2026"
            },
            "matched_orders": candidate_orders,
            "slip_id": slip_id,
            "customer_name": cust,
            "ocr_provider": extracted.get("provider", os.getenv("OCR_PROVIDER", "demo")),
            "image_url": image_rel_path,
            "bank_payment_verified": False,
            "integrity_check": integrity_check
        }
        _record_slip(slip_id, image_rel_path, slip_cents, cust, clean_ref, "YELLOW", result["message"], candidate_orders)
        return result


def _record_slip(slip_id, image_url, amount_cents, customer_name, ref, risk_level, msg, matched_orders):
    """Safely saves slip record and match links into SQLite database for the Kanban dashboard."""
    if not DB_FILE.exists():
        return
    try:
        conn = get_db()
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(payment_slips)").fetchall()]
        if cols:
            data = {
                "slip_id": slip_id,
                "filename": image_url,
                "image_url": image_url,
                "amount_cents": amount_cents or 0,
                "currency": "MYR",
                "sender_name": customer_name or "Unknown",
                "customer_name": customer_name or "Unknown",
                "reference_number": ref,
                "payment_date": "20/10/2026",
                "extraction_status": "COMPLETED",
                "risk_level": risk_level,
                "review_status": "PENDING",
                "bank_verified": 0,
                "risk_reasons": json.dumps([msg]),
                "matched_order_id": matched_orders[0]["order_id"] if matched_orders else None,
            }
            insert_cols = [c for c in cols if c in data]
            placeholders = ", ".join("?" for _ in insert_cols)
            col_names = ", ".join(insert_cols)
            vals = [data[c] for c in insert_cols]
            conn.execute(f"INSERT OR REPLACE INTO payment_slips ({col_names}) VALUES ({placeholders})", vals)

        match_cols = [r["name"] for r in conn.execute("PRAGMA table_info(payment_matches)").fetchall()]
        if match_cols and matched_orders:
            for o in matched_orders:
                m_id = f"MATCH-{uuid.uuid4().hex[:8].upper()}"
                o_cents = amount_to_cents(o.get("amount_due", 0))
                conn.execute("""
                    INSERT OR IGNORE INTO payment_matches (
                        match_id, slip_id, order_id, matched_amount_cents, match_status
                    ) VALUES (?, ?, ?, ?, 'SUGGESTED')
                """, (m_id, slip_id, o["order_id"], o_cents))

        conn.commit()
        conn.close()
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)