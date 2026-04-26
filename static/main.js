// ===== Sidebar Toggle =====
document.addEventListener('DOMContentLoaded', function () {
    const sidebar = document.getElementById('sidebar');
    const toggle = document.getElementById('sidebarToggle');

    if (toggle && sidebar) {
        toggle.addEventListener('click', function () {
            if (window.innerWidth <= 768) {
                sidebar.classList.toggle('mobile-open');
            } else {
                sidebar.classList.toggle('collapsed');
            }
        });
    }

    // Close mobile sidebar on link click
    document.querySelectorAll('.sidebar-link').forEach(function (link) {
        link.addEventListener('click', function () {
            if (window.innerWidth <= 768) {
                sidebar.classList.remove('mobile-open');
            }
        });
    });
});

// ===== Toast Notifications =====
function showToast(message, type) {
    type = type || 'info';
    var container = document.getElementById('toastContainer');
    var icons = { success: 'bi-check-circle-fill', error: 'bi-x-circle-fill', info: 'bi-info-circle-fill' };
    var colors = { success: '#10b981', error: '#ef4444', info: '#3b82f6' };

    var toast = document.createElement('div');
    toast.className = 'toast-msg ' + type;
    toast.innerHTML =
        '<i class="bi ' + (icons[type] || icons.info) + '" style="color:' + (colors[type] || colors.info) + ';font-size:20px"></i>' +
        '<span>' + message + '</span>';

    container.appendChild(toast);

    setTimeout(function () {
        toast.style.animation = 'slideOut 0.3s ease-out forwards';
        setTimeout(function () { toast.remove(); }, 300);
    }, 3000);
}

// ===== AJAX Form Helper =====
function ajaxSubmit(formId, url, onSuccess) {
    var form = document.getElementById(formId);
    if (!form) return;

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        var data = new FormData(form);
        var submitBtn = form.querySelector('[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';
        }

        fetch(url, { method: 'POST', body: data })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = 'Save';
                }
                if (data.success) {
                    showToast(data.message || 'Action completed!', 'success');
                    if (onSuccess) onSuccess(data);
                } else {
                    showToast(data.message || 'Something went wrong', 'error');
                }
            })
            .catch(function () {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = 'Save';
                }
                showToast('Network error. Please try again.', 'error');
            });
    });
}

// ===== Confirm Delete Helper =====
function confirmDelete(url, itemName) {
    if (confirm('Are you sure you want to delete "' + itemName + '"?')) {
        fetch(url, { method: 'POST' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    showToast(data.message || 'Deleted!', 'success');
                    setTimeout(function () { location.reload(); }, 500);
                } else {
                    showToast(data.message || 'Delete failed', 'error');
                }
            })
            .catch(function () {
                showToast('Network error', 'error');
            });
    }
}

// ===== Search/Filter Table =====
function setupTableSearch(inputId, tableId) {
    var input = document.getElementById(inputId);
    var table = document.getElementById(tableId);
    if (!input || !table) return;

    input.addEventListener('input', function () {
        var filter = this.value.toLowerCase();
        var rows = table.querySelectorAll('tbody tr');
        rows.forEach(function (row) {
            var text = row.textContent.toLowerCase();
            row.style.display = text.indexOf(filter) > -1 ? '' : 'none';
        });
    });
}