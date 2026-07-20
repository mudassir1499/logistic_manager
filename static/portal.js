/**
 * Portal JavaScript Module for the Logistics Manager Customer Portal
 * 
 * This file handles user-facing interactions on the public/customer portal pages:
 * - Toast notifications using Bootstrap's built-in Toast component
 * - Auto-dismissal of Django flash messages (alerts)
 * 
 * The portal is where customers track their shipments and view their order history.
 * These scripts improve the user experience by providing non-blocking feedback.
 */

/**
 * Displays a Bootstrap Toast notification to the user.
 * 
 * Unlike the admin dashboard's custom toast in main.js, this portal version uses
 * Bootstrap's native Toast component for a polished, consistent look.
 * 
 * Args:
 *     message (string): The text content to display inside the toast body.
 *     type (string): The contextual style of the toast.
 *                    'success' = green background,
 *                    'error' = red background (rendered as 'danger' in Bootstrap),
 *                    Anything else = blue background (rendered as 'info' in Bootstrap).
 * 
 * Returns:
 *     undefined (void): Modifies the DOM directly; no return value.
 * 
 * Business Logic:
 *     When a customer logs in, submits a tracking request, or updates their profile,
 *     Django renders a template with a flash message. The portal template injects
 *     that message into a hidden toast container, or backend views pass it via context.
 *     This function is called to programmatically show toast messages from JS.
 */
function showToast(message, type = 'success') {
    // Get the container element where toast elements will be appended.
    // This is a fixed-position div at the bottom or top of the portal pages.
    const container = document.getElementById('toastContainer');
    if (!container) return;
    // If the container doesn't exist, exit silently to avoid runtime errors.
    // This allows the script to be included safely on pages without toast containers.

    // Create a new div element that will become the toast.
    const toast = document.createElement('div');
    
    // Set the CSS classes for the toast.
    // We use a template literal (backticks) to dynamically insert the Bootstrap background color class.
    // 'bg-success' = green, 'bg-danger' = red, 'bg-info' = blue.
    // The ternary operator maps 'error' to 'danger' because Bootstrap uses 'danger', not 'error'.
    toast.className = `toast align-items-center text-white bg-${type === 'success' ? 'success' : type === 'error' ? 'danger' : 'info'}`;
    
    toast.setAttribute('role', 'alert');
    // Add ARIA 'role="alert"' for accessibility.
    // Screen readers will announce the toast content when it appears.

    // Build the inner HTML structure required by Bootstrap's Toast component.
    // It consists of:
    // 1. A flex container (.d-flex) to align the body and close button horizontally.
    // 2. The message text inside .toast-body.
    // 3. A close button (btn-close) that is styled white for contrast on dark backgrounds.
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${message}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    // 'data-bs-dismiss="toast"' is a Bootstrap data attribute that tells Bootstrap's JS
    // to hide this toast when the button is clicked.

    // Add the constructed toast element to the DOM so it becomes visible.
    container.appendChild(toast);
    
    // Initialize the Bootstrap Toast JavaScript component on the new element.
    if (typeof bootstrap === 'undefined') {
        console.warn('Bootstrap JS not loaded; toast skipped.');
        return;
    }
    const bsToast = new bootstrap.Toast(toast, { delay: 4000 });
    // 'delay: 4000' means the toast will automatically hide after 4000 milliseconds (4 seconds).
    
    bsToast.show();
    // Trigger the show animation. The toast slides in from the edge of the screen.

    // Listen for Bootstrap's 'hidden.bs.toast' event, which fires after the hide animation completes.
    // When the toast is fully hidden, remove it from the DOM to keep the page clean.
    toast.addEventListener('hidden.bs.toast', () => toast.remove());
}

