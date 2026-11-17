/**
 * src/background/service-worker.js
 *
 * The extension's only network-capable context.
 *
 * WHY EVERY REQUEST GOES THROUGH HERE: the content script runs inside an https
 * 1688 page, and browsers block https pages from calling http://localhost as
 * mixed content. That would rule out a local Ollama entirely. The service
 * worker has its own chrome-extension:// origin, which counts as secure, so it
 * can reach localhost, the Django site, and anything else the manifest grants.
 *
 * `importScripts` (not `import`) because this is a classic worker — see the
 * note at the top of lib/namespace.js about why the whole extension avoids ES
 * modules. Load order matters: namespace first.
 */

// Paths are root-absolute ("/src/lib/…") rather than relative ("../lib/…").
// Chrome resolves importScripts in an MV3 service worker against the EXTENSION
// ROOT, not against this file's own directory, so a relative path silently
// points outside the package and the worker dies on load.
importScripts(
  '/src/lib/namespace.js',
  '/src/lib/storage.js',
  '/src/lib/taxonomy.js',
  '/src/lib/translate.js',
  '/src/lib/providers.js'
);

console.log(
  '%c[1688 Sourcing]%c service worker started (v%s)',
  'background:#0a0a0a;color:#d9a93c;padding:2px 6px;border-radius:3px',
  '',
  chrome.runtime.getManifest().version
);

const MLK = globalThis.MLK;

/**
 * Fetch the catalogue's category list from the site.
 *
 * Cached in memory for the worker's lifetime. MV3 workers are killed after ~30s
 * idle, so this is a short-lived cache that mainly avoids re-fetching during a
 * burst of scrapes — exactly the pattern of adding several products in a row.
 */
let taxonomyCache = null;

/**
 * The site's categories, preferring what is already stored.
 *
 * Order: in-memory cache, then the copy in chrome.storage, then the site. The
 * stored copy is what makes the dropdowns work with no round trip and while the
 * site is unreachable — an MV3 worker is killed after roughly thirty seconds
 * idle, so the in-memory cache alone survived about one page.
 *
 * When the site IS reached the stored copy is refreshed, so adding a category on
 * the site shows up in the panel without touching the extension.
 */
async function fetchTaxonomy(settings) {
  if (taxonomyCache && taxonomyCache.length) return taxonomyCache;

  const stored = await MLK.storage.getTaxonomy();
  if (stored.length) {
    taxonomyCache = stored;
    // Refresh in the background so the next scrape sees any change, without
    // making this one wait for the network.
    refreshTaxonomy(settings);
    return taxonomyCache;
  }

  const fresh = await refreshTaxonomy(settings);
  return fresh.length ? fresh : [];
}

/** Re-read the taxonomy from the site and store it. Never throws. */
async function refreshTaxonomy(settings) {
  if (!settings.siteUrl || !settings.apiToken) return [];
  try {
    const base = settings.siteUrl.replace(/\/+$/, '');
    const response = await fetch(`${base}/products/api/extension/ping/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${settings.apiToken}`,
      },
      body: '{}',
    });
    if (!response.ok) return [];
    const data = await response.json();
    const taxonomy = data.taxonomy || [];
    if (taxonomy.length) {
      taxonomyCache = taxonomy;
      await MLK.storage.saveTaxonomy(taxonomy);
    }
    return taxonomy;
  } catch (error) {
    // Offline or misconfigured. The stored copy stands; a missing taxonomy only
    // means the operator picks a category by hand.
    return [];
  }
}

/** Validate the configured site + token and return what the site reports. */
async function pingSite(settings) {
  const base = (settings.siteUrl || '').replace(/\/+$/, '');
  if (!base) return { ok: false, error: 'No site URL set.' };
  if (!settings.apiToken) return { ok: false, error: 'No API token set.' };

  try {
    const response = await fetch(`${base}/products/api/extension/ping/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${settings.apiToken}`,
      },
      body: '{}',
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) {
      return { ok: false, error: data.message || `Site returned ${response.status}.` };
    }
    // A successful ping means the taxonomy just came back fresh — keep it, and
    // persist it so it survives this worker being shut down.
    taxonomyCache = data.taxonomy || [];
    await MLK.storage.saveTaxonomy(taxonomyCache);
    return { ok: true, data };
  } catch (error) {
    return {
      ok: false,
      error:
        `Could not reach ${base}. Check the address, that the server is running, ` +
        `and that you granted the extension permission for that host.`,
    };
  }
}

