# 1688 Product Sourcing extension

Reads a 1688 product page — including **every SKU variation it sells** — and
collects them into a list you can export as Excel/CSV/SQL or push straight into
the LogiManager catalogue.

**No markup is applied.** Prices shown are the supplier's own, and every one is
editable in the panel before you add it (and again on the site afterwards).

---

## Install

1. Open `chrome://extensions` in Chrome.
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and select this `extension/` folder.
4. **Pin it to the toolbar.** Click the puzzle-piece 🧩 icon at the right of
   Chrome's address bar, find *1688 Product Sourcing*, and click the pin.

Pinning is convenient but **no longer required**: the panel on every 1688 page
has a **View list & export** button that opens the same page in a normal tab. If
you cannot find the toolbar icon, use that.

Chrome will show it as an unpacked extension — that is expected for an internal
tool that is not published to the Web Store.

### After you edit any extension file

Chrome does **not** hot-reload unpacked extensions. Every time these files
change you must:

1. Go to `chrome://extensions`, find this extension, and click the **⟳ reload**
   icon on its card.
2. **Reload the 1688 tab as well** — a content script only injects at page load,
   so a tab opened before the reload is still running the old code (or none).

Skipping either step is the most common reason "it stopped working".

### Is it actually running?

Open DevTools (F12) on a 1688 product page and look at the Console for:

```
[1688 Sourcing] content script active (v1.0.0) — detail.1688.com
```

- **Banner present, panel visible** — working.
- **Banner present, then an error** — the code ran and broke; the error names
  the file and line.
- **No banner at all** — Chrome never ran the content script. The extension is
  disabled, was not reloaded after an edit, errored on load (a red **Errors**
  button appears on its card at `chrome://extensions`), or the tab predates it.
  Nothing in this folder can cause or fix that; check the card.

---

## Set it up

Open the extension's **Options** (the ⚙ in the popup, or right-click the icon →
Options).

### Pricing

| Setting | Default | What it does |
|---|---|---|
| Order quantity to price at | 100 | Which tier to read, and the product's MOQ |
| Import as drafts | on | Keeps a bad scrape out of the customer catalogue |

There is no markup setting. A single flat figure cannot be right across an
accessory at ¥12 and the machine it fits at ¥85, and a wrong-but-plausible
number is worse than a raw one because nobody re-checks it.

### Connecting to your site

Needed for **Push to site**, for category suggestions, and for the Claude
extraction mode. File exports work without it.

1. On your site, go to **`/accounts/api-tokens/`** and create a token.
   It is shown **once** — copy it immediately. Only a hash is stored, so it
   cannot be shown again; if you lose it, revoke it and make a new one.
2. Paste the token and your site address (e.g. `http://127.0.0.1:8000`) into
   Options and click **Test connection**.
3. Chrome will ask permission to reach that address. Accept it — the extension
   only requests the one host you configured.

A token can do exactly what your account can, no more. Revoke it any time on the
same page and the extension stops working immediately.

---

## Product names

The page is always read directly. 1688 names are Chinese, so they are translated
into English before being added to your list. **Options → Translate names**
switches this on or off; on is the default.

No account, key, or install is needed. Prices, weights, stock and categories are
always read from the page — translation never touches them.

### Which service does the translating

Two are tried in order, both free and key-less:

1. **MyMemory** — the primary. Roughly 5,000 characters a day anonymously,
   which is about a hundred products.
2. **Google** — the fallback, for networks where MyMemory is limited.

Google was the original first choice, and it turned out to return **HTTP 429 for
every request from this network**, persistently, across both of its endpoints.
MyMemory answers fine here, so the order is what it is. If your network is the
other way round, the fallback covers it with no configuration.

Three things keep request counts (and therefore rate-limit pressure) low:

- **Caching** — every translation is stored permanently, so a name is only ever
  translated once. **Clear cache** in Options resets it.
- **Batching** — a whole page's names go in one request, not one each.
- **Skipping** — text with no Chinese characters (model codes like
  `ST-128PlusMax`, names already in English) never leaves your machine.

**Options → Test translation** tells you in one click whether it is working
right now, and which service answered.

### The AI modes are switched off

Earlier builds also offered a local Ollama model and Claude via your own server.
Both are **disabled** — they are no longer listed in Options. The code is still
in `src/lib/providers.js` and the server endpoint still exists, so re-enabling
is a one-line change in `options.html` rather than a rewrite.

---

## Using it

1. Open any 1688 product page. A **Sourcing** panel appears at the top right.
2. It reads the page and shows either a **variation list** or a single product,
   depending on what the listing offers.
3. Check the names, prices, weight, and category — everything is editable.
4. Click **Add … to list**. Re-scraping a page you already added updates those
   entries rather than duplicating them.
