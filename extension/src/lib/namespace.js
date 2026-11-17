/**
 * src/lib/namespace.js
 *
 * Every other file in this extension hangs its exports off the single global
 * created here.
 *
 * WHY NOT ES MODULES: Manifest V3 content scripts cannot be ES modules — the
 * `js` array in the manifest loads plain scripts into a shared isolated world.
 * Using `import` would work in the popup and service worker but not in the
 * content script, so the extension would need two module systems. One global
 * namespace works identically in all three contexts, including under the
 * service worker's `importScripts()`.
 *
 * Load order matters: this file must come first in every `js` array and every
 * `importScripts` call.
 */

// globalThis rather than window: the service worker has no `window`.
globalThis.MLK = globalThis.MLK || {};

/** Extension-wide defaults, overridden by whatever the user saves in Options. */
globalThis.MLK.DEFAULTS = {
  // Which price tier to read. 1688 quotes cheaper unit prices at higher
  // quantities; this catalogue sells at 100 pieces, so that is the tier that
  // matters and the MOQ the product is created with.
  //
  // There is deliberately NO markup setting: the extension reports the
  // supplier's price and the selling price is set by hand. See pricing.js.
  targetQty: 100,

  // 'translate' — translate product and variation names into English.
  // 'none'      — no enrichment; names stay in Chinese.
  //
  // The 'ollama' and 'server' (Claude) modes are still implemented in
  // providers.js but are no longer offered in Options — see that file's header.
  aiMode: 'translate',

  ollamaUrl: 'http://localhost:11434',
  // qwen2.5 is the default because it handles Chinese notably better than
  // similarly sized Western-tuned models, which matters for every field here.
  ollamaModel: 'qwen2.5:7b',

  siteUrl: '',
  apiToken: '',

  // Products are created as drafts by default so a bad scrape never appears in
  // the customer-facing catalogue before someone has looked at it.
  importAsDraft: true,
};
