# Deployment Guide — mudassirllc.com (cPanel + MySQL)

Deploying LogiManager to cPanel on `mudassirllc.com`, using MySQL through PyMySQL.

> **Credentials are never stored in this repository.** All secrets live in a
> `.env` file on the server (git-ignored) or in cPanel's environment variable
> panel. If you previously had the database password written in this guide,
> **change that password now** — it was committed in plain text.

---

# Part A — Deploying an update to the live site

Sections 1–10 below are **first-time setup**, done once. This part is the
routine release, and it is what you want if `mudassirllc.com` is already
serving.

```bash
source /home/mudassirllc/virtualenv/logistic_manager/3.12/bin/activate && cd /home/mudassirllc/logistic_manager
```

### A1. Back up the database — not optional for this release

The collation conversion in A4 rewrites every table, and `migrate` includes
schema changes that re-running cannot undo.

```bash
mysqldump -u <db_user> -p <db_name> > ~/backup_$(date +%F_%H%M).sql
```

Check the file is not empty (`ls -lh ~/backup_*.sql`) before going on. A
zero-byte dump means the credentials were wrong and you have no backup.

### A2. Code and environment

> **Check this before you rely on `git pull`.** `origin/master` currently holds
> only the 114-file skeleton from the initial commit — no `accounts/`, no
> `api/`, no `portal/`, no `extension/`. Everything since then is local. Until it
> is committed and pushed, `git pull` on the server is a no-op that reports
> "Already up to date" and deploys nothing, which looks exactly like a
> successful release. Confirm the server actually received the code:
>
> ```bash
> git log --oneline -1 && ls accounts/ api/ extension/ >/dev/null && echo "code present"
> ```

```bash
git pull
```

**`requirements.txt` HAS changed** — the REST API added three pure-Python
packages. This is the first release that needs an install step:

```bash
pip install -r requirements.txt
```

(Google sign-in itself added nothing; it uses only the standard library.)

Add the two Google values. The client ID is public; **the secret is a credential
and must never be committed** — `.env` is git-ignored, keep it that way:

```bash
printf '\nGOOGLE_OAUTH_CLIENT_ID=871993913086-pqlrbbro5c0bl2f5lor0oeotk7b8p1fk.apps.googleusercontent.com\nGOOGLE_OAUTH_CLIENT_SECRET=paste-the-secret-here\n' >> .env
```

`DJANGO_SECURE_SSL` must be `1`. With HTTPS off, the OAuth callback is built as
`http://…` and Google rejects that for anything but localhost, so every sign-in
fails with `redirect_uri_mismatch`.

### A3. Migrations

```bash
python manage.py migrate
```

Notable in this release:

| Migration | What it changes |
|---|---|
| `khata/0006_alter_ledgerentry_date` | Ledger entry date becomes writable (was `auto_now_add`, so dates could not be set at all) and gains an index |
| `products/0016`–`0021` | Variants, attributes, slugs, remote image URLs, price-adjustment log |
| `orders/0034_orderitem_variant` | Order lines can reference a variant |
| `portal/0007`, `0008` | Blog tables, cart variant |
| `accounts/0003`–`0005` | Email verification, 2FA flags, API tokens |
| `products/0022_canonicalise_source_urls` | Rewrites existing supplier URLs to a canonical form so the extension's duplicate check matches history |
| `settings_manager/0022_companysettings_share_contact_and_more` | Tagline and contact number added to a shared product message. Defaults are deliberately plain ASCII — this runs BEFORE the collation fix below, and a non-ASCII default on latin1 columns is rejected or mangled |

### A4. Fix the database collation

This is what breaks CSV product uploads with
`(1267, "Illegal mix of collations … for operation 'like'")`. Report first, then
apply:

```bash
python manage.py fix_db_collation
```

```bash
python manage.py fix_db_collation --apply
```

Needed regardless of the import error — latin1 columns cannot store Chinese
product names at all.

### A4b. Cache table — required by API rate limiting

DRF's throttling stores counters in Django's cache, which this project backs
with a database table. Without the table every throttled endpoint raises
`OperationalError: no such table: django_cache_table` and returns 500.

The table is created in first-time setup (Part B step 6) and the login lockout
already uses the same cache, so it is almost certainly present — but the command
is safe to re-run and does nothing if it exists:

```bash
python manage.py createcachetable
```

### A4c. Product images — required this release

