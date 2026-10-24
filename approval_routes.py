import csv
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

try:
  from dotenv import load_dotenv

  load_dotenv()
except ImportError:
  pass

router = APIRouter(tags=["Approvals, Kanban & Accounting"])

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "data" / "slipmatch.db"
UPLOADS_DIR = BASE_DIR / "uploads"


def db_connection():
  conn = sqlite3.connect(DB_FILE, timeout=10)
  conn.row_factory = sqlite3.Row
  conn.execute("PRAGMA foreign_keys = ON")
  return conn


# Official Mock Bank Statement from Page 6 of the PDF (KitaBank 8800 1234 5678)
MOCK_BANK_STATEMENT = [
    (
        "10:15:32",
        "DB2610001",
        "IBG/DUITNOW TRF FR AISYAH BINTI RAHMAN",
        6500,
        "S01",
    ),
    ("10:48:05", "DP2610002", "KITAPAY TRF FR TAN MEI LING", 4400, "S02"),
    (
        "11:02:47",
        "DB2610004",
        "DUITNOW TRF FR NURUL HUDA BINTI AZMI",
        13000,
        "S04",
    ),
    (
        "12:31:44",
        "DQ2610003",
        "DUITNOW QR FR RAVI KUMAR A/L SUBRAMANIAM",
        12000,
        "S03",
    ),
    ("13:40:21", "DB2610005", "DUITNOW TRF FR JASON LIM WEI HONG", 15000, "S05"),
    (
        "14:08:19",
        "DB2610006",
        "DUITNOW TRF FR FARAH IZZATI BINTI KAMAL",
        20000,
        "S06",
    ),
    (
        "15:22:40",
        "DB2610009",
        "DUITNOW TRF FR LEE WEI JIE",
        500,
        "S09",
    ),  # Real transfer RM5, slip claimed RM35!
    (
        "16:05:12",
        "DQ2610008",
        "DUITNOW QR FR AHMAD ZAKI BIN OMAR",
        9900,
        "S08",
    ),
    ("17:12:08", "CDM2610010", "CASH DEPOSIT CDM", 9000, "S10"),
    ("17:30:52", "DB2610015", "DUITNOW TRF FR PRIYA A/P RAJAN", 10000, "S15"),
    ("18:45:51", "CDM2610011", "CASH DEPOSIT CDM", 7500, "S11"),
]


class DecisionRequest(BaseModel):
  decision: Literal["APPROVE_MATCH", "HOLD", "REJECT"]
  note: str = Field(
      default="Checked bank account manually.",
      min_length=3,
      max_length=300,
  )