// Auto-hide alerts after 5 seconds
// This section handles Django's server-rendered alert messages (e.g., "Login successful").
// Unlike the toasts above, these alerts are already in the HTML when the page loads.
document.addEventListener('DOMContentLoaded', function() {
    // Wait until the HTML is fully parsed before looking for alerts.
    
    // Select all elements with the 'alert' class, EXCLUDING those with 'alert-permanent'.
    // '.alert-permanent' is used for alerts that must stay visible until the user dismisses them manually.
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    
    alerts.forEach(alert => {
        // Loop through each alert that should auto-dismiss.
        
        // Schedule the dismissal to happen after 5000 milliseconds (5 seconds).
        // This gives the user enough time to read the message.
        setTimeout(() => {
            if (alert.classList.contains('fade')) {
                // Bootstrap's 'fade' class uses CSS transitions for smooth opacity changes.
                // For fading alerts, we remove the 'show' class, which triggers the CSS fade-out.
                alert.classList.remove('show');
                // After the CSS transition completes, Bootstrap's own JS usually removes the element.
                // If not, the element remains in the DOM but is invisible.
            } else {
                // For non-fading alerts (alerts without the 'fade' class), we manually fade the opacity.
                alert.style.opacity = '0';
                // Set inline opacity to 0 to make it invisible.
                
                // After the inline opacity transition (300ms), completely remove the element from the DOM.
                // This is a manual cleanup to prevent invisible elements from accumulating.
                setTimeout(() => alert.remove(), 300);
            }
        }, 5000);
    });
});

// =============================================================================
// MOBILE UX IMPROVEMENTS
// =============================================================================
// The following code runs on every portal page and provides:
// - Back to top button visibility toggle
// - Sticky navbar shrink on scroll
// - Scroll-triggered animations (IntersectionObserver-based AOS alternative)
// - Lazy loading helper for images
// - Smooth scroll behavior for anchor links
// =============================================================================

