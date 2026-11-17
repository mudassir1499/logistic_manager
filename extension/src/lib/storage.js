/**
 * src/lib/storage.js
 *
 * Persistence for the collected product list and the user's settings.
 *
 * Everything lives in `chrome.storage.local`, which survives browser restarts
 * and is shared by all three extension contexts (content script, popup, service
 * worker). `sync` storage is deliberately not used: it has an 8KB per-item quota
 * that a list of a few dozen products with long URLs would blow past, and the
 * list is machine-local working state rather than a preference worth roaming.
 */

(function (MLK) {
  'use strict';

  const LIST_KEY = 'productList';
  const SETTINGS_KEY = 'settings';
  const TAXONOMY_KEY = 'taxonomy';

  /** Read the saved settings, with defaults filled in for anything unset. */
  async function getSettings() {
    const stored = await chrome.storage.local.get(SETTINGS_KEY);
    return Object.assign({}, MLK.DEFAULTS, stored[SETTINGS_KEY] || {});
  }

  /** Merge a partial settings update into what is already saved. */
  async function saveSettings(partial) {
    const current = await getSettings();
    const next = Object.assign({}, current, partial);
    await chrome.storage.local.set({ [SETTINGS_KEY]: next });
    return next;
  }

  /**
   * The site's categories, as last seen.
   *
   * Persisted rather than re-fetched because the service worker is killed after
   * about thirty seconds idle, so an in-memory cache survives roughly one page.
   * Every scrape was therefore a round trip to the site, and a scrape made while
   * the site was unreachable fell back to the snapshot compiled into
   * taxonomy.js — which is a photograph of the catalogue on the day this
   * extension was built and drifts further out of date with every category
   * added since.
   *
   * Stored copy wins over that snapshot; the snapshot only covers a fresh
   * install that has not yet reached the site once.
   *
   * @returns {Promise<Array>} The stored taxonomy, or [] when there is none.
   */
  async function getTaxonomy() {
    const stored = await chrome.storage.local.get(TAXONOMY_KEY);
    const value = stored[TAXONOMY_KEY];
    return Array.isArray(value) ? value : [];
  }

  /**
   * Replace the stored taxonomy.
   *
   * An empty list is ignored rather than written. A site that answers with no
   * categories — a bad token, a half-configured install, a 500 — would otherwise
   * wipe a perfectly good local copy and leave every dropdown empty.
   */
  async function saveTaxonomy(taxonomy) {
    if (!Array.isArray(taxonomy) || taxonomy.length === 0) return false;
    await chrome.storage.local.set({ [TAXONOMY_KEY]: taxonomy });
    return true;
  }

  /** The collected products, oldest first. */
  async function getList() {
    const stored = await chrome.storage.local.get(LIST_KEY);
    return stored[LIST_KEY] || [];
  }

  async function saveList(items) {
    await chrome.storage.local.set({ [LIST_KEY]: items });
    return items;
  }

  /**
   * Append a product, replacing any earlier entry for the same listing.
   *
   * Re-scraping a page the operator already added is a correction, not a second
   * product — so the entry is replaced in place rather than appended, keeping
   * its original position in the list.
   *
   * @returns {{items: Array, replaced: boolean}}
   */
  async function addItem(item) {
    const items = await getList();
    const entry = Object.assign({ addedAt: Date.now() }, item);

    const existingIndex = item.sourceUrl
      ? items.findIndex((i) => i.sourceUrl === item.sourceUrl)
      : -1;

    if (existingIndex >= 0) {
      // Keep the original addedAt so the list does not reshuffle on a re-scrape.
      entry.addedAt = items[existingIndex].addedAt;
      items[existingIndex] = entry;
      await saveList(items);
      return { items, replaced: true };
    }

    items.push(entry);
    await saveList(items);
    return { items, replaced: false };
  }

  async function removeItem(index) {
    const items = await getList();
    items.splice(index, 1);
    return saveList(items);
  }

  async function clearList() {
    return saveList([]);
  }

  /** True when this URL is already in the list — drives the button's state. */
  async function hasUrl(url) {
    if (!url) return false;
    const items = await getList();
    return items.some((i) => i.sourceUrl === url);
  }

  MLK.storage = {
    getSettings,
    saveSettings,
    getTaxonomy,
    saveTaxonomy,
    getList,
    saveList,
    addItem,
    removeItem,
    clearList,
    hasUrl,
  };
})(globalThis.MLK);
