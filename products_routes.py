from pathlib import Path
import sqlite3
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/products", tags=["Owner Product Catalogue"])

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "data" / "slipmatch.db"


def get_db():
  conn = sqlite3.connect(DB_FILE)
  conn.row_factory = sqlite3.Row
  conn.execute("PRAGMA foreign_keys = ON")
  return conn


class ProductCreate(BaseModel):
  product_name: str = Field(
      ..., example="Nutella Sea Salt Cookie", min_length=2
  )
  size_or_unit: str = Field(default="1 pc", example="Jar")
  price_rm: float = Field(..., example=6.0, gt=0)


class ProductUpdate(BaseModel):
  product_name: str | None = None
  size_or_unit: str | None = None
  price_rm: float | None = None
  is_available: int | None = Field(default=None, ge=0, le=1)


@router.get("/")
def list_products():
  conn = get_db()
  try:
    rows = conn.execute(
        "SELECT sku, product_name, size as unit, unit_price_cents, is_available"
        " FROM products ORDER BY sku"
    ).fetchall()
    return {
        "total_products": len(rows),
        "products": [
            {
                "sku": r["sku"],
                "product_name": r["product_name"],
                "unit": r["unit"],
                "price_rm": r["unit_price_cents"] / 100,
                "is_available": bool(r["is_available"]),
            }
            for r in rows
        ],
    }
  finally:
    conn.close()


@router.post("/")
def add_product(item: ProductCreate):
  conn = get_db()
  try:
    sku = "COOKIE-" + uuid.uuid4().hex[:6].upper()
    price_cents = int(round(item.price_rm * 100))
    conn.execute(
        """
            INSERT INTO products (sku, product_name, size, unit_price_cents, is_available)
            VALUES (?, ?, ?, ?, 1)
        """,
        (sku, item.product_name.strip(), item.size_or_unit.strip(), price_cents),
    )
    conn.commit()
    return {
        "message": f"Item '{item.product_name}' added successfully!",
        "sku": sku,
        "product_name": item.product_name,
        "unit": item.size_or_unit,
        "price_rm": item.price_rm,
    }
  finally:
    conn.close()


@router.put("/{sku}")
def update_product(sku: str, item: ProductUpdate):
  conn = get_db()
  try:
    existing = conn.execute(
        "SELECT * FROM products WHERE sku = ?", (sku,)
    ).fetchone()
    if not existing:
      raise HTTPException(status_code=404, detail="Product not found")

    new_name = item.product_name or existing["product_name"]
    new_unit = item.size_or_unit or existing["size"]
    new_price_cents = (
        int(round(item.price_rm * 100))
        if item.price_rm is not None
        else existing["unit_price_cents"]
    )
    new_avail = (
        item.is_available
        if item.is_available is not None
        else existing["is_available"]
    )

    conn.execute(
        """
            UPDATE products 
            SET product_name = ?, size = ?, unit_price_cents = ?, is_available = ?
            WHERE sku = ?
        """,
        (new_name, new_unit, new_price_cents, new_avail, sku),
    )
    conn.commit()
    return {
        "message": "Product updated successfully",
        "sku": sku,
        "product_name": new_name,
        "price_rm": new_price_cents / 100,
    }
  finally:
    conn.close()


@router.delete("/{sku}")
def delete_product(sku: str):
  conn = get_db()
  try:
    conn.execute("DELETE FROM products WHERE sku = ?", (sku,))
    conn.commit()
    return {"message": f"Product {sku} deleted successfully"}
  finally:
    conn.close()