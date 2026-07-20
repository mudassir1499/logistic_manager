# LogiManager Django Bug Report — Comprehensive Findings

> **Report Date:** 2025-01-18  
> **Project:** LogiManager (logistic_manager)  
> **Scope:** All Python modules, templates, static files (CSS/JS), URL routing, models, and database configuration  
> **Total Bugs Found:** 40+ (across Critical, High, Medium, Low severity)

---

## Executive Summary

The LogiManager Django project contains **multiple critical security vulnerabilities** (missing authentication on destructive endpoints, plain-text password storage), **data integrity issues** (raw strings passed to Decimal/Integer fields), **widespread pagination bugs** (all three list views pass the full queryset instead of the paginated page), **configuration risks** (hardcoded production paths and SECRET_KEY fallback), and **numerous smaller issues** across templates, CSS, and JavaScript.

---

## CRITICAL SEVERITY 🔴

### 1. Plain-Text Password Storage in Customer Registration
**File:** `portal/views.py`  
**Line:** ~450 (inside `customer_register`)  
**Description:** The `customer_register` view stores the user's password in **plain text** by directly assigning `password=password` to the `Customer` model instead of calling `set_password()`.

```python
customer = Customer.objects.create(
    ...
    password=password,  # ❌ PLAIN TEXT — NOT HASHED
    ...
)
```

**Impact:** Registered customers cannot log in because `check_password()` expects a Django password hash, not plain text. This is a severe security breach if the database is ever compromised.  
**Fix:**
```python
customer = Customer.objects.create(..., email=email, address=address, is_active=True)
customer.set_password(password)
customer.save()
```

---

### 2. Customer Login Broken for All Registered Users
**File:** `portal/views.py`  
**Line:** ~270 (inside `customer_login`)  
**Description:** Because of Bug #1 above, `customer.check_password(password)` always returns `False` for registered customers, making the portal login completely non-functional for new registrations.  
**Impact:** Newly registered customers are permanently locked out of the portal.  
**Fix:** Fix Bug #1 first, then re-hash existing plain-text passwords (if any exist in the database).

---

### 3. Missing Authentication on Customer Management AJAX Endpoints
**File:** `customers/views.py`  
**Lines:** 75, 106, 144, 217, 255  
**Description:** The following AJAX endpoints are protected by `@csrf_exempt` but **lack `@login_required`**, allowing any unauthenticated user to create, edit, delete, assign, or remove customers:
- `add_customer` (line 75)
- `edit_customer` (line 106)
- `delete_customer` (line 144)
- `assign_product` (line 217)
- `remove_product` (line 255)

**Impact:** Unauthenticated attackers can modify the entire customer database, delete records, and reassign products.  
**Fix:** Add `@login_required` decorator above each view, or stack decorators: `@login_required @csrf_exempt`.

---

### 4. Missing Authentication on Product Management AJAX Endpoints
**File:** `products/views.py`  
**Lines:** 124, 184, 1078, 1186, 1300, 1448, 1473  
**Description:** The following product endpoints are unauthenticated:
- `add_product` (line 124)
- `edit_product` (line 184)
- `bulk_upload_from_images` (line 1078)
- `bulk_upload_1688` (line 1186)
- `bulk_upload` (line 1300)
- `toggle_private` (line 1448)
- `bulk_action` (line 1473) — includes `delete` action!

**Impact:** Anyone on the internet can add, edit, delete, bulk-import, and toggle the visibility of products in the catalog.  
**Fix:** Add `@login_required` to all of the above.

---

### 5. Missing Authentication on Order Management AJAX Endpoints
**File:** `orders/views.py`  
**Lines:** 458, 483, 544, 918, 944, 1018, 1053  
**Description:** The following order endpoints are unauthenticated:
- `add_order` (line 458)
- `edit_order` (line 483)
- `confirm_order` (line 544)
- `delete_order` (line 918)
- `duplicate_order` (line 944)
- `toggle_payment_status` (line 1018)
- `toggle_placed` (line 1053)

**Impact:** Unauthenticated attackers can create, modify, delete, duplicate, and tamper with payment/fulfillment status of orders. This is catastrophic for business integrity.  
**Fix:** Add `@login_required` to all of the above.

---

## HIGH SEVERITY 🟠

