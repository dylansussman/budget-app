# Copilot Chat Prompts — Budget App

Paste these into **VS Code Copilot Chat** (`Ctrl+Shift+I`) in order.
Each prompt is self-contained. Always attach the SPEC.md as context using `#file:SPEC.md`.

---

## 0. Project Bootstrap

**Run this first in your terminal before opening Copilot:**
```bash
mkdir budget-app && cd budget-app
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install fastapi uvicorn[standard] sqlalchemy python-multipart pandas gspread google-auth python-dotenv
mkdir data frontend
touch main.py parser.py database.py categorizer.py sheets_sync.py categories.json .env
```

---

## 1. Database Layer

> Paste into Copilot Chat with `#file:SPEC.md` attached

```
Using #file:SPEC.md as the specification, create database.py.

It should:
- Use SQLAlchemy with a SQLite backend
- Define a Transaction model with all columns from the schema in the spec
- Include an `import_id` field that is a SHA256 hash of (date + merchant + amount) used for deduplication
- Expose these functions:
    - init_db() — creates tables if they don't exist
    - insert_transactions(transactions: list[dict]) -> dict with keys imported and skipped_duplicates
    - get_transactions(month: str, category: str = None, source: str = None) -> list
    - update_category(transaction_id: int, category: str) -> bool
    - get_monthly_summary(month: str) -> dict of category -> total_amount
- Load DATABASE_URL from .env via python-dotenv
```

---

## 2. CSV Parser

> Paste into Copilot Chat with `#file:SPEC.md` attached

```
Using #file:SPEC.md as the specification, create parser.py.

It should:
- Accept a file path or file-like object and a source hint (e.g. "chase", "auto")
- Implement a Chase-specific parser matching the column format in the spec
    - Flip the sign on Amount (Chase uses negative for expenses)
    - Clean merchant names: strip store numbers, uppercase noise, and leading/trailing whitespace
- Implement a generic fallback parser that attempts to detect date/amount/description columns
  by checking for common header name variants (case-insensitive)
- Return a list of dicts with keys: date, merchant, amount, raw_description, source
- Raise a clear ValueError if required columns cannot be detected, including which headers were found
- Use pandas for CSV reading
```

---

## 3. Categorizer

> Paste into Copilot Chat with `#file:SPEC.md` attached

```
Using #file:SPEC.md as the specification, create categorizer.py.

It should:
- Load keyword mappings from categories.json
- Expose a function categorize(raw_description: str) -> str
    - Lowercase the description
    - Iterate categories in order, check if any keyword is a substring match
    - Return the first matching category name
    - Return "Other" if no match
- Expose get_categories() -> dict to read the full mapping
- Expose update_categories(new_mapping: dict) -> None to overwrite categories.json
- Include a default categories.json content matching the spec if the file doesn't exist
```

---

## 4. Google Sheets Sync

> Paste into Copilot Chat with `#file:SPEC.md` attached

```
Using #file:SPEC.md as the specification, create sheets_sync.py.

It should:
- Authenticate using a Google service account credentials file (path from .env as GOOGLE_CREDENTIALS_FILE)
- Open the spreadsheet by ID (from .env as GOOGLE_SHEET_ID)
- Expose sync_month(month: str, transactions: list[dict]) -> dict with keys sheet_url and rows_written
    - month is in format "YYYY-MM"
    - Tab name format: "Jan 2025", "Feb 2025", etc.
    - If the tab already exists, clear and overwrite it
    - If it doesn't exist, create it
    - Write a header row: Date, Merchant, Amount, Category, Source, Account, Notes
    - Write all transaction rows after the header
    - Return the spreadsheet URL and number of rows written
- Use gspread library
- Include clear error handling if credentials file is missing or sheet ID is invalid
```

---

## 5. FastAPI Backend

> Paste into Copilot Chat with `#file:SPEC.md` attached

```
Using #file:SPEC.md as the specification, create main.py.

It should:
- Create a FastAPI app that serves the frontend/index.html at GET /
- Mount the frontend/ directory as a static files directory
- Call init_db() on startup
- Implement all API routes from the spec:
    - POST /upload — accepts multiple CSV files, uses parser.py + categorizer.py + database.py
    - GET /transactions — supports month, category, source query params
    - PATCH /transactions/{id} — updates category
    - GET /summary — returns monthly spend by category
    - POST /sync — calls sheets_sync.py for the given month
    - GET /categories — returns current category mappings
    - PATCH /categories — updates category mappings
- Add CORS middleware allowing localhost origins
- Return consistent JSON error responses with a "detail" key
- Load environment variables from .env using python-dotenv
```

---

## 6. Frontend UI

> Paste into Copilot Chat with `#file:SPEC.md` attached

```
Using #file:SPEC.md as the specification, create frontend/index.html as a single self-contained HTML file.

Requirements:
- No frameworks, no build step — vanilla HTML, CSS, and JavaScript only
- Clean, modern UI with a dark sidebar and light main content area
- Drag-and-drop zone at the top for dropping one or more CSV files
    - Show a per-file result after upload: "✓ 42 imported, 3 skipped"
    - Show errors inline if a file fails to parse
- Month selector dropdown (YYYY-MM format, auto-populated from available data)
- Category filter dropdown
- Transactions table with columns: Date, Merchant, Amount, Category (inline editable dropdown), Source
    - Category dropdown calls PATCH /transactions/{id} on change
    - Color-code rows by category using soft background colors
- Monthly summary panel: show total spend per category as a simple bar list
- "Sync to Google Sheets" button that calls POST /sync for the selected month
    - Show success toast with a link to the sheet on completion
- Toast notification system (top-right corner, auto-dismiss after 4 seconds)
- All API calls to relative URLs (e.g. /upload, /transactions)
```

---

## 7. Final Wiring Check

> Paste into Copilot Chat after all files are created

```
Review all files in this project (main.py, parser.py, database.py, categorizer.py, sheets_sync.py, frontend/index.html) and:

1. Verify all imports are consistent and all internal function calls match actual function signatures
2. Check that the Transaction SQLAlchemy model fields match what parser.py returns and what the API routes expect
3. Identify any missing error handling that could cause silent failures during CSV upload
4. Generate the final requirements.txt based on actual imports used
5. Generate a .env.example file with all required environment variable keys and placeholder values
6. Generate a README.md with setup instructions matching the spec
```

---

## Tips for Using These Prompts

- **Always attach `#file:SPEC.md`** — Copilot uses it as ground truth
- **Generate one file at a time** — don't ask for everything at once
- If Copilot drifts from the spec, paste the relevant spec section directly into the prompt
- Use `@workspace` in Copilot Chat after all files exist to do cross-file reviews (Prompt 7)
- Run `uvicorn main:app --reload` after each file is generated and fix any import errors before moving on