/**
 * src/lib/xlsx.js
 *
 * A minimal .xlsx writer with no dependencies.
 *
 * WHY HAND-ROLLED: a real .xlsx is a ZIP of XML parts. The usual answer is to
 * bundle SheetJS, but that is ~900KB of third-party code inside an extension
 * that would then need reviewing and updating — for a feature that writes one
 * flat sheet of strings and numbers. The subset needed here is small enough to
 * own outright.
 *
 * TWO SIMPLIFICATIONS make it small:
 *   1. **STORE, not DEFLATE.** The ZIP spec allows storing entries uncompressed
 *      (method 0), and Excel accepts that happily. It removes any need for a
 *      compression implementation. A few hundred product rows is tens of KB.
 *   2. **Inline strings, not a shared string table.** Cells carry their own text
 *      via `t="inlineStr"`, so there is no sharedStrings.xml to build or index.
 *
 * The output opens in Excel, LibreOffice, Google Sheets, and openpyxl — the last
 * of which is how it is tested (see the note in the project README).
 */

(function (MLK) {
  'use strict';

  // ---- CRC-32 -------------------------------------------------------------
  // Required by the ZIP format for every entry. Standard table-driven
  // implementation with the reversed polynomial 0xEDB88320.

  let crcTable = null;

  function buildCrcTable() {
    const table = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) {
        c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      }
      table[n] = c >>> 0;
    }
    return table;
  }

  function crc32(bytes) {
    if (!crcTable) crcTable = buildCrcTable();
    let crc = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) {
      crc = crcTable[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
    }
    return (crc ^ 0xffffffff) >>> 0;
  }

  // ---- ZIP container ------------------------------------------------------

  const encoder = new TextEncoder();

  /**
   * Pack named byte arrays into an uncompressed ZIP archive.
   *
   * @param {Array<{name:string, data:Uint8Array}>} files
   * @returns {Uint8Array} The complete archive.
   */
  function zipStore(files) {
    const chunks = [];
    const central = [];
    let offset = 0;

    // A fixed DOS timestamp (1980-01-01 00:00). Real clock values would make
    // otherwise-identical exports differ byte-for-byte, and nothing downstream
    // reads the mtime.
    const dosTime = 0;
    const dosDate = 33; // (1980-1980)<<9 | 1<<5 | 1

    for (const file of files) {
      const nameBytes = encoder.encode(file.name);
      const crc = crc32(file.data);
      const size = file.data.length;

      const local = new Uint8Array(30 + nameBytes.length);
      const lv = new DataView(local.buffer);
      lv.setUint32(0, 0x04034b50, true);   // local file header signature
      lv.setUint16(4, 20, true);           // version needed to extract (2.0)
      lv.setUint16(6, 0x0800, true);       // flags: bit 11 = names/content are UTF-8
      lv.setUint16(8, 0, true);            // compression method: 0 = stored
      lv.setUint16(10, dosTime, true);
      lv.setUint16(12, dosDate, true);
      lv.setUint32(14, crc, true);
      lv.setUint32(18, size, true);        // compressed size (== uncompressed when stored)
      lv.setUint32(22, size, true);        // uncompressed size
      lv.setUint16(26, nameBytes.length, true);
      lv.setUint16(28, 0, true);           // extra field length
      local.set(nameBytes, 30);

      chunks.push(local, file.data);

      const centralEntry = new Uint8Array(46 + nameBytes.length);
      const cv = new DataView(centralEntry.buffer);
      cv.setUint32(0, 0x02014b50, true);   // central directory header signature
      cv.setUint16(4, 20, true);           // version made by
      cv.setUint16(6, 20, true);           // version needed
      cv.setUint16(8, 0x0800, true);
      cv.setUint16(10, 0, true);
      cv.setUint16(12, dosTime, true);
      cv.setUint16(14, dosDate, true);
      cv.setUint32(16, crc, true);
      cv.setUint32(20, size, true);
      cv.setUint32(24, size, true);
      cv.setUint16(28, nameBytes.length, true);
      cv.setUint16(30, 0, true);           // extra length
      cv.setUint16(32, 0, true);           // comment length
      cv.setUint16(34, 0, true);           // disk number start
      cv.setUint16(36, 0, true);           // internal attributes
      cv.setUint32(38, 0, true);           // external attributes
      cv.setUint32(42, offset, true);      // offset of this entry's local header
      centralEntry.set(nameBytes, 46);
      central.push(centralEntry);

      offset += local.length + size;
    }

    const centralSize = central.reduce((sum, c) => sum + c.length, 0);
    const end = new Uint8Array(22);
    const ev = new DataView(end.buffer);
    ev.setUint32(0, 0x06054b50, true);     // end of central directory signature
    ev.setUint16(4, 0, true);              // this disk number
    ev.setUint16(6, 0, true);              // disk with central directory
    ev.setUint16(8, files.length, true);   // entries on this disk
    ev.setUint16(10, files.length, true);  // total entries
    ev.setUint32(12, centralSize, true);
    ev.setUint32(16, offset, true);        // central directory offset
    ev.setUint16(20, 0, true);             // comment length

    const total =
      chunks.reduce((sum, c) => sum + c.length, 0) + centralSize + end.length;
    const out = new Uint8Array(total);
    let position = 0;
    for (const chunk of chunks) {
      out.set(chunk, position);
      position += chunk.length;
    }
    for (const chunk of central) {
      out.set(chunk, position);
      position += chunk.length;
    }
    out.set(end, position);
    return out;
  }

  // ---- Sheet XML ----------------------------------------------------------

  /** Escape the five characters that are not legal as XML text. */
  function escapeXml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&apos;')
      // Control characters are illegal in XML 1.0 even when escaped, and
      // scraped supplier text occasionally contains them.
      .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '');
  }

  /** Convert a 0-based column index to a spreadsheet letter (0→A, 26→AA). */
  function columnLetter(index) {
    let letter = '';
    let n = index;
    do {
      letter = String.fromCharCode(65 + (n % 26)) + letter;
      n = Math.floor(n / 26) - 1;
    } while (n >= 0);
    return letter;
  }

  /**
   * Render one cell.
   *
   * Numbers are written bare (`<v>`), which is what makes Excel treat them as
   * numeric and lets the importer parse them without stripping formatting.
   * Everything else becomes an inline string.
   */
  function cellXml(reference, value) {
    if (value === null || value === undefined || value === '') {
      return `<c r="${reference}"/>`;
    }
    if (typeof value === 'number' && Number.isFinite(value)) {
      return `<c r="${reference}"><v>${value}</v></c>`;
    }
    return `<c r="${reference}" t="inlineStr"><is><t xml:space="preserve">${escapeXml(value)}</t></is></c>`;
  }

  /**
   * Build a single-sheet workbook.
   *
   * @param {string[]} headers - Column headings for row 1.
   * @param {Array<Array<string|number|null>>} rows - Data rows.
   * @param {string} sheetName - Worksheet tab name.
   * @returns {Uint8Array} The .xlsx file bytes.
   */
  function buildWorkbook(headers, rows, sheetName) {
    const allRows = [headers].concat(rows);
    const rowsXml = allRows
      .map((row, rowIndex) => {
        const cells = row
          .map((value, colIndex) =>
            cellXml(columnLetter(colIndex) + (rowIndex + 1), value)
          )
          .join('');
        return `<row r="${rowIndex + 1}">${cells}</row>`;
      })
      .join('');

    const sheet =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
      `<sheetData>${rowsXml}</sheetData>` +
      '</worksheet>';

    const contentTypes =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
      '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
      '</Types>';

    const rootRels =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
      '</Relationships>';

    const workbook =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
      `<sheets><sheet name="${escapeXml((sheetName || 'Products').slice(0, 31))}" sheetId="1" r:id="rId1"/></sheets>` +
      '</workbook>';

    const workbookRels =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
      '</Relationships>';

    return zipStore([
      { name: '[Content_Types].xml', data: encoder.encode(contentTypes) },
      { name: '_rels/.rels', data: encoder.encode(rootRels) },
      { name: 'xl/workbook.xml', data: encoder.encode(workbook) },
      { name: 'xl/_rels/workbook.xml.rels', data: encoder.encode(workbookRels) },
      { name: 'xl/worksheets/sheet1.xml', data: encoder.encode(sheet) },
    ]);
  }

  MLK.xlsx = { buildWorkbook, columnLetter, escapeXml, crc32, zipStore };
})(globalThis.MLK);

// Lets the same file be require()d by the Node test that validates the output
// against openpyxl. Harmless in the browser, where `module` is undefined.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = globalThis.MLK.xlsx;
}