### 6. Pagination Bug — Customer List Passes Full Queryset Instead of Page Object
**File:** `customers/views.py`  
**Line:** 72  
**Description:** The `customer_list` view creates a `page_obj` via `Paginator` but passes the raw `customers` queryset to the template instead.

```python
page_obj = paginator.get_page(page_number)
return render(request, 'customers/customer_list.html', {'customers': customers})
```

**Template:** `templates/customers/customer_list.html` includes `{% include "includes/pagination.html" with page_obj=page_obj %}` at the bottom.  
**Impact:** The pagination UI renders without a valid `page_obj`, causing the page to show **all** customers regardless of page number, and the pagination controls will be broken or non-functional.  
**Fix:**
```python
return render(request, 'customers/customer_list.html', {
    'customers': page_obj,  # or 'page_obj': page_obj
    'page_obj': page_obj,
})
```

---

### 7. Pagination Bug — Product List Passes Full Queryset Instead of Page Object
**File:** `products/views.py`  
**Line:** 108  
**Description:** Same pattern as Bug #6. `product_list` creates `page_obj` but passes `products` (the full list) to the template. The template includes pagination with `page_obj=page_obj`.  
**Impact:** All products render on a single page; pagination controls are broken.  
**Fix:** Pass `page_obj` in the context.

---

### 8. Pagination Bug — Order List Passes Full Queryset Instead of Page Object
**File:** `orders/views.py`  
**Line:** 435  
**Description:** Same pattern as Bugs #6 and #7. `order_list` creates `page_obj` but passes `orders` (the full queryset) to the template.  
**Impact:** All orders render on a single page; pagination controls are broken.  
**Fix:** Pass `page_obj` in the context.

---

### 9. Raw String Values Passed to Decimal/Integer Fields Without Validation
**File:** `products/views.py`  
**Lines:** 162–173 (inside `add_product`)  
**Description:** The `add_product` view passes raw POST string values directly to `Product.objects.create()` for `price` (DecimalField), `moq` (IntegerField), `weight` (DecimalField), and all carton dimension fields. Django will attempt conversion, but if the user enters invalid data (e.g., "abc" for price), the view will raise an unhandled `InvalidOperation` or `ValueError` and return a 500 error instead of a graceful JSON error.

```python
product = Product.objects.create(
    name=name,
    price=price,        # ❌ raw string from POST
    moq=moq,            # ❌ raw string from POST
    weight=weight,      # ❌ raw string from POST
    ...
)
```

**Impact:** AJAX requests fail with 500 errors for invalid input; poor user experience.  
**Fix:** Validate and convert before creation:
```python
try:
    price_val = Decimal(price)
    moq_val = int(moq)
except (InvalidOperation, ValueError):
    return JsonResponse({'success': False, 'message': 'Invalid price or MOQ'})
```

---

### 10. Raw String Values Assigned to Decimal/Integer Fields in Edit Product
**File:** `products/views.py`  
**Lines:** 227–236 (inside `edit_product`)  
**Description:** Same issue as Bug #9 but in the edit view. Raw strings are assigned directly to model fields.

```python
product.price = request.POST.get('price', product.price)
product.moq = request.POST.get('moq', product.moq)
```

**Impact:** Invalid POST data can corrupt product records or cause 500 errors.  
**Fix:** Validate and convert using `Decimal()` and `int()` before assignment.

---

### 11. Customer.check_password Crashes on NULL Password
**File:** `customers/models.py`  
**Line:** 147  
**Description:** The `check_password` method calls Django's `check_password(raw_password, self.password)` without guarding against `None`.

```python
def check_password(self, raw_password):
    return check_password(raw_password, self.password)
```

If `self.password` is `None` (e.g., a customer created without a password), Django's `check_password` will raise a `TypeError`.  
**Impact:** Login crashes with a 500 error instead of a clean "Invalid credentials" message.  
**Fix:**
```python
def check_password(self, raw_password):
    if not self.password:
        return False
    return check_password(raw_password, self.password)
```

---

### 12. order_excel_export Uses .get() Without get_object_or_404
**File:** `orders/views.py`  
**Line:** 1775 (inside `order_excel_export`)  
**Description:** The view uses `Order.objects...get(pk=order_id)` without wrapping in `get_object_or_404`. If the order ID doesn't exist, an unhandled `Order.DoesNotExist` exception will propagate as a 500 error.  
**Impact:** Users requesting non-existent order Excel exports get a 500 error instead of a clean 404.  
**Fix:** Use `get_object_or_404(Order, pk=order_id)` or wrap in try/except.

