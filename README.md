# TODOS
- Have monthly summary update reload automatically (not only on month change or page reload)
- When adding a transaction from the UI, and adding to different month than what is currently being filtered/displayed, bring user to correct filtered page with month that transaction was just added to (and make sure to reload so month transaction filter dropdown updates or put a listener in the dropdown itself to auto update)
- When adding a transaction from the UI, if there is the user selects a category, don't have it try get categorized when inserting
   - Will probably need a flag of some kind
- Make transactions editable from UI table
- Add auto reload for transaction summary so that when changes are made via the ui, the monthly summary section auto updates
- In add modal, when a date is clicked, close the calendar popup
   - According to Claude, this is no workaround in Safari with browser native date picker, so need to import a third party library date picker

# Budget App

A locally-hosted web application for personal budget management. Upload transaction CSVs, automatically categorize spending, view monthly summaries, and sync to Google Sheets.

## Features

- **CSV Upload**: Drag-and-drop upload with support for Chase and generic CSV formats
- **Auto-Categorization**: Automatic transaction categorization based on merchant keywords
- **Category Management**: Override auto-assigned categories on a per-transaction basis
- **Monthly Summaries**: View spending breakdown by category each month
- **Google Sheets Sync**: Sync transactions to Google Sheets for external analysis
- **Month Filtering**: View and manage transactions by month
- **Responsive Frontend**: Single-page application with vanilla HTML/CSS/JavaScript

## Installation

### 1. Create and activate a virtual environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Google Cloud Setup (Optional)

If you want to enable Google Sheets sync:

1. Create a Google Cloud project:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project

2. Enable the Google Sheets API:
   - In the Cloud Console, navigate to "APIs & Services" > "Library"
   - Search for "Google Sheets API" and enable it

3. Create a service account:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "Service Account"
   - Complete the form and create the service account
   - Under the service account, create a JSON key
   - Download and save the JSON file as `credentials.json` in the project root

4. Share your Google Sheet:
   - Create a Google Sheet to store your transactions
   - Copy the spreadsheet ID from the URL: `https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit`
   - Share the sheet with the service account email address (found in the JSON key file)

### 4. Configuration

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:
```
GOOGLE_SHEET_ID=your_actual_spreadsheet_id
GOOGLE_CREDENTIALS_FILE=credentials.json
DATABASE_URL=sqlite:///./data/budget.db
```

## Running the Application

Start the development server:

```bash
uvicorn main:app --reload
```

The application will be available at `http://localhost:8000`

## Usage

### Uploading Transactions

1. Navigate to the "Upload" section
2. Drag and drop CSV files or click to select files
3. Supported formats:
   - Chase Bank exports (CSV with "Transaction Date", "Description", "Amount" columns)
   - Generic CSV format (auto-detects common column names)

### Managing Transactions

1. Use the month selector to view transactions from a specific month
2. Filter by category or source using the dropdown filters
3. Click on a transaction row and select a category from the dropdown to override the auto-assignment

### Viewing Summaries

1. The monthly summary shows total spending by category
2. Each category displays the total amount spent for the current month

### Syncing to Google Sheets

1. Click the "Sync to Google Sheets" button
2. Transactions for the selected month will be written to a new worksheet (e.g., "Jan 2025")
3. Existing worksheets for that month will be overwritten

## Project Structure

```
budget-app/
├── main.py                 # FastAPI application and endpoints
├── parser.py              # CSV parsing logic
├── categorizer.py         # Auto-categorization engine
├── database.py            # SQLAlchemy ORM and database operations
├── sheets_sync.py         # Google Sheets integration
├── categories.json        # Category keyword mappings
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
├── budget.db             # SQLite database (created on first run)
├── credentials.json      # Google service account key (create manually)
└── frontend/
    ├── index.html        # Main HTML structure
    ├── style.css         # Styling
    └── script.js         # Client-side logic
```

## API Endpoints

- `POST /upload` - Upload CSV files
- `GET /transactions` - Get transactions with optional filtering (month, category, source)
- `PATCH /transactions/{id}` - Update a transaction's category
- `GET /summary` - Get monthly spending summary by category
- `POST /sync` - Sync transactions to Google Sheets
- `GET /categories` - Get all categories and keyword mappings
- `PATCH /categories` - Update category keyword mappings

## Supported CSV Formats

### Chase Bank Format
- Transaction Date
- Description
- Amount
- (Optional: other columns are ignored)

### Generic Format
Auto-detects columns containing:
- Date: "date", "Date", "transaction date", "post date"
- Merchant: "merchant", "description", "transaction"
- Amount: "amount", "debit", "credit"

## Troubleshooting

### "ModuleNotFoundError" when running
- Ensure you've activated the virtual environment: `source venv/bin/activate`
- Ensure dependencies are installed: `pip install -r requirements.txt`

### Google Sheets sync fails
- Verify `credentials.json` exists in the project root
- Verify the service account email has access to your Google Sheet
- Check that `GOOGLE_SHEET_ID` is correct in `.env`

### CSV upload fails
- Ensure the file is in CSV format (`.csv` extension)
- Verify the CSV contains the required columns
- Check that the file is not empty

## License

This project is provided as-is for personal use.
