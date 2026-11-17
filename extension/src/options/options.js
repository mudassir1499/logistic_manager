/**
 * src/options/options.js
 *
 * Settings screen.
 *
 * The one non-obvious part is host permissions. The manifest grants access to
 * the marketplace sites and localhost up front, but the user's own site can be
 * any address, so it is declared as an OPTIONAL host permission and requested
 * here. `chrome.permissions.request` only works inside a user gesture, which is
 * why it happens on the Save/Test click rather than on page load.
 */

(function (MLK) {
  'use strict';

  const FIELDS = [
    'targetQty', 'aiMode', 'siteUrl', 'apiToken',
  ];

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

  /** The explanatory note only applies when translation is switched on. */
  function syncModeFields() {
    document.getElementById('translate-note').hidden =
      document.getElementById('aiMode').value !== 'translate';
  }

  function readForm() {
    const values = {};
    for (const field of FIELDS) {
      values[field] = document.getElementById(field).value.trim();
    }
    return {
      targetQty: parseInt(values.targetQty, 10),
      aiMode: values.aiMode,
      // Trailing slashes are stripped once here so every consumer can safely
      // concatenate a path without producing a double slash.
      siteUrl: values.siteUrl.replace(/\/+$/, ''),
      apiToken: values.apiToken,
      importAsDraft: document.getElementById('importAsDraft').checked,
    };
  }

  function validate(settings) {
    if (!Number.isInteger(settings.targetQty) || settings.targetQty < 1) {
      return 'Order quantity must be at least 1.';
    }
    if (settings.siteUrl && !/^https?:\/\//i.test(settings.siteUrl)) {
      return 'Site address must start with http:// or https://.';
    }
    return null;
  }

  /**
   * Ask for permission to talk to the configured site.
   *
   * Returns true when the extension may now reach it. localhost and 127.0.0.1
   * are already in the manifest, so those short-circuit.
   */
  async function ensureSitePermission(siteUrl) {
    if (!siteUrl) return true;
    let origin;
    try {
      origin = new URL(siteUrl).origin + '/*';
    } catch (error) {
      return false;
    }

    if (await chrome.permissions.contains({ origins: [origin] })) return true;

    try {
      return await chrome.permissions.request({ origins: [origin] });
    } catch (error) {
      return false;
    }
  }

  async function save() {
    const settings = readForm();
    const error = validate(settings);
    if (error) {
      setStatus(error, 'error');
      return;
    }

    if (settings.siteUrl) {
      const granted = await ensureSitePermission(settings.siteUrl);
      if (!granted) {
        setStatus(
          'Settings not saved: permission to reach that site was declined. ' +
          'Click Save again and accept the prompt.',
          'error'
        );
        return;
      }
    }

    await MLK.storage.saveSettings(settings);
    setStatus('Settings saved.', 'ok');
  }

  async function testConnection() {
    const settings = readForm();
    if (!settings.siteUrl || !settings.apiToken) {
      setStatus('Enter both a site address and an API token first.', 'error');
      return;
    }

    const granted = await ensureSitePermission(settings.siteUrl);
    if (!granted) {
      setStatus('Permission to reach that site was declined.', 'error');
      return;
    }

    setStatus('Testing…');
    const response = await chrome.runtime.sendMessage({
      type: 'PING_SITE',
      settings,
    });

    if (!response || !response.ok) {
      setStatus((response && response.error) || 'Connection failed.', 'error');
      return;
    }

    const data = response.data;
    setStatus(
      `Connected as ${data.user}. ${data.product_count} product(s), ` +
      `${(data.taxonomy || []).length} categories.`,
      'ok'
    );
  }

  /**
   * Ask the service worker to translate one phrase and report what happened.
   *
   * These endpoints are unauthenticated and rate-limit by IP, so whether they
   * work is a property of the network at this moment rather than of the code.
   * A button that answers that in one click beats guessing from an untranslated
   * product list.
   */
  async function testTranslation() {
    setStatus('Testing translation…');
    const response = await chrome.runtime.sendMessage({ type: 'TEST_TRANSLATION' });
    if (response && response.ok) {
      setStatus(
        `Translation works via ${response.provider} — ` +
        `"无刷吸尘器 黑金" became "${response.sample}".`, 'ok');
    } else {
      setStatus(
        `Translation unavailable: ${(response && response.error) || 'unknown error'}. ` +
        `Names will stay in Chinese. Ollama or Claude mode are unaffected.`,
        'warn'
      );
    }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const settings = await MLK.storage.getSettings();
    for (const field of FIELDS) {
      const element = document.getElementById(field);
      if (element) element.value = settings[field];
    }
    document.getElementById('importAsDraft').checked = settings.importAsDraft !== false;
    syncModeFields();

    document.getElementById('aiMode').addEventListener('change', syncModeFields);
    document.getElementById('save').addEventListener('click', save);
    document.getElementById('test').addEventListener('click', testConnection);
    document.getElementById('test-translate').addEventListener('click', testTranslation);
    document.getElementById('clear-cache').addEventListener('click', async () => {
      await chrome.runtime.sendMessage({ type: 'CLEAR_TRANSLATION_CACHE' });
      setStatus('Translation cache cleared.', 'ok');
    });
  });
})(globalThis.MLK);
