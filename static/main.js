/**
 * Main JavaScript Module for the Logistics Manager Admin Dashboard
 * 
 * This file contains shared utility functions used across the admin interface:
 * - Sidebar toggle behavior (responsive mobile/desktop)
 * - Toast notification system (user feedback messages)
 * - AJAX form submission helper (saves data without page reload)
 * - Delete confirmation with AJAX (safe record deletion)
 * - Live table search/filter (quickly find rows in data tables)
 * - Sidebar search (filter navigation across all sections)
 * - Notification bell (unread product requests and pending orders)
 * - Admin stats bar (real-time KPIs on every page)
 * - Portfolio drag-and-drop reordering
 * - Product image hover preview
 * 
 * All functions are designed to work with the Django backend's JSON API responses.
 */

// ===== Sidebar Toggle =====
// This section handles the collapsible left sidebar navigation.
// On desktop, it toggles a 'collapsed' class for a compact view.
// On mobile, it toggles a 'mobile-open' class to slide the sidebar in/out.
document.addEventListener('DOMContentLoaded', function () {
    // Wait for the DOM to be fully loaded before attaching event listeners.
    // This ensures all HTML elements exist before we try to reference them.
    
    const sidebar = document.getElementById('sidebar');
    // Get the sidebar element. This is the fixed left navigation panel.
    // It contains links to all sections: Orders, Shipments, Customers, etc.
    
    const toggle = document.getElementById('sidebarToggle');
    // Get the hamburger/menu button that triggers the sidebar toggle.
    // Usually located in the top navbar.

    if (toggle && sidebar) {
        // Only add the click listener if both elements exist on the current page.
        // Some pages might not have a sidebar (e.g., login pages), so this prevents errors.
        
        toggle.addEventListener('click', function () {
            // When the user clicks the toggle button...
            
            // Also toggle the overlay if it exists (for mobile sidebar)
            var overlay = document.getElementById('sidebarOverlay');
            if (overlay) {
                overlay.classList.toggle('active');
            }
            
            if (window.innerWidth <= 768) {
                // Check if the viewport is mobile (768px is the standard Bootstrap breakpoint).
                // On mobile, we don't collapse—we show/hide the sidebar as an overlay.
                sidebar.classList.toggle('mobile-open');
                // 'mobile-open' class typically slides the sidebar into view from the left.
                // 'toggle' means: if it's open, close it; if closed, open it.
            } else {
                // On desktop (screens wider than 768px)...
                sidebar.classList.toggle('collapsed');
                // 'collapsed' class usually narrows the sidebar to show only icons,
                // giving more horizontal space to the main content area.
            }
        });
    }

    // Close mobile sidebar on link click
    // When a user taps a navigation link on mobile, we want the sidebar to close
    // automatically so they can see the new page content without manually closing it.
    document.querySelectorAll('.sidebar-link').forEach(function (link) {
        // Select all anchor tags inside the sidebar that have the 'sidebar-link' class.
        // 'forEach' loops through each link and attaches a listener.
        
        link.addEventListener('click', function () {
            // When any sidebar link is clicked...
            
            if (window.innerWidth <= 768) {
                // Only do this on mobile. On desktop, the sidebar stays open
                // because there's enough space.
                sidebar.classList.remove('mobile-open');
                // Remove the 'mobile-open' class to hide the sidebar.
                // We use 'remove' (not 'toggle') because we definitely want it closed.
            }
        });
    });
});

// ===== Toast Notifications =====
/**
 * Displays a temporary popup message (toast) to the user.
 * 
 * Toasts are non-blocking notifications that appear at the bottom or top of the screen
 * and automatically disappear after a few seconds. They provide feedback without
 * interrupting the user's workflow.
 * 
 * Args:
 *     message (string): The text to display inside the toast.
 *     type (string): The visual style of the toast. 
 *                    'success' = green (things went well),
 *                    'error' = red (something failed),
 *                    'info' = blue (neutral information).
 * 
 * Returns:
 *     undefined (void): This function does not return a value; it modifies the DOM directly.
 * 
 * Business Logic:
 *     After a user submits a form or deletes a record, the Django backend sends back a JSON
 *     response with a message. We call showToast() to display that message so the user
 *     knows if the action succeeded or failed. This is better than a full page reload with
 *     a flash message because it feels faster and smoother.
 */
