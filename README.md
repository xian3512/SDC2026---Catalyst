# Orbyte SlipMatch — Instant Chat-to-Bill Generator & Automated DuitNow Receipt Validator

An intelligent automation product built for the Orbyte ecosystem that converts unstructured WhatsApp chat orders into clean bills and executes automated three-way receipt validation against bank records to eliminate manual bookkeeping and e-commerce fraud for SMEs.

## Team Information

| Field | Details |
| --- | --- |
| **Team Name** | Catalyst |
| **Team Domain** | Domain 2 (Orbyte Smart SME Challenge) |
| **SDG Track (1–17)** | SDG 8 — Decent Work and Economic Growth <br> SDG 9 — Industry, Innovation and Infrastructure |
| **Team Leader** | Ang Yi Xian |
| **University** | Universiti Malaysia Perlis (UniMAP) |
| **Number of Members** | 5 |

## Links

| Resource | Link |
| --- | --- |
| GitHub Repository | https://github.com/xian3512/SDC2026---Catalyst/ |
| Replit Project | https://sdc-2026-catalyst.replit.app/ |
| Live Demo | https://sdc-2026-catalyst.replit.app/ |
| RunPod Endpoint | https://console.runpod.io/serverless/user/endpoint/6tzygt6b8mtjgt |
| Slide Deck | https://docs.google.com/presentation/d/1uPIV80W6lJlcyAd56q7wniDFDWvIp7h5Lio-QUHiZ1Q/edit?usp=sharing |
| Demo Video | https://youtu.be/mlHd02dt9vE?si=YijI3xPMP7BqXwH_ |

## Overview

### Problem
Micro and small enterprises (MSMEs) in Malaysia rely heavily on manual, disconnected workflows across WhatsApp, spreadsheets, and personal banking apps. Owners spend hours every evening parsing unstructured chat messages, calculating totals, typing invoices, and cross-referencing payment screenshots by eye—leaving them prone to arithmetic errors and vulnerable to e-commerce fraud such as edited transfer receipts and reused transaction reference numbers.

### Solution
Orbyte SlipMatch applies AI strictly where it adds value: GenAI text parsing to extract order details from WhatsApp messages and RunPod Serverless OCR Vision AI to read payment slips. Its core decision engine executes a strict Three-Way Match (comparing the payment slip against the open order and the real bank statement) combined with Combo-Math reconciliation. Results are populated onto an intuitive traffic-light Kanban dashboard, ensuring merchants maintain complete control via one-click approvals and immutable audit logging.

### Key Features
- **Instant Chat-to-Bill**: Parses unstructured WhatsApp messages in Bahasa Malaysia, English, or Manglish to automatically extract items, quantities, and generate structured order IDs.
- **Automated DuitNow Receipt Validator**: Uses high-accuracy RunPod OCR Vision AI to extract transfer amounts, timestamps, and alphanumeric bank reference numbers from payment screenshots.
- **Three-Way Match & Traffic-Light Kanban**: Automatically cross-references payment slips, orders, and bank records, categorizing transactions into Green (Verified), Yellow (Short-pay/Check), and Red (Fraud Risk).
- **Immutable Audit Trail**: Records every staff upload, AI parsing result, and owner approval with exact timestamps for complete financial accountability.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Frontend | Replit Web UI / HTML / CSS |
| Backend | Python / FastAPI |
| Database | SQLite |
| AI / Compute | RunPod Serverless GPU (OCR Vision AI & Text Parsing) |
| Hosting / Dev | Replit |

## Project Structure

