import base64
import io
import os
from pathlib import Path
import re
import secrets
import sqlite3

from fastapi import APIRouter, Header, HTTPException
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field
from ai_helpers import ai_parse_order_message

try:
  from dotenv import load_dotenv

  load_dotenv()
except ImportError:
  pass

router = APIRouter(prefix="/billing", tags=["Billing & Universal Order Capture"])

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "data" / "slipmatch.db"


def connect_db():
  conn = sqlite3.connect(DB_FILE)
  conn.row_factory = sqlite3.Row
  conn.execute("PRAGMA foreign_keys = ON")
  return conn


def get_next_order_id(conn: sqlite3.Connection):
  """Generates sequential order IDs starting from ORD-1001, ORD-1002, ORD-1003, etc."""
  rows = conn.execute(
      "SELECT order_id FROM orders WHERE order_id LIKE 'ORD-%'"
  ).fetchall()
  max_num = 1000
  for r in rows:
    m = re.search(r"ORD-(\d+)", r["order_id"])
    if m:
      val = int(m.group(1))
      if val > max_num:
        max_num = val
  next_num = max_num + 1
  return f"ORD-{next_num}", f"SM-ORD-{next_num}"


class BillingRequest(BaseModel):
  customer_name: str = Field(
      default="",
      examples=["Aisyah binti Rahman"],
      description="Optional: Customer name or leave empty to auto-detect",
  )
  request_text: str = Field(
      ...,
      examples=[
          "assalamualaikum kak, nak 1 set buy 10 free 5 ye, pistachio 5 matcha"
          " 5 red velvet 5. tambah hojicha 3 biji nama Aisyah binti Rahman."
          " ambik sabtu 24/10 boleh?"
      ],
  )


FLAVOUR_MAP = [
    ("COOKIE-REDV", ["red velvet", "redvelvet", "cream cheese"]),
    (
        "COOKIE-CHOC",
        ["choc chip", "chocolate chip", "chocolate", "choc", "classic choc"],
    ),
    ("COOKIE-PISTA", ["pistachio", "pistasio"]),
    ("COOKIE-MATCHA", ["matcha", "green tea"]),
    ("COOKIE-CARAMEL", ["salted caramel", "caramel"]),
    (
        "COOKIE-CNC",
        ["cookies & cream", "cookies n cream", "cookies and cream", "oreo"],
    ),
    ("COOKIE-HOJICHA", ["hojicha", "houjicha"]),
    ("COOKIE-PANDAN", ["pandan", "gula melaka"]),
]


