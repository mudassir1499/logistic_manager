# First Deploy to mudassirllc.com — cPanel (no SSH), MySQL, with your data

This is the **first-time** deploy into an **empty** MySQL database, bringing your
existing SQLite data up with it. Follow the steps in order.

## Files prepared for you (on your PC, in `Desktop\Business\`)

| File | What it is | Where it goes |
|------|-----------|---------------|
| `logimanager_deploy.zip` | The whole app (code only — no venv/db/secrets) | your home folder → extracts to `logistic_manager/` |
| `logimanager_media.zip` | Product images | `public_html/` → extracts to `public_html/media/` |
| `transfer.json` | Your data (users, customers, orders, ledger…) | inside `logistic_manager/` |

> `transfer.json` contains real customer data. Upload it, load it (step 6), then
> **delete it from the server**. Never email it or leave it in a public folder.

---

## 1. Create the MySQL database  (cPanel → **MySQL® Databases**)

1. **Create New Database** → name e.g. `mudassirllc_logimanager` (cPanel prefixes it).
2. **Add New User** → pick a **new strong password**. Write down user + password.
3. **Add User To Database** → grant **ALL PRIVILEGES**.
4. **Force the database to `utf8mb4` BEFORE you migrate — this is critical.** Many
   cPanel/MariaDB hosts default new databases to `latin1` or 3-byte `utf8mb3`,
   which **cannot store the emoji/Chinese** in your ledger. If you migrate first,
   the columns are built wrong and `loaddata` fails with
   `Incorrect string value ... (1366)`.
   Open **phpMyAdmin** → select the database → **SQL** tab → run:
   ```sql
   ALTER DATABASE `mudassirllc_logimanager` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```

> ### Already migrated and hit `Incorrect string value ... (1366)`?
> Your tables were built with the wrong charset. Fix it from **Terminal**:
> ```bash
> cd ~/logistic_manager && source ~/virtualenv/logistic_manager/3.12/bin/activate
> python manage.py shell <<'EOF'
> from django.db import connection
> name = connection.settings_dict['NAME']
> with connection.cursor() as c:
>     c.execute("ALTER DATABASE `%s` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci" % name)
>     c.execute("SET FOREIGN_KEY_CHECKS=0")
>     c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s", [name])
>     tables = [r[0] for r in c.fetchall()]
>     for t in tables:
>         c.execute("DROP TABLE IF EXISTS `%s`" % t)
>     c.execute("SET FOREIGN_KEY_CHECKS=1")
> print("DB now utf8mb4; dropped", len(tables), "old tables")
> EOF
> ```
> then re-run `migrate` → `createcachetable` → `loaddata transfer.json`.

---

## 2. Upload the code  (cPanel → **File Manager**)

1. Go to your **home** directory (e.g. `/home/mudassirllc`).
2. **Upload** `logimanager_deploy.zip` there.
3. Select it → **Extract**. You now have `~/logistic_manager/` with `manage.py`,
   `passenger_wsgi.py`, `requirements.txt`, all apps, `templates/`, `static/`.
4. Upload **`transfer.json`** into `~/logistic_manager/`.
5. Upload `logimanager_media.zip` into **`~/public_html/`** → **Extract** → gives
   `~/public_html/media/product_images/...`.

---

## 3. Create the Python app  (cPanel → **Setup Python App**)

**Create Application:**
- Python version: **3.12** (or the highest offered)
- Application root: **`logistic_manager`**
- Application URL: **mudassirllc.com**
- Application startup file: **` `**
- **Create.**

Note the two things cPanel shows you: the **virtualenv activation command** and the
"Enter to the virtual environment" line — you'll need it in step 5.

---

## 4. Create the `.env` file  (File Manager)

1. In `~/logistic_manager/`, copy **`.env.example`** → rename the copy to **`.env`**.
2. Right-click `.env` → **Edit**, fill in:

```ini
DJANGO_SECRET_KEY=<paste a freshly generated key - see step 5>
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=mudassirllc.com,www.mudassirllc.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://mudassirllc.com,https://www.mudassirllc.com

DB_NAME=<cpanel-account>_<database>
DB_USER=<cpanel-account>_<db-user>
DB_PASSWORD=<the strong password you chose in step 2>
DB_HOST=localhost

DJANGO_STATIC_ROOT=/home/mudassirllc/public_html/static
DJANGO_MEDIA_ROOT=/home/mudassirllc/public_html/media

DJANGO_SECURE_SSL=1     # set 0 only until SSL is active, then back to 1
```

- `DJANGO_DEBUG=0` is **mandatory** — DEBUG on leaks your code and DB on error pages.
- Generate the secret key with the command in step 5, or any "django secret key
  generator" online, then paste it in.

> **The two paths must be under `public_html`, not under `logistic_manager`.**
> This guide previously said `/home/mudassirllc/logistic_manager/static`, which is
> wrong twice over. First, Apache only serves what is inside the document root, so
> `collectstatic` writing anywhere else means the browser never sees the new CSS.
> Second, that path *is* the project's own source `static/` folder, and settings.py
> refuses to start when `STATIC_ROOT` overlaps `STATICFILES_DIRS` — you would get
> `ImproperlyConfigured: STATIC_ROOT ... overlaps with a STATICFILES_DIRS entry`.
> The values above match `.env.example`, which was correct all along.

