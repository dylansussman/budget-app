import os
import json
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, func, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from dotenv import load_dotenv

# TODO: Need to add history table to track spending by categories on a monthly basis
#   Probably not great practice, but should sum transactions by month and category from the transactions table
#   and will manually add history for last six months
#   This table will be used for budget predictions for future months; might be able to remove it once I have 6
#   months of transaction data in the DB

# TODO: Need to look into way to keep backup of data - probably don't want to push data to Github, so
#   need to figure out another way to back up SQLite DB 

# Configure logging
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/budget.db")

# Create engine with SQLite-specific options
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for ORM models
Base = declarative_base()


class Transaction(Base):
    """SQLAlchemy ORM model for transactions table."""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transactionDate = Column(Date, nullable=False)
    postDate = Column(Date, nullable=False)
    description = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey('category.id'), nullable=False)
    amount = Column(Float, nullable=False)
    source = Column(String, nullable=False)
    account = Column(String, nullable=True)
    type = Column(String, nullable=False)
    import_id = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Relationship to Category
    category = relationship("Category", back_populates="transactions")


class Category(Base):
    """SQLAlchemy ORM model for categories table."""
    __tablename__ = "category"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    sort_order = Column(Integer, nullable=False)

    # Relationships
    keywords = relationship("Keyword", back_populates="category", cascade="all, delete-orphan")
    csv_mappings = relationship("CSVCategoryMap", back_populates="category", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="category")


class Keyword(Base):
    """SQLAlchemy ORM model for keywords table."""
    __tablename__ = "keyword"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(Integer, ForeignKey('category.id'), nullable=False)
    keyword = Column(String, nullable=False, unique=True)

    # Relationship
    category = relationship("Category", back_populates="keywords")


class CSVCategoryMap(Base):
    """SQLAlchemy ORM model for CSV category mappings table."""
    __tablename__ = "csv_category_map"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(Integer, ForeignKey('category.id'), nullable=False)
    csv_category_name = Column(String, nullable=False, unique=True)

    # Relationship
    category = relationship("Category", back_populates="csv_mappings")


def generate_import_id(transactionDate, description, amount):
    """
    Generate SHA256 hash for deduplication.
    
    Args:
        transactionDate: Transaction date (can be datetime or string)
        description: Transaction description
        amount: Transaction amount
    
    Returns:
        SHA256 hash string
    """
    # Convert date to string if needed
    date_str = str(transactionDate) if not isinstance(transactionDate, str) else transactionDate
    content = f"{date_str}{description}{amount}".lower()
    return hashlib.sha256(content.encode()).hexdigest()


