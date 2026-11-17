/**
 * src/lib/exporters.js
 *
 * Turns the collected product list into the three file formats the operator
 * asked for: SQL, Excel, and CSV.
 *
 * The CSV and Excel column order is not arbitrary — it matches exactly what
 * `products/views.py::_parse_upload_rows` expects:
 *
 *     name, image, price, moq, weight,
 *     carton_length, carton_width, carton_height, carton_qty
 *
 * so a file exported here drops straight into the existing Bulk Upload screen
 * with no reshaping. The XLSX path in that parser reads only the first nine
 * columns, which is why nothing extra is appended to the right of carton_qty.
 */

(function (MLK) {
  'use strict';

  // The columns the site's bulk importer reads, in its order.
  //
  // `category` and `subcategory` are appended after the original nine. They
  // carry SLUGS, not display names — the importer resolves them against
  // products_category.slug, and a slug is stable where a display name is not.
  // Without these two the whole point of assigning a category in the panel was
  // lost the moment you exported: the columns simply were not in the file.
  const BULK_COLUMNS = [
    'name', 'image', 'price', 'moq', 'weight',
    'carton_length', 'carton_width', 'carton_height', 'carton_qty',
    'category', 'subcategory', 'source_url', 'variant_of',
  ];

  /**
   * The price to store for an item.
   *
   * `finalPrice` is read as a fallback so a list collected by an earlier build —
   * back when a markup was added and the result lived in `finalPrice` — still
   * exports instead of silently becoming a column of blanks.
   */
  function priceOf(item) {
    const value = item.price != null ? item.price : item.finalPrice;
    return value == null ? null : Number(value);
  }

  /**
   * Flatten a stored list item into the nine bulk-upload columns.
   *
   * `image` carries the first image URL. The site's 1688 CSV importer downloads
   * from that column; the generic bulk importer ignores it and matches images by
   * filename instead, so including it is useful in one path and harmless in the
   * other.
   */
  function toBulkRow(item) {
    return [
      item.name || '',
      (item.imageUrls && item.imageUrls[0]) || '',
      priceOf(item),
      item.moq,
      item.weightKg,
      null,       // carton_length — 1688 listings rarely publish carton dimensions
      null,       // carton_width
      null,       // carton_height
      item.cartonQty,
      item.categorySlug || '',
      item.subcategorySlug || '',
      // The listing this came from. Saved so the buyer can message the supplier
      // months later without re-finding a product whose Chinese name nobody
      // kept. Staff-only — the site never shows it to customers.
      supplierUrl(item),
      '',   // variant_of — blank on a parent row
    ];
  }

  /**
   * Flatten the list into spreadsheet rows: each product, then a row per variation.
   *
   * A CSV cannot nest, so variations are expressed by convention instead: a row
   * whose `variant_of` names an earlier row is imported as a variation OF that
   * row rather than as a product of its own. `products/views.py::bulk_upload`
   * reads it. An importer that does not understand the column ignores it and
   * gets the old behaviour — a flat list of products — rather than an error.
   *
   * Variation rows carry only what differs: name, price and photo. Weight, carton
   * dimensions and category belong to the parent item, not to the colour.
   */
  function expandRows(items) {
    const rows = [];
    for (const item of items) {
      rows.push(toBulkRow(item));
      for (const variant of item.variants || []) {
        rows.push([
          variant.name || '',
          variant.imageUrl || '',
          variant.price,
          item.moq,
          null, null, null, null, null,   // weight + carton dims inherit from the parent
          '', '',                          // category/subcategory inherit too
          supplierUrl(item),
          item.name,                       // variant_of -> the parent row's name
        ]);
      }
    }
    return rows;
  }

  /**
   * The supplier listing URL for an item.
   *
   * Variations carry a '#<variation name>' fragment on sourceUrl so each one is
   * a distinct entry in the collected list. The fragment is stripped here: what
   * gets stored is the page a person should open, and every variation of a
   * listing shares one page.
   */
  function supplierUrl(item) {
    const url = item.supplierUrl || item.variationOf || item.sourceUrl || '';
    return url.split('#')[0];
  }

  // ---- CSV ----------------------------------------------------------------

  /**
   * Quote one CSV field per RFC 4180.
   *
   * Fields are quoted whenever they contain a comma, quote, or newline, and
   * embedded quotes are doubled.
   */
  function csvField(value) {
    if (value === null || value === undefined) return '';
    const text = String(value);
    if (/[",\r\n]/.test(text)) {
      return '"' + text.replace(/"/g, '""') + '"';
    }
    return text;
  }

  function buildCsv(items) {
    const lines = [BULK_COLUMNS.join(',')];
    for (const row of expandRows(items)) {
      lines.push(row.map(csvField).join(','));
    }
    // A UTF-8 BOM so Excel on Windows opens the file as UTF-8 rather than
    // guessing the system codepage and mangling any Chinese text.
    return '﻿' + lines.join('\r\n') + '\r\n';
  }

  // ---- Excel --------------------------------------------------------------

  function buildXlsx(items) {
    return MLK.xlsx.buildWorkbook(BULK_COLUMNS, expandRows(items), 'Products');
  }

  // ---- SQL ----------------------------------------------------------------

  /**
   * Escape a string for a MySQL/MariaDB single-quoted literal.
   *
   * Backslash is escaped first — doing it after the quote replacement would
   * also escape the backslashes that replacement just introduced.
   */
  function sqlString(value) {
    if (value === null || value === undefined || value === '') return 'NULL';
    const escaped = String(value)
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "\\'")
      .replace(/\n/g, '\\n')
      .replace(/\r/g, '\\r')
      .replace(/\x1a/g, '\\Z');   // Ctrl+Z terminates input on Windows mysql clients
    return "'" + escaped + "'";
  }

  /** Render a number for SQL, or NULL when it is absent or unusable. */
  function sqlNumber(value) {
    if (value === null || value === undefined || value === '') return 'NULL';
    const number = Number(value);
    return Number.isFinite(number) ? String(number) : 'NULL';
  }

  /**
   * Build an SQL script that inserts the collected products.
   *
   * Design notes:
   *   - Categories are resolved with a scalar subquery on `slug` rather than a
   *     hard-coded id, because ids differ between the local and production
   *     databases and a script with baked-in ids would silently mis-file
   *     products on the other one.
   *   - `INSERT ... SELECT ... WHERE NOT EXISTS` makes the script safe to run
   *     twice: a product whose name is already present is skipped instead of
   *     duplicated, matching how every other import path in this project
   *     behaves.
   *   - Images are listed as comments only. They live in MEDIA_ROOT as files,
   *     so a plain INSERT cannot create them — use the Excel/CSV import or the
   *     "Push to site" button when the images matter.
   */
  function buildSql(items) {
    const stamp = new Date().toISOString();
    const lines = [
      '-- Product import generated by the 1688 Sourcing extension',
      `-- Generated: ${stamp}`,
      `-- Products: ${items.length}`,
      '--',
      '-- Safe to run more than once: each statement skips a product whose name',
      '-- already exists. Review before running against production.',
      '--',
      '-- NOTE: product images cannot be created by SQL (they are files in',
      '-- MEDIA_ROOT). Use the Excel/CSV import or "Push to site" to bring',
      '-- images across. Source image URLs are listed in comments below.',
      '',
      'START TRANSACTION;',
      '',
    ];

    for (const item of items) {
      const categorySql = item.categorySlug
        ? `(SELECT id FROM products_category WHERE slug = ${sqlString(item.categorySlug)} LIMIT 1)`
        : 'NULL';
      const subcategorySql = item.subcategorySlug
        ? `(SELECT id FROM products_subcategory WHERE slug = ${sqlString(item.subcategorySlug)} LIMIT 1)`
        : 'NULL';

      lines.push(`-- ${item.name}`);
      if (item.sourceUrl) lines.push(`--   source: ${item.sourceUrl}`);
      for (const url of item.imageUrls || []) {
        lines.push(`--   image:  ${url}`);
      }
      lines.push(
        'INSERT INTO products_product',
        '    (name, price, moq, weight, carton_length, carton_width, carton_height,',
        '     carton_qty, price_air, price_sea, is_draft, is_private, sku, source,',
        '     source_url, ready_to_ship, category_id, subcategory_id)',
        'SELECT',
        `    ${sqlString(item.name)}, ${sqlNumber(priceOf(item))}, ${sqlNumber(item.moq)},`,
        `    ${sqlNumber(item.weightKg)}, NULL, NULL, NULL,`,
        `    ${sqlNumber(item.cartonQty)}, NULL, NULL, ${item.isDraft ? 1 : 0}, 0,`,
        `    ${sqlString(item.sku || '')}, ${sqlString(item.source || 'general')},`,
        `    ${sqlString(supplierUrl(item))}, 0, ${categorySql}, ${subcategorySql}`,
        'FROM DUAL',
        'WHERE NOT EXISTS (',
        `    SELECT 1 FROM products_product WHERE LOWER(name) = LOWER(${sqlString(item.name)})`,
        ');',
        ''
      );
    }

    lines.push('COMMIT;', '');
    return lines.join('\n');
  }

  // ---- Payload for the "Push to site" button -------------------------------

  /** Shape the list the way `products/api.py::extension_import` expects. */
  function buildImportPayload(items) {
    return {
      products: items.map((item) => ({
        name: item.name,
        price: priceOf(item),
        moq: item.moq,
        weight: item.weightKg,
        carton_qty: item.cartonQty,
        carton_length: item.cartonCm ? item.cartonCm.length : null,
        carton_width: item.cartonCm ? item.cartonCm.width : null,
        carton_height: item.cartonCm ? item.cartonCm.height : null,
        sku: item.sku || '',
        source: item.source || 'general',
        category_slug: item.categorySlug || null,
        subcategory_slug: item.subcategorySlug || null,
        image_urls: item.imageUrls || [],
        source_url: supplierUrl(item),
        is_draft: !!item.isDraft,
        // The specification table, which becomes the product's Specifications on
        // the site and its `additionalProperty` structured data.
        attributes: (item.attributes || []).map((attr) => ({
          name: attr.name,
          value: attr.value,
        })),
        // The listing's SKUs. The server turns these into ProductVariant rows
        // under the one product instead of separate catalogue entries.
        variants: (item.variants || []).map((variant) => ({
          name: variant.name,
          price: variant.price,
          stock: variant.stock,
          image_url: variant.imageUrl || '',
        })),
      })),
    };
  }

  MLK.exporters = {
    BULK_COLUMNS,
    toBulkRow,
    expandRows,
    buildCsv,
    buildXlsx,
    buildSql,
    buildImportPayload,
    priceOf,
    supplierUrl,
    sqlString,
    sqlNumber,
  };
})(globalThis.MLK);

if (typeof module !== 'undefined' && module.exports) {
  module.exports = globalThis.MLK.exporters;
}
