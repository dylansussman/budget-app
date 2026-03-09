import os
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

# Scope required for Google Sheets API
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Column headers as per spec
HEADERS = ["Date", "Merchant", "Amount", "Category", "Source", "Account", "Notes"]

# Month names for tab naming
MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
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


def _format_month_tab(month: str) -> str:
    """
    Convert month string from "YYYY-MM" format to tab name format "Jan 2025".
    
    Args:
        month: Month in format "YYYY-MM"
        
    Returns:
        Formatted tab name like "Jan 2025"
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
                str(txn.get("date", "")),
                str(txn.get("merchant", "")),
                str(txn.get("amount", "")),
                str(txn.get("category", "")),
                str(txn.get("source", "")),
                str(txn.get("account", "")),
                str(txn.get("raw_description", ""))  # Maps to Notes column
            ]
            data.append(row)
        
        # Write all data at once
        worksheet.append_rows(data, value_input_option="RAW")
        
        return {
            "sheet_url": spreadsheet.url,
            "rows_written": len(transactions)
        }
    
    except (ValueError, FileNotFoundError, gspread.exceptions.SpreadsheetNotFound) as e:
        raise e
    except Exception as e:
        raise RuntimeError(f"Error syncing to Google Sheets: {str(e)}")
