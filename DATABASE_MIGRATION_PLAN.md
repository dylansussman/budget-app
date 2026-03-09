# Plan: Migrate Categories from JSON to Relational Database

## TL;DR
Refactor the budget app to replace `categories.json` with a normalized database schema: a `Category` table with name and sort order, and linked `Keyword` and `CSVCategoryMap` tables for categorization rules. This enables better data integrity, dynamic category management, and removes hardcoded category lists. The `Transaction.category` field will become a foreign key to `Category.id`.

---

## Steps

### Phase 1: Database Schema (database.py)

1. **Create the `Category` ORM model** (after Transaction class)
   - Fields: `id` (PK, autoincrement), `name` (String, unique), `sort_order` (Integer)
   - Example: Category(id=1, name="Groceries", sort_order=1)

2. **Create the `Keyword` ORM model** (after Category class)
   - Fields: `id` (PK), `category_id` (FK → Category.id), `keyword` (String, UNIQUE)
   - Purpose: Match against merchant descriptions in transactions
   - **UNIQUE constraint on `keyword`**: Each keyword belongs to exactly one category
     - Enforced at database level: prevents ambiguity during categorization
     - If you migrate from categories.json with duplicate keywords, deduplication logic should assign first occurrence to category based on sort_order
   - Allow case-insensitive keyword matching via LOWER() in queries
   - Example: Keyword(id=1, category_id=1, keyword="whole foods")

3. **Create the `CSVCategoryMap` ORM model** (after Keyword class)
   - Fields: `id` (PK), `category_id` (FK → Category.id), `csv_category_name` (String, unique)
   - Purpose: Map CSV category column values to app categories (handles "Groceries" → "Food and Groceries" etc.)
   - Example: CSVCategoryMap(id=1, category_id=1, csv_category_name="Groceries")
   - Allow case-insensitive lookup when matching CSV categories

4. **Update Transaction model**: Change `category` field
   - FROM: `category = Column(String, nullable=False)`
   - TO: `category_id = Column(Integer, ForeignKey('category.id'), nullable=False)`
   - Keep `category` as a relationship property for convenient access

5. **Create migration helper function** `migrate_categories_from_json()`
   - Load categories.json
   - Create category rows (in sort order) + keyword rows
   - Create CSV category map entries (initially: csv_name = category_name, e.g., "Groceries" maps to "Groceries")
   - Ensure "Other" has sort_order last (e.g., 999)
   - Note: This creates default categories only; existing transactions are handled separately

### Phase 2: Update Categorizer (data/categorizer.py)

6. **Update `categorize()` function** with two-tier logic and logging
   - **Tier 1: CSV category mapping** (highest priority)
     - If `csv_category` param provided and non-empty:
       - Call `get_category_id_by_csv_name(csv_category)` (includes DEBUG logging for hits)
       - Return category_id if found in mapping, else continue to Tier 2
   - **Tier 2: Keyword matching** (fallback)
     - Query all keywords from database (in sort_order)
     - Perform case-insensitive substring matching on description
     - Log at DEBUG level if match found: f"Keyword match found: '{keyword}' → category_id={category_id} for description '{raw_description}'"
     - Return first matching category_id or "Other"
   - Log at DEBUG level overall result: f"Categorized transaction: description='{raw_description}', csv_category={csv_category} → category_id={result}"
   - Signature: `categorize(raw_description: str, csv_category: str = None) -> int`

7. **Add helper functions with logging**
   - `get_category_id_by_csv_name(csv_category: str) -> int` 
     - Query CSVCategoryMap for matching csv_category (case-insensitive)
     - Log at DEBUG level if found: f"CSV category mapping found: '{csv_category}' → category_id={category_id}"
     - Return category_id if found, else return None (will fall back to keyword matching)
   - `get_category_id_by_name(category_name: str) -> int`
     - Resolve app category name → ID
     - Log at DEBUG level if found: f"Category name resolved: '{category_name}' → category_id={category_id}"
     - Log at WARNING level if not found: f"Failed to resolve category name: '{category_name}', using 'Other' as fallback"
     - Return "Other" category_id if not found
   - `load_categories_from_db()` — Optional caching helper for performance during bulk imports

