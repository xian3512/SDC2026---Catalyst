# Orbyte SlipMatch — Instant Chat-to-Bill Generator & Automated DuitNow Receipt Validator

An intelligent automation product for the Orbyte ecosystem that converts WhatsApp chat orders into bills and performs automated three-way receipt validation against bank records to eliminate manual bookkeeping and e-commerce fraud for SMEs.

## Team Information

| Field | Details |
| --- | --- |
| **Team Name** | Catalyst |
| **Team Domain** | Domain 2 |
| **SDG Track (1–17)** | SDG 8 - Decent Work and Economic Growth <br> SDG 9 - Industry, Innovation and Infrastructure |
| **Team Leader** | Ang Yi Xian |
| **University** | Universiti Malaysia Perlis |
| **Number of Members** | 5 |

## Links

| Resource | Link |
| --- | --- |
| GitHub Repository | https://github.com/your-username/your-project |
| Replit Project | https://replit.com/@your-username/your-project |
| Live Demo | https://your-project.replit.app |
| RunPod Endpoint | https://api.runpod.ai/v2/your-endpoint-id |
| Slide Deck | https://example.com/slides |
| Demo Video | https://example.com/demo-video |

## Overview

### Problem
Micro and small enterprises (MSMEs) rely heavily on manual, disconnected workflows across WhatsApp, spreadsheets, and personal banking apps to manage orders and reconcile payments. Owners waste hours every evening parsing unstructured chats and checking bank screenshots, leading to calculation errors and high vulnerability to e-commerce fraud such as edited transfer receipts and reused transaction references.

### Solution
Orbyte SlipMatch applies AI strictly where it adds value—using GenAI text parsing to convert unstructured WhatsApp orders into clean bills and RunPod Serverless OCR Vision AI to read payment slips. Robust rule-based three-way matching logic cross-references slips against orders and bank statements, sorting transactions into a traffic-light Kanban dashboard while keeping merchants in complete control via one-click approval and immutable audit logging.

### Key Features
- **Chat-to-Bill Generator**: Instantly converts unstructured WhatsApp orders in BM, English, or Manglish into clean structured bills with order IDs.
- **Automated Receipt Validator**: Uses Vision AI and OCR to extract transfer amounts, dates, and reference numbers for automated verification.
- **Traffic-Light Kanban & Audit Trail**: Sorts transactions into Green (verified), Yellow (short-pay/check), and Red (fraud risk) for merchant approval and secure logging.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Frontend | HTML / Replit Web UI |
| Backend | Python / FastAPI |
| Database | SQLite |
| AI / Compute | RunPod (GPU) / GenAI OCR & Text Parsing |
| Hosting / Dev | Replit |

## Project Structure

    .
    ├── docs/                                     # Screenshots, diagrams
    ├── runpod/
    │   └── handler.py                            # RunPod serverless handler (GPU workload)
    ├── src/
    │   ├── main.py                               # Application entry point
    │   └── utils.py                              # Helper functions
    ├── submission/                               # Required submission documents
    │   ├── SDC2026_Catalyst_Preliminary.pdf      # Preliminary submission
    │   ├── SDC2026_Catalyst_TechDeclaration.pdf  # Technology declaration
    │   ├── SDC2026_Catalyst_Replit_POU.pdf       # Replit proof of use
    │   └── SDC2026_Catalyst_Runpod_POU.pdf       # RunPod proof of use
    ├── tests/
    │   └── test_utils.py                         # Unit tests
    ├── .env.example                              # Example environment variables
    ├── .gitignore
    ├── .replit                                   # Replit run configuration
    ├── LICENSE
    ├── requirements.txt                          # Python dependencies
    └── README.md


## Architecture

User → Replit (FastAPI App & UI) → RunPod Serverless Endpoint (OCR Vision AI)
           |
           └──→ Three-Way Matching Logic & Database → Traffic-Light Kanban Approval

## How to Run

### Option 1 — Run on Replit (Recommended)

1. Open the Replit Project, or import this repository via **Create Repl → Import from GitHub**.
2. Open the **Secrets** tab and add the variables listed in `.env.example`:
   * `RUNPOD_API_KEY`
   * `RUNPOD_ENDPOINT_ID`
3. Click **Run**. Replit uses the `.replit` file to start `python src/main.py`.

### Option 2 — Run Locally

    # 1. Clone the repository
    git clone https://github.com/your-username/your-project.git
    cd your-project

    # 2. Create and activate a virtual environment
    python -m venv venv
    source venv/bin/activate       # Windows: venv\Scripts\activate

    # 3. Install dependencies
    pip install -r requirements.txt

    # 4. Configure environment variables
    cp .env.example .env           # then fill in your values

    # 5. Run the app
    python src/main.py


## Run Tests

    python -m uvicorn main:app --reload --port 8000


## How We Use Replit *(Required)*

Describe how your team used Replit. For example:
- **Development:** Collaborative project coding, backend FastAPI route handling, and UI prototyping.
- **Hosting:** The FastAPI application is deployed and hosted on Replit for live preview and judge access.
- **Secrets:** Secure storage of environment credentials (`RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`) via Replit Secrets.

Proof of use: `submission/SDC2026_Catalyst_Replit_POU.pdf`

## How We Use RunPod *(Required)*

Describe how your team used RunPod. For example:
- **Workload:** High-accuracy OCR neural model inference for processing payment slip images, extracting transfer metadata, and performing tamper detection.
- **Setup:** `runpod/handler.py` is deployed as a **RunPod Serverless Endpoint**.
- **Integration:** The FastAPI application dispatches image processing requests to the endpoint using `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID`.

Example request:

    curl -X POST https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/runsync \
      -H "Authorization: Bearer $RUNPOD_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{"input": {"prompt": "Hello"}}'

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
| Ang Yi Xian | Team Lead | @username |
| Evelyn Leong Yee Ying | Frontend | @username |
| Goh Zi Wei | Backend | @username |
| Loo Zi Yan | AI / RunPod | @username |
| Wong Kai Yek | AI / RunPod | @username |

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