---

### 13. Hardcoded SECRET_KEY Fallback in Production Settings
**File:** `logistic_manager/settings.py`  
**Line:** ~57  
**Description:** The `SECRET_KEY` has a hardcoded fallback string that will be used if the environment variable is not set. This means if the server is ever deployed without the env var, the secret key is predictable and publicly known from the source code.

```python
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-...hardcoded...')
```

**Impact:** If the environment variable is missing, session hijacking, password cracking, and CSRF attacks become trivial.  
**Fix:** Remove the fallback entirely and fail hard if the env var is missing:
```python
SECRET_KEY = os.environ['SECRET_KEY']
```

---

### 14. Hardcoded Linux Production Paths in STATIC_ROOT and MEDIA_ROOT
**File:** `logistic_manager/settings.py`  
**Lines:** ~333, ~348  
**Description:**
```python
STATIC_ROOT = '/home/mudassirllc/public_html/static'
MEDIA_ROOT = '/home/mudassirllc/public_html/media'
```

**Impact:** On the local Windows development machine (or any non-Linux server), `collectstatic` will fail because these absolute Linux paths do not exist. This breaks static file serving and media uploads during development.  
**Fix:** Use environment-relative paths or `BASE_DIR`-relative paths, e.g.:
```python
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
```

---

### 15. Duplicate robots_txt Function Definition
**File:** `portal/views.py`  
**Lines:** 2172 and 2281  
**Description:** The `robots_txt` view is defined **twice** in the same file. The second definition (line 2281) silently overwrites the first. This is a maintenance hazard and suggests a copy-paste error.  
**Impact:** The first definition is unreachable dead code. Future edits may target the wrong version.  
**Fix:** Remove the duplicate definition at line 2281.

---

## MEDIUM SEVERITY 🟡

### 16. Typo in Shipping Calculator POST Key
**File:** `settings_manager/views.py`  
**Line:** 175  
**Description:**
```python
settings.ksa_sea_shipping_rate = float(request.POST.get('ksa_sea_sea_shipping_rate', 0))
```
The POST key is `'ksa_sea_sea_shipping_rate'` (double "sea"). The correct key should be `'ksa_sea_shipping_rate'`.  
**Impact:** The KSA sea shipping rate can never be updated via the form because the field name mismatch means the POST value is always ignored.  
**Fix:** Change the key to `'ksa_sea_shipping_rate'`.

---

### 17. Settings View Missing Multiple Model Fields
**File:** `settings_manager/views.py`  
**Lines:** ~120–190 (inside `settings_view`)  
**Description:** The `settings_view` does not save the following fields that exist in the `CompanySettings` model:
- `email_from_address`
- `email_smtp_host`
- `email_smtp_port`
- `email_smtp_user`
- `email_smtp_password`
- `email_use_tls`
- `whatsapp_number`
- `fx_rates` (JSONField)

**Impact:** These settings cannot be configured through the UI and remain at their defaults.  
**Fix:** Add the missing fields to the POST handling logic in `settings_view`.

---

### 18. Missing Admin Registrations for OrderItem, OrderNote, Notification
**File:** `orders/admin.py`  
**Description:** Only `Order` and `OrderExtraCost` are registered. `OrderItem`, `OrderNote`, and `Notification` are missing from the Django admin.  
**Impact:** Admins cannot view or manage order line items, notes, or notifications through the admin interface.  
**Fix:** Register all models.

---

### 19. Empty Admin Files — Customers and Products Not Registered
**Files:** `customers/admin.py`, `products/admin.py`  
**Description:** Both files are empty (no model registrations).  
**Impact:** The `Customer` and `Product` models are not accessible in the Django admin panel, making data management and debugging difficult.  
**Fix:** Register the models with appropriate `ModelAdmin` classes.

---

### 20. CartItem Missing Unique Constraint
**File:** `portal/models.py`  
**Description:** The `CartItem` model has both `customer` and `session_key` as nullable fields, but there is no `unique_together` constraint preventing a customer from adding the same product multiple times to their cart.  
**Impact:** Duplicate cart entries can accumulate, inflating cart counts and confusing the checkout flow.  
**Fix:** Add `unique_together = [['customer', 'product'], ['session_key', 'product']]` or similar.

