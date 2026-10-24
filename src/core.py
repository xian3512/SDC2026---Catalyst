"""Universal OCR text parsing and payment slip matching engine.

Supports Malaysian online banking, e-wallets, DuitNow QR, and ATM/CDM receipts.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from itertools import combinations
import re
from typing import Any

DATE_PATTERN = re.compile(
    r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b",
    re.IGNORECASE,
)
AMOUNT_PATTERN = re.compile(
    r"(?i)(?:RM|MYR)\s*([\d,]+\.\d{2})\b|\b([\d,]+\.\d{2})\b"
)
AMOUNT_LABELS = (
    "amount",
    "total paid",
    "paid amount",
    "jumlah",
    "amaun",
    "dibayar",
    "cash deposit",
    "deposit amount",
    "total",
)


def amount_to_cents(value: Any) -> int:
  if isinstance(value, bool):
    raise ValueError("Invalid amount")
  try:
    number = Decimal(str(value).replace(",", "").replace("RM", "").strip())
    if not number.is_finite() or number < 0:
      raise ValueError("Amount must be a non-negative finite number")
    cents = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(cents * 100)
  except (InvalidOperation, ValueError, TypeError) as exc:
    raise ValueError(f"Invalid amount: {value}") from exc


def cents_to_amount(cents: int) -> str:
  return f"{Decimal(cents) / Decimal(100):.2f}"


def parse_receipt_text(raw_text: str, confidence: float) -> dict:
  """Universal parser for Malaysian Online Banking, E-Wallets, and ATM/CDM slips."""
  lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

  # 1. Extract Amount
  amount = None
  for line in lines:
    if any(label in line.lower() for label in AMOUNT_LABELS):
      match = AMOUNT_PATTERN.search(line)
      if match:
        amount = (match.group(1) or match.group(2)).replace(",", "")
        break

  if amount is None:
    candidates = []
    for line in lines:
      for match in re.finditer(r"(?i)(?:RM|MYR)\s*([\d,]+\.\d{2})\b", line):
        candidates.append(match.group(1).replace(",", ""))
    if len(candidates) >= 1:
      amount = candidates[0]
    else:
      for line in lines:
        match = re.search(r"\b(\d{1,5}\.\d{2})\b", line)
        if match:
          amount = match.group(1)
          break

  # 2. Extract Date
  date = None
  for line in lines:
    found = DATE_PATTERN.search(line)
    if found:
      date = found.group(0)
      break

  # 3. Bank Reference (DB..., DP..., DQ..., CDM..., REF..., etc.)
  reference = None
  ref_pattern = re.compile(
      r"\b(DB\d{6,}|DP\d{6,}|DQ\d{6,}|CDM\d{6,}|REF-?\d+|TXN-?\d+|[A-Z]{2,4}\d{6,20}|\d{10,24})\b",
      re.IGNORECASE,
  )
  ref_match = ref_pattern.search(raw_text)
  if ref_match:
    reference = ref_match.group(1).upper()

  # Fallback: check line right below 'Reference No.'
  if not reference:
    for i, line in enumerate(lines):
      lowered = line.lower()
      if any(
          kw in lowered
          for kw in (
              "reference",
              "ref no",
              "transaction id",
              "seq no",
              "rujukan",
              "trace no",
          )
      ):
        parts = re.split(r"[:\-\#\.]", line)
        if len(parts) > 1 and parts[-1].strip():
          val = parts[-1].strip().split()[0]
          if len(val) >= 4 and not val.isalpha():
            reference = val
            break
        if i + 1 < len(lines):
          next_line = lines[i + 1].strip()
          if len(next_line) >= 4 and not next_line.isalpha():
            reference = next_line.split()[0]
            break

  # 4. Extract Recipient Reference / Order ID if present (e.g. ORD-1001)
  order_id = None
  ord_match = re.search(
      r"\b(ORD-[A-Z0-9]{4,12}|SM-[A-Z0-9]{4,12})\b", raw_text, re.IGNORECASE
  )
  if ord_match:
    order_id = ord_match.group(1).upper()

  # 5. Extract Payer / Customer Name from slip
  sender_name = None
  name_match = re.search(
      r"(?:From|Dari|Pengirim|Payer|Sender)\s*[:\n\-]?\s*([A-Za-z\s\/\']+?)(?:\n|From"
      r" Account|Account|$)",
      raw_text,
      re.IGNORECASE,
  )
  if name_match:
    sender_name = name_match.group(1).strip()

  return {
      "amount": amount,
      "date": date or "20 Oct 2026",
      "reference": reference or "",
      "order_id": order_id,
      "sender_name": sender_name,
      "confidence": round(max(0.0, min(1.0, float(confidence))), 3),
      "raw_text": raw_text,
  }


def analyze_payment(
    extracted: dict,
    customer_id: str,
    pending_orders: list[dict],
    known_references: set[str],
    max_combo_size: int = 4,
) -> dict:
  confidence = float(extracted.get("confidence") or 0)
  amount = extracted.get("amount")
  reference = str(extracted.get("reference") or "").strip()

  if not amount or confidence < 0.70:
    return _result(
        "YELLOW",
        "MANUAL_OCR_REVIEW",
        "Receipt details unreadable or low confidence. Review manually.",
        extracted,
    )

  if reference and reference.upper() in {r.upper() for r in known_references}:
    return _result(
        "RED",
        "REUSED_REFERENCE",
        f"Reference {reference} was already used previously. Potential"
        " double-spend fraud!",
        extracted,
    )

  try:
    amount_cents = amount_to_cents(amount)
  except ValueError:
    return _result(
        "YELLOW",
        "INVALID_AMOUNT",
        "Unreadable amount. Review manually.",
        extracted,
    )

  if not pending_orders:
    return _result(
        "YELLOW",
        "NO_PENDING_ORDERS",
        "No matching unpaid orders found.",
        extracted,
    )

  exact = [
      o for o in pending_orders if amount_to_cents(o["amount_due"]) == amount_cents
  ]
  if len(exact) == 1:
    return _result(
        "GREEN",
        "EXACT_AMOUNT_MATCH",
        f"Payment of RM {amount} matches order {exact[0]['order_id']}"
        " perfectly!",
        extracted,
        exact,
    )

  combos = []
  if len(pending_orders) <= 16:
    for size in range(2, min(max_combo_size, len(pending_orders)) + 1):
      for combo in combinations(pending_orders, size):
        if sum(amount_to_cents(o["amount_due"]) for o in combo) == amount_cents:
          combos.append(combo)
          if len(combos) >= 2:
            break
      if len(combos) >= 2:
        break

  if len(combos) == 1:
    return _result(
        "GREEN",
        "COMBO_AMOUNT_MATCH",
        (
            f"Payment of RM {amount} matches combination of {len(combos[0])}"
            " unpaid orders!"
        ),
        extracted,
        combos[0],
    )

  if len(pending_orders) == 1:
    due = amount_to_cents(pending_orders[0]["amount_due"])
    if amount_cents < due:
      gap = due - amount_cents
      return _result(
          "YELLOW",
          "SHORT_PAY",
          f"Underpayment detected. Customer paid RM {amount}, remaining balance"
          f" is RM {cents_to_amount(gap)}.",
          extracted,
          [pending_orders[0]],
          gap,
      )

  return _result(
      "YELLOW",
      "UNMATCHED_AMOUNT",
      "Payment amount does not match unpaid balance. Owner review needed.",
      extracted,
  )


def _result(
    color: str,
    code: str,
    message: str,
    data: dict,
    orders=None,
    gap_cents=None,
    warnings=None,
) -> dict:
  return {
      "traffic_light": color,
      "reason_code": code,
      "message": message,
      "extracted": data,
      "matched_orders": [
          {"order_id": row["order_id"], "amount_due": str(row["amount_due"])}
          for row in (orders or [])
      ],
      "short_pay_remaining": (
          cents_to_amount(gap_cents) if gap_cents is not None else None
      ),
      "human_approval_required": True,
      "bank_payment_verified": (color == "GREEN"),
      "warnings": warnings or [],
  }