```text
.
├── docs/                                   # Screenshots, diagrams & assets
├── runpod/
│   └── handler.py                          # RunPod serverless handler (GPU OCR workload)
├── src/
│   ├── main.py                             # Master FastAPI server & routing
│   └── ocr.py                              # OCR extraction helper module
├── submission/                             # Required hackathon submission documents
│   ├── SDC2026_Catalyst_Preliminary.pdf      # Preliminary proposal
│   ├── SDC2026_Catalyst_TechDeclaration.pdf  # Technical & tools declaration
│   ├── SDC2026_Catalyst_Replit_POU.pdf       # Replit proof of use
│   └── SDC2026_Catalyst_Runpod_POU.pdf       # RunPod proof of use
├── tests/
│   └── test_utils.py                       # Unit tests
├── .env.example                            # Example environment variables template
├── .gitignore
├── .replit                                 # Replit run configuration
├── LICENSE                                 # Apache License 2.0
├── requirements.txt                        # Python dependencies
└── README.md


## Architecture

    User → Replit (FastAPI App & UI) → RunPod Serverless Endpoint (OCR Vision AI)
           |
           └──→ Three-Way Matching Logic & Database → Traffic-Light Kanban Approval


## How to Run

### Option 1 — Run on Replit (Recommended)

1. Open the Live Replit Deployment.
2. Alternatively, import this repository into Replit via Create Repl → Import from GitHub.
3. In your Replit Secrets tab, verify the environment variables are configured:
   * `RUNPOD_API_KEY: rpa_6I5A57O3NDLIRATSD9E66PBNDHZ3N8BK8TAGP1OB1pxhdg`
   * `RUNPOD_ENDPOINT_ID: 6tzygt6b8mtjgt`
   * `SLIPMATCH_OWNER_KEY: demo-owner-123`
   * `OCR_PROVIDER: runpod`
4. Click Run to boot up the FastAPI server via .replit.


### Option 2 — Run Locally
# 1. Clone the repository
git clone [https://github.com/xian3512/SDC2026---Catalyst.git](https://github.com/xian3512/SDC2026---Catalyst.git)
cd SDC2026---Catalyst

# 2. Create and activate a virtual environment
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate
# On macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env        # Open .env and configure your keys

# 5. Run the application
python src/main.py

## Run Tests

    python -m uvicorn main:app --reload --port 8000


## How We Use Replit *(Required)*

- **Development:** Collaborative project coding, backend FastAPI route handling, and UI prototyping.
- **Hosting:** The FastAPI application is deployed and hosted on Replit for live preview and judge access.
- **Secrets:** Secure storage of environment credentials (`RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`) via Replit Secrets.

Proof of use: `submission/SDC2026_Catalyst_Replit_POU.pdf`

## How We Use RunPod *(Required)*

- **Workload:** High-accuracy OCR neural model inference for processing payment slip images, extracting transfer metadata, and performing tamper detection.
- **Setup:** `runpod/handler.py` is deployed as a **RunPod Serverless Endpoint**(6tzygt6b8mtjgt).
- **Integration:** The FastAPI application dispatches image processing requests to the endpoint using `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID`.

Proof of use: `submission/SDC2026_Catalyst_Runpod_POU.pdf`

## Challenges & Learnings
- **Challenge:** Handling noisy, multi-lingual WhatsApp order phrasing (BM, English, Manglish) and verifying payment receipts across varied bank and e-wallet formats against real bank statements.
- **Learning:** Combining GenAI text extraction with strict rule-based matching (Three-Way Match and Combo-Math) guarantees deterministic financial accuracy while keeping merchants in total control of approvals.

## Future Improvements
- [ ] Live bank feed API integration
- [ ] Automated WhatsApp customer reminder messaging for short-pays

## Team

| Name | Role | GitHub |
| --- | --- | --- |
| Ang Yi Xian | Team Lead / Backend / AI | @xian3512 |
| Evelyn Leong Yee Ying | Database / Integration | @leongyyevelyn-ux |
| Goh Zi Wei | Backend | @ziwei0501 |
| Loo Zi Yan | Frontend | @loozy2003 |
| Wong Kai Yek | Demo / Database | @KaiYek |

## Submission Checklist
- [x] Team name, domain (Domain 2) and SDG track filled in
- [x] Slide deck link added
- [x] Demo video link added
- [x] Replit used, with proof of use in `submission/`
- [x] RunPod used, with proof of use in `submission/`
- [x] Preliminary submission completed (`SDC2026_Catalyst_Preliminary.pdf`)
- [x] Technology declaration completed (`SDC2026_Catalyst_TechDeclaration.pdf`)
- [x] Submission files renamed with team name (`SDC2026_Catalyst_*`)
- [x] "How to Run" steps verified
- [x] No API keys or secrets committed to the repository

## License
This project is licensed under the Apache License 2.0.