### Phase 2b: Update CSV Parsers (data/parser.py)

8. **Update parsers to extract CSV category column**
   - Modify `parse_chase_csv()` and `parse_generic_csv()`
   - Check for category column (attempt to detect: 'category', 'merchant category', 'type', etc.)
   - If found and non-empty, include in transaction dict: `csv_category` field
   - If not found, set `csv_category` to None (optional)
   - Return transaction dicts with keys: date, merchant, amount, raw_description, source, **csv_category** (optional)

### Phase 3: Update Transaction Insertion (database.py)

9. **Modify `insert_transactions()` function with logging**
   - Accept transactions dict which may include optional `csv_category` field
   - For each transaction, call `categorize(raw_description, csv_category)` to get category_id
   - `categorize()` returns category_id (never a string) — includes logging
   - Store category_id in Transaction.category_id
   - Handle "Other" (always available as fallback in DB)
   - Log at INFO level for batch: f"Batch insert complete: {imported} imported, {skipped} skipped, {categorization_failures} categorization failures"
   - If any categorization failed (fell back to "Other"), log at WARNING level with transaction details

### Phase 4: Update API Endpoints (main.py)

10. **Refactor `GET /categories`**
    - Query Category table with sort_order
    - Return JSON: `[{"id": 1, "name": "Groceries", "keywords": ["whole foods", ...], "sort_order": 1}, ...]`
    - This replaces the old categories.json response

11. **Create new `POST /categories`** (dynamic category creation)
    - Request body: `{"name": "CategoryName", "keywords": ["kw1", "kw2"], "sort_order": X}`
    - Insert Category + related Keywords
    - Return created category with ID
    - Validation: name must be unique

12. **Create `PATCH /categories/{id}`** (update category)
    - Request body: `{"name": "NewName", "keywords": [...], "sort_order": X}`
    - Update category name and sort_order directly
    - For keywords: **diff & sync** approach:
      - Fetch current keywords for this category_id
      - Identify keywords to **add** (in request but not in DB)
      - Identify keywords to **remove** (in DB but not in request)
      - Execute: INSERT new keywords, DELETE removed keywords
      - Treat request list as source of truth (full replacement)
    - Prevent renaming "Other" or changing its sort_order

13. **Update `GET /transactions?month=...&category=...` with logging**
    - Accept `category` query param as **category name** (for backward compatibility with frontend)
    - Resolve category name → category_id using `get_category_id_by_name()` (includes logging)
    - Or accept `category_id` as alternative param
    - Filter transactions by category_id
    - Update response to include category name (not just ID)
    - Log at DEBUG level: f"Filtering transactions: category '{category_name}' (id={category_id}), month={month}"

14. **Update `PATCH /transactions/{id}` with logging**
    - Accept `category` as **category name** (for backward compatibility)
    - Resolve to category_id using `get_category_id_by_name()` (includes logging)
    - Log at INFO level: f"Updated transaction {id}: category changed from '{old_category_name}' to '{new_category_name}'"
    - Log at WARNING level if category name not found and "Other" was used: f"Category '{provided_name}' not found for transaction {id}, using 'Other' as fallback"
    - Return transaction with category name in response

15. **Update `GET /summary?month=...`**
    - Query still groups by category_id
    - Response should include category name for display

16. **Create CSV category mapping endpoints** (to manage CSV category aliases)
    - `GET /csv-mappings` — List all CSV category → app category mappings
      - Return: `[{"id": 1, "csv_category_name": "Groceries", "category_id": 1, "category_name": "Groceries"}, ...]`
    - `POST /csv-mappings` — Create new CSV category mapping
      - Request: `{"csv_category_name": "Groceries", "category_id": 1}`
      - Use case: "Add mapping from 'Groceries' in CSV to 'Food and Groceries' category"
      - Validation: csv_category_name must be unique
    - `PATCH /csv-mappings/{id}` — Update CSV category mapping
      - Request: `{"category_id": 3}` (remap to different app category)
    - `DELETE /csv-mappings/{id}` — Delete a mapping (unmaps a CSV category)