Nothing renders a supplier CDN link any more. `ProductImage.src` and
`ProductVariant.src` return the stored file or nothing at all, because alicdn is
unreachable or throttled from Pakistan and much of the Gulf: a hotlinked photo
was a broken frame for the customer while looking fine to staff on a connection
that could reach it.

Rows imported before this release that hold only a URL therefore now render
**nothing**. Download what can still be downloaded, then clear the rest:

```bash
python manage.py fetch_remote_images
```

Report only. It also names any link that is a CDN placeholder (alicdn answers
`200` with a 1x1 pixel rather than a 404) so those are not mistaken for photos.

```bash
python manage.py fetch_remote_images --apply --purge-failed
```

`--purge-failed` **deletes** the image rows that still have no file after the
download pass, and requires `--apply`. It never deletes a variation row — those
carry price and stock and are referenced by orders — it only clears the dead
address on them. Products left without a photo show the placeholder; re-push
them from the sourcing extension, which sends the picture as bytes.

Run it on the SERVER, not locally: a laptop behind a VPN resolves every CDN host
into a private range, the SSRF guard refuses it, and the command then purges
rows it could have saved from a machine with clean DNS.

### A5. Static files, then restart

Required this release: `portal.css` changed (the product Specifications block was
rebuilt), and `portal.js` and `main.js` changed. Static files are hashed, so
until this runs the browser keeps serving the old copy and the fixes appear to do
nothing — the Share button in particular will keep copying only a bare URL.

```bash
python manage.py collectstatic --noinput && touch tmp/restart.txt
```

### A6. Verify

```bash
python manage.py check --deploy
```

**Read the output**, do not just check the exit code. The Google checks are
warnings rather than errors on purpose — a misconfigured optional sign-in method
must never block a deploy or an urgent migration.

| ID | Means |
|---|---|
| `settings_manager.E001` | `DJANGO_MEDIA_ROOT` is wrong — uploads will 404 |
| `settings_manager.W003` | Client ID malformed — `invalid_client` at the consent screen |
| `settings_manager.W004` | Only one of the two Google values set — button silently never appears |
| `settings_manager.W005` | Google on but HTTPS off — every sign-in fails |

```bash
python manage.py shell -c "from accounts import google_oauth; print('Google sign-in ready:', google_oauth.is_configured())"
```

Then in a browser: `/accounts/login/` shows **Continue with Google**; signing in
lands on the customer dashboard; `/khata/` shows **Export CSV** and **Import
CSV**; a product image upload either succeeds or reports a real reason rather
than "Network error".

Also this release:

- The **homepage** shows a grid of real products, not just a card linking to the
  catalogue. An empty grid means the catalogue has no public, non-draft product
  with a stored image — check `fetch_remote_images` ran.
- **`/shop/`** shows a *Marketplace* filter in the sidebar **only once more than
  one channel exists**. Every extension import is `general`, so until a product
  is tagged Amazon or Noon this is correctly absent. `/shop/?source=amazon`
  works regardless, and `/portal/products/amazon/` 301s to it.
- A **product page's Specifications** block reads label-then-value in two
  columns. If it still shows values flung to the right-hand edge, `collectstatic`
  did not take — the browser has the old `portal.css`.
- No product page anywhere should load an image from `alicdn.com`. Check with
  the browser's Network tab on a product imported from 1688.
- **Share** on a product page copies four lines — product name, tagline, contact
  number, link — not just the URL. Both the wording and the number are editable
  at **Settings → Company → Product Sharing**, which shows a live preview.
  Facebook is the exception: it ignores anything the button passes and reads the
  page's `og:description`, which now carries the same tagline.

### A6b. API — optional CORS

A native mobile app needs nothing here. A BROWSER client on another domain (a
PWA, a partner dashboard) is blocked unless its origin is allowlisted:

```bash
echo 'DJANGO_API_CORS_ORIGINS=https://app.mudassirllc.com' >> .env
```

Left unset, no cross-origin browser client can call the API — which is correct
until one exists. Docs are at `/api/v1/docs/`, schema at `/api/v1/schema/`.

### A7. Google Cloud console

Verified against Google's authorization endpoint: the client ID is valid and
both `https://mudassirllc.com/accounts/google/callback/` and
`https://www.mudassirllc.com/accounts/google/callback/` are registered. Both are
needed because `PREPEND_WWW` is `False` and both hosts are in `ALLOWED_HOSTS`,
so the callback follows whichever host the visitor arrived on.

**Still to do:** on the **Audience** page the app must be **Published**. While it
is in *Testing*, only the listed test users can sign in; everyone else gets
"access blocked". Publishing does not require Google's security review here —
`openid`, `email` and `profile` are non-sensitive scopes.

