import os
from datetime import datetime
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials
import statistics
from gspread_formatting import (
    format_cell_range,
    CellFormat, TextFormat, Color,
    NumberFormat, set_column_width, set_frozen,
    batch_updater
)

# Scope required for Google Sheets API
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Column headers as per spec
HEADERS = ["Transaction Date", "Post Date", "Description", "Category", "Source", "Amount"]

# Month names for tab naming
MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


def _get_credentials():
    """
    Load Google service account credentials from the file path in .env.
    
    Returns:
        Credentials object authenticated with the service account
        
    Raises:
        FileNotFoundError: If credentials file doesn't exist
        ValueError: If GOOGLE_CREDENTIALS_FILE is not set in .env
    """
    from dotenv import load_dotenv
    
    # Load .env from project root (parent directory of data/)
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)
    credentials_path = os.getenv("GOOGLE_CREDENTIALS_FILE")
    
    if not credentials_path:
        raise ValueError("GOOGLE_CREDENTIALS_FILE not set in .env")
    
    # Resolve path relative to project root if it's not absolute
    cred_file = Path(credentials_path)
    if not cred_file.is_absolute():
        cred_file = Path(__file__).parent.parent / credentials_path
    
    if not cred_file.exists():
        raise FileNotFoundError(f"Credentials file not found: {cred_file}")
    
    return Credentials.from_service_account_file(str(cred_file), scopes=SCOPES)


def _get_spreadsheet():
    """
    Open and return the Google Spreadsheet.
    
    Returns:
        gspread.Spreadsheet object
        
    Raises:
        ValueError: If GOOGLE_SHEET_ID is not set in .env
        gspread.exceptions.SpreadsheetNotFound: If sheet ID is invalid
    """
    from dotenv import load_dotenv
    
    # Load .env from project root (parent directory of data/)
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID not set in .env")
    
    credentials = _get_credentials()
    client = gspread.authorize(credentials)
    
    try:
        return client.open_by_key(sheet_id)
    except gspread.exceptions.SpreadsheetNotFound:
        raise gspread.exceptions.SpreadsheetNotFound(
            f"Spreadsheet with ID '{sheet_id}' not found. "
            "Ensure the sheet exists and the service account has access."
        )

# Month names reused from top of file (already defined as MONTH_NAMES)

def write_rolling_summary(month_summaries: dict) -> dict:
    """
    Write a rolling multi-month spending summary to a "Rolling Summary" tab.

    Args:
        month_summaries: { "2024-11": { "Groceries": 420.50, ... }, ... }
                         Keys are YYYY-MM strings, ordered oldest → newest.

    Returns:
        dict with keys:
            - sheet_url: URL to the spreadsheet
            - rows_written: Number of month rows written (excluding header/predicted)
    """
    spreadsheet = _get_spreadsheet()
    tab_name = "Rolling Summary"
    worksheet = _get_or_create_worksheet(spreadsheet, tab_name)
    worksheet.clear()

    if not month_summaries:
        return {"sheet_url": spreadsheet.url, "rows_written": 0}

    # Collect all unique categories, preserving insertion order across months
    all_categories: list[str] = []
    seen: set[str] = set()
    for monthly in month_summaries.values():
        for cat in monthly:
            if cat not in seen:
                all_categories.append(cat)
                seen.add(cat)

    # Header row
    header = ["Month"] + all_categories + ["Total"]
    rows = [header]

    # One data row per month
    month_totals: list[float] = []
    for month_key, monthly in month_summaries.items():
        date_obj = datetime.strptime(month_key, "%Y-%m")
        label = f"{MONTH_NAMES[date_obj.month - 1]} {date_obj.year}"
        row_total = sum(monthly.get(cat, 0.0) for cat in all_categories)
        month_totals.append(-row_total)
        row = [label] + [-monthly.get(cat, 0) for cat in all_categories] + [-round(row_total, 2)]
        rows.append(row)

    # Predicted row — per-category and total averages
    # Predicted row — per-category mean and median
    n = len(month_summaries)
    mean_row = ["Mean"]
    median_row = ["Median"]

    for cat in all_categories:
        cat_values = [
            m.get(cat, 0.0)
            for m in month_summaries.values()
            if m.get(cat) is not None
        ]
        mean_row.append(round(-sum(cat_values) / n, 2) if cat_values else "")
        median_row.append(round(-statistics.median(cat_values), 2) if cat_values else "")

    # Totals column for mean/median rows
    mean_row.append(round(sum(month_totals) / n, 2) if month_totals else "")
    median_row.append(round(statistics.median(month_totals), 2) if month_totals else "")

    rows.append(mean_row)
    rows.append(median_row)

    worksheet.append_rows(rows, value_input_option="RAW")

    return {
        "sheet_url": spreadsheet.url,
        "rows_written": len(month_summaries),
    }

