# Deployment Guide — mudassirllc.com (cPanel + MySQL)

Deploying LogiManager to cPanel on `mudassirllc.com`, using MySQL through PyMySQL.

> **Credentials are never stored in this repository.** All secrets live in a
> `.env` file on the server (git-ignored) or in cPanel's environment variable
> panel. If you previously had the database password written in this guide,
> **change that password now** — it was committed in plain text.

---

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