document.addEventListener('DOMContentLoaded', function() {
    // -------------------------------------------------------------------------
    // 1. BACK TO TOP BUTTON
    // -------------------------------------------------------------------------
    // Shows a "Back to Top" button after the user scrolls 300px down the page.
    // Clicking the button smoothly scrolls back to the top.
    const backToTop = document.getElementById('backToTop');
    if (backToTop) {
        // Listen for scroll events on the window.
        // We use a throttled approach (no setTimeout) for simplicity since modern
        // browsers handle scroll events efficiently enough for this use case.
        window.addEventListener('scroll', function() {
            // window.scrollY is the number of pixels the document has been scrolled vertically.
            // Show the button when scrolled 300px or more; hide it when above 300px.
            if (window.scrollY > 300) {
                backToTop.classList.add('visible');
            } else {
                backToTop.classList.remove('visible');
            }
        });

        // Smooth scroll to top when the button is clicked.
        backToTop.addEventListener('click', function() {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }

    // -------------------------------------------------------------------------
    // 2. STICKY NAVBAR SHRINK ON SCROLL
    // -------------------------------------------------------------------------
    // The navbar shrinks (reduced padding) when the user scrolls down to give
    // more vertical space to the page content. This is a common premium UX pattern.
    const navbar = document.querySelector('.portal-navbar');
    if (navbar) {
        window.addEventListener('scroll', function() {
            if (window.scrollY > 50) {
                navbar.classList.add('shrunk');
            } else {
                navbar.classList.remove('shrunk');
            }
        });
    }

    // -------------------------------------------------------------------------
    // 3. SCROLL-TRIGGERED ANIMATIONS (Custom AOS Implementation)
    // -------------------------------------------------------------------------
    // Uses IntersectionObserver — a high-performance browser API that watches
    // for elements entering the viewport. Much more efficient than scroll event
    // listeners for every animated element.
    //
    // How to use in HTML:
    //   <div class="animate-fade-up">Content</div>
    //   <div class="animate-fade-up animate-delay-2">Content with delay</div>
    //
    // The element starts invisible (opacity: 0, translated) and becomes visible
    // when it scrolls into the viewport.
    const animatedElements = document.querySelectorAll(
        '.animate-on-scroll, .animate-fade-up, .animate-fade-down, ' +
        '.animate-fade-left, .animate-fade-right, .animate-zoom-in'
    );

    if (animatedElements.length > 0 && 'IntersectionObserver' in window) {
        // IntersectionObserver calls the callback when observed elements cross
        // a specified threshold of the viewport. Threshold 0.1 means the element
        // must be at least 10% visible before the animation triggers.
        const observer = new IntersectionObserver(function(entries) {
            entries.forEach(function(entry) {
                if (entry.isIntersecting) {
                    // Add the 'is-visible' class which triggers the CSS transition.
                    entry.target.classList.add('is-visible');
                    // Once the element is visible, stop observing it.
                    // This prevents the animation from re-triggering on every scroll.
                    observer.unobserve(entry.target);
                }
            });
        }, {
            root: null,        // Use the viewport as the root
            rootMargin: '0px', // No margin around the root
            threshold: 0.1     // Trigger when 10% of the element is visible
        });

        animatedElements.forEach(function(el) {
            observer.observe(el);
        });
    } else if (animatedElements.length > 0) {
        // Fallback for browsers that don't support IntersectionObserver
        // (very rare in modern browsers, but good for older Safari/IE).
        // Immediately show all animated elements without animation.
        animatedElements.forEach(function(el) {
            el.classList.add('is-visible');
        });
    }

    // -------------------------------------------------------------------------
    // 4. LAZY LOADING HELPER
    // -------------------------------------------------------------------------
    // Automatically adds loading="lazy" to all images that don't already have it.
    // This defers offscreen images until the user scrolls near them, improving
    // initial page load speed and reducing data usage on mobile connections.
    //
    // Additionally, we add a fade-in effect when lazy images finish loading by
    // listening for the 'load' event and adding a CSS class.
    const images = document.querySelectorAll('img:not([loading])');
    images.forEach(function(img) {
        img.setAttribute('loading', 'lazy');
    });

    // Add fade-in effect for images that are lazy-loaded.
    document.querySelectorAll('img[loading="lazy"]').forEach(function(img) {
        if (!img.complete) {
            img.classList.add('lazy-loading');
            img.addEventListener('load', function() {
                img.classList.remove('lazy-loading');
                img.classList.add('lazy-loaded');
            });
        }
    });

    // -------------------------------------------------------------------------
    // 5. SMOOTH SCROLL FOR ANCHOR LINKS
    // -------------------------------------------------------------------------
    // When a user clicks a link that points to an anchor (e.g., href="#contact"),
    // smoothly scroll to that section instead of jumping instantly.
    document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
        anchor.addEventListener('click', function(e) {
            const targetId = this.getAttribute('href');
            if (targetId === '#') return; // Skip empty anchors
            const targetElement = document.querySelector(targetId);
            if (targetElement) {
                e.preventDefault();
                targetElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    });

    // -------------------------------------------------------------------------
    // 6. ADD-TO-CART BUTTONS
    // -------------------------------------------------------------------------
    // Product cards contain buttons with class .add-to-cart-btn. Clicking sends
    // an AJAX POST to /portal/cart/add/ and shows a toast confirmation.
    document.querySelectorAll('.add-to-cart-btn').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const productId = this.dataset.productId;
            const moq = parseInt(this.dataset.moq || '1', 10);
            if (!productId) return;

            const formData = new FormData();
            formData.append('product_id', productId);
            formData.append('quantity', moq);

            // Try to find a quantity input for this product card.
            const card = this.closest('.product-card') || this.closest('.col-sm-6, .col-lg-4, .col-xl-3');
            if (card) {
                const qtyInput = card.querySelector('.product-qty-input');
                if (qtyInput) {
                    formData.set('quantity', Math.max(moq, parseInt(qtyInput.value || moq, 10)));
                }
            }

            const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
            if (csrfInput) formData.append('csrfmiddlewaretoken', csrfInput.value);

            fetch('/portal/cart/add/', {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showToast(data.message, 'success');
                    // Update any cart badge in the navbar if present.
                    document.querySelectorAll('.cart-badge-count').forEach(function(el) {
                        el.textContent = data.cart_count || '0';
                    });
                    btn.disabled = true;
                    btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>In Cart';
                    btn.classList.remove('btn-primary');
                    btn.classList.add('btn-success');
                } else {
                    showToast(data.message || 'Could not add to cart.', 'error');
                }
            })
            .catch(function(error) {
                console.error('Add to cart error:', error);
                showToast('Something went wrong. Please try again.', 'error');
            });
        });
    });
});
