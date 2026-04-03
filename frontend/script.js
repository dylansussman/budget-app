// ========================================================================
// Toast Notifications
// ========================================================================
function showToast(message, type = 'info', url = null) {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    let icon = 'ℹ️';
    if (type === 'success') icon = '✓';
    if (type === 'error') icon = '✕';

    let content = message;
    if (url) {
        content = `${message} <a href="${url}" target="_blank">View Sheet</a>`;
    }

    toast.innerHTML = `
        <span class="toast-icon">${icon}</span>
        <div class="toast-content">${content}</div>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('removing');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ========================================================================
// File Upload - Drag and Drop
// ========================================================================
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const uploadResults = document.getElementById('uploadResults');

dropzone.addEventListener('click', () => fileInput.click());

dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('active');
});

dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('active');
});

dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('active');
    fileInput.files = e.dataTransfer.files;
    uploadFiles();
});

fileInput.addEventListener('change', uploadFiles);

async function uploadFiles() {
    const files = fileInput.files;
    if (files.length === 0) return;

    uploadResults.innerHTML = '<p style="color: #666;">Uploading...</p>';

    const formData = new FormData();
    for (let file of files) {
        formData.append('files', file);
    }
    console.log(formData.getAll('files'));

    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();
        console.log('Upload response:', data);

        uploadResults.innerHTML = '';
        let hasSuccess = false;

        if (response.ok) {
            Array.from(files).forEach((file, i) => {
                let resultDiv = document.createElement('div');
                resultDiv.className = 'file-result success';
                resultDiv.innerHTML = `
                    ✓ <strong>${file.name}</strong><br>
                    Imported: ${data.imported}, Skipped: ${data.skipped_duplicates}
                `;
                uploadResults.appendChild(resultDiv);
                hasSuccess = true;
            });

            showToast(`✓ Imported ${data.imported} transactions`, 'success');
            fileInput.value = '';

            // Refresh transactions
            loadTransactions();
            loadMonths();
        } else {
            data.errors?.forEach(error => {
                let resultDiv = document.createElement('div');
                resultDiv.className = 'file-result error';
                resultDiv.innerHTML = `✕ <strong>${error.file}</strong><br>${error.error}`;
                uploadResults.appendChild(resultDiv);
            });
            showToast(`Error uploading files`, 'error');
        }
    } catch (error) {
        uploadResults.innerHTML = `<div class="file-result error">Error: ${error.message}</div>`;
        showToast(`Upload failed: ${error.message}`, 'error');
    }
}

// ========================================================================
// Month Selection
// ========================================================================
const monthSelect = document.getElementById('monthSelect');

async function loadMonths() {
    try {
        const now = new Date();
        const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

        // Fetch distinct months from the backend
        const response = await fetch('/api/transactions/months');
        if (!response.ok) throw new Error('Failed to fetch months');
        const months = await response.json();

        // Ensure current month is always included even if no transactions yet
        if (!months.includes(currentMonth)) {
            months.unshift(currentMonth);
        }

        // Populate the dropdown
        monthSelect.innerHTML = months
            .map(m => `<option value="${m}">${m}</option>`)
            .join('');

        // Default to current month if present, otherwise most recent
        monthSelect.value = months.includes(currentMonth) ? currentMonth : months[0];

        loadTransactions();
        loadSummary();
        syncBtn.disabled = false;
    } catch (error) {
        console.error('Error loading months:', error);
    }
}

monthSelect.addEventListener('change', () => {
    loadTransactions();
    loadSummary();
});

// ========================================================================
// Category Filter
// ========================================================================
const categorySelect = document.getElementById('categorySelect');

// ========================================================================
// Global Categories Cache
// ========================================================================
let categoriesCache = [];

async function loadCategories() {
    try {
        const response = await fetch('/categories');
        const categories = await response.json();
        
        // Store categories globally
        categoriesCache = Array.isArray(categories) ? categories : [];
        
        // Populate category filter dropdown (sorted by sort_order)
        categorySelect.innerHTML = '<option value="">All Categories</option>';
        categoriesCache.sort((a, b) => a.sort_order - b.sort_order).forEach(category => {
            const option = document.createElement('option');
            option.value = category.name;
            option.textContent = category.name;
            categorySelect.appendChild(option);
        });
        
        console.debug(`Loaded ${categoriesCache.length} categories from API`);
    } catch (error) {
        console.error('Error loading categories:', error);
        // Fallback to empty cache if API fails
        categoriesCache = [];
    }
}

categorySelect.addEventListener('change', loadTransactions);

// ========================================================================
// Load Transactions
// ========================================================================
const tableBody = document.getElementById('tableBody');

// --- State ---
let allTransactions = [];
let sortCol = null;
let sortDir = 'asc';
let colFilters = {};

// --- Load from API ---
async function loadTransactions() {
    const month = monthSelect.value;
    const category = categorySelect.value;

    if (!month) return;

    try {
        const params = new URLSearchParams({ month });
        if (category) params.append('category', category);

        const response = await fetch(`/transactions?${params}`);
        const data = await response.json();
        allTransactions = data.transactions || data;

        renderTable();
    } catch (error) {
        console.error('Error loading transactions:', error);
        showToast(`Error loading transactions: ${error.message}`, 'error');
    }
}

// --- Render filtered + sorted data ---
function renderTable() {
    let rows = [...allTransactions];

    // Apply column filters
    rows = rows.filter(t => {
        return Object.entries(colFilters).every(([col, val]) => {
            if (!val) return true;
            const cellVal = getColValue(t, col).toString().toLowerCase();
            return cellVal.includes(val.toLowerCase());
        });
    });

    // Apply sort
    if (sortCol) {
        rows.sort((a, b) => {
            let av = getColValue(a, sortCol);
            let bv = getColValue(b, sortCol);
            if (typeof av === 'string') av = av.toLowerCase();
            if (typeof bv === 'string') bv = bv.toLowerCase();
            if (av < bv) return sortDir === 'asc' ? -1 : 1;
            if (av > bv) return sortDir === 'asc' ? 1 : -1;
            return 0;
        });
    }

    if (rows.length === 0) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="6" class="empty-state">
                    <p>No transactions found.</p>
                </td>
            </tr>
        `;
        return;
    }

    tableBody.innerHTML = rows.map(t => `
        <tr class="category-${t.category}">
            <td>${t.transactionDate}</td>
            <td>${t.postDate}</td>
            <td>${t.description}</td>
            <td>${t.amount < 0 ? '($' : '$'}${Math.abs(t.amount).toFixed(2)}${t.amount < 0 ? ')' : ''}</td>
            <td>
                <select class="category-select" data-id="${t.id}" data-current="${t.category}">
                    ${generateCategoryOptions(t.category)}
                </select>
            </td>
            <td>${t.source}</td>
        </tr>
    `).join('');

    document.querySelectorAll('.category-select').forEach(select => {
        select.addEventListener('change', (e) => updateCategory(e.target.dataset.id, e.target.value));
    });
}