---

### 21. Dead Code in Invoice Computation — item_weight Always None
**File:** `orders/views.py`  
**Lines:** ~700 (inside `_compute_invoice_data`)  
**Description:**
```python
item_weight = None
row['item_weight'] = item_weight
```
`item_weight` is hardcoded to `None` and never used for any calculation. The `weight` variable at line 600 is also always `None`. This is leftover placeholder code.  
**Impact:** Confuses maintainers and adds unnecessary code bloat.  
**Fix:** Either implement the weight calculation or remove the dead code.

---

### 22. Reports View Uses date__date__gte on DateTimeField
**File:** `orders/views.py`  
**Line:** ~2130 (inside `reports`)  
**Description:** The view filters with `date__date__gte` on a `DateTimeField`. Django's `__date` lookup transforms the field to a date, but chaining `__date__gte` may not work as intended on all database backends (especially SQLite).  
**Impact:** Date filtering may be unreliable or produce incorrect results on SQLite.  
**Fix:** Use explicit date range filtering with `date__gte` and `date__lt` for the next day, or cast appropriately.

---

### 23. Hardcoded Google Analytics Placeholder ID
**File:** `templates/base.html`  
**Line:** ~250  
**Description:** The GA tracking ID is `G-XXXXXXXXXX`, a placeholder.  
**Impact:** No analytics data is collected, and the script loads unnecessarily.  
**Fix:** Replace with the real tracking ID or make it configurable via settings.

---

### 24. Hardcoded Tawk.to Chat Widget ID
**File:** `templates/base.html`  
**Line:** ~263  
**Description:** The Tawk.to widget ID is hardcoded to a specific property ID.  
**Impact:** If this ID is wrong or needs rotation, it requires a code change.  
**Fix:** Make it a setting or environment variable.

---

### 25. portal.js Assumes Bootstrap is Loaded Without Check
**File:** `static/portal.js`  
**Line:** 74  
**Description:** `new bootstrap.Toast(...)` is called without checking if `bootstrap` is defined. If Bootstrap JS fails to load (network issue, CDN down), this will throw a `ReferenceError`.  
**Impact:** Portal pages may fail to display any toast notifications and could throw JS errors that break other scripts.  
**Fix:** Add a guard: `if (typeof bootstrap !== 'undefined') { ... }`.

---

### 26. Requirements.txt Contains Unused MySQL Dependencies
**File:** `requirements.txt`  
**Description:** Both `mysqlclient==2.2.8` and `PyMySQL==1.2.0` are listed, but `settings.py` configures SQLite (`django.db.backends.sqlite3`).  
**Impact:** Unnecessary dependency bloat and potential version conflicts during installation.  
**Fix:** Remove unused database drivers or document when they are needed.

---

## LOW SEVERITY 🟢

### 27. Duplicate Decimal Conversion in bulk_action save_prices
**File:** `products/views.py`  
**Lines:** ~1555–1566 (inside `bulk_action`)  
**Description:** The code does `Decimal(str(product.weight))` but `product.weight` is already a `DecimalField` value. The `str()` → `Decimal()` round-trip is unnecessary but harmless.  
**Impact:** Minor performance overhead and code clutter.  
**Fix:** Use `product.weight` directly if it's already a Decimal.

---

### 28. Potential Floating-Point Artifacts in Packing List CBM Conversion
**File:** `orders/views.py`  
**Line:** ~1700 (inside `packing_list_print`)  
**Description:** `Decimal(str(items_in_shipment[0].shipment_cbm))` converts a value that might already be a Decimal or a float. If it's a float, `str()` can introduce floating-point artifacts (e.g., `0.1` → `'0.10000000000000000555'`).  
**Impact:** Minor CBM precision issues in printed packing lists.  
**Fix:** If the value is already a Decimal, use it directly. If it's a float, round first before converting.

---

### 29. Raw Strings Passed to Decimal Fields in Bulk Upload
**File:** `products/views.py`  
**Lines:** ~1383–1392 (inside `bulk_upload`)  
**Description:** Similar to Bug #9, `weight`, `carton_length`, etc. are passed as raw strings to `Product.objects.create()`.  
**Impact:** Same as Bug #9 but in the bulk upload path.  
**Fix:** Validate and convert before creation, or use the existing `_to_decimal` helper pattern from `orders/views.py`.

