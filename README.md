# Orbyte Role 3 — AI Payment Slip Matcher (Hackathon Starter)

**What is real in this starter?** FastAPI, image upload validation, English/Malay text parsing, duplicate-reference risk checks, invoice matching with exact cents, bounded multi-invoice (Combo Math) matching, traffic lights, and a human-review fallback.

**What is simulated?** Demo OCR returns known data for ONLY the supplied sample images (checked by SHA256), and orders/used references are synthetic. No actual bank integration, payment confirmation, reliable edited-image detection or real-life fraud verification is provided.

**What is optional?** Actual OCR via RapidOCR locally or on a custom Runpod Serverless worker. Accuracy on real receipts must be tested. Existing Runpod endpoints with different output formats are NOT plug-and-play.

## 1. Quick start — works without a Runpod account

Python 3.10+ is recommended (3.11 is tested). Open a terminal in this folder.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload --port 8000
```

PowerShell activation blocked? Use `\.venv\Scripts\python.exe -m pip install -r requirements.txt` and `\.venv\Scripts\python.exe -m uvicorn app:app --reload --port 8000` instead.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload --port 8000
```

Go to **http://127.0.0.1:8000/docs** -> `POST /analyze` -> `Try it out`.

- Set `customer_id` to `C001` and choose `samples/01-perfect-C001.png` -> GREEN.
- `C002`, `samples/02-combo-C002.png` -> GREEN with 2 invoices.
- `C003`, `samples/03-shortpay-C003.png` -> YELLOW with `short_pay_remaining=10.00`.
- `C001`, `samples/04-reused-ref-C001.png` -> RED, reference reuse risk (NOT proved fraudulent).
- `C004`, `samples/05-ambiguous-C004.png` -> YELLOW; owner chooses.
- `C001`, `samples/06-low-confidence-C001.png` -> YELLOW.
- `C001`, `samples/07-not-a-receipt-cat.png` -> YELLOW.

**This demo OCR is fixture-based, not real AI; do not imply otherwise to judges.**

## 2. Run tests

In a second terminal, with the environment activated:

```bash
python -m pytest -q
```

## 3. Switch from demo fixtures to real OCR (local)

Install the optional inference dependency (can be large):

```bash
python -m pip install -r requirements-ocr.txt
```

Set the mode **in the same terminal** before starting the server:

- Windows PowerShell: `$env:OCR_PROVIDER="rapidocr"`
- macOS/Linux: `export OCR_PROVIDER=rapidocr`

Then start `python -m uvicorn app:app --reload --port 8000`. Upload a *new* synthetic receipt image. The OCR is real, but extraction heuristics and OCR confidence may be imperfect; low confidence and missed fields go to YELLOW. The DEMO fixture tests assume `OCR_PROVIDER=demo`; switch back to demo for those tests.

**Note:** RapidOCR model weights/dependencies may be downloaded or installed automatically. A current, capable machine is recommended. Speed and accuracy may vary with receipt layout.

## 4. Connect Role 2 / Role 4

**Contract (v1):**

`POST /analyze`, `multipart/form-data`:

- field `file`: PNG/JPEG image, max 5 MB
- field `customer_id`: e.g. `C002`

Response excerpt:

```json
{
  "traffic_light": "GREEN",
  "reason_code": "COMBO_AMOUNT_MATCH",
  "message": "Multiple invoices sum to payment amount. Owner must confirm bank receipt.",
  "extracted": {"amount": "150.00", "date": "20/10/2026", "reference": "REF-15002", "confidence": 0.98},
  "matched_orders": [{"order_id": "ORD-2001", "amount_due": "60.00"}, {"order_id": "ORD-2002", "amount_due": "90.00"}],
  "short_pay_remaining": null,
  "human_approval_required": true,
  "bank_payment_verified": false
}
```

Minimal Replit/JS frontend call:

```javascript
const form = new FormData();
form.append("file", uploadedFile); // <input type="file"> File object
form.append("customer_id", "C002");
const response = await fetch("https://YOUR-API-URL/analyze", {
  method: "POST",
  body: form,
});
if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
const result = await response.json();
console.log(result.traffic_light, result.matched_orders);
```

If frontend and API are on different origins, set environment variable `FRONTEND_ORIGIN` to the *exact* deployed frontend origin and restart the API. Avoid permissive `*` CORS for any public app.

Role 4 owns orders storage, audit trail and approvals. The sample API **does not** update any payment/order state. This avoids treating OCR matches as confirmed payments.

## 5. Runpod cloud OCR — Stage 2, not required for today's demo

This project includes a **custom Runpod worker sample**. It runs RapidOCR inside Runpod (a cloud-hosted OCR engine), not a Vision LLM. To meet any explicit Vision LLM requirement, replace the worker inference with an approved VL model and keep the same JSON result schema.

1. Check official Runpod docs on packaging a custom Serverless Docker worker and endpoint. A GPU worker costs money; monitor usage and stop unused deployments.
2. Build/push a Docker image containing `Dockerfile.runpod`, `core.py`, `ocr.py`, `runpod_worker.py` and `requirements-runpod.txt`. This requires a container registry and Runpod endpoint configuration; **the zip does not deploy it for you**.
3. Create a Serverless endpoint for your image; copy its endpoint ID and API key into **server-side environment variables**, never a frontend script or repo.
4. Set `OCR_PROVIDER=runpod`, `RUNPOD_ENDPOINT_ID=...`, `RUNPOD_API_KEY=...` in the FastAPI host. Restart server.
5. API submits `image_base64` to `/runsync` and expects returned `output` to contain `{amount, date, reference, confidence, raw_text}`. If the job is not completed/returns invalid JSON, this starter safely assigns YELLOW/manual review (no silent fake result).
6. Confirm one real test request end-to-end before promoting this mode. Runpod timeout/cold start and pricing will vary.

Runpod API docs: https://docs.runpod.io/serverless/endpoints/operation-reference
Worker docs: https://docs.runpod.io/serverless/workers/handlers/overview

## 6. Who owns what (agreement with teammates)

- Role 3: `core.py`, OCR parsing, matching logic, and `ocr.py` / `runpod_worker.py`.
- Role 4: synthetic orders, API hosting, connection to Runpod, persistence, audit log and approvals.
- Role 2: staff-upload and owner-review UI, Kanban GREEN/YELLOW/RED.
- Role 5: test images, QA, edge cases and demo fallback.
- Role 1: judge pitch, disclosure of demo vs live features, privacy and human-approval narrative.

## 7. Acceptance criteria for Day 1

- [ ] `/health` responds.
- [ ] `/docs` loads in a browser.
- [ ] Perfect slip C001 is GREEN with one invoice.
- [ ] Combo slip C002 is GREEN with two invoices.
- [ ] Short-pay slip C003 is YELLOW with `10.00` shortfall.
- [ ] Duplicated reference is RED but labeled **risk**, not proof of fraud.
- [ ] Cat image is YELLOW, never auto-approved.
- [ ] No result has `bank_payment_verified: true`.

## Important limitations

This is a **synthetic hackathon prototype**, not a production financial or forensic product. Never use real bank slips or personal financial data without permission and privacy controls. The `GREEN` board column means invoice *amount* matched, NOT that payment was received. Approval must be done by an authorized human after checking independent bank records. Do not label an altered image 'fraudulent' based only on OCR or blurry fonts.