// --- Get a comparable value for a transaction column ---
function getColValue(t, col) {
    switch (col) {
        case 'transactionDate': return t.transactionDate || '';
        case 'postDate':        return t.postDate || '';
        case 'description':     return t.description || '';
        case 'amount':          return t.amount;
        case 'category':        return t.category || '';
        case 'source':          return t.source || '';
        default:                return '';
    }
}

// --- Sort on header click ---
document.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
        const col = th.dataset.col;
        if (sortCol === col) {
            sortDir = sortDir === 'asc' ? 'desc' : 'asc';
        } else {
            sortCol = col;
            sortDir = 'asc';
        }

        // Update header classes
        document.querySelectorAll('th.sortable').forEach(h => {
            h.classList.remove('sort-asc', 'sort-desc');
        });
        th.classList.add(sortDir === 'asc' ? 'sort-asc' : 'sort-desc');

        renderTable();
    });
});

// --- Filter on input ---
document.querySelectorAll('.col-filter').forEach(input => {
    input.addEventListener('input', (e) => {
        colFilters[e.target.dataset.col] = e.target.value;
        renderTable();
    });

    // Prevent header sort from firing when clicking into filter input
    input.addEventListener('click', (e) => e.stopPropagation());
});

function generateCategoryOptions(currentCategory) {
    // Use categories from API cache, sorted by sort_order
    const sortedCategories = categoriesCache.sort((a, b) => a.sort_order - b.sort_order);
    
    if (sortedCategories.length === 0) {
        // Fallback if categories haven't loaded yet
        console.warn('Categories cache empty, using hardcoded fallback');
        const fallback = ['Groceries', 'Dining', 'Gas', 'Utilities', 'Shopping', 'Travel', 'Health', 'Entertainment', 'Income', 'Other'];
        return fallback.map(cat => `
            <option value="${cat}" ${cat === currentCategory ? 'selected' : ''}>${cat}</option>
        `).join('');
    }
    
    return sortedCategories.map(cat => `
        <option value="${cat.name}" ${cat.name === currentCategory ? 'selected' : ''}>${cat.name}</option>
    `).join('');
}