def _format_month_tab(month: str) -> str:
    """
    Convert month string from "YYYY-MM" format to tab name format "January 2025".
    
    Args:
        month: Month in format "YYYY-MM"
        
    Returns:
        Formatted tab name like "January 2025"
    """
    date_obj = datetime.strptime(month, "%Y-%m")
    month_name = MONTH_NAMES[date_obj.month - 1]
    return f"{month_name} {date_obj.year}"


def _get_or_create_worksheet(spreadsheet, tab_name: str):
    """
    Get an existing worksheet by name, or create it if it doesn't exist.
    
    Args:
        spreadsheet: gspread.Spreadsheet object
        tab_name: Name of the worksheet
        
    Returns:
        gspread.Worksheet object
    """
    try:
        return spreadsheet.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=tab_name, rows=1, cols=len(HEADERS))


def sync_month(month: str, transactions: list[dict]) -> dict:
    """
    Sync a month's transactions to Google Sheets.
    
    Creates or overwrites a worksheet for the given month with transaction data.
    
    Args:
        month: Month in format "YYYY-MM"
        transactions: List of transaction dicts with keys: date, merchant, amount,
                     category, source, account, raw_description
                     
    Returns:
        dict with keys:
            - sheet_url: URL to the spreadsheet
            - rows_written: Number of transaction rows written (excluding header)
            
    Raises:
        ValueError: If credentials or sheet ID are not properly configured
        FileNotFoundError: If credentials file doesn't exist
        gspread.exceptions.SpreadsheetNotFound: If sheet ID is invalid
    """
    try:
        # Get spreadsheet and worksheet
        spreadsheet = _get_spreadsheet()
        tab_name = _format_month_tab(month)
        worksheet = _get_or_create_worksheet(spreadsheet, tab_name)
        
        # Clear existing content
        worksheet.clear()
        
        # Prepare data: header + transactions
        data = [HEADERS]
        
        for txn in transactions:
            row = [
                str(txn.get("transactionDate", "")),
                str(txn.get("postDate", "")),
                str(txn.get("description", "")),
                str(txn.get("category", "")),
                str(f"{txn.get('source', '')}" + (f" {txn.get('account', '').strip()}" if txn.get('account') is not None else "")),
                str(txn.get("amount", "")),
            ]
            data.append(row)
        
        # Write all data at once
        worksheet.append_rows(data, value_input_option="USER_ENTERED")
        _apply_formatting(worksheet, len(transactions)) 
        
        return {
            "sheet_url": spreadsheet.url,
            "rows_written": len(transactions)
        }
    
    except (ValueError, FileNotFoundError, gspread.exceptions.SpreadsheetNotFound) as e:
        raise e
    except Exception as e:
        raise RuntimeError(f"Error syncing to Google Sheets: {str(e)}")

def _apply_formatting(worksheet, num_rows: int):
    total_rows = num_rows + 1
    last_col = "F"

    with batch_updater(worksheet.spreadsheet) as batch:

        # Arial 12 on all cells
        batch.format_cell_range(worksheet, f"A1:{last_col}{total_rows}", CellFormat(
            textFormat=TextFormat(fontFamily="Arial", fontSize=12)
        ))

        # Bold on header row
        batch.format_cell_range(worksheet, f"A1:{last_col}1", CellFormat(
            textFormat=TextFormat(fontFamily="Arial", fontSize=12, bold=True)
        ))

        if num_rows > 0:
            # Transaction Date (A) and Post Date (B): M/D/YYYY
            for col in ["A", "B"]:
                batch.format_cell_range(worksheet, f"{col}2:{col}{total_rows}", CellFormat(
                    numberFormat=NumberFormat(type="DATE", pattern="M/D/YYYY")
                ))

            # Description (C), Category (D), Source (E): plain text
            # for col in ["C", "D", "E"]:
            #     batch.format_cell_range(worksheet, f"{col}2:{col}{total_rows}", CellFormat(
            #         numberFormat=NumberFormat(type="TEXT")
            #     ))

            # Amount (F): Accounting format
            batch.format_cell_range(worksheet, f"F2:F{total_rows}", CellFormat(
                numberFormat=NumberFormat(
                    type="NUMBER",
                    pattern='_("$"* #,##0.00_);_("$"* (#,##0.00);_("$"* "-"??_);_(@_)'
                )
            ))

    # Auto-resize all columns to fit content
    worksheet.spreadsheet.batch_update({
        "requests": [{
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": worksheet.id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": len(HEADERS)
                }
            }
        }]
    })

    # Freeze header row
    set_frozen(worksheet, rows=1)