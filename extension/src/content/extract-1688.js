/**
 * src/content/extract-1688.js
 *
 * Reads a 1688 product page: title, price, per-piece weight, MOQ, images, and —
 * the important one — every SKU variation the listing offers.
 *
 * SELECTOR STRATEGY, LEARNED FROM A REAL SAVED PAGE
 *   1688's product page is assembled from named modules, each marked with a
 *   `data-module` attribute:
 *
 *       od_title  od_main_price  od_sku_selection  od_product_attributes
 *       od_picture_gallery  od_shop_product_recommend  …
 *
 *   Those names are semantic and survive redesigns far better than class names,
 *   so they are tried first everywhere below.
 *
 *   This matters for correctness, not just robustness. The class `.offer-title`
 *   exists on the page — but it belongs to the *recommended products* carousel,
 *   not to the product being viewed. Keying off `.offer-title` silently scrapes
 *   a neighbouring advert instead of the item on screen, which is exactly the
 *   kind of failure nobody notices until a wrong product reaches the catalogue.
 *
 *   Three layers, each filling what the previous left:
 *     1. `data-module` containers, then known class names.
 *     2. Regex over the visible text, keyed to the Chinese labels the content
 *        uses (¥, 起批, 重量) rather than to any markup.
 *     3. The AI pass in providers.js.
 *
 * No network calls here — an https 1688 page cannot reach a local Ollama, so
 * everything of that sort belongs to the service worker.
 */