# 1. Kanban Slips List
@router.get("/slips")
def list_slips():
  conn = db_connection()
  try:
    rows = conn.execute("""
            SELECT
                s.slip_id, s.filename, s.sender_name, s.amount_cents,
                s.currency, s.reference_number, s.payment_date,
                s.extraction_status, s.risk_level, s.review_status,
                s.bank_verified, s.created_at
            FROM payment_slips s
            ORDER BY s.slip_id DESC
        """).fetchall()

    slips = []
    for r in rows:
      slip_dict = dict(r)
      slip_dict["amount_rm"] = (
          (r["amount_cents"] / 100) if r["amount_cents"] else 0.0
      )
      slip_dict["image_url"] = f"/uploads/{r['filename']}"

      matches = conn.execute(
          """
                SELECT m.order_id, m.matched_amount_cents, o.amount_due_cents, o.customer_name
                FROM payment_matches m
                LEFT JOIN orders o ON o.order_id = m.order_id
                WHERE m.slip_id = ?
            """,
          (r["slip_id"],),
      ).fetchall()

      slip_dict["matched_orders"] = [{
          "order_id": m["order_id"],
          "matched_amount_rm": m["matched_amount_cents"] / 100,
          "order_due_rm": (
              (m["amount_due_cents"] / 100) if m["amount_due_cents"] else 0.0
          ),
      } for m in matches]

      if matches and r["amount_cents"]:
        total_due = sum(m["amount_due_cents"] or 0 for m in matches)
        if r["amount_cents"] < total_due:
          short_rm = (total_due - r["amount_cents"]) / 100
          cust = r["sender_name"] or "Customer"
          order_ids = ", ".join(m["order_id"] for m in matches if m["order_id"])

          english_reminder = (
              f"Hi {cust}, we have received your payment of"
              f" RM{slip_dict['amount_rm']:.2f}. The remaining balance for"
              f" order {order_ids} is RM{short_rm:.2f}. Please complete the"
              " payment to confirm your order. Thank you! 🍪"
          )

          slip_dict["short_pay_remaining_rm"] = short_rm
          slip_dict["customer_reminder_text"] = english_reminder
          encoded_text = english_reminder.replace(" ", "%20")
          slip_dict["action_links"] = {
              "copy_text": english_reminder,
              "whatsapp": f"https://wa.me/?text={encoded_text}",
              "telegram": f"https://t.me/share/url?text={encoded_text}",
          }
          slip_dict["whatsapp_action_link"] = slip_dict["action_links"][
              "whatsapp"
          ]
        else:
          slip_dict["short_pay_remaining_rm"] = 0.0
          slip_dict["customer_reminder_text"] = None
          slip_dict["action_links"] = None
          slip_dict["whatsapp_action_link"] = None
      else:
        slip_dict["short_pay_remaining_rm"] = 0.0
        slip_dict["customer_reminder_text"] = None
        slip_dict["action_links"] = None
        slip_dict["whatsapp_action_link"] = None

      slips.append(slip_dict)

    return {"total_slips": len(slips), "slips": slips}
  finally:
    conn.close()


# 2. Top Dashboard KPI Cards
@router.get("/dashboard/stats")
def dashboard_stats():
  conn = db_connection()
  try:
    total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    paid_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE payment_status = 'PAID'"
    ).fetchone()[0]
    unpaid_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE payment_status = 'UNPAID'"
    ).fetchone()[0]

    revenue_cents = (
        conn.execute(
            "SELECT SUM(amount_due_cents) FROM orders WHERE payment_status ="
            " 'PAID'"
        ).fetchone()[0]
        or 0
    )

    green_count = conn.execute(
        "SELECT COUNT(*) FROM payment_slips WHERE risk_level = 'GREEN' AND"
        " review_status = 'APPROVED_MATCH'"
    ).fetchone()[0]
    yellow_count = conn.execute(
        "SELECT COUNT(*) FROM payment_slips WHERE risk_level = 'YELLOW' AND"
        " review_status = 'PENDING'"
    ).fetchone()[0]
    red_count = conn.execute(
        "SELECT COUNT(*) FROM payment_slips WHERE risk_level = 'RED'"
    ).fetchone()[0]

    return {
        "revenue_collected_rm": revenue_cents / 100,
        "orders": {
            "total": total_orders,
            "paid": paid_orders,
            "unpaid": unpaid_orders,
        },
        "kanban_counts": {
            "green_approved": green_count,
            "yellow_needs_review": yellow_count,
            "red_flagged_fraud": red_count,
        },
    }
  finally:
    conn.close()


# 3. Monthly Sales CSV Export (For Excel / Accounting / SDG 8)
@router.get("/dashboard/export-csv")
def export_sales_csv():
  conn = db_connection()
  try:
    rows = conn.execute("""
            SELECT order_id, customer_name, phone, amount_due_cents, payment_status, order_reference, created_at
            FROM orders
            ORDER BY order_id ASC
        """).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Order ID",
        "Customer Name",
        "Phone",
        "Amount Due (RM)",
        "Payment Status",
        "Reference",
        "Date Created",
    ])

    for r in rows:
      writer.writerow([
          r["order_id"],
          r["customer_name"],
          r["phone"] or "-",
          f"{r['amount_due_cents'] / 100:.2f}",
          r["payment_status"],
          r["order_reference"],
          r["created_at"],
      ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                "attachment; filename=catalyst_monthly_sales.csv"
            )
        },
    )
  finally:
    conn.close()

