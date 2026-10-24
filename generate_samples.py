"""Regenerate watermarked, generic synthetic slips (NOT real bank screenshots)."""
from pathlib import Path
import hashlib
import json
from PIL import Image, ImageDraw, ImageFont
from core import parse_receipt_text

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
SAMPLES.mkdir(exist_ok=True)
FONT_FILE = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
try:
    font_title = ImageFont.truetype(FONT_FILE, 30)
    font_body = ImageFont.truetype(FONT_FILE, 24)
    font_small = ImageFont.truetype(FONT_FILE, 18)
except OSError:
    font_title = ImageFont.load_default()
    font_body = ImageFont.load_default()
    font_small = ImageFont.load_default()

CASES = [
    ("01-perfect-C001.png", "120.00", "REF-12001", 0.98, "Amount Paid: RM 120.00"),
    ("02-combo-C002.png", "150.00", "REF-15002", 0.98, "Jumlah Dibayar: RM 150.00"),
    ("03-shortpay-C003.png", "90.00", "REF-09003", 0.98, "Amount Paid: RM 90.00"),
    ("04-reused-ref-C001.png", "120.00", "USED-9999", 0.98, "Amount Paid: RM 120.00"),
    ("05-ambiguous-C004.png", "40.00", "REF-04004", 0.98, "Amaun: RM 40.00"),
    ("06-low-confidence-C001.png", "120.00", "REF-12006", 0.32, "Amount Paid: RM 120.00"),
]

manifest = {}
for filename, amount, reference, confidence, amount_line in CASES:
    img = Image.new("RGB", (840, 500), "#ffffff")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((35, 35, 805, 468), radius=24, outline="#64748b", width=3, fill="#f8fafc")
    d.text((70, 62), "DEMO / SAMPLE - NOT A BANK RECEIPT", fill="#c1272d", font=font_title)
    d.text((70, 135), "SYNTHETIC PAYMENT SLIP", fill="#0f172a", font=font_title)
    d.line((70, 187, 760, 187), fill="#94a3b8", width=2)
    d.text((72, 212), amount_line, fill="#0f172a", font=font_body)
    d.text((72, 271), "Transaction Date: 20/10/2026", fill="#0f172a", font=font_body)
    d.text((72, 329), f"Reference No: {reference}", fill="#0f172a", font=font_body)
    d.text((70, 412), "Illustrative synthetic data only. Payment NOT verified.", fill="#b91c1c", font=font_small)
    filepath = SAMPLES / filename
    img.save(filepath)
    content = filepath.read_bytes()
    manifest[hashlib.sha256(content).hexdigest()] = {
        **parse_receipt_text("\n".join((amount_line, "Transaction Date: 20/10/2026", f"Reference No: {reference}")), confidence),
        "amount": amount,
        "reference": reference,
    }

# Deliberately not registered: should never be recognized as a receipt in demo mode.
cat = Image.new("RGB", (840, 500), "#f5e8ca")
d = ImageDraw.Draw(cat)
d.text((75, 40), "NOT A PAYMENT SLIP", fill="#171717", font=font_title)
d.ellipse((260, 130, 580, 450), fill="#cc9955", outline="#664422", width=5)
d.polygon([(280, 190), (300, 80), (390, 170)], fill="#cc9955")
d.polygon([(450, 170), (550, 80), (560, 190)], fill="#cc9955")
d.ellipse((340, 250, 365, 280), fill="#171717")
d.ellipse((480, 250, 505, 280), fill="#171717")
d.text((300, 460), "DEMO CAT IMAGE", fill="#171717", font=font_small)
cat.save(SAMPLES / "07-not-a-receipt-cat.png")
(ROOT / "demo_fixtures.json").write_text(json.dumps(manifest, indent=2), encoding="utf8")
print(f"Generated {len(CASES)} registered synthetic slips + 1 nonreceipt image")