def parse_dynamic_whatsapp(
    conn: sqlite3.Connection, text: str, default_name: str
) -> dict:
  text_clean = text.strip()
  text_lower = text_clean.lower()

  extracted_name = default_name.strip()
  name_match = re.search(
      r"(?i)(?:nama|name|my name is)\s+([A-Za-z\s\/\']+?)(?:\.|\,|\bambik\b|\bambil\b|\bdelivery\b|\bfor\b|\bpickup\b|\bsat\b|\bsabtu\b|\bsunday\b|\b\d{1,2}/\d{1,2}\b|$)",
      text_clean,
  )
  if name_match:
    extracted_name = name_match.group(1).strip()
  elif not extracted_name:
    words = text_clean.split()
    if words and words[-1].replace(".", "").isalpha():
      extracted_name = words[-1].replace(".", "")
    else:
      extracted_name = "Valued Customer"

  date_match = re.search(
      r"\b(\d{1,2}/\d{1,2}|\d{1,2}\s*(?:oct|okt|nov|dis)|sat|sabtu|sunday|ahad|esok|tomorrow|24hb|25hb)\b",
      text_clean,
      re.IGNORECASE,
  )
  pickup_date = "Saturday, 24 Oct 2026"
  if date_match:
    raw_d = date_match.group(1).lower()
    if "25" in raw_d or "sun" in raw_d or "ahad" in raw_d:
      pickup_date = "Sunday, 25 Oct 2026"
    elif "24" in raw_d or "sat" in raw_d or "sabtu" in raw_d:
      pickup_date = "Saturday, 24 Oct 2026"
    elif "esok" in raw_d or "tomorrow" in raw_d:
      pickup_date = "Tomorrow (Self-Pickup)"
    else:
      pickup_date = raw_d

  selected_items = {}

  if re.search(
      r"\b(?:gift box|kotak hadiah|giftbox|box packaging)\b", text_lower
  ):
    row = conn.execute(
        "SELECT * FROM products WHERE sku = 'ADDON-GIFTBOX'"
    ).fetchone()
    if row:
      selected_items["ADDON-GIFTBOX"] = {
          "sku": row["sku"],
          "product_name": row["product_name"],
          "unit": row["size"],
          "quantity": 1,
          "unit_price_cents": row["unit_price_cents"],
          "subtotal_cents": row["unit_price_cents"],
      }

  set_patterns = [
      ("SET-15", r"(?:buy\s*10\s*free\s*5|15\s*pcs|set\s*15)"),
      ("SET-8", r"(?:buy\s*6\s*free\s*2|8\s*pcs|set\s*8)"),
      ("SET-5", r"(?:buy\s*4\s*free\s*1|5\s*pcs|set\s*5)"),
  ]
  has_set = False
  for sku, pat in set_patterns:
    m = re.findall(r"(\d+)?\s*(?:set\s*)?" + pat, text_lower)
    if m:
      has_set = True
      qty = sum(int(q) if q else 1 for q in m)
      row = conn.execute(
          "SELECT * FROM products WHERE sku = ?", (sku,)
      ).fetchone()
      if row:
        selected_items[sku] = {
            "sku": row["sku"],
            "product_name": row["product_name"],
            "unit": row["size"],
            "quantity": qty,
            "unit_price_cents": row["unit_price_cents"],
            "subtotal_cents": qty * row["unit_price_cents"],
        }

  for sku, aliases in FLAVOUR_MAP:
    for al in aliases:
      patterns = [
          (
              r"(?:tambah|extra|\+|\bplus\b)\s*"
              + re.escape(al)
              + r"\s*(\d+)?\s*(?:biji|pcs|jar|balang|cookie)?"
          ),
          (
              r"(?:tambah|extra|\+|\bplus\b)\s*(\d+)?\s*(?:biji|pcs|jar|balang|cookie)?\s*"
              + re.escape(al)
          ),
          r"\+\s*(\d+)?\s*" + re.escape(al),
          r"\+\s*" + re.escape(al) + r"\s*(\d+)?",
      ]
      if not has_set:
        patterns += [
            (
                r"(\d+)\s*(?:biji|pcs|jar|balang|cookie)?\s*"
                + re.escape(al)
            ),
            re.escape(al) + r"\s*(?:x\s*)?(\d+)?",
        ]

      matched_flavour = False
      for pat in patterns:
        m = re.search(pat, text_lower)
        if m:
          qty = 1
          if m.groups():
            for g in m.groups():
              if g and g.strip().isdigit():
                qty = int(g.strip())
                break
          row = conn.execute(
              "SELECT * FROM products WHERE sku = ?", (sku,)
          ).fetchone()
          if row:
            selected_items[sku] = {
                "sku": row["sku"],
                "product_name": row["product_name"],
                "unit": row["size"],
                "quantity": qty,
                "unit_price_cents": row["unit_price_cents"],
                "subtotal_cents": qty * row["unit_price_cents"],
            }
            matched_flavour = True
            break
      if matched_flavour:
        break

  items = list(selected_items.values())
  total_cents = sum(it["subtotal_cents"] for it in items)

  return {
      "customer_name": extracted_name,
      "pickup_date": pickup_date,
      "items": items,
      "total_cents": total_cents,
      "total_rm": total_cents / 100,
  }