/**
 * Create a category (or a subcategory) on the site.
 *
 * The response carries the whole refreshed taxonomy, so the in-memory cache is
 * replaced from it rather than cleared — the panel repopulates immediately
 * instead of waiting for the next ping.
 */
async function createCategory(message, settings) {
  const base = (settings.siteUrl || '').replace(/\/+$/, '');
  if (!base) return { ok: false, error: 'No site URL set in Options.' };
  if (!settings.apiToken) return { ok: false, error: 'No API token set in Options.' };

  try {
    const response = await fetch(`${base}/products/api/extension/category/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${settings.apiToken}`,
      },
      body: JSON.stringify({ name: message.name, parent: message.parent || '' }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) {
      return { ok: false, error: data.message || `Site returned ${response.status}.` };
    }
    taxonomyCache = data.taxonomy || [];
    await MLK.storage.saveTaxonomy(taxonomyCache);
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: `Could not reach ${base}: ${error.message}` };
  }
}

/**
 * Save product images to the user's Downloads folder.
 *
 * @param {object} message {urls: string[], folder: string}
 * @returns {Promise<object>} {ok, data:{saved, failed}}
 *
 * WHY THIS LIVES IN THE SERVICE WORKER
 * chrome.downloads is not exposed to content scripts, so the panel cannot call
 * it however much it would like to. The worker holds the permission, so the
 * panel asks and the worker does it.
 *
 * The URL is handed to the downloads API rather than fetched and re-encoded as
 * a blob. The API is not subject to CORS, so an alicdn image downloads without
 * the host needing to allow us — and the browser owns the transfer, so it
 * survives the panel being closed halfway through.
 */
