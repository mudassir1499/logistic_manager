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

// =============================================================================
// LOADING OVERLAY
// =============================================================================
// A single overlay shown while any server request is in flight.
//
// Before this, most actions gave no feedback at all. ajaxSubmit swapped the
// submit button for a spinner, but that only covers forms - and only forms with
// a findable submit button. Everything else (bulk actions, delete, confirm
// order, toggle private, the modal-populating GETs, CSV and photo uploads) ran
// silently. On a fast local machine that is invisible. On a shared host with a
// bulk action now able to cover the entire filtered catalogue, it is seconds of
// a frozen-looking page, and people click the button again.
//
// Design notes, each one there for a reason:
//
//   * Reference counted. Two requests in flight, one finishes, the overlay must
//     stay up for the other. A plain boolean hides too early.
//
//   * Delayed appearance. Showing instantly means a 40ms request produces a
//     flash of overlay, which reads as a glitch. Nothing appears unless the
//     request is still running after APPEAR_DELAY_MS.
//
//   * Safety timeout. If a request never settles - a dropped connection that
//     the browser does not time out promptly, a promise that is never resolved -
//     a blocking overlay would trap the user with no way out. After
//     MAX_VISIBLE_MS it clears itself and says so.
// =============================================================================
var AppLoading = (function () {
    var APPEAR_DELAY_MS = 250;
    var MAX_VISIBLE_MS = 60000;

    var pending = 0;
    var appearTimer = null;
    var safetyTimer = null;
    var overlay = null;
    var textEl = null;

    function build() {
        if (overlay) return;
        overlay = document.createElement('div');
        overlay.className = 'app-loading-overlay';
        // Announced politely so a screen reader says what is happening without
        // interrupting whatever it is currently reading.
        overlay.setAttribute('role', 'status');
        overlay.setAttribute('aria-live', 'polite');
        overlay.innerHTML =
            '<div class="app-loading-card">' +
            '<div class="app-loading-spinner"></div>' +
            '<div class="app-loading-text"></div>' +
            '</div>';
        document.body.appendChild(overlay);
        textEl = overlay.querySelector('.app-loading-text');
    }

    function paint(message) {
        build();
        textEl.textContent = message;
        overlay.classList.add('is-visible');
    }

    function clear() {
        pending = 0;
        if (appearTimer) { clearTimeout(appearTimer); appearTimer = null; }
        if (safetyTimer) { clearTimeout(safetyTimer); safetyTimer = null; }
        if (overlay) overlay.classList.remove('is-visible');
    }

    return {
        /**
         * Register the start of one operation.
         *
         * Args:
         *     message (string): What to show if it runs long enough to appear.
         */
        begin: function (message) {
            pending += 1;
            if (pending > 1) return;   // already counting down or visible

            appearTimer = setTimeout(function () {
                appearTimer = null;
                // The first message wins for the whole burst. Rewriting the text
                // as concurrent requests start and finish is just flicker.
                paint(message || 'Working...');

                safetyTimer = setTimeout(function () {
                    clear();
                    if (typeof showToast === 'function') {
                        showToast('That is taking longer than expected. The page has been unlocked - reload if it did not finish.', 'error');
                    }
                }, MAX_VISIBLE_MS);
            }, APPEAR_DELAY_MS);
        },

        /** Register the end of one operation. Hides once nothing is outstanding. */
        end: function () {
            pending = Math.max(0, pending - 1);
            if (pending === 0) clear();
        },

        /** Force everything down. For error paths that need the UI back now. */
        reset: clear
    };
})();

/**
 * Show the loading overlay for work this file does not drive through fetch.
 *
 * Pair every call with hideLoading(), including on the failure path, or the
 * overlay stays up until the safety timeout releases it.
 *
 * Args:
 *     message (string): Optional label. Defaults to "Working...".
 */
function showLoading(message) { AppLoading.begin(message); }

/** Counterpart to showLoading(). */
function hideLoading() { AppLoading.end(); }