### Rolling back

```bash
git reset --hard <previous-commit> && python manage.py collectstatic --noinput && touch tmp/restart.txt
```

Migrations do not roll back with the code. To undo one, do it explicitly per app
(`python manage.py migrate <app> <previous_number>`) and read that migration's
reverse operation first — some data migrations have none, which is what the A1
backup is for.

---

# Part B — First-time setup

## 1. Prerequisites

- cPanel access to `mudassirllc.com` with **Setup Python App** available
- Python 3.12 (or the highest your host offers)
- SSH access (strongly preferred over File Manager)
- MariaDB 10.4+ / MySQL 8+ — Django 4.2 will refuse to start on older versions

---

## 2. Create the MySQL database

cPanel → **MySQL Databases**:

1. Create a database, e.g. `mudassirllc_logimanager`
2. Create a user with a **new, strong password** (do not reuse an old one)
3. Add the user to the database with **ALL PRIVILEGES**

### Character set — important

This system stores Chinese product names and emoji pasted from WhatsApp in
ledger descriptions. MySQL's legacy `utf8` is only 3 bytes per character and
**cannot store 4-byte characters** — those rows will error or be silently
truncated. The database must be `utf8mb4`.

cPanel usually creates databases as `utf8mb4` already. Confirm, and fix if not:

```sql
ALTER DATABASE mudassirllc_logimanager
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Verify:

```sql
SELECT default_character_set_name FROM information_schema.SCHEMATA
 WHERE schema_name = 'mudassirllc_logimanager';   -- expect: utf8mb4
```

---

## 3. Upload the project

Upload everything **except** these (they are git-ignored and must not go up):

| Skip | Why |
|------|-----|
| `.venv/` | Rebuilt on the server for the correct architecture |
| `db.sqlite3` | Local development database; production uses MySQL |
| `__pycache__/` | Stale bytecode for a different Python build |
| `.env` | You will create this fresh on the server |
| `*.png` screenshots | Working files, not part of the app |

Target layout:

```
/home/mudassirllc/logistic_manager/
├── manage.py
├── passenger_wsgi.py
├── requirements.txt
├── .env               ← you create this in step 5
├── logistic_manager/
├── products/  customers/  orders/  khata/  portal/  ...
├── templates/
└── static/
```

---

## 4. Create the Python app

cPanel → **Setup Python App** → Create:

- **Python version:** 3.12
- **Application root:** `logistic_manager`
- **Application URL:** `mudassirllc.com`
- **Application startup file:** `passenger_wsgi.py`

Then install dependencies (use the virtualenv path cPanel shows you):

```bash
cd /home/mudassirllc/logistic_manager
source /home/mudassirllc/virtualenv/logistic_manager/3.12/bin/activate
pip install -r requirements.txt
```

`mysqlclient` is deliberately **not** in requirements — it needs a C compiler and
usually fails on shared hosting. `settings.py` calls `pymysql.install_as_MySQLdb()`
so Django's MySQL backend runs on pure-Python PyMySQL instead.

---

## 5. Configure `.env`

```bash
cd /home/mudassirllc/logistic_manager
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(50))"   # generate a key
nano .env
chmod 600 .env        # readable only by your account
```

Fill in at minimum:

```ini
DJANGO_SECRET_KEY=<the 50+ char key you just generated>
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=mudassirllc.com,www.mudassirllc.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://mudassirllc.com,https://www.mudassirllc.com

DB_NAME=mudassirllc_logimanager
DB_USER=mudassirllc_logi
DB_PASSWORD=<the database password>
DB_HOST=localhost

DJANGO_STATIC_ROOT=/home/mudassirllc/public_html/static
DJANGO_MEDIA_ROOT=/home/mudassirllc/public_html/media

# Set to 0 only until the SSL certificate is installed, then back to 1.
DJANGO_SECURE_SSL=1
```

`DJANGO_DEBUG=0` is not optional. With DEBUG on, any error page exposes your
source code, settings and SQL queries to whoever triggered it.

If `localhost` fails to connect, try `DB_HOST=127.0.0.1` — some cPanel hosts
route `localhost` through a unix socket the Python app cannot reach.

---

## 6. Migrate, collect static, create your login

```bash
cd /home/mudassirllc/logistic_manager
source /home/mudassirllc/virtualenv/logistic_manager/3.12/bin/activate

