/**
 * src/lib/pricing.js
 *
 * Working out which supplier price applies.
 *
 * NO MARKUP IS APPLIED. The extension reports what the supplier charges and
 * nothing more; the selling price is set by hand, either in the panel before
 * adding a product or on the site afterwards. An automatic markup was removed
 * deliberately — a single flat figure cannot be right across accessories at ¥12
 * and machines at ¥85, and a wrong-but-plausible number is worse than an
 * obviously raw one because nobody re-checks it.
 *
 * What is left is the part that genuinely needs computing: 1688 quotes tiered
 * wholesale prices ("阶梯价") that fall as quantity rises —
 *
 *     2 - 99 件      ¥12.50
 *     100 - 499 件   ¥11.00
 *     ≥ 500 件       ¥9.80
 *
 * — and the tier that applies at the order quantity is not the headline price a
 * visitor sees first. Reading the headline overstates cost on every product.
 *
 * Loaded by the content script and the popup, so no DOM and no network here.
 */

(function (MLK) {
  'use strict';

  /**
   * Pick the price tier that applies at a given order quantity.
   *
   * @param {Array<{minQty:number, price:number}>} tiers - Ladder, any order.
   * @param {number} targetQty - Quantity being priced.
   * @returns {{minQty:number, price:number}|null}
   *
   * The chosen tier has the LARGEST minQty still at or below targetQty — the
   * deepest discount actually earned. When every tier starts above targetQty
   * (a supplier whose ladder begins at 500), the cheapest way in is the tier
   * with the smallest minQty, so that is returned rather than nothing: a
   * slightly conservative price beats no price at all.
   */
  function selectTier(tiers, targetQty) {
    const usable = (tiers || []).filter(
      (t) => t && Number.isFinite(t.price) && t.price > 0 && Number.isFinite(t.minQty)
    );
    if (usable.length === 0) return null;

    const applicable = usable.filter((t) => t.minQty <= targetQty);
    if (applicable.length > 0) {
      return applicable.reduce((best, t) => (t.minQty > best.minQty ? t : best));
    }
    return usable.reduce((best, t) => (t.minQty < best.minQty ? t : best));
  }

  /**
   * Resolve the supplier price for a scraped product.
   *
   * @param {object} draft - Scraped product data. `variationPrice`, when set,
   *   is a specific SKU's own price and wins outright: a listing whose
   *   variations cost ¥85 and ¥12 has no single ladder price that is right for
   *   both.
   * @param {object} settings - The user's saved settings.
   * @returns {{supplierPrice, price, moq, tierUsed, priced, source}}
   *
   * `price` is what will be stored, and equals `supplierPrice` — the two are
   * kept as separate fields so an operator-typed override in the panel can
   * replace `price` while `supplierPrice` still shows what the factory charges.
   */
  function priceProduct(draft, settings) {
    const targetQty = Number(settings.targetQty) || MLK.DEFAULTS.targetQty;

    if (draft && Number.isFinite(Number(draft.variationPrice)) && Number(draft.variationPrice) > 0) {
      const price = round2(Number(draft.variationPrice));
      return {
        supplierPrice: price,
        price,
        moq: resolveMoq(draft, targetQty),
        tierUsed: null,
        priced: true,
        source: 'variation',
      };
    }

    const tier = selectTier(draft && draft.tiers, targetQty);
    const supplierPrice = tier ? round2(tier.price) : null;

    return {
      supplierPrice,
      price: supplierPrice,
      moq: resolveMoq(draft, targetQty),
      tierUsed: tier,
      priced: supplierPrice !== null,
      source: tier ? 'tier' : 'none',
    };
  }

  /**
   * The supplier's own minimum wins when it is higher than the target — you
   * cannot order 100 of something the factory only sells in 500s.
   */
  function resolveMoq(draft, targetQty) {
    const supplierMoq = Number(draft && draft.moq) || 0;
    return Math.max(targetQty, supplierMoq);
  }

  /** Round to 2dp, matching the DECIMAL(10,2) price column. */
  function round2(value) {
    return Math.round(value * 100) / 100;
  }

  /** Format for display, or a dash when unknown. */
  function formatRmb(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
      return '—';
    }
    return '¥' + Number(value).toFixed(2);
  }

  MLK.pricing = { selectTier, priceProduct, formatRmb, round2 };
})(globalThis.MLK);

if (typeof module !== 'undefined' && module.exports) {
  module.exports = globalThis.MLK.pricing;
}