---

## 5. Install dependencies + set up the database  (cPanel → **Terminal**)

Open **Terminal** (cPanel → Advanced → **Terminal**). Run, one block at a time:

```bash
cd ~/logistic_manager
source ~/virtualenv/logistic_manager/3.12/bin/activate     # use the exact path cPanel showed you

# (optional) generate a secret key to paste into .env, if you haven't:
python -c "import secrets; print(secrets.token_urlsafe(50))"

pip install -r requirements.txt

python manage.py check --deploy        # review warnings; must not error out
python manage.py migrate               # builds all tables in the empty MySQL DB
python manage.py createcachetable      # the app uses a database cache
python manage.py loaddata transfer.json   # ← loads ALL your data (users, customers, orders, ledger, images…)

# Clear out any previous build first. Stale files here are served by Apache in
# preference to anything Django produces, so an old stylesheet left behind will
# keep overriding the new one indefinitely.
rm -rf ~/public_html/static

python manage.py collectstatic --noinput  # writes CSS/JS into public_html/static
```

> **`collectstatic` must run with `DJANGO_DEBUG=0` already set in `.env`.** With
> DEBUG off, static files are served through WhiteNoise's *manifest* storage,
> which needs a `staticfiles.json` index that only gets written when collectstatic
> runs in that mode. Run it with DEBUG on and no manifest is produced — then every
> page on the site returns a 500 with
> `ValueError: Missing staticfiles manifest entry for 'style.css'`.
> If you ever see that error, the fix is to re-run collectstatic with DEBUG=0.

> **Do NOT run `createsuperuser`.** Your existing **`admin`** account came in with
> `transfer.json` — log in with the password you already use locally. If you don't
> remember it: `python manage.py changepassword admin`.

Then **delete the data dump** (it's done its job):

```bash
rm ~/logistic_manager/transfer.json
```

**No Terminal on your host?** Create a temporary **Cron Job** (cPanel → Cron Jobs)
set to run once in a minute, with this single command, then delete the cron after:
```bash
cd ~/logistic_manager && source ~/virtualenv/logistic_manager/3.12/bin/activate && pip install -r requirements.txt && python manage.py migrate && python manage.py createcachetable && python manage.py loaddata transfer.json && rm -rf ~/public_html/static && python manage.py collectstatic --noinput
```

---

## 6. Restart + fix permissions

- cPanel → **Setup Python App** → your app → **Restart**.
- In File Manager, ensure `~/public_html/media` is permission **755**.

---

## 7. Verify the site

Visit these and confirm:

- [ ] `https://mudassirllc.com/` — public site loads **with styling** (CSS)
- [ ] `https://mudassirllc.com/accounts/login/` — the unified login page
- [ ] Log in as **admin** → `/dashboard/` shows your real numbers (10 orders, etc.)
- [ ] `/products/` — **product images display** (media uploaded + 755)
- [ ] `/khata/` → a customer → **Export PDF** shows correct balances (and Chinese/emoji text)
- [ ] A customer can log in at `/accounts/login/` with their existing password

If images 404 → media not uploaded or wrong permissions. See `DEPLOY.md` §10 for a
full troubleshooting table.

### Styling problems

| Symptom | Cause | Fix |
|---|---|---|
| Every page is a 500, log says `Missing staticfiles manifest entry` | `collectstatic` was run with `DJANGO_DEBUG=1`, so no manifest was written | Set `DJANGO_DEBUG=0` in `.env`, re-run `collectstatic --noinput`, restart |
| Site loads but shows an **old** colour scheme | A previous build is still sitting in `~/public_html/static`; Apache serves it in preference to anything Django would | `rm -rf ~/public_html/static`, re-run `collectstatic`, then hard-refresh (Ctrl+Shift+R) |
| No styling at all | `collectstatic` never ran, or `DJANGO_STATIC_ROOT` does not point inside `public_html` | Check `.env`, re-run `collectstatic` |
| `ImproperlyConfigured: STATIC_ROOT ... overlaps` on startup | `DJANGO_STATIC_ROOT` is set to the project's own `static/` folder | Point it at `/home/mudassirllc/public_html/static` |

The stylesheet links carry a `?v=` cache-buster, so a browser will pick up a new
build on its own — but only once the server is actually serving the new file.
When in doubt, check what the server returns rather than what your browser shows:

```bash
curl -s https://mudassirllc.com/static/style.css | grep -m1 'accent-1'
# current theme  ->  --accent-1: #0A0A0A
```

---

## 8. Email (SMTP)

SMTP is stored in the database, not `.env`. Log in as admin → **Settings**
(`/settings/`) and fill the three profiles (Order status / Security / News). The
simplest is cPanel mailboxes: host `mail.mudassirllc.com`, port `587`, full-address
username, TLS on. Details in `DEPLOY.md` §7.

---

## Notes specific to this build

- The unified-auth + support + shipment-tracking features are all included; their
  migrations run automatically in step 5's `migrate`.
- Because the DB is **empty**, `migrate` then `loaddata` is safe and exact — proven
  locally: all 356 records (4 users/profiles, 4 customers, 75 products, 10 orders,
  59 items, 29 ledger rows) round-trip with emoji/Chinese intact.
- The `django_cache_table` step matters — login rate-limiting uses the cache (it
  fails open if missing, but create it so the feature works).