def migrate_categories_from_json():
    """
    Migrate categories from categories.json to database.
    Creates Category rows with Keywords and CSVCategoryMap entries.
    Handles deduplication of keywords across categories.
    """
    categories_file = Path(__file__).parent.parent / "categories.json"
    
    if not categories_file.exists():
        logger.warning("categories.json not found, skipping migration")
        return
    
    session = SessionLocal()
    try:
        # Check if categories already exist
        existing_count = session.query(Category).count()
        if existing_count > 0:
            logger.info("Categories already exist in database, skipping migration")
            return
        
        # Load categories.json
        with open(categories_file, 'r') as f:
            categories_data = json.load(f)
        
        # Track all keywords to detect duplicates
        keyword_to_category = {}
        
        # First pass: identify all keywords and handle duplicates
        for cat_name, keywords_list in categories_data.items():
            for keyword in keywords_list:
                keyword_lower = keyword.lower()
                if keyword_lower in keyword_to_category:
                    # Duplicate found, log warning
                    winning_category = keyword_to_category[keyword_lower]
                    logger.warning(f"Duplicate keyword '{keyword}' found in both '{cat_name}' and '{winning_category}', assigning to '{winning_category}'")
                else:
                    keyword_to_category[keyword_lower] = cat_name
        
        # Create categories in order with sort_order
        sort_order_counter = 10
        category_map = {}  # Map category name to ID
        
        for cat_name in categories_data.keys():
            if cat_name == "Other":
                # Other gets sort_order=999 (always last)
                sort_order = 999
            else:
                sort_order = sort_order_counter
                sort_order_counter += 10
            
            category = Category(name=cat_name, sort_order=sort_order)
            session.add(category)
            session.flush()  # Flush to get the ID
            category_map[cat_name] = category.id
            logger.info(f"Created category: {cat_name} (id={category.id}, sort_order={sort_order})")
        
        # Ensure "Other" exists if not already added
        if "Other" not in category_map:
            other_category = Category(name="Other", sort_order=999)
            session.add(other_category)
            session.flush()
            category_map["Other"] = other_category.id
            logger.info(f"Created category: Other (id={other_category.id}, sort_order=999)")
        
        # Create keywords (using the deduplication mapping)
        for keyword_lower, cat_name in keyword_to_category.items():
            category_id = category_map[cat_name]
            keyword = Keyword(category_id=category_id, keyword=keyword_lower)
            session.add(keyword)
            logger.debug(f"Created keyword: '{keyword_lower}' → category_id={category_id}")
        
        # Create CSV category mappings (identity mappings initially)
        for cat_name, category_id in category_map.items():
            csv_map = CSVCategoryMap(category_id=category_id, csv_category_name=cat_name)
            session.add(csv_map)
            logger.debug(f"Created CSV mapping: '{cat_name}' → category_id={category_id}")
        
        session.commit()
        logger.info(f"Migration complete: {len(category_map)} categories created, {len(keyword_to_category)} keywords created")
    
    except Exception as e:
        session.rollback()
        logger.error(f"Error during category migration: {e}")
        raise e
    finally:
        session.close()



def init_db():
    """Create all tables if they don't exist and seed default categories."""
    Base.metadata.create_all(bind=engine)
    
    # Seed default categories from categories.json if database is empty
    session = SessionLocal()
    try:
        category_count = session.query(Category).count()
        if category_count == 0:
            logger.info("Database empty, seeding default categories from categories.json")
            migrate_categories_from_json()
        else:
            logger.debug(f"Database already has {category_count} categories, skipping seed")
    finally:
        session.close()


def insert_transactions(transactions: list[dict]) -> dict:
    """
    Insert transactions into database, skipping duplicates based on import_id.
    Automatically categorizes transactions using categorize() function.
    
    Args:
        transactions: List of transaction dicts with keys:
            - transactionDate: Transaction date (date or datetime object)
            - postDate: Post date (date or datetime object)
            - description: Transaction description
            - amount: Transaction amount (float)
            - source: Bank/source (e.g., 'chase')
            - account: Optional account identifier
            - type: Transaction type
            - csv_category: Optional CSV category name
    
    Returns:
        dict with keys:
            - 'imported': Number of transactions successfully inserted
            - 'skipped_duplicates': Number of duplicate transactions skipped
            - 'categorization_failures': Number of transactions that fell back to "Other"
    """
    # Import here to avoid circular imports
    from . import categorizer
    
    session = SessionLocal()
    imported = 0
    skipped_duplicates = 0
    categorization_failures = 0
    
    try:
        for trans in transactions:            
            # Generate import_id for deduplication
            import_id = generate_import_id(trans['transactionDate'], trans['description'], trans['amount'])
            
            # Check if this transaction already exists
            existing = session.query(Transaction).filter_by(import_id=import_id).first()
            if existing:
                skipped_duplicates += 1
                continue
            
            # Categorize transaction
            try:
                csv_category = trans.get('csv_category')
                category_id = categorizer.categorize(session, trans['description'], csv_category=csv_category)
                
                # Check if it fell back to "Other"
                other_category = session.query(Category).filter_by(name="Other").first()
                if category_id == other_category.id:
                    categorization_failures += 1
                    logger.warning(f"Transaction '{trans['description']}' (csv_category={csv_category}) fell back to 'Other'")
            except Exception as e:
                logger.error(f"Failed to categorize transaction '{trans['description']}': {e}, falling back to 'Other'")
                other_category = session.query(Category).filter_by(name="Other").first()
                category_id = other_category.id
                categorization_failures += 1
            
            # Create and add new transaction
            transaction = Transaction(
                transactionDate=trans['transactionDate'],
                postDate=trans['postDate'],
                description=trans['description'],
                category_id=category_id,
                amount=trans['amount'],
                source=trans['source'],
                account=trans.get('account'),
                type=trans['type'],
                import_id=import_id
            )
            session.add(transaction)
            imported += 1
        
        session.commit()
        logger.info(f"Batch insert complete: {imported} imported, {skipped_duplicates} skipped, {categorization_failures} categorization failures")
    except Exception as e:
        session.rollback()
        logger.error(f"Error during transaction insertion: {e}")
        raise e
    finally:
        session.close()
    
    return {"imported": imported, "skipped_duplicates": skipped_duplicates, "categorization_failures": categorization_failures}