function showToast(message, type) {
    // Default to 'info' if the caller didn't specify a type.
    // This prevents errors from undefined type keys in the icon/color lookup objects.
    type = type || 'info';
    
    var container = document.getElementById('toastContainer');
    // Find the dedicated div in the HTML where all toast messages are injected.
    // This container is usually fixed at the bottom-right of the viewport.
    
    // Lookup table for Bootstrap Icons. We map the type string to a specific icon class.
    // 'bi-check-circle-fill' = green checkmark, 'bi-x-circle-fill' = red X, 'bi-info-circle-fill' = blue info.
    var icons = { success: 'bi-check-circle-fill', error: 'bi-x-circle-fill', info: 'bi-info-circle-fill' };
    
    // Lookup table for icon colors. These hex codes match the project's color palette.
    // Green (#10b981) for success, Red (#ef4444) for error, Blue (#3b82f6) for info.
    var colors = { success: '#10b981', error: '#ef4444', info: '#3b82f6' };

    var toast = document.createElement('div');
    // Create a new <div> element in memory. It is not yet visible on the page.
    
    toast.className = 'toast-msg ' + type;
    // Add CSS classes. 'toast-msg' provides the base styling (position, padding, animation).
    // The type class (e.g., 'success') may add a left border or background tint.
    
    // Build the inner HTML of the toast.
    // It contains:
    // 1. An icon <i> tag with the appropriate Bootstrap icon class and color.
    // 2. A <span> containing the actual message text.
    toast.innerHTML =
        '<i class="bi ' + (icons[type] || icons.info) + '" style="color:' + (colors[type] || colors.info) + ';font-size:20px"></i>' +
        '<span>' + message + '</span>';
    // The '|| icons.info' and '|| colors.info' are fallbacks.
    // If an unknown type is passed, we default to the info icon/color so the toast still renders.

    container.appendChild(toast);
    // Append the newly created toast to the container div.
    // Now it becomes visible in the browser because it's part of the DOM.

    // Schedule the toast to disappear after 3000 milliseconds (3 seconds).
    setTimeout(function () {
        // First, trigger the slide-out CSS animation by setting the animation property.
        toast.style.animation = 'slideOut 0.3s ease-out forwards';
        // 'forwards' keeps the element in its final animated state (fully off-screen).
        
        // After the animation finishes (300ms), completely remove the element from the DOM.
        // This prevents the DOM from accumulating hidden toast elements over time.
        setTimeout(function () { toast.remove(); }, 300);
    }, 3000);
}

// ===== AJAX Form Helper =====
/**
 * Attaches an AJAX submit handler to a form, preventing the default page reload.
 * 
 * This helper function turns any standard HTML form into a dynamic form that submits
 * in the background via JavaScript's fetch() API. It is the core of the single-page
 * feel in the admin dashboard.
 * 
 * Args:
 *     formId (string): The HTML 'id' attribute of the <form> element to enhance.
 *     url (string): The Django URL endpoint to submit the form data to (e.g., '/orders/create/').
 *     onSuccess (function, optional): A callback function to execute if the server responds
 *                                     with success. Receives the parsed JSON response data.
 * 
 * Returns:
 *     undefined (void): Attaches an event listener; does not return a value.
 * 
 * Business Logic:
 *     In a logistics system, users frequently create or edit records (orders, customers, shipments).
 *     Reloading the entire page after every save is slow and disruptive. This helper sends the form
 *     data asynchronously, shows a toast message, and optionally refreshes only the relevant part
 *     of the page or redirects programmatically.
 */
