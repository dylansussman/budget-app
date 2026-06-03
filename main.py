from pathlib import Path
import io
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from dateutil.relativedelta import relativedelta
from datetime import date, datetime
from data.sheets_sync import sync_month, write_rolling_summary

# Import database functions and models
from data import categorizer
from data.database import (
    Transaction, init_db, insert_transactions, get_transactions, get_transaction_months,
    update_category, get_monthly_summary, SessionLocal, Category, Keyword, CSVCategoryMap,
    delete_transaction_by_id
)

# Import categorizer and sheets_sync
from data.sheets_sync import sync_month

# Import parser
from data.parser import parse_csv

# Load environment variables
load_dotenv()

# Lifespan context manager for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    yield
    # Shutdown (if needed, add cleanup here)

# Create FastAPI app with lifespan
app = FastAPI(title="Budget App API", lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
frontend_path = Path(__file__).parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")

# Serve index.html at root
@app.get("/")
async def root():
    index_path = frontend_path / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Frontend not found"}


# ============================================================================
# Pydantic models for request/response
# ============================================================================

class CategoryUpdateRequest(BaseModel):
    category: str

class SyncRequest(BaseModel):
    month: str

class CategoriesUpdateRequest(BaseModel):
    """New categories mapping"""
    pass  # Will use dict directly


# ============================================================================
# API Routes
# ============================================================================

@app.get("/api/transactions/months")
def transaction_months():
    return get_transaction_months()

@app.post("/upload")
async def upload_csv_files(files: list[UploadFile] = File(...)):
    """
    Upload and process CSV files.
    
    Returns:
        { imported: N, skipped_duplicates: N, categorization_failures: N, errors: [...] }
    """
    imported_total = 0
    skipped_total = 0
    categorization_failures_total = 0
    errors = []
    
    try:
        for file in files:
            try:
                # Validate file is CSV
                if not file.filename or not file.filename.lower().endswith('.csv'):
                    errors.append({"file": file.filename, "error": "File must be a CSV file"})
                    continue
                
                # Read CSV file contents
                contents = await file.read()
                
                if not contents:
                    errors.append({"file": file.filename, "error": "File is empty"})
                    continue
                
                # Create a file-like object from the contents for parser
                file_obj = io.BytesIO(contents)

                filename = file.filename.lower()
                account = "unknown"
                if "chase" in filename:
                    source = "chase"
                    account = filename[filename.find(source) + len(source):filename.find("_")]
                elif "capitalone" in filename:
                    source = "capitalone"
                elif "venmo" in filename:
                    source = "venmo"
                else:
                    source = "generic"
                                    
                # Parse CSV using parser.py (auto-detect format)
                transactions = parse_csv(file_obj, source=source, account=account)
                
                # Insert into database (insert_transactions handles categorization)
                result = insert_transactions(transactions)
                imported_total += result['imported']
                skipped_total += result['skipped_duplicates']
                categorization_failures_total += result['categorization_failures']
                
            except Exception as e:
                errors.append({"file": file.filename, "error": str(e)})
        
        return {
            "imported": imported_total,
            "skipped_duplicates": skipped_total,
            "categorization_failures": categorization_failures_total,
            "errors": errors
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/sync/summary")
async def sync_rolling_summary(request: SyncRequest):
    """
    Calculate a rolling 6-month spending summary ending the month before
    the selected month, then push to a "Rolling Summary" tab in Google Sheets.

    Body: { month: "2025-05" }
    Returns: { sheet_url: "...", rows_written: N, months_included: [...] }
    """
    try:
        anchor = datetime.strptime(request.month, "%Y-%m")
        # Go back 1 month so selected month is excluded, then collect 6 months
        month_summaries: dict[str, dict] = {}
        for i in range(6, 0, -1):  # 6 months before anchor → 1 month before anchor
            target = anchor - relativedelta(months=i)
            month_key = target.strftime("%Y-%m")
            summary = get_monthly_summary(month_key)
            if summary:
                month_summaries[month_key] = summary

        if not month_summaries:
            raise HTTPException(
                status_code=400,
                detail=f"No transaction data found in the 6 months before {request.month}."
            )

        result = write_rolling_summary(month_summaries)
        return {
            **result,
            "months_included": list(month_summaries.keys()),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/transactions")
async def get_all_transactions(
    month: str = Query(None),
    category: str = Query(None),
    source: str = Query(None)
):
    """
    Get transactions, optionally filtered by month, category, or source.
    
    Query params:
        - month: YYYY-MM format
        - category: Category name
        - source: Bank/source name
    """
    try:
        if not month:
            raise HTTPException(status_code=400, detail="month parameter is required")
        
        transactions = get_transactions(month, category, source)
        return transactions

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/transactions/{transaction_id}")
async def patch_transaction(transaction_id: int, request: CategoryUpdateRequest):
    """
    Update category for a specific transaction.
    
    Body: { category: "Dining" }
    """
    try:
        success = update_category(transaction_id, request.category)
        if not success:
            raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")
        
        return {"message": "Transaction updated", "id": transaction_id, "category": request.category}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/summary")
async def get_summary(month: str = Query(...)):
    """
    Get monthly spend summary by category.
    
    Query params:
        - month: YYYY-MM format
    
    Returns:
        { category_name: total_amount, ... }
    """
    try:
        if not month:
            raise HTTPException(status_code=400, detail="month parameter is required")
        
        summary = get_monthly_summary(month)
        return summary
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sync")
async def sync_to_sheets(request: SyncRequest):
    """
    Sync a month's transactions to Google Sheets.
    
    Body: { month: "2025-01" }
    
    Returns:
        { sheet_url: "...", rows_written: N }
    """
    try:
        # Get transactions for the month
        transactions = get_transactions(request.month)
        
        if not transactions:
            raise HTTPException(status_code=400, detail=f"No transactions found for {request.month}")
        
        # Sync to Google Sheets
        result = sync_month(request.month, transactions)
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/categories")
async def get_all_categories():
    """
    Get all categories with keywords and metadata.
    
    Returns:
        [
            {
                "id": 1,
                "name": "Groceries",
                "keywords": ["whole foods", "kroger", ...],
                "sort_order": 10,
                "csv_category": "Groceries"
            },
            ...
        ]
    """
    try:
        session = SessionLocal()
        try:
            categories = session.query(Category).order_by(Category.sort_order).all()
            
            result = []
            for cat in categories:
                # Get keywords for this category
                keywords = session.query(Keyword).filter_by(category_id=cat.id).all()
                keyword_list = [kw.keyword for kw in keywords]
                
                # Get CSV category mapping (typically 1:1 identity for now)
                csv_mapping = session.query(CSVCategoryMap).filter_by(category_id=cat.id).first()
                csv_category_name = csv_mapping.csv_category_name if csv_mapping else cat.name
                
                result.append({
                    "id": cat.id,
                    "name": cat.name,
                    "keywords": keyword_list,
                    "sort_order": cat.sort_order,
                    "csv_category": csv_category_name
                })
            
            return result
        finally:
            session.close()
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/categories")
async def create_category(request: dict = Body(...)):
    """
    Create a new category with keywords.
    
    Body:
    {
        "name": "CategoryName",
        "keywords": ["kw1", "kw2", ...],
        "sort_order": 10,
        "csv_category": "OptionalCSVName"  (defaults to name)
    }
    """
    try:
        if not isinstance(request, dict):
            raise HTTPException(status_code=400, detail="Body must be a dictionary")
        
        name = request.get("name")
        keywords = request.get("keywords", [])
        sort_order = request.get("sort_order")
        csv_category = request.get("csv_category", name)
        
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        
        session = SessionLocal()
        try:
            # Check if category already exists
            existing = session.query(Category).filter_by(name=name).first()
            if existing:
                raise HTTPException(status_code=409, detail=f"Category '{name}' already exists")
            
            # Determine sort_order if not provided
            if sort_order is None:
                max_sort = session.query(Category).filter(Category.name != "Other").order_by(Category.sort_order.desc()).first()
                sort_order = (max_sort.sort_order + 10) if max_sort else 10
            
            # Create category
            category = Category(name=name, sort_order=sort_order)
            session.add(category)
            session.flush()  # Get the ID
            
            # Add keywords
            for kw in keywords:
                keyword = Keyword(category_id=category.id, keyword=kw.lower())
                session.add(keyword)
            
            # Add CSV category mapping
            csv_map = CSVCategoryMap(category_id=category.id, csv_category_name=csv_category)
            session.add(csv_map)
            
            session.commit()
            
            return {
                "id": category.id,
                "name": category.name,
                "keywords": keywords,
                "sort_order": category.sort_order,
                "csv_category": csv_category,
                "message": f"Category '{name}' created successfully"
            }
        except HTTPException:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            raise HTTPException(status_code=400, detail=f"Failed to create category: {str(e)}")
        finally:
            session.close()
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/categories/{category_id}")
async def update_category_endpoint(category_id: int, request: dict = Body(...)):
    """
    Update a category (name, keywords, sort_order, CSV mapping).
    
    Body:
    {
        "name": "NewName",  (optional)
        "keywords": ["new_kw1", "new_kw2"],  (optional, replaces all keywords)
        "sort_order": 20,  (optional)
        "csv_category": "NewCSVName"  (optional)
    }
    """
    try:
        if not isinstance(request, dict):
            raise HTTPException(status_code=400, detail="Body must be a dictionary")
        
        session = SessionLocal()
        try:
            category = session.query(Category).filter_by(id=category_id).first()
            if not category:
                raise HTTPException(status_code=404, detail=f"Category {category_id} not found")
            
            # Update name if provided
            if "name" in request:
                new_name = request["name"]
                existing = session.query(Category).filter_by(name=new_name).first()
                if existing and existing.id != category_id:
                    raise HTTPException(status_code=409, detail=f"Category '{new_name}' already exists")
                category.name = new_name
            
            # Update sort_order if provided
            if "sort_order" in request:
                category.sort_order = request["sort_order"]
            
            # Update keywords if provided
            if "keywords" in request:
                keywords = request["keywords"]
                # Delete old keywords
                session.query(Keyword).filter_by(category_id=category_id).delete()
                # Add new keywords
                for kw in keywords:
                    keyword = Keyword(category_id=category_id, keyword=kw.lower())
                    session.add(keyword)
            
            # Update CSV category mapping if provided
            if "csv_category" in request:
                csv_category = request["csv_category"]
                csv_map = session.query(CSVCategoryMap).filter_by(category_id=category_id).first()
                if csv_map:
                    csv_map.csv_category_name = csv_category
                else:
                    csv_map = CSVCategoryMap(category_id=category_id, csv_category_name=csv_category)
                    session.add(csv_map)
            
            session.commit()
            
            # Return updated category
            keywords = session.query(Keyword).filter_by(category_id=category_id).all()
            keyword_list = [kw.keyword for kw in keywords]
            csv_map = session.query(CSVCategoryMap).filter_by(category_id=category_id).first()
            csv_category_name = csv_map.csv_category_name if csv_map else category.name
            
            return {
                "id": category.id,
                "name": category.name,
                "keywords": keyword_list,
                "sort_order": category.sort_order,
                "csv_category": csv_category_name,
                "message": f"Category {category_id} updated successfully"
            }
        except HTTPException:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            raise HTTPException(status_code=400, detail=f"Failed to update category: {str(e)}")
        finally:
            session.close()
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/csv-mappings")
async def get_csv_mappings():
    """
    Get all CSV category mappings.
    
    Returns:
        [
            {
                "id": 1,
                "category_id": 1,
                "category_name": "Groceries",
                "csv_category_name": "Groceries"
            },
            ...
        ]
    """
    try:
        session = SessionLocal()
        try:
            mappings = session.query(CSVCategoryMap).all()
            
            result = []
            for mapping in mappings:
                category = session.query(Category).filter_by(id=mapping.category_id).first()
                result.append({
                    "id": mapping.id,
                    "category_id": mapping.category_id,
                    "category_name": category.name if category else "Unknown",
                    "csv_category_name": mapping.csv_category_name
                })
            
            return result
        finally:
            session.close()
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/csv-mappings")
async def create_csv_mapping(request: dict = Body(...)):
    """
    Create a new CSV category mapping.
    
    Body:
    {
        "category_id": 1,
        "csv_category_name": "CSVCategoryName"
    }
    """
    try:
        if not isinstance(request, dict):
            raise HTTPException(status_code=400, detail="Body must be a dictionary")
        
        category_id = request.get("category_id")
        csv_category_name = request.get("csv_category_name")
        
        if not category_id or not csv_category_name:
            raise HTTPException(status_code=400, detail="category_id and csv_category_name are required")
        
        session = SessionLocal()
        try:
            # Check if category exists
            category = session.query(Category).filter_by(id=category_id).first()
            if not category:
                raise HTTPException(status_code=404, detail=f"Category {category_id} not found")
            
            # Check if mapping already exists
            existing = session.query(CSVCategoryMap).filter_by(csv_category_name=csv_category_name).first()
            if existing:
                raise HTTPException(status_code=409, detail=f"CSV mapping for '{csv_category_name}' already exists")
            
            # Create mapping
            mapping = CSVCategoryMap(category_id=category_id, csv_category_name=csv_category_name)
            session.add(mapping)
            session.commit()
            
            return {
                "id": mapping.id,
                "category_id": mapping.category_id,
                "category_name": category.name,
                "csv_category_name": mapping.csv_category_name,
                "message": "CSV mapping created successfully"
            }
        except HTTPException:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            raise HTTPException(status_code=400, detail=f"Failed to create CSV mapping: {str(e)}")
        finally:
            session.close()
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/csv-mappings/{mapping_id}")
async def update_csv_mapping(mapping_id: int, request: dict = Body(...)):
    """
    Update a CSV category mapping.
    
    Body:
    {
        "category_id": 1,  (optional)
        "csv_category_name": "NewCSVName"  (optional)
    }
    """
    try:
        if not isinstance(request, dict):
            raise HTTPException(status_code=400, detail="Body must be a dictionary")
        
        session = SessionLocal()
        try:
            mapping = session.query(CSVCategoryMap).filter_by(id=mapping_id).first()
            if not mapping:
                raise HTTPException(status_code=404, detail=f"CSV mapping {mapping_id} not found")
            
            # Update category_id if provided
            if "category_id" in request:
                new_category_id = request["category_id"]
                category = session.query(Category).filter_by(id=new_category_id).first()
                if not category:
                    raise HTTPException(status_code=404, detail=f"Category {new_category_id} not found")
                mapping.category_id = new_category_id
            
            # Update csv_category_name if provided
            if "csv_category_name" in request:
                new_csv_name = request["csv_category_name"]
                existing = session.query(CSVCategoryMap).filter_by(csv_category_name=new_csv_name).first()
                if existing and existing.id != mapping_id:
                    raise HTTPException(status_code=409, detail=f"CSV mapping for '{new_csv_name}' already exists")
                mapping.csv_category_name = new_csv_name
            
            session.commit()
            
            # Return updated mapping
            category = session.query(Category).filter_by(id=mapping.category_id).first()
            return {
                "id": mapping.id,
                "category_id": mapping.category_id,
                "category_name": category.name if category else "Unknown",
                "csv_category_name": mapping.csv_category_name,
                "message": "CSV mapping updated successfully"
            }
        except HTTPException:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            raise HTTPException(status_code=400, detail=f"Failed to update CSV mapping: {str(e)}")
        finally:
            session.close()
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/csv-mappings/{mapping_id}")
async def delete_csv_mapping(mapping_id: int):
    """
    Delete a CSV category mapping.
    """
    try:
        session = SessionLocal()
        try:
            mapping = session.query(CSVCategoryMap).filter_by(id=mapping_id).first()
            if not mapping:
                raise HTTPException(status_code=404, detail=f"CSV mapping {mapping_id} not found")
            
            session.delete(mapping)
            session.commit()
            
            return {"message": f"CSV mapping {mapping_id} deleted successfully"}
        except HTTPException:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            raise HTTPException(status_code=400, detail=f"Failed to delete CSV mapping: {str(e)}")
        finally:
            session.close()
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/transactions")
async def add_transaction(transaction: dict):
    """Manually add a single transaction."""
    try:
        if not transaction.get("type"):
            transaction["type"] = None
        
        transaction.setdefault("source", "manual")
        transaction.setdefault("raw_description", transaction.get("description", ""))

        result = insert_transactions([transaction])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/transactions/{id}")
async def delete_transaction(id: int):
    """Delete a transaction by ID."""
    try:
        success = delete_transaction_by_id(id)
        if not success:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return {"deleted": id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Debug/Admin Endpoints
# ============================================================================

@app.post("/debug/migrate-categories")
async def migrate_categories():
    """
    Migration utility endpoint to verify and report on category data.
    Checks for any transactions with invalid category references.
    
    Returns:
        {
            "total_transactions": N,
            "valid_transactions": N,
            "invalid_transactions": N,
            "stats": {...}
        }
    """
    try:
        session = SessionLocal()
        try:
            # Get all transactions
            all_transactions = session.query(Transaction).all()
            total = len(all_transactions)
            
            valid = 0
            invalid = 0
            categories_used = {}
            
            for txn in all_transactions:
                # Check if category_id references a valid category
                category = session.query(Category).filter_by(id=txn.category_id).first()
                if category:
                    valid += 1
                    categories_used[category.name] = categories_used.get(category.name, 0) + 1
                else:
                    invalid += 1
            
            # Get category statistics
            all_categories = session.query(Category).all()
            category_stats = [
                {
                    "name": cat.name,
                    "id": cat.id,
                    "sort_order": cat.sort_order,
                    "transaction_count": categories_used.get(cat.name, 0),
                    "keyword_count": len(cat.keywords)
                }
                for cat in all_categories
            ]
            
            return {
                "total_transactions": total,
                "valid_transactions": valid,
                "invalid_transactions": invalid,
                "category_statistics": category_stats,
                "message": f"Migration check complete: {valid}/{total} transactions have valid category references"
            }
        finally:
            session.close()
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
