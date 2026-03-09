import logging
from sqlalchemy.orm import Session

# Configure logging
logger = logging.getLogger(__name__)


def get_category_id_by_csv_name(session: Session, csv_category: str) -> int:
    """
    Resolve CSV category name to app category_id via CSVCategoryMap.
    
    Args:
        session: SQLAlchemy session
        csv_category: CSV category name from CSV file
    
    Returns:
        Category ID if found, else None
    """
    from .database import CSVCategoryMap
    
    if not csv_category or not isinstance(csv_category, str):
        return None
    
    # Case-insensitive lookup
    mapping = session.query(CSVCategoryMap).filter(
        CSVCategoryMap.csv_category_name.ilike(csv_category)
    ).first()
    
    if mapping:
        logger.debug(f"CSV category mapping found: '{csv_category}' → category_id={mapping.category_id}")
        return mapping.category_id
    
    return None


def get_category_id_by_name(session: Session, category_name: str) -> int:
    """
    Resolve app category name to category_id.
    
    Args:
        session: SQLAlchemy session
        category_name: Category name to resolve
    
    Returns:
        Category ID if found, else ID of "Other" category
    """
    from .database import Category
    
    category = session.query(Category).filter_by(name=category_name).first()
    
    if category:
        logger.debug(f"Category name resolved: '{category_name}' → category_id={category.id}")
        return category.id
    
    # Fallback to "Other"
    other_category = session.query(Category).filter_by(name="Other").first()
    if other_category:
        logger.warning(f"Failed to resolve category name: '{category_name}', using 'Other' as fallback")
        return other_category.id
    
    logger.error(f"Failed to resolve category name: '{category_name}' and 'Other' category not found!")
    raise ValueError("'Other' category not found in database")


def categorize(session: Session, raw_description: str, csv_category: str = None) -> int:
    """
    Categorize a transaction using two-tier priority logic with logging.
    
    Tier 1: CSV category mapping (highest priority)
    Tier 2: Keyword matching (fallback)
    
    Args:
        session: SQLAlchemy session
        raw_description: Transaction description
        csv_category: Optional CSV category name from CSV file
    
    Returns:
        Category ID (integer, never a string)
    """
    from .database import Category, Keyword
    
    result_category_id = None
    
    # Tier 1: CSV category mapping
    if csv_category:
        result_category_id = get_category_id_by_csv_name(session, csv_category)
        if result_category_id:
            logger.debug(f"Categorized transaction (CSV mapping): description='{raw_description}', csv_category={csv_category} → category_id={result_category_id}")
            return result_category_id
    
    # Tier 2: Keyword matching
    description_lower = raw_description.lower()
    
    # Query keywords ordered by category sort_order to respect priority
    keywords = session.query(Keyword, Category).join(
        Category, Keyword.category_id == Category.id
    ).order_by(Category.sort_order).all()
    
    for keyword_obj, category_obj in keywords:
        if keyword_obj.keyword.lower() in description_lower:
            result_category_id = keyword_obj.category_id
            logger.debug(f"Keyword match found: '{keyword_obj.keyword}' → category_id={result_category_id} for description '{raw_description}'")
            logger.debug(f"Categorized transaction (keyword match): description='{raw_description}', csv_category={csv_category} → category_id={result_category_id}")
            return result_category_id
    
    # Fallback to "Other"
    other_category = session.query(Category).filter_by(name="Other").first()
    if other_category:
        result_category_id = other_category.id
        logger.debug(f"Categorized transaction (fallback to Other): description='{raw_description}', csv_category={csv_category} → category_id={result_category_id}")
        return result_category_id
    
    logger.error(f"'Other' category not found! Failed to categorize: '{raw_description}'")
    raise ValueError("'Other' category not found in database")