5. Click **View list & export** in the panel (or the toolbar icon, if pinned) to
   open the list and export or push.

### Variations

Most 1688 listings sell several SKUs under one page (颜色分类 / 规格), each with
its own price and photo. The panel lists them all, ticked by default, with an
editable price on each row. **The ticked rows are imported as variations of ONE
catalogue product**, not as separate products.

Each variation keeps its own price, stock and photo. The product headlines the
cheapest as a "from" figure, and the customer picks a variation on the product
page before adding it to their cart — so the price they are charged is the price
of the option they chose.

This used to work the other way, with every ticked row becoming its own
top-level product. A water-gun listing with seventeen SKUs then produced
seventeen near-identical catalogue cards, which made the catalogue unbrowsable
and started tripping the duplicate-name guard. Weight, carton dimensions and
category belong to the item rather than to the colour, so they live on the
parent product and are entered once.

With an AI mode on, each variation name is translated too. Prices, stock, and
photos are always taken from the page and are never touched by the model.

### Adding a category without leaving the page

Both category dropdowns have a **+ New** link beside them. It asks for a name,
creates it on the site, and reselects the dropdowns from the refreshed taxonomy —
so a product the catalogue has no home for can be filed in one step instead of
"leave the listing, add it on the site, come back, re-scan". A sub category needs
a category selected first, since it has to hang off a parent.

Creating a name that already exists selects the existing one rather than making a
second copy, so a double-click cannot produce two "Garden Tools".

This needs the site address and token configured, like **Push to site** does. The
token still only does what its owner can — a customer-role token is refused.

### Specifications

1688 lists a spec table on most pages (`货号`, `材质`, `功率` …). The extension
reads it as **name/value pairs** and imports them as the product's
Specifications, which appear on the product page and in its structured data.

Both halves are translated along with the names, because a spec list is worth
nothing to an English-reading buyer as `材质 / 不锈钢`. They go in the same
batched request as the title and the variation names, and every string is cached
forever — so a page's whole vocabulary costs one request the first time and none
afterwards. Attribute names in particular repeat across every product you scrape.

The panel reports what it found (`12 specs captured`, or `No spec table found on
this page`), so a page whose table failed to parse is visible before you add it
rather than after it reaches the catalogue.

**A translated list is only used when it comes back the same length as the
scraped one.** A shorter or longer list means the pairs no longer line up with
what was read off the page, and a mislabelled spec — `Material: 220V` — is worse
than an untranslated one, so in that case the Chinese is kept.

### Exports

| Format | Use it for |
|---|---|
| **Excel** (`.xlsx`) | The **Bulk Upload** screen on your site |
| **CSV** | Same, plus opening in Excel or Sheets |
| **SQL** | Running directly against the database |

The Excel and CSV column order matches exactly what
`products/views.py::_parse_upload_rows` expects, so the file drops into the
existing Bulk Upload screen with no reshaping.

**Categories and the supplier link travel with the file.** Every export carries
four extra columns: `category` and `subcategory` (holding slugs such as
`home-kitchen`, `home-appliances`), `source_url` — the 1688 listing the product
came from — and `variant_of`.

**`variant_of` is how a flat file expresses variations.** A spreadsheet cannot
nest, so each product is written as one row followed by a row per variation, and
each variation row names its parent in `variant_of`. The Bulk Upload screen reads
the column and attaches those rows as variations rather than creating products
from them; the parent may appear anywhere in the file, or already exist in the
catalogue. A variation naming a parent that is in neither is reported as a row
error rather than silently becoming a product of its own. An importer that does
not know the column ignores it and gets a flat product list, which is what the
old behaviour was.

`source_url` is what puts a **Contact supplier** button on the product card in
the admin screens, so months later you can open the supplier's page and message
them about a reorder without re-finding a product whose Chinese name nobody
kept. Variations of one listing all share the page URL. **It is staff-only** —
which factory supplies a product is never rendered anywhere in the customer
portal.
The Bulk Upload screen reads them and files each product accordingly. Leave them
blank and the importer classifies the product from its name instead, so nothing
lands uncategorised. A hand-filled template may use display names
("Home & Kitchen") — both are accepted.

The SQL script is wrapped in a transaction, resolves categories by *slug* rather
than by a hard-coded id (ids differ between your local and production
databases), and skips any product whose name already exists — so it is safe to
run twice.

**SQL cannot bring images across.** Images are files in `MEDIA_ROOT`, not rows.
Source image URLs are written into the script as comments; use the Excel/CSV
import or **Push to site** when the images matter.

### Push to site

Sends the list straight to Django, which creates the products. Products that
import successfully are removed from the list; duplicates and errors stay so you
can deal with them.

