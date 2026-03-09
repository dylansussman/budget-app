# Budget App — Project Specification

## Overview
A locally-hosted web application for personal budget management. The user drops CSV files
exported from credit card providers (primarily Chase, with support for other formats) into a
drag-and-drop UI. Transactions are parsed, normalized, stored in a local SQLite database, and
synced to Google Sheets — one tab per calendar month.

---

## Goals
- Eliminate manual copy/paste from bank CSVs into Google Sheets
- Centralize all transactions in a local SQLite database
- Automatically detect spending categories with manual override support
- Push clean, deduplicated data to Google Sheets (one tab per month)
- Keep Google Sheets as the primary visualization/reporting layer

---

## Tech Stack

| Layer        | Technology                          |
|--------------|-------------------------------------|
| Backend      | Python 3.11+, FastAPI               |
| Database     | SQLite (via SQLAlchemy ORM)         |
| Frontend     | Single-page HTML + Vanilla JS       |
| Sheets Sync  | Google Sheets API v4 (gspread lib)  |
| Auth         | Google OAuth2 (service account)     |
| Dev tooling  | VS Code + GitHub Copilot            |

---

## Project Structure

```
budget-app/
├── main.py                 # FastAPI app entry point, all routes
├── parser.py               # CSV ingestion and normalization per bank format
├── database.py             # SQLAlchemy models, DB init, CRUD operations
├── categorizer.py          # Keyword-based auto-categorization engine
├── sheets_sync.py          # Google Sheets API integration
├── frontend/
│   └── index.html          # Drag-and-drop UI (single file, no build step)
├── data/
│   └── budget.db           # SQLite database (auto-created on first run)
├── categories.json         # User-editable keyword → category mapping
├── credentials.json        # Google service account key (NEVER commit this)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Database Schema

### `transactions` table

| Column        | Type     | Notes                                      |
|---------------|----------|--------------------------------------------|
| id            | INTEGER  | Primary key, autoincrement                 |
| date          | DATE     | Transaction date                           |
| merchant      | TEXT     | Cleaned merchant name                      |
| amount        | REAL     | Positive = expense, Negative = credit/refund |
| category      | TEXT     | Auto-assigned or user-overridden           |
| source        | TEXT     | Bank/card source (e.g. "chase", "amex")    |
| account       | TEXT     | Optional: last 4 digits or account label  |
| raw_description | TEXT   | Original unmodified description from CSV  |
| import_id     | TEXT     | Hash of (date+merchant+amount) for dedup  |
| created_at    | DATETIME | Timestamp of import                        |

---

## CSV Format Support

### Chase (primary)
```
Transaction Date, Post Date, Description, Category, Type, Amount, Memo
01/15/2025, 01/16/2025, WHOLE FOODS #123, Food & Drink, Sale, -54.32,
```
- Date column: `Transaction Date`
- Amount: negative = expense (flip sign on ingest)
- Description → `merchant` after cleanup

### Generic / Other Banks
Support a fallback parser that attempts to detect columns by common header names:
- Date: `date`, `transaction date`, `posted date`
- Amount: `amount`, `debit`, `transaction amount`
- Description: `description`, `merchant`, `payee`, `name`

If headers can't be auto-detected, surface an error to the user with the actual headers found.

---

## Auto-Categorization

File: `categories.json`

```json
{
  "Groceries": ["whole foods", "trader joe", "jewel", "marianos", "aldi", "costco"],
  "Dining": ["mcdonald", "chipotle", "doordash", "grubhub", "uber eats", "starbucks"],
  "Gas": ["shell", "bp", "mobil", "exxon", "speedway", "marathon"],
  "Utilities": ["comed", "nicor", "att", "verizon", "comcast", "xfinity"],
  "Shopping": ["amazon", "target", "walmart", "best buy", "apple"],
  "Travel": ["united", "delta", "american air", "marriott", "hilton", "airbnb", "uber", "lyft"],
  "Health": ["cvs", "walgreens", "pharmacy", "doctor", "dental", "vision"],
  "Entertainment": ["netflix", "spotify", "hulu", "disney", "amc", "ticketmaster"],
  "Income": ["payroll", "direct deposit", "zelle from", "venmo from"],
  "Other": []
}
```

**Logic:**
1. Lowercase the `raw_description`
2. Check each keyword list in order
3. First match wins → assign category
4. No match → assign `"Other"`
5. User can override category per-transaction in the UI (saved to DB)

---

## API Endpoints

### `POST /upload`
- Accepts: `multipart/form-data` with one or more CSV files
- Returns: `{ imported: N, skipped_duplicates: N, errors: [...] }`
- Behavior: parse → categorize → dedup by `import_id` → insert to DB

### `GET /transactions`
- Query params: `month` (YYYY-MM), `category`, `source`
- Returns: paginated list of transactions

### `PATCH /transactions/{id}`
- Body: `{ category: "Dining" }`
- Allows manual category override

### `GET /summary`
- Query param: `month` (YYYY-MM)
- Returns: spend by category for that month

### `POST /sync`
- Body: `{ month: "2025-01" }`
- Pushes that month's transactions to Google Sheets as a new tab named `Jan 2025`
- Returns: `{ sheet_url: "...", rows_written: N }`

### `GET /categories`
- Returns the full categories.json mapping

### `PATCH /categories`
- Updates categories.json with new keyword mappings

---

## Google Sheets Sync Behavior

- Auth: Google service account with Editor access to the target spreadsheet
- Target sheet ID stored in a `.env` file as `GOOGLE_SHEET_ID`
- Tab naming: `Jan 2025`, `Feb 2025`, etc.
- If a tab for that month already exists: **overwrite it** (do not append)
- Columns written to sheet:

| Date | Merchant | Amount | Category | Source | Account | Notes |
|------|----------|--------|----------|--------|---------|-------|

- After sync, user can continue using Sheets for pivot tables, charts, and SUMIF formulas

---

## Frontend (frontend/index.html)

Single HTML file, no build step, no frameworks.

### Features
- Drag-and-drop zone for CSV files (multiple at once)
- Upload status with per-file results (imported / skipped / errors)
- Transactions table with:
  - Month filter dropdown
  - Category filter dropdown
  - Inline category override (dropdown, saves on change)
  - Color coding by category
- Monthly summary card (total spend per category)
- "Sync to Google Sheets" button (triggers POST /sync for selected month)
- Toast notifications for success/error states

---

## Environment Variables (.env)

```
GOOGLE_SHEET_ID=your_spreadsheet_id_here
GOOGLE_CREDENTIALS_FILE=credentials.json
DATABASE_URL=sqlite:///./data/budget.db
```

---

## Setup Steps (for README)

1. `python -m venv venv && source venv/bin/activate`
2. `pip install -r requirements.txt`
3. Create a Google Cloud project → enable Sheets API → download service account JSON → save as `credentials.json`
4. Share your Google Sheet with the service account email
5. Copy `.env.example` to `.env` and fill in `GOOGLE_SHEET_ID`
6. `uvicorn main:app --reload`
7. Open `http://localhost:8000`

---

## requirements.txt

```
fastapi
uvicorn[standard]
sqlalchemy
python-multipart
pandas
gspread
google-auth
python-dotenv
```

---

## Out of Scope (v1)
- User authentication (single-user local app)
- Multiple budget profiles
- Recurring transaction detection
- Mobile UI
- Automatic CSV download from banks