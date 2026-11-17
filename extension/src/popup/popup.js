/**
 * src/popup/popup.js
 *
 * The collected-product list, its exports, and the one-click push to the site.
 *
 * Downloads are produced with a blob URL plus `chrome.downloads.download`
 * rather than an <a download> click: the popup closes the instant it loses
 * focus, which cancels an in-flight anchor download. Handing the URL to the
 * downloads API makes the browser own the transfer, so it completes regardless.
 */

(function (MLK) {
  'use strict';

  let items = [];
  /** Categories as last seen from the site; see MLK.storage.getTaxonomy. */
  let taxonomy = [];

  // ---- Rendering ----------------------------------------------------------

  function setStatus(text, kind) {
    const status = document.getElementById('status');
    if (!text) {
      status.hidden = true;
      return;
    }
    status.hidden = false;
    status.textContent = text;
    status.className = 'status' + (kind ? ' status-' + kind : '');
  }

  /**
   * Show what the site did with each product that was sent.
   *
   * @param {Array<Object>} results Per-row outcomes from the import endpoint:
   *   {name, status: 'created'|'skipped'|'error', message, existing_id,
   *    existing_name, matched_on}
   *
   * Created rows are deliberately NOT listed. They are already reflected in the
   * summary and in the list shrinking, and printing twenty "created" lines
   * buries the two that need attention.
   */
  function renderResults(results) {
    const box = document.getElementById('results');
    box.textContent = '';

    const notable = (results || []).filter((r) => r.status !== 'created');
    if (!notable.length) {
      box.hidden = true;
      return;
    }

    notable.forEach((row) => {
      const li = document.createElement('li');
      li.className = 'result result-' + (row.status || 'skipped');

      const name = document.createElement('div');
      name.className = 'result-name';
      // textContent, not innerHTML: these strings are supplier-controlled
      // product titles straight off a 1688 page.
      name.textContent = row.name || '(unnamed)';
      li.appendChild(name);

      const why = document.createElement('div');
      why.className = 'result-why';
      why.textContent = row.message || row.status;
      li.appendChild(why);

      // A name clash is the one an operator has to judge: it may be the same
      // offer, or two different listings that happen to share a title. Flag it
      // so it is not read as a settled "already imported".
      if (row.status === 'skipped' && row.matched_on === 'name') {
        const flag = document.createElement('div');
        flag.className = 'result-flag';
        flag.textContent = 'Matched on name, not on the listing URL — check this one.';
        li.appendChild(flag);
      }

      box.appendChild(li);
    });

    box.hidden = false;
  }

  function render() {
    const list = document.getElementById('list');
    const empty = document.getElementById('empty');

    document.getElementById('summary').textContent =
      `${items.length} product${items.length === 1 ? '' : 's'}`;

    empty.hidden = items.length > 0;
    list.innerHTML = '';

    items.forEach((item, index) => {
      const entry = document.createElement('li');
      entry.className = 'item';
      entry.innerHTML = `
        <div class="item-thumb">${
          item.imageUrls && item.imageUrls[0]
            ? `<img src="${item.imageUrls[0]}" alt="" loading="lazy">`
            : '<span class="no-img">—</span>'
        }</div>
        <div class="item-main">
          <div class="item-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
          <div class="item-meta">
            <span class="item-price">${MLK.pricing.formatRmb(MLK.exporters.priceOf(item))}</span>
            <span>MOQ ${item.moq}</span>
            ${item.weightKg != null ? `<span>${item.weightKg} kg</span>` : '<span class="missing">no weight</span>'}
          </div>
          <div class="item-sub">
            ${item.categorySlug ? escapeHtml(categoryLabel(item)) : '<span class="missing">uncategorised</span>'}
            ${item.variants && item.variants.length ? ` · ${item.variants.length} variations` : ''}
            ${item.attributes && item.attributes.length ? ` · ${item.attributes.length} specs` : ''}
          </div>
        </div>
        <button class="item-remove" data-index="${index}" title="Remove" type="button">×</button>
      `;
      list.appendChild(entry);
    });

    list.querySelectorAll('.item-remove').forEach((button) => {
      button.addEventListener('click', async () => {
        items = await MLK.storage.removeItem(Number(button.dataset.index));
        render();
      });
    });
  }

  /**
   * "Home & Kitchen / Kitchen" rather than "home-kitchen".
   *
   * Slugs are what get exported and imported, but they are not what a person
   * reading the list wants to see.
   */
  function categoryLabel(item) {
    // `taxonomy` is the stored copy, loaded on boot. It used to read
    // MLK.DEFAULT_TAXONOMY — the snapshot compiled into the extension — so any
    // category created on the site after this build was rendered as its raw
    // slug ("home-kitchen") in the collected list.
    const source = taxonomy.length ? taxonomy : (MLK.DEFAULT_TAXONOMY || []);
    const name = MLK.categoryName(source, item.categorySlug);
    if (!item.subcategorySlug) return name;
    return name + ' / ' +
      MLK.subcategoryName(source, item.categorySlug, item.subcategorySlug);
  }

  function escapeHtml(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ---- Downloads ----------------------------------------------------------

  function timestamp() {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return (
      now.getFullYear() +
      pad(now.getMonth() + 1) +
      pad(now.getDate()) + '-' +
      pad(now.getHours()) +
      pad(now.getMinutes())
    );
  }

  function download(filename, data, mimeType) {
    const blob = new Blob([data], { type: mimeType });
    const url = URL.createObjectURL(blob);
    chrome.downloads.download({ url, filename, saveAs: true }, () => {
      // Revoking immediately would race the download; a delayed revoke still
      // frees the blob without risking a cancelled transfer.
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    });
  }

  function requireItems() {
    if (items.length === 0) {
      setStatus('Nothing to export — the list is empty.', 'warn');
      return false;
    }
    return true;
  }

  // ---- Actions ------------------------------------------------------------

  async function exportXlsx() {
    if (!requireItems()) return;
    const bytes = MLK.exporters.buildXlsx(items);
    download(
      `1688-products-${timestamp()}.xlsx`,
      bytes,
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    );
    setStatus(`Excel file with ${items.length} product(s) saved.`, 'ok');
  }

  async function exportCsv() {
    if (!requireItems()) return;
    download(
      `1688-products-${timestamp()}.csv`,
      MLK.exporters.buildCsv(items),
      'text/csv;charset=utf-8'
    );
    setStatus(`CSV with ${items.length} product(s) saved.`, 'ok');
  }

  async function exportSql() {
    if (!requireItems()) return;
    download(
      `1688-products-${timestamp()}.sql`,
      MLK.exporters.buildSql(items),
      'application/sql;charset=utf-8'
    );
    setStatus(`SQL script with ${items.length} product(s) saved.`, 'ok');
  }

  // How many products go in one request to the site.
  //
  // The site downloads every product image server-side, up to three per product
  // with a 15-second timeout each. A single request carrying the old maximum of
  // 200 products could therefore ask one PHP/Passenger worker for over an hour
  // of downloading, and a shared host kills the request long before that. The
  // operator then saw a network error with no way to tell what had been created
  // before the axe fell.
  //
  // Ten keeps the worst case for one request to roughly 30 image fetches, which
  // finishes inside any sane server timeout.
  const PUSH_CHUNK_SIZE = 10;

  /**
   * Send the collected list to the site in small batches.
   *
   * Each batch is a separate request, and the products it created are removed
   * from the list before the next one starts. Three things follow from that,
   * and all three were broken when this was one giant request:
   *
   *   * A failure costs one batch, not the run. Everything already imported
   *     stays imported and leaves the list.
   *   * Pressing the button again RESUMES rather than starting over, because
   *     the list now holds exactly what has not been imported yet.
   *   * Progress is visible. A push of 80 products used to sit on "Sending to
   *     the site…" for minutes with no way to tell whether it was working.
   */
  /**
   * Show or hide the push progress bar.
   *
   * @param {object|null} state {phase, done, total, name}, or null to hide.
   */
  function setPushProgress(state) {
    const box = document.getElementById('pushProgress');
    const fill = document.getElementById('pushProgressFill');
    const text = document.getElementById('pushProgressText');
    if (!box) return;

    if (!state) { box.hidden = true; fill.style.width = '0'; return; }

    box.hidden = false;
    const total = state.total || 0;
    const done = Math.min(state.done || 0, total);
    fill.style.width = total ? `${Math.round((done / total) * 100)}%` : '0';

    if (state.phase === 'images') {
      text.textContent = state.name
        ? `Downloading photos ${done + 1}/${total} — ${state.name}`
        : `Downloading photos ${done}/${total}`;
    } else if (state.phase === 'variants') {
      // Named separately from 'images' because this pass can be much the longer
      // of the two - a dozen variations per product against three gallery shots -
      // and a bar that restarts with no explanation reads as a stall.
      text.textContent = state.name
        ? `Downloading variation photos ${done + 1}/${total} — ${state.name}`
        : `Downloading variation photos ${done}/${total}`;
    } else if (state.phase === 'uploading') {
      text.textContent = 'Uploading to the site…';
    } else {
      text.textContent = state.label || '';
    }
  }

  // The service worker reports progress as it goes. Registered once, at load,
  // rather than per push: adding a listener inside pushToSite would stack a new
  // one on every attempt.
  chrome.runtime.onMessage.addListener((message) => {
    if (message && message.type === 'PUSH_PROGRESS') setPushProgress(message);
  });

  async function pushToSite() {
    if (!requireItems()) return;

    const button = document.getElementById('push');
    button.disabled = true;

    const total = items.length;
    let created = 0;
    let processed = 0;
    const allResults = [];
    let failure = null;

    try {
      // Walk a FIXED snapshot of the list, not `items` itself. `items` shrinks
      // as batches succeed, and slicing a shrinking array by a moving index
      // either re-sends rows or skips them - which is exactly the bug the first
      // version of this loop had.
      const snapshot = items.slice();

      for (let start = 0; start < snapshot.length; start += PUSH_CHUNK_SIZE) {
        const batch = snapshot.slice(start, start + PUSH_CHUNK_SIZE);

        button.textContent = `Pushing ${start + 1}–${start + batch.length} of ${total}…`;
        setStatus(`Sending ${start + batch.length} of ${total} to the site…`);

        const response = await chrome.runtime.sendMessage({
          type: 'PUSH_TO_SITE',
          payload: MLK.exporters.buildImportPayload(batch),
        });

        if (!response || !response.ok) {
          failure = (response && response.error) || 'Push failed.';
          break;
        }

        const data = response.data;
        created += data.created || 0;
        processed += batch.length;
        (data.results || []).forEach((row) => allResults.push(row));

        // Remove only what the site actually created. Duplicates and errors
        // stay on the list, because those are the ones the operator still has
        // to look at - and they are never re-sent, since the loop walks the
        // snapshot rather than the list.
        const createdNames = new Set(
          (data.results || []).filter((r) => r.status === 'created').map((r) => r.name)
        );
        if (createdNames.size) {
          items = items.filter((item) => !createdNames.has(item.name));
          await MLK.storage.saveList(items);
          render();
        }
      }

      renderResults(allResults);

      if (failure) {
        setStatus(
          `${failure} ${created} product(s) were imported before this happened; ` +
          `they have been removed from the list. Press "Push to site" again to continue.`,
          'error'
        );
      } else {
        const skipped = allResults.filter((r) => r.status === 'skipped').length;
        const errored = allResults.filter((r) => r.status === 'error').length;
        let summary = `${created} product(s) imported.`;
        if (skipped) summary += ` ${skipped} already in the catalogue.`;
        if (errored) summary += ` ${errored} could not be imported.`;
        setStatus(summary, created ? 'ok' : 'warn');
      }
    } catch (error) {
      renderResults(allResults);
      setStatus(
        `Push failed: ${error.message}. ${created} product(s) were imported first.`,
        'error'
      );
    } finally {
      button.disabled = false;
      button.textContent = 'Push to site';
      // Always clear it: leaving a full bar on screen after a failure
      // reads as success.
      setPushProgress(null);
    }
  }

  async function clearList() {
    if (items.length === 0) return;
    if (!confirm(`Remove all ${items.length} product(s) from the list?`)) return;
    items = await MLK.storage.clearList();
    render();
    setStatus('List cleared.', 'ok');
  }

  // ---- Boot ---------------------------------------------------------------

  document.addEventListener('DOMContentLoaded', async () => {
    items = await MLK.storage.getList();
    taxonomy = await MLK.storage.getTaxonomy();
    render();

    document.getElementById('export-xlsx').addEventListener('click', exportXlsx);
    document.getElementById('export-csv').addEventListener('click', exportCsv);
    document.getElementById('export-sql').addEventListener('click', exportSql);
    document.getElementById('push').addEventListener('click', pushToSite);
    document.getElementById('clear').addEventListener('click', clearList);
    document.getElementById('open-options').addEventListener('click', (event) => {
      event.preventDefault();
      chrome.runtime.openOptionsPage();
    });

    const settings = await MLK.storage.getSettings();
    if (!settings.siteUrl || !settings.apiToken) {
      // Exports work without a site; only the push needs one. Say so rather
      // than letting the button fail later with a vaguer message.
      document.getElementById('push').disabled = true;
      document.getElementById('push').title =
        'Set your site address and API token in Options to enable this.';
    }
  });
})(globalThis.MLK);
