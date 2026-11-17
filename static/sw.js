/* Service worker for the back-office app.
 *
 * THE ONE RULE THAT SHAPES ALL OF THIS
 *
 * This runs on a STAFF site behind a login. A service worker cache is stored on
 * the device and survives logout, so anything cached here is readable by
 * whoever next picks up the phone — including a different member of staff on a
 * shared warehouse handset.
 *
 * Therefore: static assets are cached, and NOTHING ELSE. No HTML, no API
 * responses, no images from /media/. A cached order list is a customer list
 * sitting on an unlocked device, and an offline order list is not worth that.
 *
 * What the worker actually buys is:
 *   - the app opens instantly, because CSS/JS/fonts come off the device
 *   - it is installable, which is what makes it an app on the home screen
 *   - a real offline page instead of the browser's dinosaur
 */

const VERSION = 'mlk-admin-v1';
const SHELL_CACHE = `${VERSION}-shell`;
const OFFLINE_URL = '/static/offline.html';

/* Only files that are identical for every user. Note what is missing: no page
 * URLs, because every page on this site is user-specific. */
const SHELL_ASSETS = [
  OFFLINE_URL,
  '/static/style.css',
  '/static/main.js',
  '/static/images/icon-192.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      // addAll rejects the whole install if ANY file 404s, which would leave the
      // worker permanently uninstalled. Cached individually so one renamed asset
      // cannot take the app offline.
      .then((cache) => Promise.all(
        SHELL_ASSETS.map((url) => cache.add(url).catch(() => null)),
      ))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => !key.startsWith(VERSION))
            .map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Only GET. A POST that got served from cache would silently drop somebody's
  // edit, and a cached response to a login attempt is worse still.
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Never touch another origin.
  if (url.origin !== self.location.origin) return;

  // --- static assets: cache first -----------------------------------------
  // Safe because these are identical for every user and carry no data.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })),
    );
    return;
  }

  // --- everything else: network only --------------------------------------
  // Pages, API calls and /media/ all fall here. They are fetched live or they
  // fail; the only thing added is a readable offline page for navigations
  // rather than the browser's error screen.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => caches.match(OFFLINE_URL)),
    );
  }
});