### Phase 5: Frontend Updates (script.js)

17. **Fix hardcoded category list**
    - Remove hardcoded `['Groceries', 'Dining', ...]` from `generateCategoryOptions()`
    - Use the categories already fetched from `GET /categories`
    - This fixes the current desync issue

18. **Update category filter dropdown**
    - Sort by `sort_order` from API response
    - Use category name as value (maintain compatibility)

### Phase 6: Migration of Existing Transactions

19. **Create migration script / endpoint** `migrate_transactions_categories()` with logging
    - Fetch all transactions with string category
    - For each transaction, resolve category string → category_id using `get_category_id_by_name()` (includes logging)
    - Update Transaction table to use category_id
    - Handle edge cases: corrupted/unknown categories → "Other" (log WARNING for each)
    - Log at INFO level: f"Migration complete: {migrated} transactions migrated, {failed} failures (fell back to 'Other')"
    - Log at WARNING level for each category name that failed to resolve: f"Category '{category_name}' not found for transaction {id}, migrated to 'Other'"
    - This runs one-time after schema changes

### Phase 7: Cleanup

20. **Delete or archive categories.json**
    - Remove from repository / move to `.gitignore`
    - Update README to document new schema

21. **Update initialization** `init_db()` in database.py
    - After creating tables, also call a function to populate default categories if database is empty
    - Ensures a fresh database starts with predefined categories

---

## Relevant Files

- [data/database.py](data/database.py) — Add Category, Keyword, CSVCategoryMap models; migrations; update Transaction FK
- [data/categorizer.py](data/categorizer.py) — CSV-aware categorization (two-tier: CSV mapping, then keyword matching)
- [data/parser.py](data/parser.py) — Extract optional CSV category column in parsers
- [main.py](main.py) — New endpoints (/categories, /csv-mappings), refactor query logic
- [frontend/script.js](frontend/script.js) — Fix hardcoded categories list
- [categories.json](categories.json) — Archive/delete after migration

---

## Verification

1. **Schema integrity**
   - Run `init_db()` and verify Category, Keyword, CSVCategoryMap, Transaction tables exist with correct columns
   - Verify foreign key constraints on Transaction.category_id → Category.id and Keyword.category_id → Category.id
   - Verify unique constraints on Category.name, Keyword.keyword, CSVCategoryMap.csv_category_name

2. **Categorization logic**
   - Test CSV mapping priority: `categorize("any description", csv_category="Groceries")` → should resolve to "Groceries" app category_id (or mapped category if configured)
   - Test keyword fallback: `categorize("CHIPOTLE #123", csv_category=None)` → should match "chipotle" keyword and return Dining category_id
   - Verify case-insensitive matching: "WHOLE FOODS MARKET" should match keyword "whole foods"
   - Verify sort_order priority: if both "Shopping" and "Groceries" have keywords matching a transaction, lower sort_order wins
   - Verify fallback to "Other": unknown description + no CSV category → returns "Other" category_id

3. **API endpoints** (manual or integration tests)
   - `GET /categories` returns all categories with keywords, sorted by sort_order ✓
   - `POST /categories` creates new category with keywords ✓
   - `PATCH /categories/{id}` updates name, sort_order, keywords (diff & sync) ✓
   - `PATCH /categories/{id}` rejects attempts to rename "Other" ✓
   - `GET /csv-mappings` returns all CSV category mappings ✓
   - `POST /csv-mappings` creates mapping (CSV "Food" → app "Groceries") ✓
   - `PATCH /csv-mappings/{id}` remaps CSV category to different app category ✓
   - `DELETE /csv-mappings/{id}` deletes mapping ✓
   - `GET /transactions?month=2026-03&category=Dining` filters correctly by category name ✓
   - `PATCH /transactions/{id}` with `{"category": "Shopping"}` resolves to correct category_id ✓