async function downloadImages(message) {
  const urls = (message.urls || []).filter(Boolean);
  if (!urls.length) return { ok: false, error: 'No images to save.' };

  // Windows, macOS and Linux all reject some of these in a path, and Chrome
  // refuses the whole download rather than sanitising it for you.
  const folder = (message.folder || '1688-product')
    .replace(/[\\/:*?"<>|]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 60) || '1688-product';

  let saved = 0;
  let failed = 0;

  for (let i = 0; i < urls.length; i += 1) {
    const url = urls[i];
    // Keep the real extension where there is one; alicdn serves .jpg_.webp and
    // similar, so anything unrecognised falls back to .jpg rather than being
    // saved without an extension and opening in nothing.
    const match = /\.(jpe?g|png|webp|gif)/i.exec(url);
    const extension = match ? match[1].toLowerCase() : 'jpg';
    const filename = `1688 images/${folder}/${String(i + 1).padStart(2, '0')}.${extension}`;

    try {
      await new Promise((resolve, reject) => {
        chrome.downloads.download({ url, filename, conflictAction: 'uniquify' }, (id) => {
          if (chrome.runtime.lastError || id === undefined) {
            reject(new Error(chrome.runtime.lastError
              ? chrome.runtime.lastError.message : 'refused'));
          } else {
            resolve(id);
          }
        });
      });
      saved += 1;
    } catch (error) {
      // One dead URL should not abandon the rest of the set.
      failed += 1;
      console.warn('[1688 Sourcing] image download failed', url, error.message);
    }
  }

  return { ok: true, data: { saved, failed } };
}


// Per-image ceiling for what gets sent as bytes. A 1688 product photo is well
// under this; anything larger is a banner or a mistake, and sending it would
// bloat the request for a picture nobody wants at that size.
const MAX_INLINE_IMAGE_BYTES = 3 * 1024 * 1024;

// Gallery photos per product. Matches MAX_IMAGES_PER_PRODUCT in products/api.py,
// which is what the site actually enforces - sending more just wastes the
// bandwidth on images the importer discards.
const MAX_IMAGES_PER_PRODUCT = 3;

// Variation photos per product. The server accepts up to MAX_VARIANTS_PER_PRODUCT
// (100) variations; this caps how many of them travel as BYTES, which is a
// different question. A colour range runs to a dozen or so, and the rows beyond
// this keep their image_url and are picked up by `fetch_remote_images` - so the
// cap costs completeness later, never correctness now.
const MAX_VARIANT_IMAGES_PER_PRODUCT = 24;

// Total base64 one push request may carry.
//
// Django rejects a body over DATA_UPLOAD_MAX_MEMORY_SIZE (20 MB in this
// project's settings) with RequestDataTooBig, BEFORE any import code runs - so
// exceeding it does not lose one photo, it loses the entire batch of ten
// products. Variation photos made that reachable for the first time: ten
// products with a dozen variations each is over a hundred images in one request,
// where the gallery-only path could only ever be thirty.
//
// The budget is spent gallery-first (see pushToSite), so the primary product
// shots can never be crowded out by variation thumbnails. 14 MB leaves room for
// the JSON around them - names, specs, and base64's own one-third overhead is
// already counted, since what is measured below is the encoded length.
const MAX_PUSH_PAYLOAD_BYTES = 14 * 1024 * 1024;

// ---------------------------------------------------------------------------
// IMAGES: WHY THE EXTENSION FETCHES THEM AND NOT THE SITE
// ---------------------------------------------------------------------------
// The site can download image URLs itself, and often cannot. Its SSRF guard only
// permits known CDNs, a VPN can resolve every host into a private range, and
// shared hosting frequently has no outbound access at all - which is why
// fetch_remote_images exists as a retry command. Meanwhile this browser is
// already on the 1688 page with the CDN serving it happily.
//
// So the bytes are taken here and posted with the product. Nothing to fetch
// server-side means nothing to fail server-side.
//
// The service worker does it rather than the content script because the CDN is
// a different origin from the page, so a content-script fetch is subject to
// CORS; the worker has host permission for alicdn and is not.
// ---------------------------------------------------------------------------

// A catalogue photo is displayed at a few hundred pixels. Anything beyond this
// is detail nobody sees, at a cost everybody pays.
const MAX_IMAGE_EDGE_PX = 1400;
const JPEG_QUALITY = 0.85;

/**
 * Shrink an oversized photo before it is sent.
 *
 * @param {Blob} blob The downloaded image.
 * @returns {Promise<Blob>} A smaller JPEG, or the original when it is already
 *   small enough or cannot be decoded.
 *
 * WHY THIS IS NOT OPTIONAL
 *
 * The import request is JSON, so the images travel base64-encoded INSIDE the
 * request body - and Django caps a request body at DATA_UPLOAD_MAX_MEMORY_SIZE,
 * 2.5 MB by default. Base64 adds a third again on top. A handful of 2 MB
 * supplier photos therefore blows the limit and the whole batch is rejected
 * before a line of the import code runs.
 *
 * Resizing to a sane display size takes a typical listing photo from megabytes
 * to a couple of hundred kilobytes, which is what makes sending bytes at all
 * practical.
 */
async function downscale(blob) {
  // OffscreenCanvas and createImageBitmap both exist in an MV3 service worker;
  // Image and document do not, which is why this cannot use the usual approach.
  if (typeof createImageBitmap !== 'function' || typeof OffscreenCanvas !== 'function') {
    return blob;
  }

  try {
    const bitmap = await createImageBitmap(blob);
    const longest = Math.max(bitmap.width, bitmap.height);

    // Already small enough, and re-encoding would only lose quality.
    if (longest <= MAX_IMAGE_EDGE_PX && blob.size <= 400 * 1024) {
      bitmap.close();
      return blob;
    }

    const scale = Math.min(1, MAX_IMAGE_EDGE_PX / longest);
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));

    const canvas = new OffscreenCanvas(width, height);
    const context = canvas.getContext('2d');
    context.drawImage(bitmap, 0, 0, width, height);
    bitmap.close();

    const resized = await canvas.convertToBlob({ type: 'image/jpeg', quality: JPEG_QUALITY });
    // Only take it if it actually helped. A small PNG logo can come out of JPEG
    // encoding LARGER than it went in.
    return resized.size < blob.size ? resized : blob;
  } catch (error) {
    // A format the worker cannot decode still deserves to be sent as-is.
    console.warn('[1688 Sourcing] could not downscale an image:', error.message);
    return blob;
  }
}