function ajaxSubmit(formId, url, onSuccess) {
    var form = document.getElementById(formId);
    // Look up the form element in the DOM using its unique ID.
    
    if (!form) return;
    // If the form doesn't exist on this page, exit silently.
    // This prevents errors if the script is included on a page that doesn't have that specific form.

    // Attach a 'submit' event listener to the form.
    // The 'submit' event fires when the user clicks the submit button OR presses Enter inside a field.
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        // Stop the browser's default form submission behavior.
        // Without this, the browser would navigate to the URL and reload the page.
        
        var data = new FormData(form);
        // Collect all the form's input values into a FormData object.
        // FormData automatically handles text inputs, textareas, selects, and file uploads.
        // It preserves the 'name' attributes of each field, which Django expects.
        
        var submitBtn = form.querySelector('[type="submit"]');
        // Find the submit button inside the form so we can disable it during submission.
        // This prevents the user from accidentally double-clicking and submitting twice.
        
        if (submitBtn) {
            // Only modify the button if we found one.
            submitBtn.disabled = true;
            // Disable the button. It becomes grayed out and unclickable.
            
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';
            // Replace the button text with a small Bootstrap spinner icon and the word "Saving...".
            // This gives the user immediate visual feedback that their request is being processed.
        }

        // Send the form data to the Django backend using the modern fetch() API.
        fetch(url, { method: 'POST', body: data })
            // The first .then() receives the raw HTTP Response object.
            // We call .json() to parse the response body as JSON.
            // Django views that handle AJAX usually return JsonResponse.
            .then(function (r) { return r.json(); })
            
            // The second .then() receives the parsed JavaScript object.
            .then(function (data) {
                // Re-enable the submit button regardless of success or failure.
                // The user might want to correct errors and try again.
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = 'Save';
                }
                
                if (data.success) {
                    // If the Django view returned {'success': true, ...}
                    showToast(data.message || 'Action completed!', 'success');
                    // Display the success message from the server, or a generic fallback.
                    
                    if (onSuccess) onSuccess(data);
                    // If the caller provided a callback function, execute it now.
                    // This is used for custom behavior like closing a modal, redirecting, or updating a table.
                } else {
                    // If the server returned {'success': false, ...} (e.g., validation errors).
                    showToast(data.message || 'Something went wrong', 'error');
                }
            })
            // The .catch() block handles network-level errors.
            // This fires if the user is offline, the server is down, or the request times out.
            .catch(function () {
                // Re-enable the button so the user can retry.
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = 'Save';
                }
                showToast('Network error. Please try again.', 'error');
            });
    });
}

// ===== Confirm Delete Helper =====
/**
 * Prompts the user for confirmation before deleting a record via AJAX.
 * 
 * This function prevents accidental data loss by requiring the user to confirm
 * the deletion in a browser dialog. If confirmed, it sends a POST request to the
 * server and reloads the page on success.
 * 
 * Args:
 *     url (string): The Django URL endpoint that handles the delete action.
 *     itemName (string): The display name of the item being deleted (shown in the prompt).
 * 
 * Returns:
 *     undefined (void): No return value; performs side effects (network request, page reload).
 * 
 * Business Logic:
 *     Deleting an order, customer, or shipment is destructive. We must be absolutely sure
 *     the admin intends to do this. The 'confirm' dialog is a simple built-in safeguard.
 *     After deletion, the page reloads so the list view no longer shows the deleted item.
 */
function confirmDelete(url, itemName) {
    // Display a browser-native confirmation dialog with the item name included.
    // This blocks the JavaScript thread until the user clicks OK or Cancel.
    if (confirm('Are you sure you want to delete "' + itemName + '"?')) {
        // Only proceed if the user clicked OK.
        
        // Send a POST request to the Django delete view.
        // We use POST (not DELETE) for broader compatibility and because Django forms often expect POST.
        fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCookie('csrftoken') }
        })
            .then(function (r) { return r.json(); })
            // Parse the JSON response from Django.
            .then(function (data) {
                if (data.success) {
                    // Deletion was successful on the server.
                    showToast(data.message || 'Deleted!', 'success');
                    
                    // Wait 500 milliseconds before reloading the page.
                    // This gives the user enough time to see the success toast before the page disappears.
                    setTimeout(function () { location.reload(); }, 500);
                } else {
                    // The server refused to delete (e.g., foreign key constraints, permissions).
                    showToast(data.message || 'Delete failed', 'error');
                }
            })
            // Handle network errors (server unreachable, timeout, etc.).
            .catch(function () {
                showToast('Network error', 'error');
            });
    }
}

// ===== Search/Filter Table =====
/**
 * Adds live client-side search/filtering to an HTML table.
 * 
 * As the user types into a search input, this function hides table rows that do not
 * contain the typed text. This is purely a frontend enhancement—no server request is made.
 * 
 * Args:
 *     inputId (string): The HTML 'id' of the <input> element the user types into.
 *     tableId (string): The HTML 'id' of the <table> element to filter.
 * 
 * Returns:
 *     undefined (void): Attaches an event listener; no return value.
 * 
 * Business Logic:
 *     Logistics admins manage hundreds of orders, customers, and shipments.
 *     Scrolling through long tables to find a specific record is inefficient.
 *     This function provides instant filtering so the admin can type a customer name,
 *     order ID, or tracking number and immediately see matching rows.
 */