**The photos are downloaded by this browser, not by the server**, and travel
base64-encoded inside the request. The server *can* fetch image URLs itself and
frequently cannot: its SSRF guard only permits known CDNs, a VPN resolves every
host into a private range, and shared hosting often has no outbound access at
all. Meanwhile this browser is already on the 1688 page with the CDN serving it
happily — so the bytes are taken here, and there is nothing left to fail
server-side.

**Both the gallery photos and the variation photos are stored as real files.**
Variation photos used to be kept as links to alicdn. That was backwards on
exactly the listings it mattered for: a seventeen-SKU page contributes three
gallery photos and seventeen variation photos, so almost every picture on a
variation-heavy product was a hotlink. Selecting a variation swaps its photo into
the main image slot on the product page, so those are the product shot, not a
thumbnail that degrades quietly — and a hotlink breaks the day the supplier
delists the offer or the CDN turns on referer checking.

Three limits keep one request inside Django's `DATA_UPLOAD_MAX_MEMORY_SIZE`. That
matters more than it sounds: an oversized body is rejected with
`RequestDataTooBig` *before any import code runs*, so exceeding it does not lose
one photo, it loses the whole batch of ten products.

| Limit | Value | Why |
|---|---|---|
| Gallery photos per product | 3 | Matches what the site's importer stores |
| Variation photos per product | 24 | A colour range runs to a dozen; the rest keep their links |
| Total bytes per request | 14 MB | Under the server's 20 MB body cap, with room for the JSON |

The budget is spent **gallery-first across every product**, then on variation
photos, so a single listing with forty variations cannot crowd out the main
product shot of the nine products behind it. Anything skipped keeps its URL, so
the picture still renders and `python manage.py fetch_remote_images --apply`
can download it later. The push result reports `variant_images` per product,
which is how you see the gap.

A photo shared by several variations is fetched and encoded once, not once per
row.

---

## How the extraction works

1688 assembles its product page from named modules, each tagged with a
`data-module` attribute — `od_title`, `od_main_price`, `od_sku_selection`,
`od_product_attributes`, `od_picture_gallery`. Those names are semantic and
survive redesigns far better than class names, so they are tried first.

That choice is about correctness, not just durability. The class `.offer-title`
**does** exist on the page — on the *recommended products* carousel. Keying off
it scrapes a neighbouring advert instead of the item on screen, which is the
kind of bug nobody notices until a wrong product reaches the catalogue.

Three layers, each filling what the previous left:

1. **`data-module` containers**, then known class names.
2. **Regex over the page text** — keys off the Chinese labels the *content* uses
   (`¥`, `起批`, `重量`), so it survives any amount of class renaming.
3. **The AI pass** — reads the same raw text and fixes what the first two got
   wrong.

Three things the sample page taught, all now handled:

- **Prices split across tags.** `<span>¥</span><span>12</span><span>.50</span>`
  can surface as `¥ 12 .50`; a naive pattern reads that as ¥12 and silently
  drops the decimals.
- **Stock counts look exactly like price tiers.** `库存9971台` beside a `¥12`
  is indistinguishable from `9971件 ¥12` once labels are gone — it produced
  phantom tiers at minQty 9971. Stock and sold-counts are stripped before the
  ladder is parsed.
- **Attribute tables pack two label/value pairs per row.** Pairing a label with
  the first value in its row mislabels every second attribute; the sample's
  `货号` came back as `100W（W）` instead of `ST-128PlusMax`. Labels and values
  are zipped by document order instead.

### Sending a page that scraped wrong

The panel has a **Snapshot** link beside Re-scan. It downloads the page *as the
extractor sees it* — the live DOM after JavaScript has run — with the extraction
result embedded at the top as an HTML comment. One file answers both "what was on
the page" and "what did we make of it".

**Ctrl+S is not a substitute.** It saves the HTML the server sent, and 1688 builds
the SKU table, the price ladder and the spec table client-side afterwards, so a
Ctrl+S copy contains a shell with none of the data the extractor reads. A
screenshot has the same problem in reverse: it shows what the page looks like but
not the attributes and nesting the selectors key off.

### If a page extracts badly

- Click **Re-scan page**. 1688 loads prices and specs after the initial render,
  and a very slow page can be scraped too early.
- Turn on an AI mode — it reads the raw text and does not depend on selectors.
- Edit the fields in the panel by hand before adding; everything is editable.

### Weight is deliberately left blank rather than guessed

A wrong weight produces a wrong air-freight quote. If the page does not state a
weight, the field stays empty and the popup marks the product `no weight` so you
can see at a glance what still needs filling in.

This is not hypothetical: the sample page lists twenty attributes and **none of
them is a weight**. An earlier build matched a bare `250g` somewhere in the
page's 20,000 characters and confidently reported 0.037 kg. Unlabelled
`N g` / `N kg` patterns are now only trusted inside the attributes table; over
whole-page text, only an explicit `重量` / `毛重` / `净重` label counts.

