/**
 * src/lib/providers.js
 *
 * The AI layer that refines what the DOM scraper found.
 *
 * Modes, chosen in Options:
 *
 *   'translate' — translate names via lib/translate.js. Free, no setup. THE
 *                 ONLY MODE OFFERED IN THE UI.
 *   'none'      — no enrichment at all; names stay in Chinese.
 *
 * The two AI modes below are DISABLED in the interface but left implemented, so
 * turning them back on is a one-line change in options.html rather than a
 * rewrite:
 *
 *   'ollama' — a model running locally (qwen2.5 handles Chinese well). Free and
 *              private; nothing leaves the machine.
 *   'server' — the Django site proxies to Claude. Best quality, costs per page,
 *              and keeps the Anthropic key on the server rather than inside an
 *              extension anyone can unpack.
 *
 * THE AI NEVER BLOCKS A SCRAPE. It is a refinement pass: `mergeExtraction`
 * below only overwrites fields the AI is more likely to be right about, and any
 * failure leaves the DOM draft untouched. A model being down degrades the tool
 * to 'none' rather than breaking it.
 *
 * Runs in the service worker, which is the only context that can reach
 * http://localhost — an https 1688 page cannot, because the browser blocks
 * mixed content.
 */

(function (MLK) {
  'use strict';

  /** The JSON shape both providers are asked to return. */
  const FIELD_SPEC = `{
  "name_en": "concise English product name, 3-10 words",
  "tiers": [{"min_qty": 100, "price_rmb": 11.0}],
  "moq": 100,
  "weight_kg": 0.5,
  "carton_qty": 24,
  "variations": [{"name_original": "白色11.1V", "name_en": "White 11.1V"}],
  "category_slug": "home-kitchen",
  "subcategory_slug": "kitchen",
  "confidence": "high"
}`;

  function buildOllamaPrompt(page, taxonomy) {
    const categoryLines = (taxonomy || [])
      .map((category) => {
        const subs = (category.subcategories || [])
          .map((sub) => `    ${sub.slug}`)
          .join('\n');
        return `  ${category.slug}\n${subs}`;
      })
      .join('\n');

    return `You extract product data from Chinese wholesale listings (1688.com).

Return ONLY a JSON object in this exact shape, with no commentary:
${FIELD_SPEC}

Rules:
- Prices are RMB per piece and exclude shipping. Do NOT add any markup.
- 1688 shows tiered prices ("2-99件 ¥12.50 / 100-499件 ¥11.00"). List every tier.
- Weight: 1斤 = 0.5kg, 1克 = 0.001kg. Use null if the page does not state a weight.
  Never guess a weight — a wrong one produces a wrong shipping quote.
- name_en describes the product in English. No supplier names, no 包邮/厂家直销.
- variations: translate EVERY line under VARIATIONS below, in the same order, one
  entry each. Keep what distinguishes each from its siblings (colour, capacity,
  voltage, which part of a set). They become separate products, so a name that
  does not say which variation it is would be useless. Empty array if none.
- category_slug and subcategory_slug must be copied exactly from this list, or null:
${categoryLines}

PRODUCT PAGE
Title: ${page.title || ''}
Price area: ${(page.price_text || '').slice(0, 1500)}
Specs area: ${(page.spec_text || '').slice(0, 3000)}

VARIATIONS (translate each, same order):
${(page.variation_text || '(none)').slice(0, 2000)}

Page text: ${(page.text || '').slice(0, 5000)}`;
  }

  /**
   * Call a local Ollama server.
   *
   * `format: 'json'` puts Ollama into JSON mode, which constrains generation to
   * syntactically valid JSON. It does not enforce our field names, so the merge
   * step below still treats every field as optional.
   */
  async function extractViaOllama(page, taxonomy, settings) {
    const base = (settings.ollamaUrl || 'http://localhost:11434').replace(/\/+$/, '');
    const response = await fetch(`${base}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: settings.ollamaModel || 'qwen2.5:7b',
        stream: false,
        format: 'json',
        options: { temperature: 0 },
        messages: [{ role: 'user', content: buildOllamaPrompt(page, taxonomy) }],
      }),
    });

    if (!response.ok) {
      throw new Error(
        `Ollama returned ${response.status}. Is it running, and was it started ` +
        `with OLLAMA_ORIGINS set so the extension may call it?`
      );
    }

    const data = await response.json();
    const content = data && data.message && data.message.content;
    if (!content) throw new Error('Ollama returned an empty response.');

    try {
      return JSON.parse(content);
    } catch (error) {
      throw new Error('Ollama did not return valid JSON.');
    }
  }

  // ---- Translation --------------------------------------------------------

  /**
   * Translate a page's title and every variation name.
   *
   * The actual translating lives in lib/translate.js — this only shapes the
   * result to match what the Ollama and Claude modes return, so
   * `mergeExtraction` handles all three identically.
   *
   * Names only. Prices, weights, stock and categories stay exactly as scraped;
   * a translator has no opinion on any of them.
   */
  async function extractViaTranslate(page) {
    const variationNames = (page.variation_text || '')
      .split('\n')
      .map((line) => line.replace(/\s*¥[\d.]+\s*$/, '').trim())
      .filter(Boolean);

    // The specification table, both halves. A spec list is worth nothing to an
    // English-reading buyer as 材质 / 不锈钢, and these are the lines that end up
    // on the public product page and in its structured data — so they get
    // translated alongside the names rather than left as the one Chinese thing
    // on an otherwise English page.
    //
    // Names and values go in the SAME batch as the title and variations: the
    // translator batches one request per call and caches every string forever,
    // so a page's whole vocabulary costs one request the first time and none
    // after that. Attribute names especially repeat across every product.
    const attributes = Array.isArray(page.attributes) ? page.attributes : [];
    const attrNames = attributes.map((a) => a.name || '');
    const attrValues = attributes.map((a) => a.value || '');

    const inputs = [page.title || '']
      .concat(variationNames)
      .concat(attrNames)
      .concat(attrValues);
    const outcome = await MLK.translate.translateAll(inputs);

    if (!outcome.ok) {
      throw new Error(
        `${outcome.error}. Names left in Chinese — the page data is still correct.`
      );
    }

    // Unpack in the order they were packed.
    const out = outcome.translations;
    let cursor = 0;
    const title = out[cursor++];
    const names = out.slice(cursor, cursor + variationNames.length);
    cursor += variationNames.length;
    const outNames = out.slice(cursor, cursor + attrNames.length);
    cursor += attrNames.length;
    const outValues = out.slice(cursor, cursor + attrValues.length);

    const note = outcome.fromCache
      ? `Translated via ${outcome.provider} (${outcome.fromCache} from cache).`
      : `Translated via ${outcome.provider}.`;

    return {
      name_en: title,
      variations: variationNames.map((original, index) => ({
        name_original: original,
        name_en: names[index] || original,
      })),
      attributes: attributes.map((attr, index) => ({
        name: outNames[index] || attr.name,
        value: outValues[index] || attr.value,
      })),
      confidence: 'medium',
      notes: note,
    };
  }

  /** Call the Django site, which forwards to Claude with the server's API key. */
  async function extractViaServer(page, settings) {
    const base = (settings.siteUrl || '').replace(/\/+$/, '');
    if (!base) throw new Error('No site URL configured in Options.');
    if (!settings.apiToken) throw new Error('No API token configured in Options.');

    const response = await fetch(`${base}/products/api/extension/extract/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${settings.apiToken}`,
      },
      body: JSON.stringify({ page }),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) {
      throw new Error(data.message || `Server returned ${response.status}.`);
    }
    return data.result;
  }

  /**
   * Fold an AI result into the DOM draft.
   *
   * The split of authority is deliberate:
   *   - **name**: the AI wins outright. Translation is the one thing the DOM
   *     scraper genuinely cannot do.
   *   - **tiers**: the AI wins only when the scraper found none, or when the AI
   *     found strictly more tiers. Regex over the price region is very reliable
   *     when it matches, and a model that hallucinates a ladder is a real risk.
   *   - **weight / carton / MOQ / category**: fill gaps only. Never overwrite a
   *     value read directly off the page with a generated one.
   *
   * @returns {object} A new draft; the input is not mutated.
   */
  function mergeExtraction(draft, ai) {
    if (!ai || typeof ai !== 'object') return draft;
    const merged = Object.assign({}, draft);

    if (typeof ai.name_en === 'string' && ai.name_en.trim()) {
      merged.name = ai.name_en.trim();
      merged.nameSource = 'ai';
    }

    // Specifications. Only replaced when the returned list is the same length as
    // the scraped one — a shorter or longer list means the pairs no longer line
    // up with what was read off the page, and a mislabelled spec ("Material:
    // 220V") is worse than an untranslated one.
    if (Array.isArray(ai.attributes) &&
        ai.attributes.length === (merged.attributes || []).length) {
      merged.attributes = ai.attributes
        .map((attr, index) => ({
          name: (attr && attr.name) || merged.attributes[index].name,
          value: (attr && attr.value) || merged.attributes[index].value,
        }))
        .filter((attr) => attr.name && attr.value);
      merged.attributesSource = 'ai';
    }

    const aiTiers = Array.isArray(ai.tiers)
      ? ai.tiers
          .map((tier) => ({
            minQty: parseInt(tier.min_qty, 10),
            price: parseFloat(tier.price_rmb),
          }))
          .filter(
            (tier) =>
              Number.isFinite(tier.minQty) && tier.minQty > 0 &&
              Number.isFinite(tier.price) && tier.price > 0
          )
          .sort((a, b) => a.minQty - b.minQty)
      : [];

    if (aiTiers.length > (merged.tiers || []).length) {
      merged.tiers = aiTiers;
      merged.tiersSource = 'ai';
    }

    if (merged.weightKg == null && Number.isFinite(Number(ai.weight_kg))) {
      const weight = Number(ai.weight_kg);
      if (weight >= 0.001 && weight <= 500) {
        merged.weightKg = weight;
        merged.weightSource = 'ai';
      }
    }

    if (merged.cartonQty == null && Number.isInteger(ai.carton_qty) && ai.carton_qty > 0) {
      merged.cartonQty = ai.carton_qty;
    }

    if (merged.moq == null && Number.isInteger(ai.moq) && ai.moq > 0) {
      merged.moq = ai.moq;
    }

    // Variation names: translation only. Prices, stock, and images stay exactly
    // as scraped — those were read off the page and must never be replaced by
    // generated values.
    //
    // Matching is BY POSITION, guarded by a length check. A model that dropped
    // or merged an entry would otherwise shift every later translation onto the
    // wrong variation, silently mislabelling products that differ only by
    // colour. If the count disagrees, all translations are discarded and the
    // original Chinese names are kept — obviously untranslated beats
    // confidently wrong.
    if (
      Array.isArray(ai.variations) &&
      merged.variations &&
      Array.isArray(merged.variations.items) &&
      ai.variations.length === merged.variations.items.length
    ) {
      merged.variations = {
        dimension: merged.variations.dimension,
        items: merged.variations.items.map((item, index) => {
          const translated = ai.variations[index];
          const nameEn =
            translated && typeof translated.name_en === 'string'
              ? translated.name_en.trim()
              : '';
          return Object.assign({}, item, {
            nameEn: nameEn || '',
            nameSource: nameEn ? 'ai' : 'page',
          });
        }),
      };
    }

    if (!merged.categorySlug && typeof ai.category_slug === 'string') {
      merged.categorySlug = ai.category_slug || null;
    }
    if (!merged.subcategorySlug && typeof ai.subcategory_slug === 'string') {
      merged.subcategorySlug = ai.subcategory_slug || null;
    }

    merged.aiConfidence = ai.confidence || null;
    merged.aiNotes = ai.notes || '';
    return merged;
  }

  /**
   * Run whichever AI mode is configured.
   *
   * @returns {Promise<{ok: boolean, result?: object, error?: string, mode: string}>}
   *   Never rejects: a failure is reported as `ok: false` so the caller can show
   *   a warning and keep the DOM draft rather than losing the scrape entirely.
   */
  async function runExtraction(page, taxonomy, settings) {
    const mode = settings.aiMode || 'none';
    if (mode === 'none') return { ok: true, result: null, mode };

    try {
      let result;
      if (mode === 'translate' || mode === 'google') {
        // 'google' is the pre-1.2 name for this mode; accepted so a saved
        // setting from an older build keeps working after an upgrade.
        result = await extractViaTranslate(page);
      } else if (mode === 'ollama') {
        result = await extractViaOllama(page, taxonomy, settings);
      } else {
        result = await extractViaServer(page, settings);
      }
      return { ok: true, result, mode };
    } catch (error) {
      return { ok: false, error: error.message || String(error), mode };
    }
  }

  MLK.providers = {
    runExtraction,
    mergeExtraction,
    buildOllamaPrompt,
    extractViaTranslate,
  };
})(globalThis.MLK);

if (typeof module !== 'undefined' && module.exports) {
  module.exports = globalThis.MLK.providers;
}