function setupTableSearch(inputId, tableId) {
    var input = document.getElementById(inputId);
    // Get the search input field (usually an <input type="text"> with a placeholder).
    
    var table = document.getElementById(tableId);
    // Get the target table that contains the data to be filtered.
    
    if (!input || !table) return;
    // If either element is missing, exit silently. This makes the function safe
    // to include on pages where the table or input might not be present.

    // Listen for the 'input' event, which fires every time the user types, pastes, or deletes text.
    input.addEventListener('input', function () {
        var filter = this.value.toLowerCase();
        // Convert the search text to lowercase for case-insensitive comparison.
        // 'this' refers to the input element because we're inside its event listener.
        
        var rows = table.querySelectorAll('tbody tr');
        // Select all table rows inside the <tbody> section.
        // We intentionally skip <thead> so the header row is never hidden.
        
        rows.forEach(function (row) {
            // Loop through each data row.
            
            var text = row.textContent.toLowerCase();
            // Get all the text inside this row (across all columns) and lowercase it.
            // This means the search matches any column, not just the first one.
            
            // Check if the row's text contains the search string.
            // 'indexOf' returns -1 if the substring is not found.
            row.style.display = text.indexOf(filter) > -1 ? '' : 'none';
            // If found, set display to '' (default, visible). If not found, set display to 'none' (hidden).
        });
    });
}

// ===== Sidebar Search =====
/**
 * Filters sidebar navigation links as the user types in the sidebar search input.
 * Shows matching links and hides non-matching ones. Also populates a dropdown
 * with direct links to matching sections for quick keyboard navigation.
 */
function initSidebarSearch() {
    var input = document.getElementById('sidebarSearchInput');
    var results = document.getElementById('sidebarSearchResults');
    var nav = document.getElementById('sidebarNav');
    if (!input || !nav) return;

    var links = nav.querySelectorAll('.sidebar-link');
    var sectionTitles = nav.querySelectorAll('.nav-section-title');

    input.addEventListener('input', function () {
        var filter = this.value.toLowerCase().trim();
        results.innerHTML = '';
        if (!filter) {
            results.classList.remove('active');
            // Show all links and titles
            links.forEach(function (link) { link.style.display = ''; });
            sectionTitles.forEach(function (title) { title.style.display = ''; });
            return;
        }

        var matches = [];
        links.forEach(function (link) {
            var text = (link.textContent || '').toLowerCase();
            var href = (link.getAttribute('href') || '').toLowerCase();
            if (text.indexOf(filter) > -1 || href.indexOf(filter) > -1) {
                link.style.display = '';
                matches.push(link);
            } else {
                link.style.display = 'none';
            }
        });

        // Hide section titles if no links under them are visible
        sectionTitles.forEach(function (title) {
            var next = title.nextElementSibling;
            var anyVisible = false;
            while (next && !next.classList.contains('nav-section-title')) {
                if (next.classList.contains('sidebar-link') && next.style.display !== 'none') {
                    anyVisible = true;
                }
                next = next.nextElementSibling;
            }
            title.style.display = anyVisible ? '' : 'none';
        });

        // Populate dropdown results
        if (matches.length > 0) {
            matches.forEach(function (link) {
                var a = document.createElement('a');
                a.href = link.getAttribute('href') || '#';
                a.innerHTML = link.innerHTML;
                a.addEventListener('click', function () {
                    input.value = '';
                    results.classList.remove('active');
                    // Reset visibility
                    links.forEach(function (l) { l.style.display = ''; });
                    sectionTitles.forEach(function (t) { t.style.display = ''; });
                });
                results.appendChild(a);
            });
            results.classList.add('active');
        } else {
            var noResults = document.createElement('div');
            noResults.className = 'no-results';
            noResults.textContent = 'No sections found';
            results.appendChild(noResults);
            results.classList.add('active');
        }
    });

    // Close search results when clicking outside
    document.addEventListener('click', function (e) {
        var wrap = document.getElementById('sidebarSearchWrap');
        if (wrap && !wrap.contains(e.target)) {
            results.classList.remove('active');
        }
    });

    // Keyboard shortcut: Escape clears search
    input.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            input.value = '';
            results.classList.remove('active');
            links.forEach(function (l) { l.style.display = ''; });
            sectionTitles.forEach(function (t) { t.style.display = ''; });
        }
    });
}

// ===== Notification Bell =====
/**
 * Fetches unread notification counts (product requests + pending orders) from
 * the server and updates the bell badge. The dropdown shows summary details
 * and links to the relevant sections.
 */
