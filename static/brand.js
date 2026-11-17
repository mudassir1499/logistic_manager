/**
 * brand.js — the brand palette for anything painted to a <canvas>.
 *
 * Loaded from <head> on every page, BEFORE any chart code runs. That placement
 * is deliberate and load-bearing: the Chart.js blocks on the dashboard and the
 * reports page are inline in the middle of the document, well above the
 * bottom-of-body main.js. Defining BRAND here instead would leave it undefined
 * at the moment those blocks execute, and every chart on both pages would fail
 * with a ReferenceError. Keep this file in <head>.
 *
 * Chart.js paints to a canvas and cannot read CSS custom properties, so these
 * values are literals that mirror the tokens in style.css / portal.css. If a
 * token changes there, change it here too.
 */

var BRAND = {
    /**
     * Categorical series colours.
     *
     * THE ORDER IS FIXED AND MUST NOT BE CYCLED OR REORDERED. Slots are assigned
     * in sequence — one series takes slot 0, two series take 0 and 1, and so on.
     * That fixed order is the mechanism that keeps neighbouring series apart for
     * colour-blind readers; it was picked by validating every candidate ordering,
     * not by eye. This set scores:
     *
     *   worst adjacent CVD ΔE 13.0   (protanopia/deuteranopia, target >= 8)
     *   worst adjacent normal ΔE 28.4 (floor >= 15)
     *   all six slots >= 3:1 contrast on a white card
     *
     * Slot 0 is the gold of the logo's star mark, so a single-series chart — the
     * common case here — comes out on-brand with no extra thought.
     *
     * Two cautions:
     *  - Slots 0 and 2 (gold and orange) are only safe as NEIGHBOURS. Where any
     *    two marks can sit side by side (scatter, bubble, small multiples) the
     *    safe set is at most four: 0, 1, 3, 4.
     *  - A 7th series is never a newly invented hue. Fold the tail into "Other"
     *    or facet the chart; a generated 7th would break the guarantees above.
     */
    series: [
        '#B08421',  // 0 gold — brand, the star mark
        '#2a78d6',  // 1 blue
        '#eb6834',  // 2 orange
        '#4a3aa7',  // 3 violet
        '#d55181',  // 4 magenta
        '#008300'   // 5 green
    ],

    /**
     * Slice colours for PIE and DOUGHNUT charts — a different order to `series`,
     * for a specific reason.
     *
     * In a bar or line chart only neighbouring series touch, so `series` only has
     * to hold up pair-by-pair along its order. In a pie every slice can touch
     * every other, which is a strictly harder test — and `series` fails it: its
     * gold and orange sit at ΔE 3.3 under protanopia, indistinguishable when
     * they meet. This order drops orange out of the head and is verified with
     * ALL pairs in play:
     *
     *   first four slices: worst all-pairs CVD ΔE 10.6, normal-vision 16.3 — pass
     *   full six:          worst adjacent CVD ΔE 13.0 — pass
     *
     * So: up to four slices are safe unconditionally. Past four, no ordering of
     * these hues can clear the all-pairs floor — that is a property of the
     * palette, not of this order — and the chart leans on its legend and the 2px
     * gap between slices to carry identity. If you find yourself with more than
     * four, the better fix is to fold the tail into an "Other" slice.
     */
    slices: [
        '#B08421',  // gold — brand
        '#2a78d6',  // blue
        '#4a3aa7',  // violet
        '#d55181',  // magenta
        '#008300',  // green
        '#1baf7a'   // aqua
    ],

    /**
     * Status colours. Reserved meaning — never reuse one of these as "series 4",
     * and never give a plain series a status colour. Always pair with a label.
     */
    success: '#157F4A',
    danger: '#B3261E',
    warning: '#C2410C',
    info: '#44546A',

    /** Chart chrome — mirrors the ink/neutral tokens in the stylesheets. */
    ink: '#0A0A0A',
    text: '#3F3F42',
    muted: '#6A6A6C',
    border: '#DFE1E6',
    surface: '#FFFFFF',
    grid: 'rgba(10,10,10,0.06)'
};
