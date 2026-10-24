import json
from pathlib import Path

from fastapi.testclient import TestClient
from app import app
from core import amount_to_cents, analyze_payment, parse_receipt_text

ROOT = Path(__file__).resolve().parent.parent
client = TestClient(app)


def upload(filename, customer_id):
    with (ROOT / "samples" / filename).open("rb") as fp:
        return client.post("/analyze", files={"file": (filename, fp, "image/png")}, data={"customer_id": customer_id})


def test_exact_match():
    data = upload("01-perfect-C001.png", "C001").json()
    assert data["traffic_light"] == "GREEN"
    assert data["reason_code"] == "EXACT_AMOUNT_MATCH"
    assert [r["order_id"] for r in data["matched_orders"]] == ["ORD-1001"]
    assert data["bank_payment_verified"] is False


def test_combo_match():
    data = upload("02-combo-C002.png", "C002").json()
    assert data["traffic_light"] == "GREEN"
    assert data["reason_code"] == "COMBO_AMOUNT_MATCH"
    assert len(data["matched_orders"]) == 2


def test_short_pay():
    data = upload("03-shortpay-C003.png", "C003").json()
    assert data["traffic_light"] == "YELLOW"
    assert data["reason_code"] == "SHORT_PAY"
    assert data["short_pay_remaining"] == "10.00"


def test_reused_reference():
    data = upload("04-reused-ref-C001.png", "C001").json()
    assert data["traffic_light"] == "RED"
    assert data["reason_code"] == "REUSED_REFERENCE"


def test_ambiguous_match():
    data = upload("05-ambiguous-C004.png", "C004").json()
    assert data["traffic_light"] == "YELLOW"
    assert data["reason_code"] == "AMBIGUOUS_MATCH"


def test_low_confidence_never_green():
    data = upload("06-low-confidence-C001.png", "C001").json()
    assert data["traffic_light"] == "YELLOW"
    assert data["reason_code"] == "MANUAL_OCR_REVIEW"


def test_cat_never_green():
    data = upload("07-not-a-receipt-cat.png", "C001").json()
    assert data["traffic_light"] == "YELLOW"
    assert data["reason_code"] == "MANUAL_OCR_REVIEW"


def test_wrong_customer_not_matched():
    data = upload("01-perfect-C001.png", "C002").json()
    assert data["traffic_light"] != "GREEN"


def test_parser_malay():
    output = parse_receipt_text("Jumlah Dibayar: RM 1,250.00\nTarikh: 20/10/2026\nRujukan: ABC9988", .90)
    assert output["amount"] == "1250.00"
    assert output["reference"] == "ABC9988"
    assert output["date"] == "20/10/2026"


def test_precise_cents():
    assert amount_to_cents("0.10") + amount_to_cents("0.20") == amount_to_cents("0.30")


def test_health():
    assert client.get("/health").status_code == 200