# 4. Bank Statement Viewer (Self-Healing Table with KitaBank Credits)
@router.get("/bank-statement")
def list_bank_statement():
  conn = db_connection()
  try:
    # Auto-create table if missing
    conn.execute("""
            CREATE TABLE IF NOT EXISTS bank_statement (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                txn_time TEXT NOT NULL,
                bank_ref TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL,
                credit_cents INTEGER NOT NULL,
                linked_slip TEXT
            )
        """)

    # Do not repopulate the bank statement automatically. An empty table is a
    # valid state after the owner clears history; demo rows must not reappear.

    rows = conn.execute("""
            SELECT id, txn_time, bank_ref, description, credit_cents, linked_slip
            FROM bank_statement
            ORDER BY id ASC
        """).fetchall()

    return {
        "bank_account": "KitaBank 8800 1234 5678 (CATALYST)",
        "total_transactions": len(rows),
        "transactions": [{
            "id": r["id"],
            "time": r["txn_time"],
            "bank_ref": r["bank_ref"],
            "description": r["description"],
            "credit_rm": r["credit_cents"] / 100,
            "linked_slip": r["linked_slip"],
        } for r in rows],
    }
  finally:
    conn.close()


# 5. Audit Trail
@router.get("/audit-logs")
def list_audit_logs():
  conn = db_connection()
  try:
    rows = conn.execute("""
            SELECT log_id, entity_type, entity_id, actor_name, actor_role, action, details, created_at
            FROM audit_logs
            ORDER BY log_id DESC
            LIMIT 50
        """).fetchall()
    return {"logs": [dict(r) for r in rows]}
  finally:
    conn.close()


# 6. Owner Decision (APPROVE -> Green / REJECT -> Red)
@router.post("/slips/{slip_id}/decision")
def review_slip(
    slip_id: str,
    request: DecisionRequest,
    x_owner_key: str | None = Header(default=None),
):

  expected = os.getenv("SLIPMATCH_OWNER_KEY") or "demo-owner-123"
  if not x_owner_key or not secrets.compare_digest(x_owner_key, expected):
    raise HTTPException(status_code=403, detail="Owner authorization required")

  conn = db_connection()
  try:
    conn.execute("BEGIN IMMEDIATE")
    slip = conn.execute(
        "SELECT * FROM payment_slips WHERE slip_id = ?", (slip_id,)
    ).fetchone()
    if not slip:
      raise HTTPException(status_code=404, detail="Payment slip not found")

    old_status = slip["review_status"]
    old_risk = slip["risk_level"]

    matches = conn.execute(
        "SELECT * FROM payment_matches WHERE slip_id = ?", (slip_id,)
    ).fetchall()

    if request.decision == "APPROVE_MATCH":
      new_status = "APPROVED_MATCH"
      new_risk = "GREEN"
      bank_verified = 1

      conn.execute(
          """
                UPDATE payment_slips 
                SET review_status = ?, risk_level = ?, bank_verified = ?
                WHERE slip_id = ?
            """,
          (new_status, new_risk, bank_verified, slip_id),
      )
      conn.execute(
          "UPDATE payment_matches SET match_status = 'APPROVED_MATCH' WHERE"
          " slip_id = ?",
          (slip_id,),
      )
      for m in matches:
        conn.execute(
            "UPDATE orders SET payment_status = 'PAID' WHERE order_id = ?",
            (m["order_id"],),
        )

    elif request.decision == "REJECT":
      new_status = "REJECTED"
      new_risk = "RED"
      bank_verified = 0

      conn.execute(
          """
                UPDATE payment_slips 
                SET review_status = ?, risk_level = ?, bank_verified = ?
                WHERE slip_id = ?
            """,
          (new_status, new_risk, bank_verified, slip_id),
      )
      conn.execute(
          "UPDATE payment_matches SET match_status = 'REJECTED' WHERE slip_id ="
          " ?",
          (slip_id,),
      )

    else:
      new_status = "HELD"
      new_risk = old_risk
      bank_verified = 0
      conn.execute(
          "UPDATE payment_slips SET review_status = ? WHERE slip_id = ?",
          (new_status, slip_id),
      )

    details = {
        "previous_status": old_status,
        "new_status": new_status,
        "previous_color": old_risk,
        "new_color": new_risk,
        "note": request.note,
        "bank_verified": bool(bank_verified),
    }
    conn.execute(
        """
            INSERT INTO audit_logs (entity_type, entity_id, actor_name, actor_role, action, details)
            VALUES (?, ?, 'Owner (Manual Check)', 'OWNER', ?, ?)
        """,
        (
            "PAYMENT_SLIP",
            slip_id,
            f"MANUAL_DECISION_{request.decision}",
            json.dumps(details),
        ),
    )

    conn.commit()
    return {
        "slip_id": slip_id,
        "previous_color": old_risk,
        "new_color": new_risk,
        "review_status": new_status,
        "bank_verified": bool(bank_verified),
        "message": (
            f"Slip {slip_id} successfully updated by owner. Changed from"
            f" {old_risk} to {new_risk}!"
        ),
    }
  except Exception:
    conn.rollback()
    raise
  finally:
    conn.close()


