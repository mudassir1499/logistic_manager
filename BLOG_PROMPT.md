# Blog generation prompt

Paste everything between the `---` markers into ChatGPT, Claude or any other
model. Replace the bracketed parts at the top with what you want this time.

The output drops straight into `portal/blog_content/` and loads with:

```bash
python manage.py seed_blog_posts --dry-run   # check first
python manage.py seed_blog_posts             # create what is missing
```

The loader computes `reading_minutes`, staggers the publication dates and skips
anything whose slug already exists, so you never have to think about those.

---

## ROLE

You are writing for the blog of **Mudassir LLC**, a China-based sourcing agency.
We are physically in Xuzhou, China. We find factories for clients, verify
suppliers on the ground, run pre-shipment inspections, negotiate in Mandarin,
and arrange freight. We are not a freight forwarder and not a marketplace.

Our reader is an **importer or e-commerce seller** who buys goods from China.
They are commercially experienced but not a logistics specialist. They are
trying to decide something — which freight mode, whether a supplier is real,
what a shipment will actually cost — and they have landed on us from a search.

## THIS BATCH

- **Target market:** [e.g. Nigeria and Ghana / Kenya and Tanzania / Saudi Arabia]
- **Category:** [pick one existing slug from the list below, or propose a new
  category and give it a name, slug, description and display_order]
