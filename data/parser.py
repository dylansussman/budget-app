import pandas as pd
import re
from datetime import datetime
from typing import Union, List, Dict


def clean_merchant_name(description: str) -> str:
    """
    Clean merchant name by:
    - Stripping leading/trailing whitespace
    - Removing store numbers (e.g., #123)
    - Converting to title case
    
    Args:
        description: Raw merchant description from CSV
    
    Returns:
        Cleaned merchant name
    """
    # Strip whitespace
    cleaned = description.strip()
    
    # Remove store numbers (e.g., #123, #1234)
    cleaned = re.sub(r'#\d+', '', cleaned)
    
    # Remove extra whitespace
    cleaned = ' '.join(cleaned.split())
    
    # Title case (but preserve intentional all-caps like "CVS")
    # Only convert if it's all uppercase with numbers mixed in
    if cleaned and not any(c.islower() for c in cleaned):
        cleaned = cleaned.title()
    
    return cleaned


def parse_chase_csv(file_input: Union[str, object]) -> List[Dict]:
    """
    Parse Chase CSV format.
    
    Expected columns:
    Transaction Date, Post Date, Description, Category, Type, Amount, Memo
    
    Args:
        file_input: File path (str) or file-like object
    
    Returns:
        List of transaction dicts with keys:
        date, merchant, amount, raw_description, source, csv_category (optional)
    
    Raises:
        ValueError: If required columns not found
    """
    try:
        df = pd.read_csv(file_input)
    except Exception as e:
        raise ValueError(f"Failed to read CSV file: {str(e)}")
    
    # Normalize column names (strip whitespace)
    df.columns = df.columns.str.strip()
    
    # Check for required columns
    required_cols = ['Transaction Date', 'Description', 'Amount']
    found_cols = set(df.columns)
    missing_cols = [col for col in required_cols if col not in found_cols]
    
    if missing_cols:
        raise ValueError(
            f"Chase CSV parser: Missing required columns {missing_cols}. "
            f"Found columns: {list(found_cols)}"
        )
    
    # Try to detect optional category column
    category_col = None
    for col in df.columns:
        if col.lower() in ['category', 'merchant category', 'type']:
            category_col = col
            break
    
    transactions = []
    
    for _, row in df.iterrows():
        # Parse date
        try:
            trans_date = pd.to_datetime(row['Transaction Date']).date()
        except Exception:
            continue  # Skip rows with invalid dates
        
        # Get amount and flip sign (Chase uses negative for expenses)
        try:
            amount = float(row['Amount']) * -1
        except (ValueError, TypeError):
            continue  # Skip rows with invalid amounts
        
        # Clean merchant name
        raw_desc = str(row['Description']).strip()
        merchant = clean_merchant_name(raw_desc)
        
        # Extract CSV category if available
        csv_category = None
        if category_col and pd.notna(row[category_col]):
            csv_category = str(row[category_col]).strip()
            if not csv_category:
                csv_category = None
        
        transactions.append({
            'date': trans_date,
            'merchant': merchant,
            'amount': amount,
            'raw_description': raw_desc,
            'source': 'chase',
            'csv_category': csv_category
        })
    
    return transactions


def detect_column(df: pd.DataFrame, possible_names: List[str]) -> str:
    """
    Detect a column by checking for any of the possible names (case-insensitive).
    
    Args:
        df: Pandas DataFrame
        possible_names: List of possible column names to search for
    
    Returns:
        The matching column name from the DataFrame
    
    Raises:
        ValueError: If no matching column found
    """
    possible_names_lower = [name.lower() for name in possible_names]
    
    for col in df.columns:
        if col.strip().lower() in possible_names_lower:
            return col
    
    raise ValueError(f"Could not find column matching: {possible_names}")