function initNotificationBell() {
    var badge = document.getElementById('notificationBadge');
    var list = document.getElementById('notificationList');
    var countLabel = document.getElementById('notificationCount');
    if (!badge) return;

    function loadCounts() {
        fetch('/portal/notifications/')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var total = (data.pending_requests || 0) + (data.pending_orders || 0);
                if (total > 0) {
                    badge.textContent = total > 99 ? '99+' : total;
                    badge.style.display = 'flex';
                } else {
                    badge.style.display = 'none';
                }
                if (countLabel) {
                    countLabel.textContent = total + ' unread';
                }
                // Build dropdown list
                if (list) {
                    list.innerHTML = '';
                    if (data.pending_requests > 0) {
                        var item = document.createElement('div');
                        item.className = 'notification-item';
                        item.innerHTML =
                            '<i class="bi bi-clipboard-check" style="color:#a78bfa"></i>' +
                            '<div class="notification-body">' +
                                '<div class="notification-title">' + data.pending_requests + ' Product Request(s)</div>' +
                                '<div class="notification-desc">Pending review from customers</div>' +
                            '</div>';
                        list.appendChild(item);
                    }
                    if (data.pending_orders > 0) {
                        var item = document.createElement('div');
                        item.className = 'notification-item';
                        item.innerHTML =
                            '<i class="bi bi-cart-check" style="color:#f59e0b"></i>' +
                            '<div class="notification-body">' +
                                '<div class="notification-title">' + data.pending_orders + ' Pending Order(s)</div>' +
                                '<div class="notification-desc">Not yet placed with supplier</div>' +
                            '</div>';
                        list.appendChild(item);
                    }
                    if (total === 0) {
                        list.innerHTML = '<div class="notification-empty">All caught up!</div>';
                    }
                }
            })
            .catch(function () {
                // Silently fail — notifications are not critical
            });
    }

    // Load counts on page load
    loadCounts();
    // Refresh every 60 seconds
    setInterval(loadCounts, 60000);
}

/**
 * Toggles the notification dropdown visibility.
 */
function toggleNotificationDropdown() {
    var dropdown = document.getElementById('notificationDropdown');
    if (dropdown) {
        dropdown.classList.toggle('active');
    }
}

// Close notification dropdown when clicking outside
document.addEventListener('click', function (e) {
    var bell = document.getElementById('notificationBell');
    var dropdown = document.getElementById('notificationDropdown');
    if (bell && dropdown && !bell.contains(e.target)) {
        dropdown.classList.remove('active');
    }
});

// ===== Admin Stats Bar =====
/**
 * Fetches real-time admin KPI stats from the server and populates the mini
 * stat widgets that appear at the top of every admin page. This avoids
 * requiring every view to pass the same context data.
 */
function initAdminStats() {
    var container = document.getElementById('adminStatsInner');
    if (!container) return;

    fetch('/orders/admin-stats/')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!data.success) return;
            var stats = [
                { icon: 'bi-box-seam-fill', cls: 'indigo', label: 'Products', value: data.product_count || 0 },
                { icon: 'bi-people-fill', cls: 'emerald', label: 'Customers', value: data.customer_count || 0 },
                { icon: 'bi-cart-check-fill', cls: 'amber', label: 'Orders', value: data.order_count || 0 },
                { icon: 'bi-journal-text', cls: 'blue', label: 'Ledger', value: data.ledger_count || 0 },
                { icon: 'bi-clipboard-check', cls: 'purple', label: 'Requests', value: data.pending_requests || 0 },
                { icon: 'bi-exclamation-triangle', cls: 'danger', label: 'Pending', value: data.pending_orders || 0 },
            ];
            container.innerHTML = '';
            stats.forEach(function (s) {
                var div = document.createElement('div');
                div.className = 'admin-stat';
                div.innerHTML =
                    '<div class="stat-icon ' + s.cls + '"><i class="bi ' + s.icon + '"></i></div>' +
                    '<div class="stat-info">' +
                        '<div class="stat-value">' + s.value + '</div>' +
                        '<div class="stat-label">' + s.label + '</div>' +
                    '</div>';
                container.appendChild(div);
            });
        })
        .catch(function () {
            // Silently fail — stats are not critical to page operation
        });
}

// Initialize all shared components on DOM ready
document.addEventListener('DOMContentLoaded', function () {
    initSidebarSearch();
    initNotificationBell();
    initAdminStats();
});

// ===== Portfolio Drag & Drop Reorder =====
/**
 * Enables HTML5 drag-and-drop reordering for portfolio table rows.
 * After dropping, sends the new order to the server via AJAX.
 */