- **How many posts:** [e.g. 5]
- **Topics:** [list them, or write "propose them and tell me why each one earns
  its place"]

## OUTPUT FORMAT — follow exactly

A single Python module, ready to save as `portal/blog_content/<name>.py`:

```python
"""Blog articles: <one line on what this file covers>."""

CATEGORY = {
    'name': 'Shipping & Freight',
    'slug': 'shipping-freight',
    'description': 'One line shown at the top of the category listing.',
    'display_order': 2,
}

POSTS = [
    {
        'slug': 'air-vs-sea-freight-china-to-uae',
        'title': 'Air vs Sea Freight from China to the UAE: How to Choose',
        'category': 'shipping-freight',
        'featured': True,
        'excerpt': 'One or two sentences. Shown in listings.',
        'meta_description': 'The search-result snippet. Aim for 150-160 characters.',
        'keywords': 'comma, separated, search, phrases',
        'body': """
<p>The article, as HTML.</p>
""",
    },
]
```

Those eight keys are the only ones the loader reads. Do not add others — there
is no `published_at`, `author_name`, `meta_title` or `reading_minutes` here,
because the system fills those in.

If you are adding posts to a category that already exists, still emit the
`CATEGORY` dict with the existing values exactly as listed below, so the file
is self-contained.

## FIELD RULES

| Key | Rule |
|---|---|
| `slug` | Lower-case, hyphens, no dates. Keep under 60 characters. **Permanent** — it is the URL. |
| `title` | Max 220 characters. Written for a person, not stuffed with keywords. |
| `category` | Must equal the `slug` in the `CATEGORY` dict. |
| `featured` | `True` on at most one post per batch. |
| `excerpt` | **Max 400 characters.** Must read as a sentence, not a truncated opener. |
| `meta_description` | **Max 320 characters, aim 150-160.** Describes the answer, not the article. |
| `keywords` | Max 400 characters. Real search phrases, comma-separated. |
| `body` | HTML, in a triple-quoted string, starting with a newline. |

## HTML VOCABULARY

Use only these. The blog stylesheet does not style anything else:

- `<p>`, `<h2>`, `<h3>`, `<ul>`/`<ol>` with `<li>`, `<strong>`, `<em>`, `<a>`
- `<blockquote><p>…</p></blockquote>` — for a formula or a single key rule
- A callout, for the one thing a reader must not miss:
  ```html
  <div class="blog-callout">
    <p><strong>The practical consequence:</strong> …</p>
  </div>
  ```
- A table, which **must** be wrapped so it scrolls on a phone:
  ```html
  <div class="blog-table-wrap">
  <table>
    <thead><tr><th>…</th></tr></thead>
    <tbody><tr><td>…</td></tr></tbody>
  </table>
  </div>
  ```

No `<script>`, no `<style>`, no inline `style=` attributes, no images, no `<h1>`
(the template renders the title as the h1), and **no backslashes anywhere**.

## EDITORIAL RULES — these are not optional

1. **Answer the search query in the first two paragraphs.** A reader who has to
   dig leaves, and the short visit is itself a ranking signal. Do not open with
   "In today's globalised economy".

2. **Never invent a precise figure that moves.** Freight rates, exchange rates,
   duty percentages and factory lead times change constantly. A number stated as
   fact is wrong within weeks and takes the article's credibility with it.
   Give the *structure* of the cost and the *method* to work it out, then invite
   a live quote. Where a range genuinely helps, mark it as indicative
   ("roughly 12-20 days") rather than exact.

3. **Describe regulation in general terms and point at the authority.** Name the
   programme (SONCAP, PVoC, MOIAT) and what it is *for*. Do not reproduce a
   fee schedule or a regulated-product list — only the authority is current.

4. **Write what we actually know.** We are in China. We walk into factories, we
   check business licences, we hold the balance payment until inspection passes.
   Say that where it is relevant. Do not claim offices, staff or services we have
   not described above.

5. **One internal link per two or three sections**, from this set only:
   `/contact/`, `/services/`, `/shipping-calculator/`, `/shop/`, and
   `/blog/<slug>/` for a post in the list below. Never invent a URL.

6. **Close with a specific next step**, not "contact us today for all your
   sourcing needs".

7. **Plain English.** No "leverage", "seamless", "robust", "in the ever-evolving
   landscape". Short sentences. Contractions are fine. If a sentence could open
   any article on any subject, cut it.

8. **800-1,200 words**, with `<h2>` sections a reader can scan. The existing
   archive runs 620-1,100 words with a median around 850 — match that density
   rather than padding to a target.

## EXISTING CATEGORIES — reuse these slugs, do not invent near-duplicates

| slug | name | display_order |
|---|---|---|
| `sourcing-suppliers` | Sourcing & Suppliers | 1 |
| `shipping-freight` | Shipping & Freight | 2 |
| `customs-compliance` | Customs & Compliance | 3 |
| `costs-payments` | Costs & Payments | 4 |
| `selling-in-uae` | Selling in the UAE | 5 |

A new category needs `display_order: 6` or higher.

## EXISTING POSTS — do not duplicate these slugs or re-cover these topics

```
how-to-verify-a-chinese-supplier          air-vs-sea-freight-china-to-uae
what-is-a-china-sourcing-agent            incoterms-explained-for-uae-importers
alibaba-vs-sourcing-agent                 lcl-vs-fcl-shipping-from-china
how-to-negotiate-moq-with-chinese-factories   chinese-new-year-shipping-delays
pre-shipment-inspection-guide             jebel-ali-port-guide-for-importers
uae-customs-duty-and-vat-on-imports-from-china    shipping-from-china-to-saudi-arabia
documents-needed-to-import-from-china-to-uae      shipping-batteries-and-battery-powered-products-from-china
uae-free-zone-vs-mainland-for-importers   how-to-calculate-landed-cost-china-to-uae
product-certification-for-uae-imports     cbm-and-volumetric-weight-explained
amazon-fba-uae-sourcing-from-china        paying-chinese-suppliers-safely
selling-on-noon-sourcing-from-china       what-a-china-sourcing-agent-costs
private-label-products-from-china-for-uae-sellers
```

If a topic you want overlaps one of these, write the *market-specific* angle
instead — "LCL vs FCL" already exists, but "LCL vs FCL into Mombasa, where the
inland leg changes the maths" does not.

## BEFORE YOU ANSWER

List the posts you intend to write, one line each, with the search query the
post answers. Wait for me to approve the list, then write the module.

---

## After you get the output

1. Save it as `portal/blog_content/<name>.py`.
2. Add it to `portal/blog_content/__init__.py`, following the existing imports
   and adding it to both `CATEGORIES` and `POSTS`.
3. `python manage.py seed_blog_posts --dry-run` to see what it would do.
4. `python manage.py seed_blog_posts` to create it.

Re-running is safe: existing posts are left alone unless you pass `--update`,
which overwrites them from the source and **discards any edits made in Django
admin**.

### Check the facts before publishing

Anything an AI writes about duty rates, conformity programmes, port procedures
or transit times needs a human who knows the market to read it first. The
editorial rules above are designed to keep the article useful without making
checkable claims that go stale — but they reduce the risk, they do not remove it.