def parse_generic_csv(file_input: Union[str, object]) -> List[Dict]:
    """
    Parse generic CSV format by auto-detecting common column names.
    
    Attempts to detect:
    - Date: 'date', 'transaction date', 'posted date'
    - Amount: 'amount', 'debit', 'transaction amount'
    - Description: 'description', 'merchant', 'payee', 'name'
    - Category: 'category', 'merchant category', 'type' (optional)
    
    Args:
        file_input: File path (str) or file-like object
    
    Returns:
        List of transaction dicts with keys:
        date, merchant, amount, raw_description, source, csv_category (optional)
    
    Raises:
        ValueError: If required columns cannot be detected
    """
    try:
        df = pd.read_csv(file_input)
    except Exception as e:
        raise ValueError(f"Failed to read CSV file: {str(e)}")
    
    # Normalize column names (strip whitespace)
    df.columns = df.columns.str.strip()
    
    # Try to detect required columns
    try:
        date_col = detect_column(df, ['date', 'transaction date', 'posted date'])
    except ValueError:
        raise ValueError(
            f"Generic CSV parser: Could not detect date column. "
            f"Found columns: {list(df.columns)}"
        )
    
    try:
        amount_col = detect_column(df, ['amount', 'debit', 'transaction amount'])
    except ValueError:
        raise ValueError(
            f"Generic CSV parser: Could not detect amount column. "
            f"Found columns: {list(df.columns)}"
        )
    
    try:
        desc_col = detect_column(df, ['description', 'merchant', 'payee', 'name'])
    except ValueError:
        raise ValueError(
            f"Generic CSV parser: Could not detect description/merchant column. "
            f"Found columns: {list(df.columns)}"
        )
    
    # Try to detect optional category column
    category_col = None
    try:
        category_col = detect_column(df, ['category', 'merchant category', 'type'])
    except ValueError:
        pass  # Category column is optional
    
    transactions = []
    
    for _, row in df.iterrows():
        # Parse date
        try:
            trans_date = pd.to_datetime(row[date_col]).date()
        except Exception:
            continue  # Skip rows with invalid dates
        
        # Get amount (assume positive = expense)
        try:
            amount = float(row[amount_col])
            # If amount is positive, assume it's an expense and negate it
            # If already negative, keep as is
            if amount > 0:
                amount = amount * -1
        except (ValueError, TypeError):
            continue  # Skip rows with invalid amounts
        
        # Clean merchant name
        raw_desc = str(row[desc_col]).strip()
        merchant = clean_merchant_name(raw_desc)
        
        # Extract CSV category if available
        csv_category = None
        if category_col and pd.notna(row[category_col]):
            csv_category = str(row[category_col]).strip()
            if not csv_category:
                csv_category = None
        
        transactions.append({
            'date': trans_date,
            'merchant': merchant,
            'amount': amount,
            'raw_description': raw_desc,
            'source': 'generic',
            'csv_category': csv_category
        })
    
    return transactions


def parse_csv(file_input: Union[str, object], source: str = "auto") -> List[Dict]:
    """
    Parse CSV file with automatic format detection or specified source.
    
    Args:
        file_input: File path (str) or file-like object
        source: One of "chase", "generic", or "auto" for automatic detection
    
    Returns:
        List of transaction dicts with keys:
        date, merchant, amount, raw_description, source
    
    Raises:
        ValueError: If parsing fails or required columns not found
    """
    source = source.lower().strip()
    
    if source == "chase":
        return parse_chase_csv(file_input)
    elif source == "generic":
        return parse_generic_csv(file_input)
    elif source == "auto":
        # Try Chase first, then fall back to generic
        try:
            return parse_chase_csv(file_input)
        except ValueError as chase_error:
            try:
                # Reset file pointer if it's a file-like object
                if hasattr(file_input, 'seek'):
                    file_input.seek(0)
                return parse_generic_csv(file_input)
            except ValueError as generic_error:
                raise ValueError(
                    f"Auto-detection failed. "
                    f"Chase parser: {str(chase_error)}. "
                    f"Generic parser: {str(generic_error)}"
                )
    else:
        raise ValueError(
            f"Unknown source: {source}. Must be one of 'chase', 'generic', or 'auto'"
        )
