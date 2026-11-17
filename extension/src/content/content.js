/**
 * src/content/content.js
 *
 * Injects the sourcing panel onto a 1688 product page and drives the
 * scrape → enrich → review → add flow.
 *
 * TWO MODES, decided by what the listing actually offers:
 *
 *   VARIATIONS — the listing sells several SKUs (颜色分类 / 规格), each with its
 *     own price and photo. The panel lists them all with a checkbox and an
 *     editable price each, and adds one catalogue product per ticked row. A
 *     real example: a cordless vacuum at ¥85 in two colours plus its floor-brush
 *     accessory at ¥12 in two colours — four products from one page, and no
 *     single price that is right for more than half of them.
 *
 *   SINGLE — no variation list, so the page is one product priced from its
 *     quantity ladder.
 *
 * NO MARKUP IS APPLIED anywhere. Prices shown are the supplier's, and every one
 * is editable before adding.
 *
 * The panel is fixed-position and appended to <body> rather than grafted into
 * the page: 1688 re-renders large parts of its DOM as you scroll and switch
 * SKUs, and anything inside that tree gets destroyed.
 */

(function (MLK) {
  'use strict';

  // A startup banner, on purpose and permanently.
  //
  // When the panel does not appear there are two very different causes — the
  // extension is not loaded at all, or it is loaded and something threw — and
  // without a marker in the console they look identical. This one line
  // distinguishes them instantly: no banner means Chrome never ran the content
  // script (extension disabled, not reloaded after an edit, or the page was
  // open before it was enabled); a banner followed by an error means the code
  // ran and broke.
  const VERSION = (chrome.runtime.getManifest && chrome.runtime.getManifest().version) || '?';
  console.log(
    '%c[1688 Sourcing]%c content script active (v%s) — %s',
    'background:#0a0a0a;color:#d9a93c;padding:2px 6px;border-radius:3px',
    '',
    VERSION,
    location.hostname
  );

  if (document.getElementById('mlk-panel')) return;

  let draft = null;
  // Seeded from the bundled snapshot so the dropdowns are never empty, then
  // replaced by the STORED copy as soon as it can be read (see scanPage). The
  // snapshot is a photograph of the catalogue on the day this extension was
  // built, so it only ever covers a fresh install that has not reached the site
  // yet — anything else prefers what was last seen from the site itself.
  let taxonomy = (MLK.DEFAULT_TAXONOMY || []).slice();
  let settings = Object.assign({}, MLK.DEFAULTS);
  /** Per-variation UI state: {selected, price, name}. Index-aligned with draft.variations.items. */
  let rows = [];

  // ---- Panel --------------------------------------------------------------

  function buildPanel() {
    const panel = document.createElement('div');
    panel.id = 'mlk-panel';
    panel.className = 'mlk-panel';
    panel.innerHTML = `
      <div class="mlk-header" id="mlk-header">
        <span class="mlk-logo">✦</span>
        <span class="mlk-title">Sourcing</span>
        <span class="mlk-count" id="mlk-count">0</span>
        <button class="mlk-toggle" id="mlk-toggle" type="button" aria-label="Toggle panel">▴</button>
      </div>
      <div class="mlk-body" id="mlk-body">
        <div class="mlk-status" id="mlk-status">Reading page…</div>

        <div class="mlk-field">
          <label for="mlk-name">Base product name</label>
          <textarea id="mlk-name" rows="2" placeholder="Product name"></textarea>
          <div class="mlk-hint" id="mlk-name-hint"></div>
        </div>

        <div class="mlk-grid">
          <div class="mlk-field">
            <label for="mlk-weight">Weight (kg)</label>
            <input id="mlk-weight" type="number" step="0.001" min="0" placeholder="not stated">
          </div>
          <div class="mlk-field">
            <label for="mlk-moq">MOQ</label>
            <input id="mlk-moq" type="number" step="1" min="1">
          </div>
        </div>

        <div class="mlk-field">
          <div class="mlk-label-row">
            <label for="mlk-category">Category</label>
            <button type="button" class="mlk-linkbtn" id="mlk-add-category">+ New</button>
          </div>
          <select id="mlk-category"><option value="">— none —</option></select>
        </div>
        <div class="mlk-field">
          <div class="mlk-label-row">
            <label for="mlk-subcategory">Sub category</label>
            <button type="button" class="mlk-linkbtn" id="mlk-add-subcategory">+ New</button>
          </div>
          <select id="mlk-subcategory"><option value="">— none —</option></select>
        </div>

        <div id="mlk-variations-block" hidden>
          <div class="mlk-vars-head">
            <span id="mlk-vars-label">Variations</span>
            <button type="button" class="mlk-linkbtn" id="mlk-toggle-all">Select none</button>
          </div>
          <div class="mlk-vars" id="mlk-vars"></div>
        </div>

        <div id="mlk-single-block" hidden>
          <div class="mlk-field">
            <label for="mlk-price">Price (RMB)</label>
            <input id="mlk-price" type="number" step="0.01" min="0" placeholder="—">
            <div class="mlk-hint" id="mlk-price-hint"></div>
          </div>
          <div class="mlk-tiers" id="mlk-tiers"></div>
        </div>

        <div class="mlk-images" id="mlk-images"></div>

        <button class="mlk-add" id="mlk-add" type="button">Add to list</button>
        <button class="mlk-open-list" id="mlk-open-list" type="button">
          View list &amp; export (<span id="mlk-count2">0</span>)
        </button>
        <div class="mlk-links">
          <span class="mlk-hint" id="mlk-added-note"></span>
          <a href="#" id="mlk-rescan">Re-scan</a>
          <a href="#" id="mlk-save-images" title="Save this product's photos to your Downloads folder">Save images</a>
          <a href="#" id="mlk-snapshot" title="Download this page as the extension sees it, for debugging a bad scrape">Snapshot</a>
        </div>
      </div>
    `;
    document.body.appendChild(panel);
    return panel;
  }

  // ---- Rendering ----------------------------------------------------------

  function setStatus(text, kind) {
    const status = document.getElementById('mlk-status');
    status.textContent = text;
    status.className = 'mlk-status' + (kind ? ' mlk-status-' + kind : '');
  }

  function escapeHtml(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /** The name a variation will be imported under: base name + its own label. */
  function composedName(index) {
    const base = document.getElementById('mlk-name').value.trim();
    const row = rows[index];
    if (!row) return base;
    return base ? `${base} — ${row.name}` : row.name;
  }

  function renderVariations() {
    const block = document.getElementById('mlk-variations-block');
    const container = document.getElementById('mlk-vars');
    const items = (draft.variations && draft.variations.items) || [];

    if (items.length === 0) {
      block.hidden = true;
      return;
    }
    block.hidden = false;

    const dimension = draft.variations.dimension;
    document.getElementById('mlk-vars-label').textContent =
      `Variations${dimension ? ` (${dimension})` : ''} — ${items.length}`;

    container.innerHTML = rows
      .map((row, index) => `
        <label class="mlk-var">
          <input type="checkbox" class="mlk-var-check" data-index="${index}" ${row.selected ? 'checked' : ''}>
          ${row.imageUrl ? `<img class="mlk-var-img" src="${escapeHtml(row.imageUrl)}" alt="" loading="lazy">` : '<span class="mlk-var-noimg">—</span>'}
          <span class="mlk-var-body">
            <span class="mlk-var-name" title="${escapeHtml(row.name)}">${escapeHtml(row.name)}</span>
            ${row.stock != null ? `<span class="mlk-var-stock">stock ${row.stock}</span>` : ''}
          </span>
          <input type="number" class="mlk-var-price" data-index="${index}"
                 step="0.01" min="0" value="${row.price == null ? '' : row.price}"
                 placeholder="price" title="Supplier price — edit to set your own">
        </label>
      `)
      .join('');

    container.querySelectorAll('.mlk-var-check').forEach((box) => {
      box.addEventListener('change', () => {
        rows[Number(box.dataset.index)].selected = box.checked;
        updateAddButton();
      });
    });
    container.querySelectorAll('.mlk-var-price').forEach((input) => {
      input.addEventListener('input', () => {
        const value = parseFloat(input.value);
        rows[Number(input.dataset.index)].price = Number.isFinite(value) ? value : null;
        updateAddButton();
      });
    });
  }

  function renderTiers() {
    const container = document.getElementById('mlk-tiers');
    const tiers = draft.tiers || [];
    if (tiers.length === 0) {
      container.innerHTML = '';
      return;
    }
    const target = Number(document.getElementById('mlk-moq').value) ||
      Number(settings.targetQty) || 100;
    const chosen = MLK.pricing.selectTier(tiers, target);
    container.innerHTML =
      '<div class="mlk-tiers-label">Supplier price ladder</div>' +
      tiers
        .map((tier) => {
          const active = chosen && tier.minQty === chosen.minQty ? ' mlk-tier-active' : '';
          return `<div class="mlk-tier${active}"><span>${tier.minQty}+</span><span>${MLK.pricing.formatRmb(tier.price)}</span></div>`;
        })
        .join('');
  }

  function renderSingle() {
    const block = document.getElementById('mlk-single-block');
    const hasVariations = ((draft.variations && draft.variations.items) || []).length > 0;
    block.hidden = hasVariations;
    if (hasVariations) return;

    const priced = MLK.pricing.priceProduct(draft, settings);
    const input = document.getElementById('mlk-price');
    if (input.value === '' && priced.price !== null) input.value = priced.price;

    document.getElementById('mlk-price-hint').textContent =
      priced.priced
        ? `Supplier price — edit to set your own.`
        : 'No price found on the page. Enter one to add this product.';

    renderTiers();
  }

  /**
   * The gallery strip, with a remove button on each photo.
   *
   * 1688 galleries routinely include images that are no use in a catalogue — a
   * size chart, a certificate, a banner of the supplier's other products — and
   * sometimes a URL that simply does not load. Whichever ends up FIRST becomes
   * the product's main photo on the site, so being able to drop one here is the
   * difference between a listing that looks right and one that has to be fixed
   * on the site afterwards.
   *
   * An image that fails to load marks itself, so a dead URL is visible before it
   * is imported rather than showing up as a blank box on the product page.
   */
  function renderImages() {
    const container = document.getElementById('mlk-images');
    const urls = draft.imageUrls || [];

    if (urls.length === 0) {
      container.innerHTML =
        '<div class="mlk-warn">No gallery images found. Variation photos are used where available.</div>';
      return;
    }

    container.innerHTML = urls
      .map((url, index) => `
        <div class="mlk-img" data-index="${index}">
          <img src="${escapeHtml(url)}" alt="" loading="lazy">
          <button type="button" class="mlk-img-del" data-index="${index}"
                  title="Remove this image" aria-label="Remove image ${index + 1}">×</button>
          ${index === 0 ? '<span class="mlk-img-main">main</span>' : ''}
        </div>
      `)
      .join('');

    container.querySelectorAll('.mlk-img-del').forEach((button) => {
      button.addEventListener('click', () => {
        draft.imageUrls.splice(Number(button.dataset.index), 1);
        // Re-rendered rather than removing the one node, so the remaining
        // indexes and the "main" badge both stay correct.
        renderImages();
      });
    });

    // Marking a bad photo has to test the SIZE, not just listen for an error.
    // alicdn answers a dead image URL with 200 and a 1x1 pixel, so `error` never
    // fires — the image "loads" and then stretches to fill its box, which is why
    // a missing photo reaches the site as a large blank panel instead of an
    // obvious gap.
    const MIN_USABLE_PX = 8;
    container.querySelectorAll('.mlk-img img').forEach((img) => {
      const mark = () => {
        const wrap = img.closest('.mlk-img');
        if (wrap) wrap.classList.add('mlk-img-broken');
      };
      const check = () => {
        if (img.naturalWidth < MIN_USABLE_PX || img.naturalHeight < MIN_USABLE_PX) mark();
      };
      img.addEventListener('error', mark);
      img.addEventListener('load', check);
      if (img.complete && img.naturalWidth) check();
    });
  }

  function renderCategories(selectedCategory, selectedSubcategory) {
    const categorySelect = document.getElementById('mlk-category');
    categorySelect.innerHTML = '<option value="">— none —</option>';
    for (const category of taxonomy) {
      const option = document.createElement('option');
      option.value = category.slug;
      option.textContent = category.name;
      if (category.slug === selectedCategory) option.selected = true;
      categorySelect.appendChild(option);
    }
    renderSubcategories(selectedCategory, selectedSubcategory);
    categorySelect.onchange = () => renderSubcategories(categorySelect.value, null);
  }

  function renderSubcategories(categorySlug, selectedSubcategory) {
    const select = document.getElementById('mlk-subcategory');
    select.innerHTML = '<option value="">— none —</option>';
    const category = taxonomy.find((c) => c.slug === categorySlug);
    if (!category) return;
    for (const sub of category.subcategories || []) {
      const option = document.createElement('option');
      option.value = sub.slug;
      option.textContent = sub.name;
      if (sub.slug === selectedSubcategory) option.selected = true;
      select.appendChild(option);
    }
  }

  function updateAddButton() {
    const button = document.getElementById('mlk-add');
    const items = (draft && draft.variations && draft.variations.items) || [];

    if (items.length > 0) {
      const ready = rows.filter((row) => row.selected && row.price != null && row.price > 0);
      const selected = rows.filter((row) => row.selected);
      button.disabled = ready.length === 0;
      // "1 product, N variations" — the ticked rows become variations of one
      // catalogue product now, not one product each.
      button.textContent =
        ready.length === 0
          ? (selected.length === 0 ? 'Select a variation' : 'Enter a price')
          : `Add product (${ready.length} variation${ready.length === 1 ? '' : 's'})`;
    } else {
      const price = parseFloat(document.getElementById('mlk-price').value);
      button.disabled = !(Number.isFinite(price) && price > 0);
      button.textContent = 'Add to list';
    }
  }

  /** Build the per-variation UI state from a freshly scraped/enriched draft. */
  function buildRows() {
    const items = (draft.variations && draft.variations.items) || [];
    rows = items.map((item) => ({
      // The AI's translation when it produced one, otherwise the page's own
      // Chinese label. See mergeExtraction for why a count mismatch discards
      // all translations rather than risking a misaligned one.
      name: item.nameEn || item.name,
      originalName: item.name,
      price: item.price,
      stock: item.stock,
      imageUrl: item.imageUrl,
      // Everything ticked by default: "import them all" is the common case, and
      // unticking two is less work than ticking twelve.
      selected: true,
    }));
  }

  function renderAll() {
    document.getElementById('mlk-name').value = draft.name || draft.title || '';
    document.getElementById('mlk-weight').value =
      draft.weightKg == null ? '' : draft.weightKg;
    document.getElementById('mlk-moq').value =
      draft.moq || settings.targetQty || 1;

    const items = (draft.variations && draft.variations.items) || [];
    const specCount = (draft.attributes || []).length;
    const specNote = specCount
      ? ` ${specCount} spec${specCount === 1 ? '' : 's'} captured.`
      : ' No spec table found on this page.';
    document.getElementById('mlk-name-hint').textContent = (items.length
      ? 'Added as ONE product; the ticked rows become its variations.'
      : '') + specNote;

    renderVariations();
    renderSingle();
    renderImages();
    renderCategories(draft.categorySlug || '', draft.subcategorySlug || '');
    updateAddButton();
  }

  async function refreshCount() {
    const items = await MLK.storage.getList();
    document.getElementById('mlk-count').textContent = String(items.length);
    const secondary = document.getElementById('mlk-count2');
    if (secondary) secondary.textContent = String(items.length);
  }

  // ---- Flow ---------------------------------------------------------------

  async function scanPage() {
    setStatus('Reading page…');
    settings = await MLK.storage.getSettings();

    // The categories last seen from the site. Read before the scrape so the
    // dropdowns are right even when the site is unreachable and the enrichment
    // step below never runs.
    const stored = await MLK.storage.getTaxonomy();
    if (stored.length) taxonomy = stored;

    document.getElementById('mlk-price').value = '';

    draft = MLK.extract1688.scrape();
    buildRows();
    renderAll();
    await refreshCount();

    // Logged so a bad scrape can be diagnosed from the console without having
    // to reproduce it — which matters because 1688 pages differ per session.
    console.log('[1688 Sourcing] scraped:', {
      title: draft.title,
      variations: rows.length,
      prices: rows.map((row) => row.price),
      tiers: draft.tiers,
      moq: draft.moq,
      weightKg: draft.weightKg,
      images: (draft.imageUrls || []).length,
    });

    const variationCount = rows.length;
    const summary = variationCount
      ? `Found ${variationCount} variation${variationCount === 1 ? '' : 's'}.`
      : 'Read from page.';

    if ((settings.aiMode || 'none') === 'none') {
      setStatus(summary + ' Names are in Chinese — turn on an AI mode to translate.', 'ok');
      return;
    }

    setStatus(settings.aiMode === 'ollama' ? 'Asking local model…' : 'Asking Claude…');

    let response;
    try {
      response = await chrome.runtime.sendMessage({ type: 'ENRICH', page: draft.raw });
    } catch (error) {
      setStatus(summary + ' Extension worker unavailable — page data only.', 'warn');
      return;
    }

    if (response && response.taxonomy && response.taxonomy.length) {
      taxonomy = response.taxonomy;
    }

    if (!response || !response.ok) {
      setStatus(
        `${summary} AI step failed (${(response && response.error) || 'unknown'}) — page data only.`,
        'warn'
      );
      renderCategories(draft.categorySlug || '', draft.subcategorySlug || '');
      return;
    }

    if (response.result) {
      draft = MLK.providers.mergeExtraction(draft, response.result);
      buildRows();
      renderAll();

      const translated = rows.filter((row) => row.name !== row.originalName).length;
      const confidence = draft.aiConfidence;
      setStatus(
        `${summary} ${translated} name${translated === 1 ? '' : 's'} translated` +
        (confidence ? ` (confidence: ${confidence})` : '') +
        (draft.aiNotes ? ` — ${draft.aiNotes}` : ''),
        confidence === 'low' ? 'warn' : 'ok'
      );
    } else {
      setStatus(summary, 'ok');
      renderCategories(draft.categorySlug || '', draft.subcategorySlug || '');
    }
  }

  /** Fields every product from this page shares. */
  function commonFields() {
    const weightRaw = document.getElementById('mlk-weight').value;
    return {
      moq: parseInt(document.getElementById('mlk-moq').value, 10) || 1,
      weightKg: weightRaw === '' ? null : Number(weightRaw),
      cartonQty: draft.cartonQty || null,
      // Carton size, as stated per SKU in the page's own data model. Without
      // it the site cannot compute CBM, which is what air/sea pricing needs.
      cartonCm: draft.cartonCm || null,
      categorySlug: document.getElementById('mlk-category').value || null,
      subcategorySlug: document.getElementById('mlk-subcategory').value || null,
      source: 'general',
      // The listing's specification table. A property of the item rather than of
      // the colour, so every entry from this page carries the same list.
      attributes: draft.attributes || [],
      sourceUrl: draft.sourceUrl,
      // The listing page itself, without the per-variation fragment appended
      // below. This is what the site stores and what "Contact supplier" opens.
      supplierUrl: draft.sourceUrl,
      isDraft: settings.importAsDraft !== false,
    };
  }

  async function addToList() {
    if (!draft) return;
    const common = commonFields();
    const items = (draft.variations && draft.variations.items) || [];
    let added = 0;
    let replaced = 0;

    if (items.length > 0) {
      // ONE product carrying its variations, not one product per variation.
      //
      // This used to add a separate entry per ticked row, which meant a listing
      // selling seventeen SKUs produced seventeen catalogue products that were all
      // the same item under different labels. The catalogue became unbrowsable.
      // The variations are now nested under a single product and the site stores
      // them as ProductVariant rows.
      const selected = rows.filter((row) => row.selected && row.price > 0);
      if (selected.length === 0) {
        setStatus('Tick at least one variation with a price.', 'error');
        return;
      }

      const baseName = document.getElementById('mlk-name').value.trim();
      if (!baseName) {
        setStatus('Give the product a name first.', 'error');
        return;
      }

      const variants = selected.map((row) => ({
        name: row.name,
        price: MLK.pricing.round2(row.price),
        stock: row.stock,
        imageUrl: row.imageUrl || '',
      }));

      // The headline price is the cheapest variation — the "from" figure. Quoting
      // the dearest one would make every listing look overpriced.
      const lowest = Math.min.apply(null, variants.map((v) => v.price));

      const entry = Object.assign({}, common, {
        name: baseName,
        price: lowest,
        supplierPrice: lowest,
        variants,
        // Variation photos first: they are the ones that actually show each SKU.
        // The gallery fills any remaining slots.
        imageUrls: variants
          .map((v) => v.imageUrl)
          .concat(draft.imageUrls || [])
          .filter(Boolean)
          .slice(0, 3),
        sku: draft.modelNumber || '',
        // The listing URL, unfragmented — one entry per page now, so re-scraping
        // the page replaces it in place rather than accumulating duplicates.
        sourceUrl: draft.sourceUrl,
      });

      const outcome = await MLK.storage.addItem(entry);
      if (outcome.replaced) replaced++; else added++;
    } else {
      const price = parseFloat(document.getElementById('mlk-price').value);
      const name = document.getElementById('mlk-name').value.trim();
      if (!name) {
        setStatus('Give the product a name first.', 'error');
        return;
      }
      if (!(Number.isFinite(price) && price > 0)) {
        setStatus('Enter a price first.', 'error');
        return;
      }
      const outcome = await MLK.storage.addItem(Object.assign({}, common, {
        name,
        price: MLK.pricing.round2(price),
        supplierPrice: price,
        imageUrls: draft.imageUrls || [],
        sku: draft.modelNumber || '',
      }));
      if (outcome.replaced) replaced++; else added++;
    }

    await refreshCount();
    const parts = [];
    if (added) parts.push(`${added} added`);
    if (replaced) parts.push(`${replaced} updated`);
    setStatus(parts.join(', ') + '. Open the toolbar icon to export.', 'ok');
    document.getElementById('mlk-added-note').textContent =
      `${added + replaced} from this page`;
  }

  /**
   * Add a category (or a sub category under `parentSlug`) without leaving the page.
   *
   * Sourcing constantly turns up products the catalogue has no home for, and the
   * alternative was to leave the listing, add the category on the site, come
   * back and re-scan — which in practice meant products got filed under a
   * near-enough category or none at all.
   *
   * `prompt` rather than an inline form: the panel is injected into a hostile
   * page whose CSS can and does affect anything we render, and a native dialog
   * is the one input that cannot be restyled out of existence by the host page.
   *
   * The server answers with the full refreshed taxonomy, so the dropdowns are
   * rebuilt from that single response and the new entry is pre-selected.
   */
  async function createCategory(parentSlug) {
    const label = parentSlug ? 'sub category' : 'category';
    const name = (window.prompt(`Name of the new ${label}:`) || '').trim();
    if (!name) return;

    setStatus(`Creating ${label} “${name}”…`);

    let response;
    try {
      response = await chrome.runtime.sendMessage({
        type: 'CREATE_CATEGORY', name, parent: parentSlug || '',
      });
    } catch (error) {
      setStatus('Extension worker unavailable — could not create it.', 'error');
      return;
    }

    if (!response || !response.ok) {
      setStatus(
        `Could not create the ${label}: ${(response && response.error) || 'unknown error'}`,
        'error'
      );
      return;
    }

    const data = response.data;
    taxonomy = data.taxonomy || taxonomy;

    // Select what was just created, keeping the parent selected when it was a
    // sub category so the operator is left exactly where they meant to be.
    if (parentSlug) {
      renderCategories(parentSlug, data.slug);
    } else {
      renderCategories(data.slug, null);
    }
    updateAddButton();

    setStatus(
      data.existed
        ? `“${data.name}” already existed — selected it.`
        : `${label.charAt(0).toUpperCase()}${label.slice(1)} “${data.name}” created.`,
      'ok'
    );
  }

  /**
   * Download the page exactly as the extractor sees it, plus what it extracted.
   *
   * Ctrl+S is no use for diagnosing a bad scrape on 1688. It saves the HTML the
   * server sent, and 1688 builds the SKU table, the price ladder and the spec
   * table with JavaScript afterwards — so the saved file contains a shell with
   * none of the data the extractor reads. Reporting "it scraped wrong" then
   * comes down to screenshots, which show what a page LOOKS like but not the
   * attributes and nesting the selectors key off.
   *
   * This writes `document.documentElement.outerHTML` — the live DOM, after
   * hydration — with the extraction result embedded at the top as a comment, so
   * one file answers both "what was on the page" and "what did we make of it".
   */
  function saveSnapshot() {
    let report;
    try {
      report = JSON.stringify({
        url: location.href,
        scrapedAt: new Date().toISOString(),
        extractorVersion: VERSION,
        result: draft ? {
          title: draft.title,
          name: draft.name,
          moq: draft.moq,
          weightKg: draft.weightKg,
          cartonQty: draft.cartonQty,
          modelNumber: draft.modelNumber,
          tiers: draft.tiers,
          imageUrls: draft.imageUrls,
          attributes: draft.attributes,
          variations: draft.variations,
        } : 'no draft — the scrape did not complete',
      }, null, 2);
    } catch (error) {
      report = `could not serialise the extraction result: ${error.message}`;
    }

    // The comment goes first so it is readable without loading the page, and the
    // marker is escaped so a "-->" inside the data cannot close it early.
    const header = [
      '<!-- MLK SOURCING SNAPSHOT',
      report.replace(/--+>/g, '-- >'),
      'END MLK SOURCING SNAPSHOT -->',
      '',
    ].join('\n');

    const blob = new Blob([header, document.documentElement.outerHTML],
      { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);

    const link = document.createElement('a');
    link.href = url;
    const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '');
    link.download = `1688-snapshot-${stamp}.html`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Revoked late: revoking immediately can cancel the download mid-flight.
    setTimeout(() => URL.revokeObjectURL(url), 60000);

    setStatus('Snapshot saved to your downloads — send that file to debug this page.', 'ok');
  }

  /**
   * Save this product's photos to the Downloads folder.
   *
   * Gallery images first, then any variation photos - and de-duplicated,
   * because a listing routinely uses the same picture for the gallery and for
   * its first variation, and saving it twice makes the operator wonder which of
   * the two is the right one.
   *
   * The files land in "1688 images/<product name>/01.jpg" so a session spent
   * collecting a dozen products does not produce a Downloads folder full of
   * loose 01.jpg files with no idea which product each belongs to.
   *
   * The actual downloading happens in the service worker: chrome.downloads is
   * not available to a content script.
   */
  async function saveImages() {
    const gallery = draft.imageUrls || [];
    const variantImages = rows.map((row) => row.imageUrl).filter(Boolean);

    const urls = [];
    const seen = new Set();
    gallery.concat(variantImages).forEach((url) => {
      if (url && !seen.has(url)) { seen.add(url); urls.push(url); }
    });

    if (!urls.length) {
      setStatus('No images found on this page to save.', 'error');
      return;
    }

    const name = (document.getElementById('mlk-name').value || draft.title || 'product').trim();
    setStatus(`Saving ${urls.length} image${urls.length === 1 ? '' : 's'}…`);

    try {
      const response = await chrome.runtime.sendMessage({
        type: 'DOWNLOAD_IMAGES',
        urls,
        folder: name,
      });
      if (!response || !response.ok) {
        setStatus((response && response.error) || 'Could not save the images.', 'error');
        return;
      }
      const { saved, failed } = response.data;
      setStatus(
        failed
          ? `${saved} image(s) saved to Downloads; ${failed} could not be fetched.`
          : `${saved} image(s) saved to Downloads / "1688 images".`,
        failed ? 'warn' : 'ok'
      );
    } catch (error) {
      setStatus(`Could not save the images: ${error.message}`, 'error');
    }
  }

  // ---- Wiring -------------------------------------------------------------

  function attachHandlers(panel) {
    document.getElementById('mlk-header').addEventListener('click', (event) => {
      if (event.target.closest('button') && event.target.id !== 'mlk-toggle') return;
      panel.classList.toggle('mlk-collapsed');
      document.getElementById('mlk-toggle').textContent =
        panel.classList.contains('mlk-collapsed') ? '▾' : '▴';
    });

    document.getElementById('mlk-add').addEventListener('click', addToList);

    // Opens the list as a normal tab. The toolbar popup is unreachable unless
    // the extension is pinned, and "I cannot see my list" is a dead end when
    // the products are already collected — this button removes that dependency.
    document.getElementById('mlk-open-list').addEventListener('click', () => {
      chrome.runtime.sendMessage({ type: 'OPEN_LIST' });
    });

    document.getElementById('mlk-snapshot').addEventListener('click', (event) => {
      event.preventDefault();
      saveSnapshot();
    });

    document.getElementById('mlk-rescan').addEventListener('click', (event) => {
      event.preventDefault();
      scanPage();
    });

    document.getElementById('mlk-save-images').addEventListener('click', (event) => {
      event.preventDefault();
      saveImages();
    });

    document.getElementById('mlk-toggle-all').addEventListener('click', () => {
      const anySelected = rows.some((row) => row.selected);
      rows.forEach((row) => { row.selected = !anySelected; });
      document.getElementById('mlk-toggle-all').textContent =
        anySelected ? 'Select all' : 'Select none';
      renderVariations();
      updateAddButton();
    });

    document.getElementById('mlk-add-category').addEventListener('click', () => {
      createCategory(null);
    });
    document.getElementById('mlk-add-subcategory').addEventListener('click', () => {
      const parent = document.getElementById('mlk-category').value;
      if (!parent) {
        setStatus('Pick a category first — a sub category needs a parent.', 'error');
        return;
      }
      createCategory(parent);
    });

    document.getElementById('mlk-price').addEventListener('input', updateAddButton);
    document.getElementById('mlk-name').addEventListener('input', updateAddButton);

    document.getElementById('mlk-moq').addEventListener('change', () => {
      if (draft) renderTiers();
    });
  }

  const panel = buildPanel();
  attachHandlers(panel);

  // 1688 hydrates its price and SKU panels client-side; scraping at
  // document_idle regularly catches the page before they exist.
  setTimeout(scanPage, 1200);
})(globalThis.MLK);