(function (MLK) {
  'use strict';

  // ---- Helpers ------------------------------------------------------------

  function firstMatch(selectors, root) {
    const scope = root || document;
    for (const selector of selectors) {
      try {
        const element = scope.querySelector(selector);
        if (element) return element;
      } catch (error) {
        // Ignore a selector a future browser rejects rather than aborting.
      }
    }
    return null;
  }

  function tidy(text) {
    return (text || '').replace(/\s+/g, ' ').trim();
  }

  /** The visible text of a page module, or '' when the module is absent. */
  function moduleText(name, extraSelectors) {
    const element = firstMatch(
      [`[data-module="${name}"]`].concat(extraSelectors || [])
    );
    return element ? tidy(element.innerText || element.textContent) : '';
  }

  /**
   * Parse a price out of text, tolerating a decimal point split across tags.
   *
   * 1688 renders a price as separate elements — `<span>¥</span><span>12</span>
   * <span>.00</span>` — which can surface as "¥ 12 .00" once whitespace creeps
   * in between them. A naive `[¥￥]\s*([\d.]+)` reads that as 12 and silently
   * discards the decimals, turning ¥12.50 into ¥12. Hence the optional
   * whitespace inside the decimal group.
   */
  const PRICE_PATTERN = '[¥￥]\\s*(\\d[\\d,]*(?:\\s*\\.\\s*\\d+)?)';

  function toPrice(raw) {
    if (!raw) return null;
    const value = parseFloat(String(raw).replace(/[,\s]/g, ''));
    // Above this is a total, a phone number, or a sales figure that happened to
    // sit beside a ¥ — not a wholesale unit price.
    return Number.isFinite(value) && value > 0 && value <= 100000 ? value : null;
  }

  // ---- Title --------------------------------------------------------------

  function extractTitle() {
    // NOTE: `.offer-title` is deliberately absent — see the header comment.
    const element = firstMatch([
      '[data-module="od_title"] h1',
      '[data-module="od_title"]',
      '.title-content h1',
      '.title-text',
      '.d-title',
      'h1',
    ]);
    if (element) {
      const text = tidy(element.textContent);
      if (text) return text;
    }

    const meta = document.querySelector('meta[property="og:title"]');
    if (meta && meta.content) return tidy(meta.content);

    return tidy(document.title.replace(/\s*[-|_]\s*(阿里巴巴|1688|淘宝).*$/, ''));
  }

  // ---- Embedded data model ------------------------------------------------

  /**
   * Pull a balanced JSON value out of `text`, starting at the first { or [ at or
   * after `from`.
   *
   * A brace counter rather than a regex, because the object contains braces
   * inside strings (product names routinely include 【】 and quotes) and no
   * regex can match balanced delimiters. Strings and their escapes are tracked
   * so a `{` inside a name cannot throw the depth off.
   *
   * @returns {*} The parsed value, or null when it is absent or malformed.
   */
  function parseBalancedJson(text, from) {
    const openers = { '{': '}', '[': ']' };
    let start = from;
    while (start < text.length && !openers[text[start]]) start++;
    if (start >= text.length) return null;

    let depth = 0;
    let inString = false;
    let escaped = false;

    for (let i = start; i < text.length; i++) {
      const c = text[i];
      if (inString) {
        if (escaped) escaped = false;
        else if (c === '\\') escaped = true;
        else if (c === '"') inString = false;
        continue;
      }
      if (c === '"') inString = true;
      else if (c === '{' || c === '[') depth++;
      else if (c === '}' || c === ']') {
        depth--;
        if (depth === 0) {
          try {
            return JSON.parse(text.slice(start, i + 1));
          } catch (error) {
            return null;
          }
        }
      }
    }
    return null;
  }

  /**
   * The page's own data model, lifted out of the inline script that carries it.
   *
   * THIS IS THE BEST SOURCE ON THE PAGE and is tried before any DOM reading.
   * 1688 ships the complete offer as JSON inside a <script> tag, and everything
   * visible is rendered from it. Reading the JSON instead of the rendered result
   * removes every failure mode the DOM strategies have:
   *
   *   - No hydration race. The JSON is in the HTML the server sent, so a scrape
   *     that runs before the SKU table renders still gets every SKU.
   *   - No selector rot. Class names are generated and change; these keys have
   *     not.
   *   - Exact values. Names come through untruncated (the DOM clamps them to two
   *     lines) and prices keep their decimals.
   *   - Fields the page never shows at all — per-SKU stock, carton dimensions
   *     and weight — which is where the missing weights and CBMs were.
   *
   * Content scripts run in an isolated world and cannot read the page's JS
   * variables, so the script TEXT is parsed rather than the objects it creates.
   *
   * @returns {object|null} `{skuModel, weightBySkuId}` or null when absent.
   */
  function extractEmbeddedModel() {
    const scripts = document.querySelectorAll('script');

    for (const script of scripts) {
      const text = script.textContent;
      if (!text || text.indexOf('"skuModel"') === -1) continue;

      const skuModel = parseBalancedJson(text, text.indexOf('"skuModel"') + 10);
      if (!skuModel || typeof skuModel !== 'object') continue;

      // Per-SKU weight and carton size, keyed by skuId so it can be joined onto
      // the variations below. Weight is in GRAMS and the dimensions in CM —
      // confirmed against `volume`, which equals length × width × height.
      const weightBySkuId = {};
      const weightIndex = text.indexOf('"pieceWeightScaleInfo"');
      if (weightIndex !== -1) {
        const rows = parseBalancedJson(text, weightIndex + 22);
        if (Array.isArray(rows)) {
          for (const row of rows) {
            if (row && row.skuId != null) weightBySkuId[String(row.skuId)] = row;
          }
        }
      }

      return { skuModel, weightBySkuId };
    }
    return null;
  }

  /**
   * Decode the HTML entities 1688 leaves in its SKU strings.
   *
   * The embedded JSON carries display-escaped text, so a two-dimension SKU key
   * is the literal string "蓝色&gt;40oz/1200ml". Without this the operator sees
   * the escape in the panel and it travels into the catalogue as the variation
   * name.
   */
  function decodeEntities(text) {
    if (!text) return '';
    return String(text)
      .replace(/&gt;/g, '>')
      .replace(/&lt;/g, '<')
      .replace(/&quot;/g, '"')
      .replace(/&#0?39;|&apos;/g, "'")
      .replace(/&nbsp;/g, ' ')
      // Ampersand last, or "&amp;gt;" would decode to ">" in one pass.
      .replace(/&amp;/g, '&');
  }

  /**
   * The photo for one SKU, given the per-VALUE image map.
   *
   * WHY THIS IS NOT A PLAIN LOOKUP
   *
   * `skuInfoMap` is keyed by the SKU's full spec string. On a one-dimension
   * listing that equals a value name and a direct lookup works. On a
   * TWO-dimension listing the key is the values joined with ">" -
   * "蓝色>40oz/1200ml" - while the image map holds "蓝色" and "40oz/1200ml"
   * separately, so the direct lookup misses every row.
   *
   * Measured on offer 1054370457410: 0 of 38 variations resolved to a photo,
   * although all 38 colours carried one.
   *
   * Returns '' when the listing genuinely publishes no per-variation photo -
   * offer 855416167191 is that case - and the caller falls back to the
   * product's own gallery image.
   */
  function variantImage(name, imageByName) {
    if (!name) return '';
    if (imageByName[name]) return imageByName[name];

    // Split the compound key and take the first part that carries a picture.
    // Colour is the dimension that usually has one, and it is usually first.
    const parts = String(name).split(/\s*>\s*/);
    for (const part of parts) {
      const key = tidy(part);
      if (key && imageByName[key]) return imageByName[key];
    }
    return '';
  }

  /**
   * Variations from the embedded model.
   *
   * `skuInfoMap` is keyed by the variation's own name and holds its price and
   * `canBookCount` (stock). `skuProps` carries the photo for each name. The two
   * are joined on that name, which is what the page itself does.
   */
  function extractVariationsFromModel(embedded) {
    if (!embedded || !embedded.skuModel) return { dimension: '', items: [] };

    const { skuModel, weightBySkuId } = embedded;
    const infoMap = skuModel.skuInfoMap;
    if (!infoMap || typeof infoMap !== 'object') return { dimension: '', items: [] };

    const props = Array.isArray(skuModel.skuProps) ? skuModel.skuProps : [];
    // EVERY dimension, not just the first. A listing sold by colour AND capacity
    // reported only "颜色" and silently dropped "容量", so the panel implied the
    // options were one axis when they are two.
    const dimension = props.map((p) => tidy(p && p.prop)).filter(Boolean).join(' / ');

    // name -> photo, across every dimension the listing defines.
    const imageByName = {};
    for (const prop of props) {
      for (const value of (prop && prop.value) || []) {
        if (value && value.name && value.imageUrl) {
          imageByName[decodeEntities(value.name)] = normaliseImageUrl(value.imageUrl);
        }
      }
    }

    const items = [];
    for (const rawName of Object.keys(infoMap)) {
      const info = infoMap[rawName] || {};
      // The key arrives HTML-escaped - a two-dimension SKU is literally
      // "蓝色&gt;40oz/1200ml" - so it has to be decoded before it is shown to an
      // operator or used as a lookup key.
      const name = decodeEntities(rawName);
      // `price`, NOT `discountPrice`. The two differ when a listing is running a
      // promotion, and three reasons favour the standard price: it is the figure
      // shown in the SKU list, so the operator can check the panel against the
      // page; a promotion expires, and a catalogue built on it would be quietly
      // underpriced the day it ends; and the panel leaves every price editable
      // anyway, so taking the lower one saves nothing.
      const price = toPrice(info.price) || toPrice(info.discountPrice);
      const stock = Number.isFinite(Number(info.canBookCount))
        ? Number(info.canBookCount)
        : null;

      const measurements = weightBySkuId[String(info.skuId)] || null;

      items.push({
        name: tidy(name),
        price,
        stock,
        imageUrl: variantImage(name, imageByName),
        skuId: info.skuId != null ? String(info.skuId) : '',
        // Grams on the page; kilograms everywhere in this project.
        weightKg: measurements && Number(measurements.weight) > 0
          ? Math.round(Number(measurements.weight)) / 1000
          : null,
        cartonCm: measurements && Number(measurements.length) > 0
          ? {
              length: Number(measurements.length),
              width: Number(measurements.width),
              height: Number(measurements.height),
            }
          : null,
      });
    }

    return { dimension, items };
  }

  // ---- Variations (SKUs) --------------------------------------------------

  /**
   * Read an SKU matrix rendered as a TABLE.
   *
   * A third layout, and the one that produced variations with no prices. Some
   * listings show a handful of filter buttons (全部 / 裸机 / 1电1充) and then a
   * full table underneath — "匹配到10个规格型号" — one row per real SKU:
   *
   *     产品规格            电源电压(V)  额定功率(W)  价格 | 库存(件)   进货数量
   *     双速裸机（无电无充）      21        其他        ¥42 | 10000      [ 0 ]
   *     冲击裸机（无电无充）      21        其他        ¥46 |  9999      [ 0 ]
   *
   * The buttons above it are FILTERS over this table, not the SKUs themselves,
   * so reading them gave four names and no prices while ten priced rows sat
   * below.
   *
   * COLUMNS ARE FOUND BY HEADER TEXT, not by class name or position. The header
   * words are content the page has to show a human — 规格, 价格, 库存 — whereas
   * the class names are generated and differ between listings. This is the same
   * reasoning that makes the regex layer more durable than the selector layer.
   *
   * Price and stock frequently share one cell ("¥42 | 10000"), so a combined
   * column is split rather than requiring two.
   */
  function extractVariationsFromTable() {
    const items = [];

    for (const table of document.querySelectorAll('table')) {
      const headerCells = table.querySelectorAll('thead th, thead td, tr:first-child th');
      if (headerCells.length < 2) continue;

      const headers = Array.prototype.map.call(headerCells, (cell) => tidy(cell.textContent));
      const findColumn = (pattern) => headers.findIndex((h) => pattern.test(h));

      const specColumn = findColumn(/规格|型号|款式|颜色/);
      const priceColumn = findColumn(/价格|单价|价\s*\|/);
      if (specColumn === -1 || priceColumn === -1) continue;

      // A dedicated stock column when there is one; otherwise it rides along in
      // the price cell.
      const stockColumn = findColumn(/库存/);

      const rows = table.querySelectorAll('tbody tr');
      const source = rows.length ? rows : table.querySelectorAll('tr');

      Array.prototype.forEach.call(source, (row, index) => {
        // Skip the header row when the table has no <thead>.
        if (!rows.length && index === 0) return;

        const cells = row.querySelectorAll('td, th');
        if (cells.length <= Math.max(specColumn, priceColumn)) return;

        const name = tidy(cells[specColumn].textContent);
        if (!name) return;

        const priceText = tidy(cells[priceColumn].textContent);
        const priceMatch = priceText.match(new RegExp(PRICE_PATTERN));
        const price = priceMatch ? toPrice(priceMatch[1]) : null;

        let stock = null;
        const stockText = stockColumn !== -1 && cells[stockColumn]
          ? tidy(cells[stockColumn].textContent)
          : priceText;

        if (/已售罄|售罄|无货|缺货/.test(stockText)) {
          // Sold out. 1688 writes this as words, not as 0 — without the check
          // the digit scan below finds nothing and the row reports "unknown
          // stock", which reads as "we did not manage to scrape it" rather than
          // "the supplier has none". A real zero is worth knowing before you
          // build a catalogue around the item.
          stock = 0;
        } else {
          // In a combined "¥42 | 10000" cell the price has already been taken, so
          // the stock is the number that is NOT attached to a ¥.
          const stockMatch = stockText.replace(new RegExp(PRICE_PATTERN, 'g'), ' ')
            .match(/(\d[\d,]*)/);
          if (stockMatch) {
            const value = parseInt(stockMatch[1].replace(/,/g, ''), 10);
            if (Number.isFinite(value)) stock = value;
          }
        }

        // The thumbnail lives in the spec cell, beside the name — not spread
        // across the row — so search there first and fall back to the whole row.
        const imageUrl =
          imageUrlFrom(cells[specColumn]) || imageUrlFrom(row);

        items.push({ name, price, stock, imageUrl });
      });

      // A table that yielded rows is the matrix; no need to look at the rest of
      // the page's tables (attributes, shipping, recommendations).
      if (items.length) break;
    }

    return items;
  }

  /**
   * Read every SKU variation the listing offers.
   *
   * The layout confirmed against a real page:
   *
   *     [data-module="od_sku_selection"]
   *       .feature-item
   *         .feature-item-label > h3        ← dimension name, e.g. 颜色分类
   *         .expand-view-item               ← one per variation
   *           .item-image-icon img          ← its own photo
   *           .item-label[title]            ← its full name
   *           .item-price-stock  (1st)      ← ¥85
   *           .item-price-stock  (2nd)      ← 库存9934台
   *
   * Each variation is a separate sellable product with its own price and photo,
   * which is why they are imported as separate catalogue products rather than
   * collapsed into one.
   *
   * @returns {{dimension: string, items: Array}} `items` is empty for a listing
   *   with no variations, which callers treat as a single-product page.
   */
  function extractVariations(embedded) {
    // Strategy 1: the page's own JSON. Complete and exact where it exists, so
    // nothing below runs. See extractEmbeddedModel for why this beats the DOM.
    const fromModel = extractVariationsFromModel(embedded);
    if (fromModel.items.length) return fromModel;

    const container = firstMatch([
      '[data-module="od_sku_selection"]',
      '.module-od-sku-selection',
      '#skuSelection',
    ]);
    if (!container) return { dimension: '', items: [] };

    const label = container.querySelector('.feature-item-label h3, .feature-item-label');
    const dimension = label ? tidy(label.textContent) : '';

    const rows = container.querySelectorAll('.expand-view-item');
    const items = [];

    rows.forEach((row) => {
      const labelElement = row.querySelector('.item-label');
      // The title attribute carries the untruncated name; the text node is
      // CSS-clamped to two lines and can be visually cut short.
      const name =
        tidy(labelElement && (labelElement.getAttribute('title') || labelElement.textContent));
      if (!name) return;

      // Two .item-price-stock spans: price first, stock second.
      const priceStock = row.querySelectorAll('.item-price-stock');
      let price = null;
      let stock = null;

      priceStock.forEach((span) => {
        const text = tidy(span.textContent);
        const priceMatch = text.match(new RegExp(PRICE_PATTERN));
        if (priceMatch && price === null) {
          price = toPrice(priceMatch[1]);
          return;
        }
        const stockMatch = text.match(/库存\s*(\d[\d,]*)/);
        if (stockMatch) stock = parseInt(stockMatch[1].replace(/,/g, ''), 10);
      });

      // Resolved through imageUrlFrom, not straight off `src`: these rows sit in
      // a scroll container, so most have never been visible and still hold a
      // placeholder in `src` with the real URL in a data- attribute.
      const imageUrl = imageUrlFrom(row.querySelector('.item-image-icon') || row);

      items.push({ name, price, stock, imageUrl });
    });

    // The SKU matrix rendered as a table, which some listings use INSTEAD of the
    // row layout above. Tried before the filter buttons because those buttons are
    // filters over this very table — reading them first yielded four names and no
    // prices while ten priced rows sat underneath.
    if (items.length === 0) {
      const tableItems = extractVariationsFromTable();
      if (tableItems.length) return { dimension, items: tableItems };
    }

    // Last resort: the button-style picker, when there is no table to read
    // either. These carry a name and a thumbnail but no price — that is a
    // property of the page, not a parsing failure — so the operator fills the
    // price in.
    if (items.length === 0) {
      container.querySelectorAll('.sku-filter-button').forEach((button) => {
        const name = tidy(
          button.getAttribute('title') ||
          (button.querySelector('.label-name') || {}).textContent
        );
        // These buttons DO carry a thumbnail — often as a CSS background rather
        // than an <img>. Skipping it left every variation of a two-dimension
        // listing with a blank photo, which is most of what this fallback
        // handles. Price genuinely is not here; the matrix lives elsewhere.
        if (name) {
          items.push({ name, price: null, stock: null, imageUrl: imageUrlFrom(button) });
        }
      });
    }

    return { dimension, items };
  }

  // ---- Price ladder -------------------------------------------------------

  /**
   * Parse a quantity/price ladder ("阶梯价") out of text.
   *
   * Shapes handled:
   *     "2-99件 ¥12.50"     → {minQty: 2,   price: 12.5}
   *     "≥500件 ¥9.80"      → {minQty: 500, price: 9.8}
   *     "100件以上 ¥11.00"   → {minQty: 100, price: 11}
   *     "¥12.50 起批量:2件"  → {minQty: 2,   price: 12.5}
   */
  function parseTiersFromText(rawText) {
    if (!rawText) return [];

    // Stock counts are written in the same shape as a quantity tier —
    // "库存9971台" next to a "¥12" is indistinguishable from "9971台 ¥12" once
    // the labels are gone. Left in, they produced tiers at minQty 9971 and
    // 9999 on a listing whose real minimum is 1. Strip them before parsing.
    const text = rawText
      .replace(/库存\s*\d[\d,]*\s*(?:台|件|个|只|条|双|套|pcs?)?/gi, ' ')
      .replace(/已售\s*[\d.]+\s*[万千]?\s*\+?\s*(?:台|件|个|只)?/gi, ' ');

    const tiers = [];
    const P = PRICE_PATTERN;

    const patterns = [
      // quantity range, then price
      new RegExp(`(\\d[\\d,]*)\\s*(?:-|~|—|到)?\\s*(?:\\d[\\d,]*)?\\s*(?:件|个|只|条|双|套|台|pcs?|pieces?)[^¥￥\\d]{0,12}${P}`, 'gi'),
      // "≥N" / "满N", then price
      new RegExp(`(?:≥|>=|大于等于|满)\\s*(\\d[\\d,]*)\\s*(?:件|个|只|条|双|套|台|pcs?)?[^¥￥\\d]{0,12}${P}`, 'gi'),
      // "N以上" / "N起", then price
      new RegExp(`(\\d[\\d,]*)\\s*(?:件|个|只|条|双|套|台|pcs?)?\\s*(?:以上|起)[^¥￥\\d]{0,12}${P}`, 'gi'),
    ];

    for (const regex of patterns) {
      let match;
      while ((match = regex.exec(text)) !== null) {
        const minQty = parseInt(match[1].replace(/,/g, ''), 10);
        const price = toPrice(match[2]);
        if (Number.isFinite(minQty) && minQty > 0 && price !== null) {
          tiers.push({ minQty, price });
        }
      }
    }

    // Price first, then a stated minimum.
    const priceFirst = new RegExp(
      `${P}[^\\d]{0,20}?(?:起批量|起订量|最小起订)\\D{0,4}(\\d[\\d,]*)`, 'gi'
    );
    let match;
    while ((match = priceFirst.exec(text)) !== null) {
      const price = toPrice(match[1]);
      const minQty = parseInt(match[2].replace(/,/g, ''), 10);
      if (price !== null && Number.isFinite(minQty) && minQty > 0) {
        tiers.push({ minQty, price });
      }
    }

    // Collapse duplicates, keeping the lowest price per quantity. The same
    // ladder often renders twice (sticky header plus main panel), and a
    // struck-through "was" price sits beside the real one.
    const byQty = new Map();
    for (const tier of tiers) {
      const existing = byQty.get(tier.minQty);
      if (!existing || tier.price < existing.price) byQty.set(tier.minQty, tier);
    }
    return Array.from(byQty.values()).sort((a, b) => a.minQty - b.minQty);
  }

  function parseBarePrices(text) {
    const prices = [];
    const regex = new RegExp(PRICE_PATTERN, 'g');
    let match;
    while ((match = regex.exec(text)) !== null) {
      const price = toPrice(match[1]);
      if (price !== null) prices.push(price);
    }
    return prices;
  }

  // ---- Specifications -----------------------------------------------------

  /**
   * Read the attributes table.
   *
   * On the current page this is an Ant Design "descriptions" grid of
   * label/content pairs, which flattens cleanly into "label: value" lines that
   * both the regex layer and the AI can read.
   */
  /**
   * The attributes table as STRUCTURED pairs: [{name, value}, ...].
   *
   * This used to flatten straight to text, which threw away the one thing the
   * page had already worked out for us — which string is a field name and which
   * is its value. The catalogue has a per-product specification list
   * (ProductAttribute on the server), and it is also what makes a product page
   * substantial rather than a name and a price, so the pairs are worth keeping.
   *
   * `extractSpecRegion` below now renders these back to text for the callers
   * that want a blob (weight/MOQ regexes, the AI prompt).
   */
  function extractSpecPairs() {
    const container = firstMatch([
      '[data-module="od_product_attributes"]',
      '.od-pc-attribute',
      '[class*="offer-attr"]',
      '[class*="attribute"]',
    ]);
    if (!container) return [];

    // Labels and values are zipped BY DOCUMENT ORDER, not by walking up to a
    // shared row. An Ant Design descriptions row holds TWO label/content
    // pairs side by side, so `row.querySelector('.…-content')` returns the
    // row's first value for both labels — which silently pairs every second
    // attribute with the wrong value (货号 came back as "100W（W）" that way).
    const labels = container.querySelectorAll('.ant-descriptions-item-label');
    const values = container.querySelectorAll('.ant-descriptions-item-content');
    if (!labels.length) return [];

    const pairs = [];
    labels.forEach((label, index) => {
      let valueEl;
      if (labels.length === values.length) {
        valueEl = values[index];
      } else {
        // Counts disagree (a colspan, or a layout we have not seen): pair each
        // label with the value element that immediately follows it instead.
        valueEl = label.nextElementSibling;
        while (valueEl && !valueEl.classList.contains('ant-descriptions-item-content')) {
          valueEl = valueEl.nextElementSibling;
        }
      }
      // Trailing colons are part of the label's styling, not its name.
      const name = tidy(label.textContent).replace(/[:：]\s*$/, '');
      const value = tidy(valueEl && valueEl.textContent);
      if (name && value) pairs.push({ name, value });
    });
    return pairs;
  }

  /**
   * The packing table as one row per variation.
   *
   * 1688 publishes 包装信息 / 商品件重尺 as a table whose FIRST column is the
   * variation name and whose remaining columns are dimensions and weight, with
   * the unit written into the column header rather than beside the number:
   *
   *     颜色                  长(cm)  宽(cm)  高(cm)  体积(cm³)  重量(g)
   *     机械狗                  22     4.50    18     1782      230
   *     机械狗【中文】+2节7号电池  22     4.50    18     1782      250
   *
   * This is often the ONLY source of carton dimensions on a listing - the
   * embedded model's `pieceWeightScaleInfo` is absent on plenty of offers - and
   * dimensions are what CBM is computed from, so without them a product cannot
   * be quoted for sea freight at all.
   *
   * Columns are located BY HEADER TEXT, never by position: the same table
   * appears with and without a 体积 column, and with 规格 or 型号 in place of
   * 颜色, so a fixed index reads the wrong figure on the next listing.
   *
   * @returns {{rows: Array, byName: Object}} rows carry
   *   `{name, cm:{length,width,height}, weightKg}`.
   */
  function extractPackTable() {
    const empty = { rows: [], byName: {} };
    const container = firstMatch([
      '[data-module="od_product_pack_info"]',
      '[class*="pack-info"]',
      '.od-pc-offer-table',
    ]);
    if (!container) return empty;

    for (const table of container.querySelectorAll('table')) {
      const headCells = table.querySelectorAll('thead th, thead td');
      if (headCells.length < 2) continue;
      const heads = Array.prototype.map.call(headCells, (c) => tidy(c.textContent));

      // Header -> column index. The unit lives in the header's parentheses.
      const find = (re) => heads.findIndex((h) => re.test(h));
      const col = {
        length: find(/^长|长度/),
        width: find(/^宽|宽度/),
        height: find(/^高|高度/),
        weight: find(/毛重|净重|重量/),
      };
      if (col.weight === -1 && col.length === -1) continue;

      const weightUnit = (heads[col.weight] || '').match(/[（(]\s*(kg|g|千克|公斤|克)\s*[）)]/i);
      const toKg = (value) => {
        const n = parseFloat(String(value).replace(/[^\d.]/g, ''));
        if (!Number.isFinite(n) || n <= 0) return null;
        const unit = (weightUnit ? weightUnit[1] : 'g').toLowerCase();
        const kg = (unit === 'g' || unit === '克') ? n / 1000 : n;
        // A packed item over a tonne or under a gram is a misread cell, not a
        // real figure - the same guard the single-weight reader applied.
        return (kg > 0 && kg < 1000) ? Math.round(kg * 1000) / 1000 : null;
      };
      const num = (value) => {
        const n = parseFloat(String(value).replace(/[^\d.]/g, ''));
        return Number.isFinite(n) && n > 0 ? n : null;
      };

      const rows = [];
      const byName = {};
      table.querySelectorAll('tbody tr').forEach((tr) => {
        const cells = Array.prototype.map.call(
          tr.querySelectorAll('td, th'), (c) => tidy(c.textContent)
        );
        if (cells.length < 2) return;

        // The name is the first column. It is the SKU spec string, so it needs
        // the same entity decoding the skuInfoMap keys get.
        const name = decodeEntities(cells[0]);
        if (!name) return;

        const length = col.length > -1 ? num(cells[col.length]) : null;
        const width = col.width > -1 ? num(cells[col.width]) : null;
        const height = col.height > -1 ? num(cells[col.height]) : null;
        const weightKg = col.weight > -1 ? toKg(cells[col.weight]) : null;

        const row = {
          name,
          cm: (length && width && height) ? { length, width, height } : null,
          weightKg,
        };
        rows.push(row);
        byName[name] = row;
      });

      if (rows.length) return { rows, byName };
    }
    return empty;
  }

  /**
   * Shipping weight from the listing's "包装信息 / 商品件重尺" table.
   *
   * @returns {number|null} weight in kilograms, or null when the table is absent.
   *
   * WHY THIS EXISTS SEPARATELY FROM extractWeightKg
   *
   * That function matches "重量 2000 g" - a label, then a number, then a unit.
   * This table states the unit in the COLUMN HEADER instead:
   *
   *     <th>重量(g)</th>
   *     <td>2000</td>
   *
   * so the number and its unit are never adjacent in the text, and every
   * pattern in extractWeightKg misses it. A listing that publishes its packed
   * weight was coming back with no weight at all - and weight is what sea and
   * air freight are priced on, so the product could not be quoted.
   *
   * This is also the RIGHT weight to prefer. It is the packed shipping weight,
   * whereas the 重量 in the attributes table is the bare product weight; a 2 kg
   * parcel holding a 2.5 kg-listed drill is the difference between a carton and
   * a bare machine head.
   */
  function extractPackWeightKg() {
    // One source of truth: the full table parser above already resolves the
    // unit from the column header and guards the range. This used to walk the
    // cells itself with a flattened index, which only lined up while the first
    // row happened to align with the header - and it could never see the
    // dimension columns sitting beside the weight.
    const rows = extractPackTable().rows;
    const first = rows.find((r) => r.weightKg);
    return first ? first.weightKg : null;
  }

  function extractSpecRegion() {
    const pairs = extractSpecPairs();
    if (pairs.length) {
      return pairs.map((p) => `${p.name}: ${p.value}`).join('\n').slice(0, 6000);
    }

    const container = firstMatch([
      '[data-module="od_product_attributes"]',
      '.od-pc-attribute',
      '[class*="offer-attr"]',
      '[class*="attribute"]',
    ]);
    if (container) {
      return tidy(container.innerText || container.textContent).slice(0, 6000);
    }

    // Nothing recognisable: fall back to any small table on the page, skipping
    // the huge recommendation grids.
    const parts = [];
    document.querySelectorAll('table').forEach((table) => {
      const text = tidy(table.innerText || table.textContent);
      if (text && text.length < 3000) parts.push(text);
    });
    return parts.join('\n').slice(0, 6000);
  }

  /**
   * Find a per-piece weight in kilograms, or null.
   *
   * Null is the correct answer far more often than it looks: the real page this
   * was built against lists 20 attributes and none of them is a weight. A
   * guessed weight produces a wrong air-freight quote, so it is never inferred.
   */
  function extractWeightKg(text, options) {
    if (!text) return null;
    const allowUnlabelled = !!(options && options.allowUnlabelled);

    // Explicitly labelled weights. Safe to look for anywhere.
    const labelled = [
      { regex: /(?:毛重|重量|净重|单件重量|克重)\D{0,8}?([\d]+(?:\.\d+)?)\s*(?:kg|千克|公斤)/i, factor: 1 },
      { regex: /(?:毛重|重量|净重|单件重量|克重)\D{0,8}?([\d]+(?:\.\d+)?)\s*(?:g|克)(?![\w])/i, factor: 0.001 },
      { regex: /(?:毛重|重量|净重)\D{0,8}?([\d]+(?:\.\d+)?)\s*斤/i, factor: 0.5 },
    ];

    // Bare "1.2 kg" / "500g" with no label. These are only trustworthy inside
    // the attributes table. Run against whole-page text they match the first
    // number-plus-unit anywhere on the page — a recommended product's spec, a
    // shipping blurb, a battery rating — and invent a weight for a listing that
    // states none. That is how this returned 0.037kg for a vacuum cleaner whose
    // 20 attributes contain no weight at all.
    const unlabelled = [
      { regex: /([\d]+(?:\.\d+)?)\s*(?:kg|千克|公斤)/i, factor: 1 },
      { regex: /([\d]+(?:\.\d+)?)\s*(?:g|克)(?![\w])/i, factor: 0.001 },
    ];

    const patterns = allowUnlabelled ? labelled.concat(unlabelled) : labelled;

    for (const { regex, factor } of patterns) {
      const match = text.match(regex);
      if (match) {
        const value = parseFloat(match[1]) * factor;
        if (Number.isFinite(value) && value >= 0.001 && value <= 500) {
          return Math.round(value * 1000) / 1000;
        }
      }
    }
    return null;
  }

  /**
   * Minimum order quantity.
   *
   * Two phrasings, both real: the label form ("起批量: 2") and the inline form
   * ("1台起批"), which is what the page this was built against uses.
   */
  function extractMoq(text) {
    if (!text) return null;
    const labelled = text.match(/(?:起批量|起订量|最小起订量|最小起批)\D{0,6}?(\d[\d,]*)/);
    const inline = text.match(/(\d[\d,]*)\s*(?:台|件|个|只|条|双|套|pcs?)\s*起批/i);
    const raw = (labelled && labelled[1]) || (inline && inline[1]);
    if (!raw) return null;
    const value = parseInt(raw.replace(/,/g, ''), 10);
    return Number.isFinite(value) && value > 0 ? value : null;
  }

  function extractCartonQty(text) {
    const match = (text || '').match(/(?:装箱数|箱规|每箱|一箱)\D{0,8}?(\d[\d,]*)/);
    if (!match) return null;
    const value = parseInt(match[1].replace(/,/g, ''), 10);
    return Number.isFinite(value) && value > 0 ? value : null;
  }

  /** Supplier model number (货号) — a genuinely useful SKU when present. */
  function extractModelNumber(text) {
    const match = (text || '').match(/(?:货号|型号|款号)\s*[:：]?\s*([A-Za-z0-9\-_.]{2,40})/);
    return match ? match[1] : '';
  }

  // ---- Images -------------------------------------------------------------

  /**
   * Normalise an image URL to full resolution.
   *
   * 1688 appends a size/format suffix after the real extension — the saved page
   * shows both `….jpg_sum.jpg` (SKU thumbnails) and `….jpg_.webp` (gallery).
   * Stripping it yields the original; importing the 40px thumbnail instead
   * would produce unusable catalogue photos.
   */
  /**
   * The real image URL behind an element, whatever lazy-loading it uses.
   *
   * 1688 does not put the photo in `src` until the element scrolls into view.
   * Until then `src` holds a 1x1 spacer or a data: URI and the actual address
   * sits in one of several data- attributes, which differ between the modules on
   * a single page. Reading `src` first therefore yields a transparent pixel that
   * looks like a working image right up until it reaches the catalogue.
   *
   * The variation rows are the worst case: they are inside a scroll container,
   * so most of them have never been visible and almost none have a real `src`.
   *
   * Also handles the picker variant that has no <img> at all and paints the
   * thumbnail as a CSS background instead.
   *
   * @param {Element|null} element An <img>, or a container holding one.
   * @returns {string} An absolute https URL, or '' when there is nothing usable.
   */
  function imageUrlFrom(element) {
    if (!element) return '';

    const img = element.tagName === 'IMG' ? element : element.querySelector('img');

    if (img) {
      // In priority order: the attributes that hold the true URL, then `src`.
      const candidates = [
        'data-src', 'data-lazyload', 'data-ks-lazyload', 'data-original',
        'data-lazy-src', 'data-image', 'src',
      ];
      for (const attribute of candidates) {
        const raw = (img.getAttribute(attribute) || '').trim();
        // A data: URI is the placeholder, never the photo.
        if (!raw || raw.startsWith('data:')) continue;
        const url = normaliseImageUrl(raw);
        if (/^https?:\/\//i.test(url)) return url;
      }
    }

    // No usable <img>: the thumbnail may be a CSS background on the element or
    // on a child of it.
    //
    // Capped, because getComputedStyle forces a style resolve per node and this
    // can be handed a whole table row. A thumbnail is always near the top of its
    // container; scanning hundreds of descendants would cost more than the photo
    // is worth.
    const painted = [element].concat(
      Array.prototype.slice.call(element.querySelectorAll('*'), 0, 40)
    );
    for (const node of painted) {
      const background = (node.style && node.style.backgroundImage) ||
        (window.getComputedStyle ? window.getComputedStyle(node).backgroundImage : '');
      const match = /url\(["']?([^"')]+)["']?\)/i.exec(background || '');
      if (match) {
        const url = normaliseImageUrl(match[1]);
        if (/^https?:\/\//i.test(url)) return url;
      }
    }

    return '';
  }

  function normaliseImageUrl(url) {
    if (!url) return '';
    let clean = url.trim();
    if (clean.startsWith('//')) clean = 'https:' + clean;
    clean = clean.replace(/\.(jpg|jpeg|png|webp)_[^/]*$/i, '.$1');
    clean = clean.replace(/_\d+x\d+(?:q\d+)?\.(jpg|jpeg|png|webp)$/i, '.$1');
    return clean.split('?')[0];
  }

  function extractImages() {
    const urls = new Set();
    // Gallery thumbnails lazy-load the same way the variation rows do, so they
    // go through the same resolver rather than reading `src` directly.
    const addFrom = (element) => {
      const url = imageUrlFrom(element);
      if (url) urls.add(url);
    };

    const meta = document.querySelector('meta[property="og:image"]');
    if (meta && meta.content) urls.add(normaliseImageUrl(meta.content));

    const gallery = firstMatch([
      '[data-module="od_picture_gallery"]',
      '.od-gallery',
      '[class*="detail-gallery"]',
      '[class*="gallery"]',
    ]);

    const scope = gallery || document;
    scope.querySelectorAll('img').forEach(addFrom);

    return Array.from(urls)
      .filter((url) => /^https?:\/\//i.test(url))
      // Only marketplace CDNs: the page is full of sprites, icons and tracking
      // pixels, and the import endpoint refuses anything else anyway.
      .filter((url) => /(alicdn|aliimg|taobaocdn|tbcdn)\./i.test(url))
      // ...but 1688 serves its OWN INTERFACE off those same CDNs, so the host
      // check alone is not enough. On offer 1054370457410 the first two images
      // taken were a 15x8 scroll arrow and a 24x24 button icon, which pushed the
      // real product photo into third place and filled two of the three import
      // slots with furniture.
      //
      // Two independent signatures, because either alone is a guess:
      //   - a product photograph is never an SVG; every 1688 UI glyph is.
      //   - "-tps-15-8" is Alibaba's own naming for an interface asset and
      //     encodes its pixel size, which is how a 15px-wide "image" is spotted
      //     without downloading it.
      .filter((url) => !/\.svg(\?|$)/i.test(url))
      .filter((url) => !/-tps-\d+-\d+/i.test(url))
      .slice(0, 3);
  }

  // ---- Entry point --------------------------------------------------------

  function scrape() {
    const priceText = moduleText('od_main_price', ['#mainPrice', '.price-comp', '[class*="price"]']);
    const specPairs = extractSpecPairs();
    const specText = extractSpecRegion();
    const bodyText = tidy(document.body.innerText || '').slice(0, 20000);

    const moq = extractMoq(priceText) || extractMoq(specText) || extractMoq(bodyText);
    const embedded = extractEmbeddedModel();
    const variations = extractVariations(embedded);

    // When the variations carry their own prices, THEY are the prices — the
    // listing has no single figure that is right for both an ¥85 machine and
    // its ¥12 accessory. Skipping the whole-page fallbacks in that case also
    // keeps the SKU panel's own numbers from being re-read as a price ladder.
    const hasVariationPrices = variations.items.some((item) => item.price !== null);

    let tiers = parseTiersFromText(priceText);
    if (tiers.length === 0 && !hasVariationPrices) {
      tiers = parseTiersFromText(bodyText);
    }

    if (tiers.length === 0 && !hasVariationPrices) {
      const prices = parseBarePrices(priceText).concat(parseBarePrices(bodyText));
      if (prices.length > 0) {
        tiers = [{ minQty: moq || 1, price: Math.min.apply(null, prices) }];
      }
    }

    // Weight and carton size as stated by the supplier per SKU in the embedded
    // model. Taken from the first variation that carries them.
    // The packing table, joined onto the variations by name.
    //
    // `pieceWeightScaleInfo` in the embedded model is the most specific source
    // but is absent from plenty of listings - offer 855416167191 has none, and
    // its carton size exists ONLY in this table. Filling it here is what makes
    // CBM computable, and CBM is what sea freight is priced on.
    const packTable = extractPackTable();
    if (packTable.rows.length) {
      for (const item of variations.items) {
        const row = packTable.byName[item.name];
        if (!row) continue;
        // The model's per-SKU figures still win where they exist; this only
        // fills what they left empty.
        if (!item.weightKg && row.weightKg) item.weightKg = row.weightKg;
        if (!item.cartonCm && row.cm) item.cartonCm = row.cm;
      }
    }

    const measured = variations.items.find((item) => item.weightKg || item.cartonCm);
    const modelWeightKg = measured ? measured.weightKg : null;
    const modelCartonCm = measured ? measured.cartonCm : null;

    // Product-level carton size. A listing whose options all ship in the same
    // box - which is the common case - yields one row per option with identical
    // dimensions, so the first row is the product's carton.
    const packCartonCm = (packTable.rows.find((r) => r.cm) || {}).cm || null;

    const title = extractTitle();

    const imageUrls = extractImages();

    // A variation with no photo of its own shows the product's main photo.
    //
    // Plenty of suppliers publish one gallery and no per-option pictures - offer
    // 855416167191 has three options and zero variation images. Left blank, every
    // one of those rows imports with an empty frame, and the customer picking an
    // option on the product page watches the picture disappear. The parent photo
    // is the honest stand-in: it is a picture of the thing being bought.
    //
    // Deliberately NOT applied when the listing does publish per-variation
    // photos - there, a blank means that one option genuinely has no image and
    // substituting a different colour's photo would be worse than showing none.
    const anyVariationHasPhoto = variations.items.some((item) => item.imageUrl);
    if (!anyVariationHasPhoto && imageUrls.length) {
      for (const item of variations.items) {
        item.imageUrl = imageUrls[0];
        item.imageFromParent = true;
      }
    }

    return {
      title,
      name: title,
      tiers,
      moq,
      // Bare "N g" / "N kg" is only trusted inside the attributes table; over
      // whole-page text it invents weights. See extractWeightKg.
      // The embedded model states weight and carton size per SKU, so it wins
      // over anything pattern-matched out of page text — which is where the
      // "not stated" weights were coming from.
      // Order matters. The embedded model states weight per SKU and is the most
      // specific. Next the packing table, which is the PACKED weight freight is
      // actually priced on. Only then the pattern matchers over text, which are
      // the guesses.
      weightKg:
        modelWeightKg ||
        extractPackWeightKg() ||
        extractWeightKg(specText, { allowUnlabelled: true }) ||
        extractWeightKg(bodyText),
      // Model first, then the packing table. Before this the table's
      // dimensions were never read at all, so any listing without
      // pieceWeightScaleInfo imported with no carton size and could not be
      // quoted for sea freight.
      cartonCm: modelCartonCm || packCartonCm,
      cartonQty: extractCartonQty(specText) || extractCartonQty(bodyText),
      modelNumber: extractModelNumber(specText),
      // The spec table as name/value pairs. These become the product's
      // Specifications on the site — the difference between a product page that
      // is a name and a price and one that describes the thing.
      attributes: specPairs,
      imageUrls,
      variations,
      sourceUrl: location.href.split('?')[0],
      raw: {
        url: location.href,
        title,
        price_text: priceText,
        spec_text: specText,
        // The same table as structured pairs, so the translate pass can render
        // each half back into place rather than re-parsing the blob above.
        attributes: specPairs,
        // Variation names go to the AI explicitly: they are the text that most
        // needs translating and they are easy to lose in a 20,000-character
        // page dump.
        variation_text: variations.items
          .map((item) => `${item.name}${item.price != null ? ` ¥${item.price}` : ''}`)
          .join('\n'),
        text: bodyText,
      },
    };
  }

  MLK.extract1688 = {
    scrape,
    extractSpecPairs,
    extractPackWeightKg,
    extractPackTable,
    parseTiersFromText,
    parseBarePrices,
    extractWeightKg,
    extractMoq,
    extractTitle,
    extractVariations,
    extractVariationsFromTable,
    extractSpecRegion,
    extractImages,
    extractModelNumber,
    normaliseImageUrl,
    toPrice,
    tidy,
    PRICE_PATTERN,
  };
})(globalThis.MLK);

if (typeof module !== 'undefined' && module.exports) {
  module.exports = globalThis.MLK.extract1688;
}
