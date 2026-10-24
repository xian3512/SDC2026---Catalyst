"""Database initializer for Orbyte SlipMatch (Dynamic Homemade Cookies Store)."""
from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = DATA_DIR / "slipmatch.db"

# Initial starting menu (Owner can add/change any item anytime via /products)
INITIAL_PRODUCTS = [
    ("COOKIE-CHOC", "Classic Chocolate Chip", "1 pc", 500, 1),
    ("COOKIE-PISTA", "Pistachio", "1 pc", 500, 1),
    ("COOKIE-REDV", "Red Velvet Cream Cheese", "1 pc", 500, 1),
    ("COOKIE-MATCHA", "Matcha White Chocolate", "1 pc", 500, 1),
    ("COOKIE-CARAMEL", "Salted Caramel", "1 pc", 500, 1),
    ("COOKIE-CNC", "Cookies & Cream", "1 pc", 500, 1),
    ("COOKIE-HOJICHA", "Hojicha White Chocolate", "1 pc", 500, 1),
    ("COOKIE-PANDAN", "Pandan Gula Melaka", "1 pc", 500, 1),
    ("SET-5", "Buy 4 Free 1 (Mix & Match)", "5 pcs", 2000, 1),
    ("SET-8", "Buy 6 Free 2 (Mix & Match)", "8 pcs", 3000, 1),
    ("SET-15", "Buy 10 Free 5 (Mix & Match)", "15 pcs", 5000, 1),
    ("ADDON-GIFTBOX", "Gift Box Packaging", "1 box", 400, 1),
]


def init_db():
  conn = sqlite3.connect(DB_FILE)
  conn.execute("PRAGMA foreign_keys = ON")
  cur = conn.cursor()

  # Clean reset of old clothing tables
  cur.execute("DROP TABLE IF EXISTS order_items")
  cur.execute("DROP TABLE IF EXISTS payment_matches")
  cur.execute("DROP TABLE IF EXISTS payment_slips")
  cur.execute("DROP TABLE IF EXISTS orders")
  cur.execute("DROP TABLE IF EXISTS products")
  cur.execute("DROP TABLE IF EXISTS audit_logs")

  # 1. Products (Owner key-in catalogue)
  cur.execute("""
    CREATE TABLE products (
        sku TEXT PRIMARY KEY,
        product_name TEXT NOT NULL,
        size TEXT NOT NULL DEFAULT '1 pc',
        unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
        is_available INTEGER NOT NULL DEFAULT 1
    )
    """)

  # 2. Orders (Purely generated from Owner input, NO hardcoded orders)
  cur.execute("""
    CREATE TABLE orders (
        order_id TEXT PRIMARY KEY,
        customer_name TEXT NOT NULL,
        phone TEXT,
        amount_due_cents INTEGER NOT NULL CHECK (amount_due_cents >= 0),
        currency TEXT NOT NULL DEFAULT 'MYR',
        payment_status TEXT NOT NULL DEFAULT 'UNPAID',
        customer_request_text TEXT,
        order_reference TEXT UNIQUE,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

  # 3. Order Items
  cur.execute("""
    CREATE TABLE order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        sku TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        unit_price_cents INTEGER NOT NULL,
        subtotal_cents INTEGER NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(order_id),
        FOREIGN KEY (sku) REFERENCES products(sku)
    )
    """)

  # 4. Payment Slips
  cur.execute("""
    CREATE TABLE payment_slips (
        slip_id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        amount_cents INTEGER,
        currency TEXT DEFAULT 'MYR',
        sender_name TEXT,
        reference_number TEXT,
        payment_date TEXT,
        extraction_status TEXT DEFAULT 'PENDING',
        risk_level TEXT DEFAULT 'UNASSESSED',
        review_status TEXT DEFAULT 'PENDING',
        bank_verified INTEGER DEFAULT 0,
        risk_reasons TEXT DEFAULT '[]',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

  # 5. Payment Matches
  cur.execute("""
    CREATE TABLE payment_matches (
        match_id TEXT PRIMARY KEY,
        slip_id TEXT NOT NULL,
        order_id TEXT NOT NULL,
        matched_amount_cents INTEGER NOT NULL,
        match_status TEXT DEFAULT 'SUGGESTED',
        FOREIGN KEY (slip_id) REFERENCES payment_slips(slip_id),
        FOREIGN KEY (order_id) REFERENCES orders(order_id)
    )
    """)

  # 6. Audit Trail
  cur.execute("""
    CREATE TABLE audit_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        actor_name TEXT NOT NULL,
        actor_role TEXT NOT NULL,
        action TEXT NOT NULL,
        details TEXT DEFAULT '{}',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

  # Explicit column mapping prevents any column mismatch
  for p in INITIAL_PRODUCTS:
    cur.execute(
        """
        INSERT INTO products (sku, product_name, size, unit_price_cents, is_available)
        VALUES (?, ?, ?, ?, ?)
        """,
        p,
    )

  conn.commit()
  conn.close()
  print("Database schema created cleanly! Ready for dynamic owner input.")


if __name__ == "__main__":
  init_db()