/**
 * src/lib/translate.js
 *
 * Chinese → English translation for product and variation names.
 *
 * WHY TWO PROVIDERS, MYMEMORY FIRST:
 *   The obvious choice is Google's public `translate_a` endpoint, and that is
 *   what this started as. It turned out to return HTTP 429 for every request
 *   from this network — persistently, across both of its endpoint variants and
 *   with browser headers — so a build that relied on it produced Chinese names
 *   and looked broken. MyMemory answers the same requests fine here, so it
 *   leads and Google is kept as a fallback for networks where the reverse is
 *   true. Neither needs an account or a key.
 *
 * THREE THINGS KEEP REQUEST COUNT DOWN, because both services rate-limit:
 *
 *   1. **Cache.** Translations are stored permanently in chrome.storage. The
 *      same variation names recur constantly across a supplier's listings, and
 *      a cached name costs nothing.
 *   2. **Batching.** All of a page's names go in ONE request, joined by
 *      newlines, which both services preserve in the reply. A five-variation
 *      page costs one request rather than six.
 *   3. **Skipping.** Text with no Chinese characters — model codes like
 *      "ST-128PlusMax", names already in English — never leaves the machine.
 *
 * Runs in the service worker: a content script on an https 1688 page is blocked
 * from calling these hosts by the page's CSP.
 */

(function (MLK) {
  'use strict';

  const CACHE_KEY = 'translationCache';
  // Enough for a long sourcing session; well under the point where the object
  // is slow to serialise on every write.
  const CACHE_LIMIT = 2000;

  /**
   * The providers, in the order they are tried.
   *
   * `translate` takes an array of strings and returns an array of the same
   * length, or null when the provider could not be used. Returning null (rather
   * than throwing) lets the caller move to the next provider quietly.
   */
  const PROVIDERS = [
    {
      name: 'MyMemory',
      // Anonymous use is capped at ~5000 characters/day, which is roughly a
      // hundred products — comfortably more than a day's sourcing.
      async translate(texts) {
        const joined = texts.join('\n');
        const url =
          'https://api.mymemory.translated.net/get?langpair=zh-CN|en&q=' +
          encodeURIComponent(joined);

        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(
            response.status === 429
              ? 'MyMemory daily limit reached'
              : `MyMemory returned ${response.status}`
          );
        }
        const data = await response.json();
        const text = data && data.responseData && data.responseData.translatedText;
        if (!text) throw new Error('MyMemory returned nothing');
        return splitBatch(text, texts.length);
      },
    },
    {
      name: 'Google',
      async translate(texts) {
        const joined = texts.join('\n');
        const url =
          'https://translate.googleapis.com/translate_a/single' +
          '?client=gtx&sl=zh-CN&tl=en&dt=t&q=' + encodeURIComponent(joined);

        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(
            response.status === 429
              ? 'Google is rate-limiting this network'
              : `Google returned ${response.status}`
          );
        }
        const data = await response.json();
        if (!Array.isArray(data) || !Array.isArray(data[0])) {
          throw new Error('Google returned an unexpected shape');
        }
        // Segments come back split; re-join, then re-split on the newlines we
        // sent so the pieces line up with the inputs again.
        const text = data[0].map((s) => (Array.isArray(s) ? s[0] : '')).join('');
        return splitBatch(text, texts.length);
      },
    },
  ];

  /**
   * Split a batched reply back into one line per input.
   *
   * Returns null when the line count does not match. That is deliberate: a
   * mismatch means the lines no longer correspond to the inputs, and silently
   * using them would attach the wrong English name to a variation — worse than
   * showing the Chinese. The caller falls back to translating one at a time.
   */
  function splitBatch(text, expected) {
    const lines = String(text).split('\n').map((line) => line.trim());
    if (lines.length !== expected) return null;
    return lines;
  }

  /** True when the string contains CJK and is therefore worth translating. */
  function needsTranslation(text) {
    return /[一-鿿]/.test(text || '');
  }

  async function readCache() {
    const stored = await chrome.storage.local.get(CACHE_KEY);
    return stored[CACHE_KEY] || {};
  }

  async function writeCache(cache) {
    const keys = Object.keys(cache);
    if (keys.length > CACHE_LIMIT) {
      // Oldest-inserted first: object key order is insertion order, so dropping
      // from the front approximates an LRU closely enough for a name cache.
      const trimmed = {};
      for (const key of keys.slice(keys.length - CACHE_LIMIT)) {
        trimmed[key] = cache[key];
      }
      cache = trimmed;
    }
    await chrome.storage.local.set({ [CACHE_KEY]: cache });
  }

  /**
   * Translate a list of strings, in order.
   *
   * @param {string[]} texts
   * @returns {Promise<{translations: string[], ok: boolean, provider: string|null,
   *                    error: string|null, fromCache: number, requested: number}>}
   *
   * Never rejects. Anything that cannot be translated comes back as the
   * original string, with `ok:false` so the caller can say so rather than
   * quietly presenting Chinese as a translation.
   */
  async function translateAll(texts) {
    const inputs = (texts || []).map((t) => (t || '').trim());
    const result = {
      translations: inputs.slice(),
      ok: true,
      provider: null,
      error: null,
      fromCache: 0,
      requested: 0,
    };
    if (inputs.length === 0) return result;

    const cache = await readCache();

    // Work out what actually needs a network call.
    const pending = [];
    const pendingIndexes = [];
    inputs.forEach((text, index) => {
      if (!text || !needsTranslation(text)) return;      // already English
      if (cache[text]) {
        result.translations[index] = cache[text];
        result.fromCache++;
        return;
      }
      pending.push(text);
      pendingIndexes.push(index);
    });

    if (pending.length === 0) {
      result.provider = result.fromCache ? 'cache' : 'none needed';
      return result;
    }
    result.requested = pending.length;

    let lastError = 'no provider available';

    for (const provider of PROVIDERS) {
      try {
        let translated = await provider.translate(pending);

        // Batch came back misaligned — retry this provider one string at a
        // time rather than risk pairing names with the wrong translations.
        if (translated === null) {
          translated = [];
          for (const text of pending) {
            const single = await provider.translate([text]);
            translated.push(single && single[0] ? single[0] : text);
          }
        }

        pendingIndexes.forEach((position, i) => {
          const value = (translated[i] || '').trim();
          if (value) {
            result.translations[position] = value;
            cache[inputs[position]] = value;
          }
        });

        await writeCache(cache);
        result.provider = provider.name;
        return result;
      } catch (error) {
        lastError = error.message || String(error);
      }
    }

    result.ok = false;
    result.error = lastError;
    return result;
  }

  /** One-off check for the Options page's "Test translation" button. */
  async function selfTest() {
    const outcome = await translateAll(['无刷吸尘器 黑金']);
    return outcome.ok
      ? { ok: true, sample: outcome.translations[0], provider: outcome.provider }
      : { ok: false, error: outcome.error };
  }

  async function clearCache() {
    await chrome.storage.local.remove(CACHE_KEY);
  }

  MLK.translate = {
    translateAll,
    selfTest,
    clearCache,
    needsTranslation,
    splitBatch,
    PROVIDERS,
  };
})(globalThis.MLK);

if (typeof module !== 'undefined' && module.exports) {
  module.exports = globalThis.MLK.translate;
}