async function updateCategory(id, category) {
    try {
        const response = await fetch(`/transactions/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ category })
        });

        if (response.ok) {
            showToast('Category updated', 'success');
            loadTransactions();
        } else {
            showToast('Error updating category', 'error');
        }
    } catch (error) {
        showToast(`Error: ${error.message}`, 'error');
    }
}

// ========================================================================
// Load Summary
// ========================================================================
const summaryGrid = document.getElementById('summaryGrid');

async function loadSummary() {
    const month = monthSelect.value;
    if (!month) return;

    try {
        const response = await fetch(`/summary?month=${month}`);
        const summary = await response.json();

        if (Object.keys(summary).length === 0) {
            summaryGrid.innerHTML = `<div class="empty-state"><p>No data for this month.</p></div>`;
            return;
        }

        const sorted = Object.entries(summary)
            .sort(([, a], [, b]) => b - a);

        summaryGrid.innerHTML = sorted.map(([category, amount]) => {
            const formatted = amount < 0
                ? `($${Math.abs(amount).toFixed(2)})`
                : `$${amount.toFixed(2)}`;

            return `
                <div class="summary-item">
                    <span class="summary-item-label">${category}</span>
                    <span class="summary-item-amount category-${category}">
                        ${formatted}
                    </span>
                </div>
            `;
        }).join('');
    } catch (error) {
        console.error('Error loading summary:', error);
        showToast(`Error loading summary: ${error.message}`, 'error');
    }
}

// ========================================================================
// Sync to Google Sheets
// ========================================================================
const syncBtn = document.getElementById('syncBtn');

syncBtn.addEventListener('click', async () => {
    const month = monthSelect.value;
    if (!month) {
        showToast('Please select a month', 'info');
        return;
    }

    syncBtn.disabled = true;
    syncBtn.textContent = '🔄 Syncing...';

    try {
        const response = await fetch('/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ month })
        });

        const data = await response.json();

        if (response.ok) {
            showToast(
                `✓ Synced ${data.rows_written} transactions to Google Sheets`,
                'success',
                data.sheet_url
            );
        } else {
            showToast(`Error: ${data.detail}`, 'error');
        }
    } catch (error) {
        showToast(`Sync failed: ${error.message}`, 'error');
    } finally {
        syncBtn.disabled = false;
        syncBtn.textContent = '🔄 Sync to Google Sheets';
    }
});

// ========================================================================
// Initialize
// ========================================================================
document.addEventListener('DOMContentLoaded', () => {
    loadCategories();
    loadMonths();
});