---

## Layout

```
extension/
  manifest.json
  src/
    lib/
      namespace.js     shared global + defaults (must load first everywhere)
      storage.js       chrome.storage wrapper for the list and settings
      taxonomy.js      bundled snapshot of the site's categories
      translate.js     name translation: providers, batching, cache
      pricing.js       which supplier tier applies (no markup — see the file)
      providers.js     the three AI modes + how results merge into the draft
      xlsx.js          dependency-free .xlsx writer
      exporters.js     CSV / SQL / import-payload builders
    content/
      extract-1688.js  the page reader
      content.js       the injected panel
      panel.css
    background/
      service-worker.js  all network I/O lives here
    popup/             the collected list and exports
    options/           settings
```

**Categories are stored, not re-fetched.** The taxonomy read from the site is
saved in `chrome.storage` and used from there. This matters because an MV3
service worker is killed after about thirty seconds idle, so an in-memory cache
survived roughly one page — every scrape was a round trip, and a scrape made
while the site was unreachable fell back to the snapshot compiled into
`taxonomy.js`.

The stored copy is refreshed in the background whenever the site answers, so a
category added on the site appears on the next scrape. Changing the site address
in Options clears it, so one site's categories never leak into another's.

`taxonomy.js` remains only as the first-install fallback, for a copy of the
extension that has not reached the site even once. Refresh that snapshot after a
big taxonomy change:

```
python manage.py shell -c "
import json
from products.models import Category
print(json.dumps([
    {'slug': c.slug, 'name': c.name,
     'subcategories': [{'slug': s.slug, 'name': s.name}
                       for s in c.subcategories.filter(is_active=True)]}
    for c in Category.objects.filter(is_active=True)
], ensure_ascii=False, indent=2))"
```

and paste the result into `MLK.DEFAULT_TAXONOMY`.

**Why no ES modules:** Manifest V3 content scripts cannot be modules. One
global namespace (`MLK`) works identically in the content script, the popup, and
the service worker. Load order matters — `namespace.js` first, always.

**Why all network calls go through the service worker:** an https 1688 page
cannot call `http://localhost`; the browser blocks it as mixed content, which
would rule out a local Ollama entirely. The service worker has its own secure
origin and no such restriction.

---

## Server side

| Path | Purpose |
|---|---|
| `POST /products/api/extension/ping/` | Validate a token, return the taxonomy |
| `POST /products/api/extension/extract/` | Claude extraction proxy |
| `POST /products/api/extension/import/` | Create products, variations, specs, images |
| `POST /products/api/extension/category/` | Create a category or sub category |

All three take `Authorization: Bearer <token>` and are CSRF-exempt — CSRF
protects cookie-authenticated requests, and a bearer token is never attached
automatically by the browser, so there is nothing for a hostile page to forge.

**Image downloads are restricted to marketplace CDNs** (`alicdn.com`,
`aliimg.com`, and similar) and refuse any host that resolves to a private
address. Without that, a token holder could point the importer at internal
services and use the server as a proxy into the private network.

---

## Testing notes

**There is currently no automated test suite.** An earlier version of this file
described one in detail — jsdom over `samplepage.html`, an openpyxl round-trip on
the .xlsx writer, an idempotency check on the SQL export, API auth and SSRF
tests. None of it exists in the repository: there is no `package.json`, no test
runner, and every Django app's `tests.py` is the stock three-line placeholder.
The description was aspirational and is corrected here rather than left to be
discovered by someone relying on it.

What that means in practice: every change to the parsers, the exporters or the
import API is verified by hand, once, and nothing catches it if a later change
breaks it. These are the parts worth covering first, roughly in order of what
would hurt most if it broke silently:

1. **The money path** — variation price into the cart line, into the order line,
   into the invoice total. A regression here charges a customer the wrong amount.
2. **Price-ladder and weight parsing** against the text shapes 1688 renders
   (`2-99件 ¥12.50`, `≥500件`, `起批量`, `克`/`斤`/`kg`), including the three
   traps described under *How the extraction works*.
3. **The import API** — token auth, the CDN allowlist, the private-IP guard,
   duplicate handling, and variation grouping.
4. **The .xlsx writer**, generated under Node and opened with `openpyxl`.
5. **The extractor against `samplepage.html`** with jsdom.

**Keep `samplepage.html` regardless.** It is a saved 1688 listing and the only
fixture a selector test could be written against. When 1688 changes its markup,
save a fresh page over it.

**Not covered:** the live site. 1688 blocks automated browsing, so the selectors
are verified against the saved page rather than a live one. If a real listing
extracts poorly, save it alongside the sample and start from the selector list
at the top of each `extract*` function.