function initPortfolioDragDrop() {
    var tbody = document.getElementById('portfolioTableBody');
    if (!tbody) return;

    var rows = tbody.querySelectorAll('tr');
    var dragSrcEl = null;

    function handleDragStart(e) {
        dragSrcEl = this;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/html', this.innerHTML);
        this.classList.add('dragging');
    }

    function handleDragOver(e) {
        if (e.preventDefault) e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        return false;
    }

    function handleDragEnter(e) {
        this.classList.add('drag-over');
    }

    function handleDragLeave(e) {
        this.classList.remove('drag-over');
    }

    function handleDrop(e) {
        if (e.stopPropagation) e.stopPropagation();

        var targetRow = this;
        if (dragSrcEl !== targetRow) {
            // Swap the rows visually
            var tbody = dragSrcEl.parentNode;
            var allRows = Array.from(tbody.querySelectorAll('tr'));
            var srcIndex = allRows.indexOf(dragSrcEl);
            var targetIndex = allRows.indexOf(targetRow);

            if (srcIndex < targetIndex) {
                tbody.insertBefore(dragSrcEl, targetRow.nextSibling);
            } else {
                tbody.insertBefore(dragSrcEl, targetRow);
            }

            // Collect new order IDs
            var ids = [];
            tbody.querySelectorAll('tr').forEach(function (row) {
                var id = row.getAttribute('data-item-id');
                if (id) ids.push(parseInt(id, 10));
            });

            // Send new order to server
            var body = new FormData();
            body.append('csrfmiddlewaretoken', getCookie('csrftoken'));
            body.append('ids', JSON.stringify(ids));
            fetch('/portal/admin/portfolio/reorder/', {
                method: 'POST',
                headers: { 'X-CSRFToken': getCookie('csrftoken') },
                body: body
            })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    showToast('Order updated!', 'success');
                } else {
                    showToast(data.message || 'Failed to update order', 'error');
                }
            })
            .catch(function () {
                showToast('Network error while saving order', 'error');
            });
        }

        dragSrcEl.classList.remove('dragging');
        rows.forEach(function (row) { row.classList.remove('drag-over'); });
        return false;
    }

    function handleDragEnd(e) {
        rows.forEach(function (row) {
            row.classList.remove('dragging');
            row.classList.remove('drag-over');
        });
    }

    rows.forEach(function (row) {
        row.setAttribute('draggable', 'true');
        row.addEventListener('dragstart', handleDragStart, false);
        row.addEventListener('dragenter', handleDragEnter, false);
        row.addEventListener('dragover', handleDragOver, false);
        row.addEventListener('dragleave', handleDragLeave, false);
        row.addEventListener('drop', handleDrop, false);
        row.addEventListener('dragend', handleDragEnd, false);
    });
}

// Cookie helper for CSRF token (used by portfolio reorder and other AJAX calls)
function getCookie(name) {
    var v = document.cookie.match('(^|;) ?' + name + '=([^;]*)(;|$)');
    return v ? v[2] : null;
}

// ===== Product Image Hover Preview =====
/**
 * Attaches a larger image preview overlay to product card images.
 * The preview is injected once per page and reused for all cards.
 */
function initProductImagePreview() {
    var grids = document.querySelectorAll('#productsGrid, #privateProductsGrid');
    if (!grids.length) return;

    var preview = document.createElement('div');
    preview.className = 'product-image-hover-preview';
    preview.innerHTML = '<img src="" alt="Preview">';
    document.body.appendChild(preview);

    var previewImg = preview.querySelector('img');

    grids.forEach(function (grid) {
        grid.addEventListener('mouseover', function (e) {
            var media = e.target.closest('.product-card-media');
            if (!media) return;
            var img = media.querySelector('.product-card-img');
            if (img && img.src) {
                previewImg.src = img.src;
                // Position the preview above the card
                var rect = media.getBoundingClientRect();
                var scrollTop = window.pageYOffset || document.documentElement.scrollTop;
                var scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
                preview.style.left = (rect.left + rect.width / 2 + scrollLeft) + 'px';
                preview.style.top = (rect.top + scrollTop - 4) + 'px';
                preview.style.bottom = 'auto';
                preview.style.transform = 'translateX(-50%) translateY(-4px)';
                preview.style.opacity = '1';
            }
        });

        grid.addEventListener('mouseout', function (e) {
            var related = e.relatedTarget;
            if (!related || !related.closest('.product-card-media')) {
                preview.style.opacity = '0';
            }
        });
    });
}

// Initialize product preview on DOM ready if grids exist
document.addEventListener('DOMContentLoaded', function () {
    initProductImagePreview();
});