python manage.py check --deploy      # should report no critical issues
python manage.py migrate
python manage.py createcachetable    # the app uses a database cache backend
python manage.py collectstatic --noinput
python manage.py createsuperuser

mkdir -p /home/mudassirllc/public_html/media
chmod 755 /home/mudassirllc/public_html/media
```

Restart the app from cPanel (or `touch passenger_wsgi.py`).

---

## 7. Email setup

SMTP credentials are **not** in `.env`. They are stored in the database and
edited in the admin UI, because the app supports three independent sending
profiles. Log in at `/admin/login/`, then go to **Settings** (`/settings/`).

| Profile | Used for | Suggested sender |
|---------|----------|------------------|
| **Order status** | Order confirmed, placed with supplier, shipped, delivered | `orders@mudassirllc.com` |
| **Security** | Registration, password reset, login alerts | `security@mudassirllc.com` |
| **News** | New Amazon/Noon product announcements | `news@mudassirllc.com` |

For each profile enter: **From address, SMTP host, port, username, password, TLS**.

Using cPanel's own mail (simplest — create the mailboxes in cPanel → Email Accounts):

```
Host: mail.mudassirllc.com
Port: 587
Username: orders@mudassirllc.com     (the full address)
Password: <the mailbox password>
Use TLS: yes
```

You can point all three profiles at the same mailbox to start; splitting them
later means a marketing-email problem can never affect password resets.

If a profile is left blank the app falls back to the default backend and simply
does not send — order flows keep working rather than erroring.

---

## 8. Post-deploy checks

```bash
curl -I https://mudassirllc.com/                    # 200, and redirects http -> https
```

- [ ] `/` public site loads with CSS
- [ ] `/admin/login/` — log in
- [ ] `/dashboard/` — stats and charts render
- [ ] `/products/` — product images load (check `public_html/media/` permissions)
- [ ] `/khata/` → a customer → **Export PDF** downloads and shows correct balances
- [ ] Place a test order and confirm the status email arrives

### Ledger PDF fonts on Linux

The PDF export picks a Unicode font at runtime. On Windows it uses Microsoft
YaHei; on Linux it looks for Noto CJK, then DejaVu, then falls back to a
Latin-only font. If Chinese characters come out blank in exported statements:

```bash
fc-list | grep -i "noto\|cjk" | head        # is a CJK font installed?
```

If none is present, ask your host to install `fonts-noto-cjk`, or drop a
`.ttf`/`.ttc` on the server and add its path to `_PDF_FONT_CANDIDATES` in
`khata/views.py`.

---

## 9. Migrating existing data (optional)

If you want the local SQLite records in production:

```bash
# Locally — exclude tables that must not be copied
python manage.py dumpdata --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission --exclude sessions \
  --indent 2 -o transfer.json
```

Upload `transfer.json`, then on the server **after** `migrate`:

```bash
python manage.py loaddata transfer.json
```

Write the dump as UTF-8 and confirm Chinese text and emoji survive the round
trip — this is exactly where a non-`utf8mb4` database corrupts data.

---

## 10. Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `ImproperlyConfigured: DJANGO_SECRET_KEY ... required` | `.env` missing or unreadable by the app user |
| 500 with no detail | Correct behaviour with `DEBUG=0` — read cPanel → Errors, or `stderr.log` |
| CSS/JS 404 | `collectstatic` not run, or `DJANGO_STATIC_ROOT` doesn't match `public_html/static` |
| Uploaded images 404 | `public_html/media/` missing or not `755` |
| CSRF verification failed | Host missing from `DJANGO_CSRF_TRUSTED_ORIGINS`, or scheme omitted |
| Infinite redirect loop | SSL terminating upstream — `SECURE_PROXY_SSL_HEADER` handles this; if it persists set `DJANGO_SECURE_SSL=0` and investigate |
| `Can't connect to MySQL server` | Try `DB_HOST=127.0.0.1`; confirm user has ALL PRIVILEGES |
| Chinese text shows as `???` | Database is not `utf8mb4` — see step 2 |

---

## Security checklist

- [ ] `DJANGO_DEBUG=0`
- [ ] `DJANGO_SECRET_KEY` is new, 50+ characters, never committed
- [ ] Old database password rotated (it was previously in this file in plain text)
- [ ] `.env` is `chmod 600` and git-ignored
- [ ] `db.sqlite3` not uploaded to the server or committed
- [ ] SSL installed and `DJANGO_SECURE_SSL=1`
- [ ] `python manage.py check --deploy` reviewed