4. **Data migration**
   - Export all transactions before schema change (backup)
   - Run `migrate_transactions_categories()`
   - Verify all transactions have valid category_id (no nulls, all foreign keys valid)
   - Verify category names were preserved (query transactions and confirm categories match)
   - Spot-check: random sample of transactions show correct category before and after migration

5. **Frontend UI**
   - Category filter dropdown populates from `GET /categories` API (not hardcoded) ✓
   - Category options appear in correct order (sort_order) ✓
   - Category selector in transaction rows shows all categories ✓
   - Manual category edits via dropdown save correctly ✓
   - Category names display correctly after updating Transaction.category_id ✓

6. **Cleanup & final state**
   - categories.json no longer exists (or is gitignored)
   - Categories table is sole source of truth ✓
   - All old string category references in codebase replaced with category_id references
   - Main.py no longer imports categorizer.get_categories() ✓

---

## Decisions

- **Schema: ID + name + sort_order** per category (no color/icon for now, can add later without breaking schema)
- **"Other" is a database entry** with sort_order=999 (always appears last in UI and has lowest priority in categorization)
- **Keywords in separate table** — semantic purpose: match transaction descriptions
  - **UNIQUE constraint on keyword column** across all categories (prevents ambiguity during categorization)
  - Each keyword belongs to exactly one category
- **CSVCategoryMap in separate table** — semantic purpose: map CSV column values to app categories (not mixed with keywords)
  - Separation clarifies intent, simplifies queries, enables different UI/management workflows
- **Two-tier categorization priority**: (1) CSV mapping lookup → (2) Keyword substring matching → (3) "Other" fallback
- **Comprehensive logging strategy** for categorization and category resolution
  - DEBUG level: categorization hits, category name resolutions, keyword matches
  - WARNING level: category name resolution failures (fallback to "Other"), migration issues, duplicate keywords
  - INFO level: batch operations (bulk import summary, migration completion)
  - Enables tracking of data quality issues and debugging categorization logic
- **Full migration from JSON to DB** — categories.json deleted; database is single source of truth
- **Dynamic endpoints** — support runtime category management (POST /categories) and CSV mapping management (POST/PATCH/DELETE /csv-mappings)
- **Backward compatibility** — API accepts category names (not numeric IDs) from frontend; internally resolves to category_id

---

## Further Considerations

1. **Keyword deduplication during migration**
   - If categories.json has duplicate keywords across categories, the migration step should detect and handle this
   - Recommendation: Assign first occurrence (lowest sort_order category) to the duplicate keyword
   - Log at WARNING level for each duplicate: f"Duplicate keyword '{keyword}' found, assigning to category '{winning_category}' (sort_order={sort_order})"

2. **Logging configuration**
   - Set up logging in database.py and categorizer.py (use Python's logging module)
   - Configure DEBUG/WARNING/INFO levels in main.py log setup
   - Recommendation: Write logs to file for audit trail of all categorization decisions

3. **Performance: Category caching**
   - Bulk importing 100+ transactions queries keywords & mappings repeatedly
   - Recommendation: Cache keywords + CSV mappings (in-memory dict) during bulk import, invalidate after POST /categories or POST/PATCH/DELETE /csv-mappings
   - Cache structure: `{keyword: category_id}` + `{csv_category_name: category_id}`

4. **CSV mapping management UI** (future)
   - Initially, seed CSVCategoryMap with identity mappings (e.g., "Groceries" → "Groceries") via `migrate_categories_from_json()`
   - Admin can then create/edit mappings via POST/PATCH /csv-mappings endpoints to handle mismatches (e.g., CSV "Food" → app "Food and Groceries")
   - Recommendation: If you work with many CSV sources from different banks, consider adding simple admin UI page to view/edit CSV mappings in bulk