def get_transactions(month: str, category: str = None, source: str = None) -> list:
    """
    Get transactions for a specific month, optionally filtered by category or source.
    
    Args:
        month: Transaction month in YYYY-MM format
        category: Optional category name filter
        source: Optional source (bank) filter
    
    Returns:
        List of Transaction objects matching the filters
    """
    session = SessionLocal()
    try:
        query = session.query(Transaction)
        
        # Filter by month using SQLite strftime
        year, month_num = month.split('-')
        month_filter = f"{year}-{month_num.zfill(2)}"
        query = query.filter(
            func.strftime('%Y-%m', Transaction.transactionDate) == month_filter
        )
        
        # Apply category filter (by name)
        if category:
            category_obj = session.query(Category).filter_by(name=category).first()
            if category_obj:
                query = query.filter(Transaction.category_id == category_obj.id)
        
        # Apply optional source filter
        if source:
            query = query.filter(Transaction.source == source)
        
        # Sort by date descending
        query = query.order_by(Transaction.transactionDate.desc())
        
        return query.all()
    finally:
        session.close()


def update_category(transaction_id: int, category_name: str) -> bool:
    """
    Update the category for a specific transaction.
    
    Args:
        transaction_id: ID of the transaction to update
        category_name: New category name
    
    Returns:
        True if successful, False if transaction or category not found
    """
    session = SessionLocal()
    try:
        transaction = session.query(Transaction).filter_by(id=transaction_id).first()
        if not transaction:
            logger.warning(f"Transaction {transaction_id} not found")
            return False
        
        # Resolve category name to ID
        category = session.query(Category).filter_by(name=category_name).first()
        if not category:
            logger.warning(f"Category '{category_name}' not found, using 'Other' as fallback")
            category = session.query(Category).filter_by(name="Other").first()
        
        old_category_name = transaction.category.name if transaction.category else "Unknown"
        transaction.category_id = category.id
        session.commit()
        
        logger.info(f"Updated transaction {transaction_id}: category changed from '{old_category_name}' to '{category.name}'")
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating category for transaction {transaction_id}: {e}")
        raise e
    finally:
        session.close()


def get_monthly_summary(month: str) -> dict:
    """
    Get total spending by category for a given month.
    
    Args:
        month: Transaction month in YYYY-MM format
    
    Returns:
        Dictionary mapping category names to total amounts spent
    """
    session = SessionLocal()
    try:
        year, month_num = month.split('-')
        month_filter = f"{year}-{month_num.zfill(2)}"
        
        # Query transactions grouped by category_id with sum of amounts
        results = session.query(
            Category.name,
            func.sum(Transaction.amount).label('total')
        ).join(
            Transaction, Transaction.category_id == Category.id
        ).filter(
            func.strftime('%Y-%m', Transaction.transactionDate) == month_filter
        ).group_by(Category.id).all()
        
        # Convert to dict
        return {row[0]: row[1] for row in results}
    finally:
        session.close()