/** Blob -> base64 payload, without the "data:...;base64," prefix. */
async function blobToBase64(blob) {
  const buffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  // Chunked: String.fromCharCode.apply with a few hundred thousand arguments
  // overflows the call stack, which is how this fails on exactly the large
  // images it most needs to handle.
  let binary = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

/**
 * Download one image and return it as a base64 payload.
 *
 * @param {string} url The image address.
 * @param {Map} cache Per-push url -> payload|null, so a photo shared by several
 *   variations (common: one shot per colour, reused across its sizes) is fetched
 *   and re-encoded once instead of once per row. Failures are cached too - a
 *   dead URL should be attempted once per push, not once per variation.
 * @returns {Promise<object|null>} `{filename, content_base64, source_url}`, or
 *   null when the image is unreachable or not worth sending.
 */
async function fetchImageAsBase64(url, cache) {
  if (cache && cache.has(url)) return cache.get(url);

  let payload = null;
  try {
    const response = await fetch(url);
    if (response.ok) {
      let blob = await response.blob();
      // A dead alicdn image is not a 404 - it is a 200 carrying a 1x1 pixel.
      // Anything this small is that placeholder, and storing it would put a
      // white dot on the product page stretched to fill the frame.
      if (blob.size >= 512 && blob.size <= MAX_INLINE_IMAGE_BYTES) {
        blob = await downscale(blob);
        const base64 = await blobToBase64(blob);
        const match = /\.(jpe?g|png|webp|gif)/i.exec(url);
        payload = {
          // Downscaling re-encodes as JPEG, so the name has to say so or the
          // site would store JPEG bytes under a .png name.
          filename: blob.type === 'image/jpeg'
            ? 'image.jpg'
            : `image.${match ? match[1].toLowerCase() : 'jpg'}`,
          content_base64: base64,
          source_url: url,
        };
      }
    }
  } catch (error) {
    // A single unreachable image must not sink the product it belongs to. The
    // URL still travels in image_urls / image_url, so the site can try for
    // itself and `fetch_remote_images` can retry later.
    console.warn('[1688 Sourcing] could not fetch image', url, error.message);
  }

  if (cache) cache.set(url, payload);
  return payload;
}


/** POST the collected list to the site's import endpoint. */
/**
 * Tell the popup how far along a push is.
 *
 * Fire and forget: when the popup has been closed there is no receiver and
 * Chrome reports "Receiving end does not exist". That is expected, not an
 * error, so it is swallowed - the push itself carries on regardless of whether
 * anyone is watching.
 */
function reportProgress(update) {
  try {
    chrome.runtime.sendMessage(Object.assign({ type: 'PUSH_PROGRESS' }, update));
  } catch (error) {
    /* no popup open */
  }
}

async function pushToSite(payload, settings) {
  const base = (settings.siteUrl || '').replace(/\/+$/, '');
  if (!base) return { ok: false, error: 'No site URL set in Options.' };
  if (!settings.apiToken) return { ok: false, error: 'No API token set in Options.' };

  // Download every photo here before posting, so the site is handed the bytes
  // rather than a list of addresses it may not be able to reach.
  //
  // TWO PASSES, GALLERY FIRST. Both passes draw on one byte budget, and the
  // request is capped rather than unbounded (see MAX_PUSH_PAYLOAD_BYTES). A
  // single interleaved loop would let one listing with forty variations spend
  // the whole budget before the ninth and tenth products got their main product
  // shot. Gallery photos are the ones the catalogue card renders, so they are
  // claimed first for every product; variation photos then take what is left.
  const products = payload.products || [];
  const cache = new Map();
  let budget = MAX_PUSH_PAYLOAD_BYTES;
  let withBytes = 0;
  let variantImages = 0;
  let variantImagesSkipped = 0;

  let outOfBudget = false;

  /**
   * Fetch one image and take it, if the budget can still afford it.
   *
   * Once a single image has been refused, nothing further is fetched for the
   * rest of this push. Photos within a batch are roughly uniform in size and the
   * budget only ever shrinks, so carrying on downloads megabytes purely to
   * discard them - a batch of ten products with 3 MB photos pulled 80 MB over
   * the network for nothing before this short-circuit existed.
   *
   * Stopping early can pass over a small image that would still have fitted.
   * That costs nothing permanent: every skipped photo keeps its URL, so the site
   * can fetch it and `fetch_remote_images` can retry it later.
   */
  const takeImage = async (url) => {
    if (outOfBudget) return null;
    const image = await fetchImageAsBase64(url, cache);
    if (!image) return null;
    if (image.content_base64.length > budget) {
      outOfBudget = true;
      return null;
    }
    budget -= image.content_base64.length;
    return image;
  };

  // Pass 1 - the product gallery.
  for (let i = 0; i < products.length; i += 1) {
    const product = products[i];
    reportProgress({
      phase: 'images',
      done: i,
      total: products.length,
      name: product.name || '',
    });

    const images = [];
    for (const url of (product.image_urls || []).slice(0, MAX_IMAGES_PER_PRODUCT)) {
      const image = await takeImage(url);
      if (image) images.push(image);
    }
    if (images.length) {
      product.images = images;
      withBytes += 1;
    }
    // image_urls is deliberately left in place. Anything that could not be
    // fetched here still has an address the site can try, and the site keeps
    // the URL as a fallback when its own download fails too.
  }

  // Pass 2 - the variation photos.
  //
  // These used to travel as URLs only, which meant a seventeen-SKU listing put
  // three pictures in the catalogue and seventeen hotlinks to alicdn. Selecting
  // a variation swaps its photo into the main image slot on the product page, so
  // those links are the product shot, not a thumbnail that degrades quietly.
  const withVariants = products.filter(
    (p) => (p.variants || []).some((v) => v.image_url)
  );
  for (let i = 0; i < withVariants.length; i += 1) {
    const product = withVariants[i];
    reportProgress({
      phase: 'variants',
      done: i,
      total: withVariants.length,
      name: product.name || '',
    });

    let taken = 0;
    for (const variant of product.variants || []) {
      if (!variant.image_url) continue;
      if (taken >= MAX_VARIANT_IMAGES_PER_PRODUCT) {
        variantImagesSkipped += 1;
        continue;
      }
      const image = await takeImage(variant.image_url);
      if (image) {
        // image_url stays alongside, same as the gallery keeps source_url: it is
        // what `fetch_remote_images` retries from if these bytes are rejected.
        variant.image = image;
        variantImages += 1;
        taken += 1;
      } else {
        variantImagesSkipped += 1;
      }
    }
  }

  reportProgress({ phase: 'uploading', done: products.length, total: products.length });
  console.log(
    `[1688 Sourcing] fetched gallery images for ${withBytes}/${products.length} product(s), ` +
    `${variantImages} variation photo(s)` +
    (variantImagesSkipped ? `, ${variantImagesSkipped} left as links` : '') +
    `; ${(budget / 1024 / 1024).toFixed(1)} MB of payload budget unused`
  );

  try {
    const response = await fetch(`${base}/products/api/extension/import/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${settings.apiToken}`,
      },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) {
      return { ok: false, error: data.message || `Site returned ${response.status}.` };
    }
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: `Could not reach ${base}: ${error.message}` };
  }
}