def parse_order_message(conn: sqlite3.Connection, text: str, default_name: str) -> dict:
  """Prefer AI interpretation when configured; otherwise preserve legacy parser."""
  provider = os.getenv("MESSAGE_AI_PROVIDER", "auto").lower().strip()
  has_key = bool(os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip())
  use_ai = provider in ("gemini", "openai") or (provider == "auto" and has_key)
  if provider not in ("auto", "gemini", "openai", "rules"):
    raise HTTPException(status_code=500, detail="MESSAGE_AI_PROVIDER must be auto, gemini, openai, or rules.")
  if use_ai:
    try:
      return ai_parse_order_message(conn, text, default_name)
    except Exception as exc:
      # Do not silently create an inaccurate order if the user explicitly enabled AI.
      raise HTTPException(status_code=502, detail=f"AI order analysis failed: {exc}") from exc
  parsed = parse_dynamic_whatsapp(conn, text, default_name)
  parsed["needs_review"] = not bool(parsed.get("items"))
  parsed["review_reason"] = "AI is not configured; using the basic rule-based parser."
  parsed["parser"] = "rules"
  return parsed


def generate_cookie_invoice_image(
    order_id: str,
    order_ref: str,
    customer_name: str,
    items: list,
    total_rm: float,
    pickup_date: str,
) -> str:
  width = 720
  height = 540 + (len(items) * 35)
  img = Image.new("RGB", (width, height), "#fffdfa")
  draw = ImageDraw.Draw(img)

  draw.rounded_rectangle(
      (20, 20, width - 20, height - 20), radius=16, outline="#78350f", width=2
  )
  draw.rectangle((20, 20, width - 20, 95), fill="#451a03")
  draw.text(
      (35, 30),
      "CATALYST HOMEMADE BAKES & COOKIES 🍪",
      fill="#fef3c7",
  )
  draw.text(
      (35, 58),
      f"Order ID: {order_id}   |   Ref: {order_ref}",
      fill="#fde68a",
  )

  y = 115
  draw.text((35, y), f"Customer Name: {customer_name}", fill="#1c1917")
  draw.text((width - 250, y), f"Pickup / Date: {pickup_date}", fill="#1c1917")
  y += 26
  draw.text(
      (35, y),
      "Bakery: Catalyst Homemade Bakes & Cookies",
      fill="#78350f",
  )
  y += 35
  draw.line((35, y, width - 35, y), fill="#e7e5e4", width=1)
  y += 15

  draw.text((35, y), "ITEM DESCRIPTION", fill="#451a03")
  draw.text((width - 130, y), "AMOUNT", fill="#451a03")
  y += 28

  for it in items:
    name_str = f"• {it['quantity']}x {it['product_name']} ({it['unit']})"
    price_str = f"RM {it['subtotal_cents'] / 100:.2f}"
    draw.text((40, y), name_str, fill="#292524")
    draw.text((width - 130, y), price_str, fill="#292524")
    y += 26

  y += 10
  draw.line((35, y, width - 35, y), fill="#78350f", width=2)
  y += 16
  draw.text((35, y), "TOTAL AMOUNT DUE:", fill="#451a03")
  draw.text((width - 140, y), f"RM {total_rm:.2f}", fill="#b45309")
  y += 25
  draw.text((35, y), "STATUS: UNPAID (Awaiting Payment)", fill="#dc2626")

  y += 35
  draw.rounded_rectangle(
      (35, y, width - 35, y + 80), radius=10, fill="#fefce8", outline="#fef08a"
  )
  draw.text(
      (50, y + 10),
      "PAYMENT INSTRUCTIONS (KitaBank / DuitNow Transfer):",
      fill="#78350f",
  )
  draw.text(
      (50, y + 32),
      "Bank Account: 8800 1234 5678 (Catalyst Homemade Bakes & Cookies)",
      fill="#b45309",
  )
  # Displays the sequential Order ID as the required payment note
  draw.text(
      (50, y + 54), f"Payment Reference / Note: {order_id}", fill="#713f12"
  )

  buf = io.BytesIO()
  img.save(buf, format="PNG")
  return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(
      "ascii"
  )


