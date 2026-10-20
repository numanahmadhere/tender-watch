/**
 * TenderWatch webhook. Bound to the Google Sheet that should hold the results.
 *
 * The GitHub Action POSTs one JSON payload per day. This script:
 *   1. checks a shared secret (script property TW_TOKEN),
 *   2. upserts rows into the "Tenders" and "Awards" tabs (keyed by UID),
 *   3. appends a line to the "Runs" tab,
 *   4. emails the digest to TW_RECIPIENT (falls back to the account that owns the script).
 *
 * Setup: see README.md. Script properties needed: TW_TOKEN, TW_RECIPIENT.
 */

function doGet() {
  return ContentService.createTextOutput('TenderWatch webhook is up');
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const body = JSON.parse(e.postData.contents);
    const token = PropertiesService.getScriptProperties().getProperty('TW_TOKEN');
    if (!token || body.token !== token) {
      return out_({ ok: false, error: 'unauthorized' });
    }
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const result = {};
    result.tenders = upsert_(ss, 'Tenders', body.columns, body.tenders || [], body.dateColumns || []);
    result.awards = upsert_(ss, 'Awards', body.columns, body.awards || [], body.dateColumns || []);
    logRun_(ss, body.run || {}, body.sources || []);
    if (body.email) {
      sendDigest_(body.email);
      result.emailed = true;
    }
    return out_({ ok: true, result: result });
  } catch (err) {
    return out_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function toDate_(v) {
  if (!v) return '';
  const s = String(v);
  const d = new Date(s.length === 10 ? s + 'T00:00:00' : s + ':00');
  return isNaN(d.getTime()) ? s : d;
}

function upsert_(ss, name, columns, rows, dateColumns) {
  if (!rows.length) return { added: 0, updated: 0 };
  let sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name);
  if (sh.getLastRow() === 0) {
    sh.getRange(1, 1, 1, columns.length).setValues([columns])
      .setFontWeight('bold').setBackground('#0b1f3a').setFontColor('#ffffff');
    sh.setFrozenRows(1);
  } else {
    const header = sh.getRange(1, 1, 1, columns.length).getValues()[0];
    if (header.join('|') !== columns.join('|')) {
      throw new Error('Header of tab "' + name + '" does not match the columns sent by the pipeline');
    }
  }

  const uidIdx = columns.indexOf('UID');
  const firstSeenIdx = columns.indexOf('First seen');
  const dateIdx = dateColumns.map(function (c) { return columns.indexOf(c); }).filter(function (i) { return i >= 0; });

  const lastRow = sh.getLastRow();
  const existing = lastRow > 1 ? sh.getRange(2, 1, lastRow - 1, columns.length).getValues() : [];
  const index = {};
  existing.forEach(function (r, i) { index[r[uidIdx]] = i; });

  let added = 0, updated = 0;
  const append = [];
  rows.forEach(function (row) {
    const r = row.map(function (v, i) { return dateIdx.indexOf(i) >= 0 ? toDate_(v) : v; });
    const key = r[uidIdx];
    if (Object.prototype.hasOwnProperty.call(index, key)) {
      const old = existing[index[key]];
      if (firstSeenIdx >= 0 && old[firstSeenIdx]) r[firstSeenIdx] = old[firstSeenIdx]; // keep original first seen
      existing[index[key]] = r;
      updated++;
    } else {
      append.push(r);
      added++;
    }
  });
  if (existing.length) sh.getRange(2, 1, existing.length, columns.length).setValues(existing);
  if (append.length) sh.getRange(sh.getLastRow() + 1, 1, append.length, columns.length).setValues(append);

  const total = sh.getLastRow() - 1;
  dateIdx.forEach(function (i) { sh.getRange(2, i + 1, total, 1).setNumberFormat('yyyy-mm-dd'); });

  // "Days left" is a live formula so it stays correct between runs.
  const daysIdx = columns.indexOf('Days left');
  const deadlineIdx = columns.indexOf('Deadline');
  if (daysIdx >= 0 && deadlineIdx >= 0 && total > 0) {
    const col = sh.getRange(1, deadlineIdx + 1).getA1Notation().replace(/\d+/g, '');
    const formulas = [];
    for (let r = 2; r <= total + 1; r++) formulas.push(['=IF(' + col + r + '="","",INT(' + col + r + ')-TODAY())']);
    sh.getRange(2, daysIdx + 1, total, 1).setFormulas(formulas);
    if (sh.getConditionalFormatRules().length === 0) {
      const range = sh.getRange(2, daysIdx + 1, 2000, 1);
      sh.setConditionalFormatRules([
        SpreadsheetApp.newConditionalFormatRule().whenNumberBetween(0, 3).setBackground('#f8c9c4').setRanges([range]).build(),
        SpreadsheetApp.newConditionalFormatRule().whenNumberBetween(4, 7).setBackground('#fde9b8').setRanges([range]).build()
      ]);
    }
  }

  if (!sh.getFilter()) sh.getRange(1, 1, Math.max(sh.getLastRow(), 2), columns.length).createFilter();
  const titleIdx = columns.indexOf('Title');
  if (titleIdx >= 0) sh.setColumnWidth(titleIdx + 1, 460);
  return { added: added, updated: updated };
}

function logRun_(ss, run, sources) {
  let sh = ss.getSheetByName('Runs');
  if (!sh) {
    sh = ss.insertSheet('Runs');
    sh.getRange(1, 1, 1, 6).setValues([['Date', 'New', 'Updated', 'Closing soon', 'Sources OK', 'Source notes']])
      .setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  const notes = sources
    .filter(function (s) { return s.status !== 'ok'; })
    .map(function (s) { return s.name + ': ' + s.status + (s.message ? ' (' + s.message + ')' : ''); })
    .join('; ');
  sh.appendRow([run.date || '', run.new || 0, run.updated || 0, run.closing_soon || 0, run.sources_ok || 0, notes]);
}

function sendDigest_(email) {
  const props = PropertiesService.getScriptProperties();
  const to = props.getProperty('TW_RECIPIENT') || Session.getEffectiveUser().getEmail();
  MailApp.sendEmail({ to: to, subject: email.subject, body: email.text, htmlBody: email.html, name: 'TenderWatch' });
}