/**
 * Message router.
 *
 * Returning `true` keeps the message channel open for the async reply — without
 * it Chrome closes the port the moment the listener returns and the caller's
 * promise never settles.
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    try {
      const settings = await MLK.storage.getSettings();

      switch (message.type) {
        case 'ENRICH': {
          // The content script scraped a page and wants the AI pass run on it.
          const taxonomy = await fetchTaxonomy(settings);
          const outcome = await MLK.providers.runExtraction(
            message.page, taxonomy, settings
          );
          sendResponse({ ...outcome, taxonomy });
          return;
        }

        case 'PING_SITE': {
          taxonomyCache = null;   // force a fresh read when the user re-tests
          sendResponse(await pingSite(message.settings || settings));
          return;
        }

        case 'PUSH_TO_SITE': {
          sendResponse(await pushToSite(message.payload, settings));
          return;
        }

        case 'DOWNLOAD_IMAGES': {
          sendResponse(await downloadImages(message));
          return;
        }

        case 'TEST_TRANSLATION': {
          // Runs here, not in the Options page: only the service worker has the
          // host permissions that let it call the translation services
          // cross-origin.
          sendResponse(await MLK.translate.selfTest());
          return;
        }

        case 'CLEAR_TRANSLATION_CACHE': {
          await MLK.translate.clearCache();
          sendResponse({ ok: true });
          return;
        }

        case 'OPEN_LIST': {
          // The popup opened as a normal tab. A content script cannot open the
          // toolbar popup itself, and if the extension is not pinned there is
          // otherwise no way to reach the collected list at all.
          await chrome.tabs.create({
            url: chrome.runtime.getURL('src/popup/popup.html'),
          });
          sendResponse({ ok: true });
          return;
        }

        case 'CREATE_CATEGORY': {
          sendResponse(await createCategory(message, settings));
          return;
        }

        case 'GET_TAXONOMY': {
          sendResponse({ ok: true, taxonomy: await fetchTaxonomy(settings) });
          return;
        }

        default:
          sendResponse({ ok: false, error: `Unknown message type: ${message.type}` });
      }
    } catch (error) {
      sendResponse({ ok: false, error: error.message || String(error) });
    }
  })();

  return true;
});

// Settings changes invalidate the cached taxonomy: pointing the extension at a
// different site must not keep serving the previous site's categories.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.settings) {
    const before = changes.settings.oldValue || {};
    const after = changes.settings.newValue || {};
    taxonomyCache = null;
    // Only when the site itself changed. Saving an unrelated setting must not
    // throw away a taxonomy that is still correct.
    if (before.siteUrl !== after.siteUrl) {
      chrome.storage.local.remove('taxonomy');
    }
  }
});