@router.post("/preview")
def billing_preview(request: BillingRequest):
  conn = connect_db()
  try:
    parsed = parse_order_message(
        conn, request.request_text, request.customer_name
    )
    next_order_id, _ = get_next_order_id(conn)
    return {
        "order_id": f"{next_order_id} (Preview)",
        "customer_name": parsed["customer_name"],
        "pickup_date": parsed["pickup_date"],
        "items": parsed["items"],
        "total_rm": parsed["total_rm"],
        "status": "PREVIEW",
        "needs_review": parsed.get("needs_review", False),
        "review_reason": parsed.get("review_reason", ""),
        "parser": parsed.get("parser", "rules"),
    }
  finally:
    conn.close()


@router.post("/confirm")
def billing_confirm(
    request: BillingRequest, x_owner_key: str = Header(default="")
):
  expected = os.getenv("SLIPMATCH_OWNER_KEY") or "demo-owner-123"
  if not secrets.compare_digest(x_owner_key, expected):
    raise HTTPException(status_code=403, detail="Owner authorization required")

  conn = connect_db()
  try:
    parsed = parse_order_message(
        conn, request.request_text, request.customer_name
    )
    if not parsed["items"]:
      raise HTTPException(
          status_code=422,
          detail="No matching cookie flavours or sets recognized in message.",
      )

    # Proceed to create order even if needs_review is True (Owner override/manual approval)
    order_id, order_ref = get_next_order_id(conn)

    conn.execute(
        """
        INSERT INTO orders (order_id, customer_name, amount_due_cents, currency, payment_status, customer_request_text, order_reference)
        VALUES (?, ?, ?, 'MYR', 'UNPAID', ?, ?)
        """,
        (
            order_id,
            parsed["customer_name"],
            parsed["total_cents"],
            request.request_text,
            order_ref,
        ),
    )

    for it in parsed["items"]:
      conn.execute(
          """
            INSERT INTO order_items (order_id, sku, quantity, unit_price_cents, subtotal_cents)
            VALUES (?, ?, ?, ?, ?)
        """,
          (
              order_id,
              it["sku"],
              it["quantity"],
              it["unit_price_cents"],
              it["subtotal_cents"],
          ),
      )

    items_text = "\n".join(
        f"• {it['quantity']}x {it['product_name']} ({it['unit']}) — RM"
        f" {it['subtotal_cents'] / 100:.2f}"
        for it in parsed["items"]
    )

    english_chat_receipt = f"""🍪 *CATALYST HOMEMADE BAKES & COOKIES — ORDER INVOICE*
Order ID: {order_id}
Customer Name: {parsed['customer_name']}
Pickup / Delivery Date: {parsed['pickup_date']}

ORDER SUMMARY:
{items_text}

💰 *TOTAL AMOUNT DUE: RM {parsed['total_rm']:.2f}*
Status: UNPAID (Awaiting Payment)

Payment Details (DuitNow / Bank Transfer):
Bank: KitaBank 8800 1234 5678 (Catalyst Homemade Bakes & Cookies)
Payment Reference / Note: {order_id}

Please send your payment receipt screenshot in this chat once transferred. Thank you! ❤️"""

    receipt_img = generate_cookie_invoice_image(
        order_id,
        order_ref,
        parsed["customer_name"],
        parsed["items"],
        parsed["total_rm"],
        parsed["pickup_date"],
    )

    conn.commit()
    return {
        "message": f"Order {order_id} created successfully",
        "order_id": order_id,
        "order_reference": order_ref,
        "customer_name": parsed["customer_name"],
        "items": parsed["items"],
        "total_rm": parsed["total_rm"],
        "payment_status": "UNPAID",
        "customer_receipt_text": english_chat_receipt,
        "whatsapp_receipt_text": english_chat_receipt,
        "receipt_image_base64": receipt_img,
    }
  finally:
    conn.close()