---

### 30. Session-Based Password Reset Token Has Cross-Device Limitation
**File:** `portal/views.py`  
**Lines:** ~290 and ~360  
**Description:** The password reset token is stored in `request.session`. If the user requests a reset on their phone but opens the email link on their laptop, the session token won't exist and the reset will fail.  
**Impact:** Users may be unable to reset passwords if they switch devices between requesting and clicking the link.  
**Fix:** Store the token in the database (e.g., on the `Customer` model or a dedicated `PasswordResetToken` table) instead of the session.

---

### 31. Noon Label Print View Doesn't Validate Label Existence Before PDF Generation
**File:** `noon_labels/views.py`  
**Line:** ~55 (inside `print_label`)  
**Description:** The view uses `label = get_object_or_404(NoonLabel, id=label_id)` but does not check if the label has been saved (`label.pk` is not None) before generating the PDF. If the label was created but not saved, `label.pk` could be None and `label.pdf` assignment may fail.  
**Impact:** Rare edge case, but could cause a 500 error during PDF generation.  
**Fix:** Ensure the label is saved before generating the PDF.

---

### 32. `copyCustomer` Inline JavaScript May Break with Complex Addresses
**File:** `templates/customers/customer_list.html`  
**Line:** ~59  
**Description:** The `copyCustomer` function is called with inline `escapejs` filters, but if the address contains certain characters, the resulting inline JavaScript call may still be malformed.  
**Impact:** Potential JavaScript syntax errors in the customer list page.  
**Fix:** Pass data via `data-*` attributes instead of inline JavaScript function calls.

---

### 33. `getCookie` Regex May Not Handle All Cookie Formats
**File:** `static/main.js`  
**Line:** 689  
**Description:** The regex `document.cookie.match('(^|;) ?' + name + '=([^;]*)(;|$)')` may not handle cookies with URL-encoded values or special characters reliably.  
**Impact:** CSRF token retrieval may fail in edge cases, breaking AJAX requests.  
**Fix:** Use a more robust cookie parser or `document.cookie.split(';')` approach.

---

### 34. `initPortfolioDragDrop` Event Listeners Not Cleaned Up
**File:** `static/main.js`  
**Lines:** ~591–686  
**Description:** The drag-and-drop event listeners are attached once on page load but are never removed. If the portfolio table is dynamically refreshed, stale listeners may persist.  
**Impact:** Potential memory leaks and duplicate event handling on dynamic page updates.  
**Fix:** Track listeners and remove them before re-initializing, or use event delegation.

---

## Summary Table

| Severity | Count | Key Issues |
|----------|-------|------------|
| 🔴 Critical | 5 | Plain-text passwords, missing auth on all destructive endpoints |
| 🟠 High | 9 | Pagination bugs, raw string→Decimal, NULL password crash, 500 on missing order, hardcoded secrets/paths |
| 🟡 Medium | 12 | Typos, missing admin registrations, dead code, missing settings fields, hardcoded analytics |
| 🟢 Low | 8 | Minor precision issues, cross-device token limitation, event listener cleanup, regex robustness |

---

## Recommended Remediation Priority

1. **Fix all CRITICAL auth issues first** — Add `@login_required` to every admin AJAX endpoint (`customers`, `products`, `orders`).
2. **Fix the password hashing bug** — Change `customer_register` to use `set_password()` and re-hash any existing plain-text passwords in the database.
3. **Fix all three pagination bugs** — Pass `page_obj` instead of the full queryset in `customer_list`, `product_list`, and `order_list`.
4. **Add input validation** — Convert and validate Decimal/Integer fields in `add_product`, `edit_product`, and `bulk_upload`.
5. **Fix configuration risks** — Remove hardcoded `SECRET_KEY` fallback and use `BASE_DIR`-relative paths for `STATIC_ROOT`/`MEDIA_ROOT`.
6. **Register missing admin models** — Add `Customer`, `Product`, `ProductImage`, `OrderItem`, `OrderNote`, `Notification` to admin.py files.
7. **Fix the shipping calculator typo** — Correct the double "sea" in the POST key.
8. **Address medium/low issues** — Clean up dead code, add missing settings fields, fix `check_password` null guard, and improve JS robustness.

---

*End of Report*