// =============================================================================
// CSRF PROTECTION FOR ALL AJAX REQUESTS
// =============================================================================
// Django rejects state-changing requests that arrive without a CSRF token. The
// back-office worked around that by putting @csrf_exempt on ~36 views —
// including order create/edit/delete and settings updates. That disabled a real
// protection: any page a logged-in admin visited could POST to those endpoints
// on their behalf, and the browser would attach their session cookie.
//
// Most of this app's fetch() calls already sent the token by hand, but ten did
// not, which is why the exemptions could not simply be deleted. Rather than
// patch ten call sites and hope none are missed later, fetch is wrapped once
// here: every same-origin, state-changing request gets the header automatically.
//
// This only ADDS a header. Calls that already set their own X-CSRFToken keep it,
// cross-origin requests are left completely untouched, and GET/HEAD/OPTIONS —
// which Django does not check — are passed straight through.
// =============================================================================
(function () {
    var SAFE_METHODS = { GET: 1, HEAD: 1, OPTIONS: 1, TRACE: 1 };
    var nativeFetch = window.fetch;
    if (!nativeFetch) return;

    // Requests the user did not ask for. A background poll or a keystroke-driven
    // lookup must never throw a blocking overlay over the page - the notification
    // bell alone would do it every 60 seconds.
    var QUIET_URLS = [
        '/portal/notification-counts/',
        '/orders/admin-stats/',
        '/accounts/search/'
    ];

    function isQuiet(url, init) {
        if (init && init.quiet) return true;
        for (var i = 0; i < QUIET_URLS.length; i++) {
            if (url.indexOf(QUIET_URLS[i]) !== -1) return true;
        }
        return false;
    }

    function readCsrfCookie() {
        var match = document.cookie.match(/(^|;\s*)csrftoken=([^;]*)/);
        return match ? decodeURIComponent(match[2]) : null;
    }

    function isSameOrigin(url) {
        try {
            // Relative URLs resolve against the current origin, so they are same-origin
            // by definition. Absolute ones are compared properly.
            return new URL(url, window.location.href).origin === window.location.origin;
        } catch (e) {
            return false;
        }
    }

    window.fetch = function (input, init) {
        init = init || {};
        var method = (init.method || (input && input.method) || 'GET').toUpperCase();
        var url = (typeof input === 'string') ? input : (input && input.url) || '';

        if (!SAFE_METHODS[method] && isSameOrigin(url)) {
            var token = readCsrfCookie();
            if (token) {
                // Headers may arrive as a Headers instance, an array of pairs, or a
                // plain object. Normalising to Headers handles all three without
                // clobbering anything the caller already set.
                var headers = new Headers(init.headers || (input && input.headers) || {});
                if (!headers.has('X-CSRFToken')) {
                    headers.set('X-CSRFToken', token);
                }
                init = Object.assign({}, init, { headers: headers });
                // Same-origin credentials so the session cookie still rides along.
                if (!init.credentials) { init.credentials = 'same-origin'; }
            }
        }

        var request = nativeFetch.call(this, input, init);
        if (isQuiet(url, init)) return request;

        // Callers can name the operation with `loadingMessage`; otherwise the
        // method decides, because "Saving..." over a GET that is populating a
        // modal is simply wrong.
        AppLoading.begin(
            (init && init.loadingMessage) ||
            (SAFE_METHODS[method] ? 'Loading...' : 'Working...')
        );

        // then/catch rather than .finally so this keeps working on older
        // browsers, and re-throwing preserves the rejection for the caller.
        //
        // This settles when the response headers arrive, not when the body has
        // been read. Every endpoint here returns small JSON, and the wait being
        // covered is the server's, so that is the right moment.
        return request.then(
            function (response) { AppLoading.end(); return response; },
            function (error) { AppLoading.end(); throw error; }
        );
    };
})();

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
            
            var overlay = document.getElementById('sidebarOverlay');

            if (window.innerWidth <= 768) {
                // Mobile: the sidebar slides in OVER the page, so the dimming
                // overlay belongs with it — it is what the user taps to close.
                sidebar.classList.toggle('mobile-open');
                if (overlay) {
                    overlay.classList.toggle('active');
                }
            } else {
                // Desktop: the sidebar narrows to icons IN PLACE. Nothing is
                // covered, so there is nothing to dim.
                //
                // The overlay used to be toggled above this branch, i.e. on every
                // click at every width. Collapsing the sidebar on a desktop
                // therefore dropped a fixed, full-screen rgba(15,23,42,.35) sheet
                // with a 2px blur over the whole page at z-index 1035 — the page
                // greyed out, and because the sheet takes pointer events, every
                // field under it stopped responding. Measured on the Noon Label
                // screen: labelQty, cartonQty and labelMark all received the click
                // on .sidebar-overlay instead of themselves, so the form could not
                // be filled in at all.
                sidebar.classList.toggle('collapsed');
                // remove(), not toggle(): if the viewport was resized from mobile
                // to desktop while the sidebar was open, the overlay is already
                // active and toggling would leave it stuck on.
                if (overlay) {
                    overlay.classList.remove('active');
                }
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
    // Green (#157F4A) for success, red (#B3261E) for error, slate (#44546A) for info.
    var colors = { success: '#157F4A', error: '#B3261E', info: '#44546A' };

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
/**
 * Turn an HTTP status that produced a non-JSON body into a message that says
 * what to do about it.
 *
 * Every one of these used to surface as "Network error. Please try again.",
 * which is wrong in all of them and actively misleading in most: retrying a 413
 * with the same file fails identically every time.
 *
 * Args:
 *     status (number): The HTTP status code of the response.
 *
 * Returns:
 *     string: A message naming the likely cause.
 */
function describeNonJsonResponse(status) {
    if (status === 413) {
        return 'That file is too large for the server to accept. Try an image under 2 MB.';
    }
    if (status === 403) {
        return 'Session expired or permission denied. Reload the page and sign in again.';
    }
    if (status === 404) {
        return 'That address does not exist on the server (404).';
    }
    if (status === 502 || status === 503 || status === 504) {
        return 'The server is not responding (' + status + '). It may be restarting — wait a moment and retry.';
    }
    if (status >= 500) {
        return 'The server hit an error (' + status + '). The details are in the server error log.';
    }
    return 'Unexpected reply from the server (' + status + '). See the browser console for details.';
}

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
        
        // Find the submit button. It may live inside the form OR outside it (e.g. a
        // modal footer button associated via form="<id>"), so fall back to a
        // document-wide lookup by the form attribute.
        var submitBtn = form.querySelector('[type="submit"]') ||
                        document.querySelector('[type="submit"][form="' + formId + '"]');
        // Remember the original label so we can restore it (not a hardcoded "Save",
        // which would wrongly relabel a "Create Order" button).
        var submitBtnLabel = submitBtn ? submitBtn.innerHTML : '';

        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';
        }

        // Send the form data to the Django backend using the modern fetch() API.
        // Read the body as TEXT, then try to parse it as JSON.
        //
        // Calling r.json() directly looks tidier but hides the most common real
        // failures. When the web server rejects an upload it replies with an
        // HTML error page, not JSON — a 413 when the file exceeds the server's
        // request-body limit, or a 500 when Django could not write the file to
        // MEDIA_ROOT. r.json() then throws a SyntaxError, which lands in the
        // same .catch() as a genuine connection failure, and every one of those
        // very different problems was reported to the user as "Network error".
        // That message sent people looking at their internet connection while
        // the actual cause sat in the server error log.
        fetch(url, { method: 'POST', body: data, loadingMessage: 'Saving...' })
            .then(function (r) {
                return r.text().then(function (text) {
                    var parsed = null;
                    try { parsed = JSON.parse(text); } catch (e) { /* not JSON */ }
                    return { ok: r.ok, status: r.status, data: parsed, text: text };
                });
            })
            .then(function (res) {
                // Re-enable the submit button regardless of success or failure.
                // The user might want to correct errors and try again.
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = submitBtnLabel;
                }

                if (res.data) {
                    if (res.data.success) {
                        showToast(res.data.message || 'Action completed!', 'success');
                        if (onSuccess) onSuccess(res.data);
                        // If the caller provided a callback function, execute it now.
                        // This is used for custom behavior like closing a modal, redirecting, or updating a table.
                    } else {
                        // The view returned {'success': false, ...} (e.g. validation errors).
                        showToast(res.data.message || 'Something went wrong', 'error');
                    }
                    return;
                }

                // A reply the server produced, but not one this code can use.
                // Name the status so the cause is actionable.
                showToast(describeNonJsonResponse(res.status), 'error');
                console.error('Expected JSON from ' + url + ', got HTTP ' + res.status + ':',
                              res.text.slice(0, 2000));
            })
            // Reached only when the request never completed: offline, DNS
            // failure, the connection dropped, or the request was aborted.
            .catch(function (err) {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = submitBtnLabel;
                }
                showToast('Could not reach the server. Check your connection and try again.', 'error');
                console.error('Request to ' + url + ' failed:', err);
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
            headers: { 'X-CSRFToken': getCookie('csrftoken') },
            loadingMessage: 'Deleting...'
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

    /**
     * Renders one clickable row in the notification dropdown.
     *
     * These used to be plain <div>s, so seeing "3 Pending Order(s)" told you a
     * number and then made you go and find the page yourself. They are links now:
     * the notification IS the way into the work.
     */
    function notificationRow(href, icon, colour, title, description) {
        var a = document.createElement('a');
        a.className = 'notification-item';
        a.href = href;
        a.innerHTML =
            '<i class="bi ' + icon + '" style="color:' + colour + '"></i>' +
            '<div class="notification-body">' +
                '<div class="notification-title">' + title + '</div>' +
                '<div class="notification-desc">' + description + '</div>' +
            '</div>';
        return a;
    }

    /**
     * Mirrors a count onto a sidebar badge, hiding it at zero.
     * Keeps the sidebar and the bell telling the same story.
     */
    function setSidebarBadge(id, count) {
        var el = document.getElementById(id);
        if (!el) return;
        if (count > 0) {
            el.textContent = count > 99 ? '99+' : count;
            el.hidden = false;
        } else {
            el.hidden = true;
        }
    }

    function loadCounts() {
        fetch('/portal/notification-counts/')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var leads = data.new_leads || 0;
                var requests = data.pending_requests || 0;
                var orders = data.pending_orders || 0;
                var total = leads + requests + orders;

                if (total > 0) {
                    badge.textContent = total > 99 ? '99+' : total;
                    badge.style.display = 'flex';
                } else {
                    badge.style.display = 'none';
                }
                if (countLabel) {
                    countLabel.textContent = total + ' unread';
                }

                setSidebarBadge('leadsBadge', leads);
                setSidebarBadge('requestsBadge', requests);

                if (list) {
                    list.innerHTML = '';
                    // Leads first: they are the only item here where a slow reply
                    // loses the business money rather than just delaying work.
                    if (leads > 0) {
                        list.appendChild(notificationRow(
                            '/portal/admin/leads/', 'bi-inbox', '#C2410C',
                            leads + ' website ' + (leads === 1 ? 'enquiry' : 'enquiries'),
                            'Awaiting a reply'));
                    }
                    if (requests > 0) {
                        list.appendChild(notificationRow(
                            '/portal/admin/requests/', 'bi-clipboard-check', '#B08421',
                            requests + ' product request' + (requests === 1 ? '' : 's'),
                            'Pending review from customers'));
                    }
                    if (orders > 0) {
                        list.appendChild(notificationRow(
                            '/orders/?placed=no', 'bi-cart-check', '#44546A',
                            orders + ' order' + (orders === 1 ? '' : 's') + ' not placed',
                            'Not yet placed with supplier'));
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

/* =============================================================================
   GLOBAL SEARCH (Ctrl+K) — extends the sidebar section search with live server
   results (orders / customers / products) from /accounts/search/. Results are
   appended into the same dropdown under a divider, and respect the current
   user's module permissions server-side.
   ============================================================================= */
(function () {
    var input = document.getElementById('sidebarSearchInput');
    var results = document.getElementById('sidebarSearchResults');
    if (!input || !results) return;

    // Ctrl+K / Cmd+K focuses the search from anywhere in the back office.
    document.addEventListener('keydown', function (e) {
        if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            var sidebar = document.getElementById('sidebar');
            if (sidebar) sidebar.classList.remove('collapsed');
            input.focus();
            input.select();
        }
    });
    input.setAttribute('placeholder', 'Search…  (Ctrl+K)');

    var timer = null;
    input.addEventListener('input', function () {
        var q = this.value.trim();
        if (timer) clearTimeout(timer);
        if (q.length < 2) return;
        timer = setTimeout(function () {
            fetch('/accounts/search/?q=' + encodeURIComponent(q), {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(function (r) { return r.ok ? r.json() : { results: [] }; })
            .then(function (data) {
                // Stale response guard: only render if the query hasn't changed.
                if (input.value.trim() !== q || !data.results || !data.results.length) return;
                var divider = document.createElement('div');
                divider.className = 'nav-section-title';
                divider.style.padding = '8px 12px 4px';
                divider.textContent = 'Data';
                results.appendChild(divider);
                data.results.forEach(function (hit) {
                    var a = document.createElement('a');
                    a.href = hit.url;
                    a.innerHTML = '<i class="bi ' + hit.icon + '"></i> <span class="link-text">' +
                        hit.label.replace(/</g, '&lt;') + ' <small style="opacity:.6">' + hit.section + '</small></span>';
                    results.appendChild(a);
                });
                results.classList.add('active');
            })
            .catch(function () { /* search is best-effort */ });
        }, 250);
    });
})();