# 7. Owner 1-Click History Reset
@router.delete("/dashboard/reset-history")
def reset_all_history(x_owner_key: str | None = Header(default=None)):
  expected = os.getenv("SLIPMATCH_OWNER_KEY") or "demo-owner-123"
  if not x_owner_key or not secrets.compare_digest(x_owner_key, expected):
    raise HTTPException(status_code=403, detail="Owner authorization required")

  conn = db_connection()
  try:
    # Ensure the table exists so reset works on databases that have not yet
    # opened the Bank Statement page.
    conn.execute("""
      CREATE TABLE IF NOT EXISTS bank_statement (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        txn_time TEXT NOT NULL,
        bank_ref TEXT UNIQUE NOT NULL,
        description TEXT NOT NULL,
        credit_cents INTEGER NOT NULL,
        linked_slip TEXT
      )
    """)
    with conn:
      conn.execute("DELETE FROM order_items")
      conn.execute("DELETE FROM payment_matches")
      conn.execute("DELETE FROM payment_slips")
      conn.execute("DELETE FROM orders")
      conn.execute("DELETE FROM bank_statement")
      conn.execute("DELETE FROM audit_logs")

    if UPLOADS_DIR.exists():
      for file in UPLOADS_DIR.glob("*"):
        if file.is_file():
          try:
            file.unlink()
          except Exception:
            pass

    return {
        "status": "SUCCESS",
        "message": (
            "Orders, Payment Review, bank statement transactions, and audit history cleared. Product catalogue preserved."
        ),
    }
  finally:
    conn.close()
# 8. Delete Single Payment Slip
@router.delete("/slips/{slip_id}")
def delete_slip(slip_id: str, x_owner_key: str | None = Header(default=None)):
    expected = os.getenv("SLIPMATCH_OWNER_KEY") or "demo-owner-123"
    if not x_owner_key or not secrets.compare_digest(x_owner_key, expected):
        raise HTTPException(status_code=403, detail="Owner authorization required")
    conn = db_connection()
    try:
        exists = conn.execute("SELECT slip_id, filename FROM payment_slips WHERE slip_id = ?", (slip_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Payment slip not found")
        
        conn.execute("DELETE FROM payment_matches WHERE slip_id = ?", (slip_id,))
        conn.execute("DELETE FROM payment_slips WHERE slip_id = ?", (slip_id,))
        
        filename = str(exists["filename"] or "").replace("/uploads/", "").strip()
        if filename:
            local_fp = UPLOADS_DIR / filename
            if local_fp.exists():
                try:
                    local_fp.unlink()
                except Exception:
                    pass

        conn.execute(
            """INSERT INTO audit_logs (entity_type, entity_id, actor_name, actor_role, action, details)
               VALUES ('payment_slip', ?, 'Owner', 'OWNER', 'DELETE_SLIP', ?)""",
            (slip_id, json.dumps({"reason": "Deleted individually by owner from payment review queue"})),
        )
        conn.commit()
        return {"message": f"Payment slip {slip_id} deleted successfully", "slip_id": slip_id}
    finally:
        conn.close()
