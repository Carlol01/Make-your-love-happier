/* Parser locali (nessun dato lascia il browser). Porting semplificato di
 * cycle_notifier/sources/_tolerant.py: stesso approccio "tollerante", best-effort. */
(function (root) {
  "use strict";

  var START_KEYS = ["start", "start_date", "startdate", "period_start", "period_start_date", "periodstart", "begin", "inizio", "data_inizio", "from"];
  var END_KEYS = ["end", "end_date", "enddate", "period_end", "period_end_date", "periodend", "fine", "data_fine", "to"];
  var DAY_KEYS = ["date", "day", "data", "giorno", "datetime", "timestamp", "time"];
  var INDICATOR_RE = /period|menstru|flow|bleed|ciclo|periodo|mestruaz/i;
  var FALSY = ["", "0", "no", "false", "none", "n", "-", "nessuno", "null", "off", "0.0"];

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function iso(y, m, d) { return y + "-" + pad(m) + "-" + pad(d); }
  function todayIso() { var t = new Date(); return iso(t.getFullYear(), t.getMonth() + 1, t.getDate()); }

  function normKey(k) {
    return String(k).normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_|_$/g, "").toLowerCase();
  }
  function keyVariants(k) {
    var snake = String(k).replace(/([a-z0-9])([A-Z])/g, "$1_$2");
    return [normKey(k), normKey(snake)];
  }

  /** Restituisce "AAAA-MM-GG" oppure null. order: "DMY" | "MDY" | "YMD". */
  function parseDate(value, order) {
    order = (order || "DMY").toUpperCase();
    if (value === null || value === undefined || typeof value === "boolean") return null;
    if (typeof value === "number" || /^\d{9,13}$/.test(String(value).trim())) {
      var n = Number(value);
      if (n > 1e11) n = n / 1000;
      var dt = new Date(n * 1000);
      return isNaN(dt) ? null : iso(dt.getFullYear(), dt.getMonth() + 1, dt.getDate());
    }
    var s = String(value).trim();
    if (!s) return null;
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
    if (m) return iso(+m[1], +m[2], +m[3]);
    m = /^(\d{1,2})[\/.\-](\d{1,2})[\/.\-](\d{2,4})/.exec(s);
    if (m) {
      var a = +m[1], b = +m[2], y = +m[3];
      if (y < 100) y += 2000;
      var d = order === "MDY" ? b : a;
      var mo = order === "MDY" ? a : b;
      if (mo > 12 && d <= 12) { var t = d; d = mo; mo = t; }
      if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
      return iso(y, mo, d);
    }
    var parsed = new Date(s);
    return isNaN(parsed) ? null : iso(parsed.getFullYear(), parsed.getMonth() + 1, parsed.getDate());
  }

  function truthy(v) {
    if (typeof v === "boolean") return v;
    if (v === null || v === undefined) return false;
    if (typeof v === "number") return v !== 0;
    if (typeof v === "object") return Object.keys(v).length > 0;
    return FALSY.indexOf(String(v).trim().toLowerCase()) === -1;
  }

  function flowOf(v) {
    var t = String(v).toLowerCase();
    var words = ["spotting", "light", "medium", "heavy"];
    for (var i = 0; i < words.length; i++) if (t.indexOf(words[i]) !== -1) return words[i];
    return FALSY.indexOf(t.trim()) !== -1 ? null : "unspecified";
  }

  /** Cammina ricorsivamente un JSON qualsiasi e raccoglie periodi e giorni di flusso. */
  function walkJson(obj, order) {
    var periods = [], flows = [];
    function visit(node) {
      if (Array.isArray(node)) { node.forEach(visit); return; }
      if (!node || typeof node !== "object") return;
      var keys = {};
      Object.keys(node).forEach(function (k) {
        keyVariants(k).forEach(function (v) { if (!(v in keys)) keys[v] = node[k]; });
      });
      var startKey = START_KEYS.filter(function (k) { return k in keys && keys[k] !== null && keys[k] !== ""; })[0];
      var start = startKey ? parseDate(keys[startKey], order) : null;
      if (start) {
        var endKey = END_KEYS.filter(function (k) { return k in keys && keys[k] !== null && keys[k] !== ""; })[0];
        periods.push({ start: start, end: endKey ? parseDate(keys[endKey], order) : null });
        return;
      }
      var dayKey = DAY_KEYS.filter(function (k) { return k in keys; })[0];
      var day = dayKey ? parseDate(keys[dayKey], order) : null;
      if (day) {
        var hit = false, flow = null;
        Object.keys(node).forEach(function (k) {
          if (DAY_KEYS.indexOf(normKey(k)) !== -1) return;
          if (k.toLowerCase() === "type" && typeof node[k] === "string") {
            if (INDICATOR_RE.test(node[k]) || /spotting/i.test(node[k])) {
              hit = true;
              flow = /spotting/i.test(node[k]) ? "spotting" : (flowOf(node.value && node.value.option ? node.value.option : node.value) || "unspecified");
            }
            return;
          }
          if (INDICATOR_RE.test(k) && truthy(node[k])) { hit = true; flow = flowOf(node[k]) || "unspecified"; }
        });
        if (hit) { flows.push({ day: day, flow: flow }); return; }
      }
      Object.keys(node).forEach(function (k) { visit(node[k]); });
    }
    visit(obj);
    return { periods: periods, flows: flows };
  }

  /** CSV con delimitatore rilevato (, ; tab |) e virgolette. */
  function parseCsvText(text) {
    text = text.replace(/^﻿/, "");
    var first = text.split(/\r?\n/)[0] || "";
    var delim = [",", ";", "\t", "|"].sort(function (a, b) { return first.split(b).length - first.split(a).length; })[0];
    var rows = [], row = [], cur = "", q = false;
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (q) {
        if (c === '"' && text[i + 1] === '"') { cur += '"'; i++; }
        else if (c === '"') q = false;
        else cur += c;
      } else if (c === '"') q = true;
      else if (c === delim) { row.push(cur); cur = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(cur); cur = "";
        if (row.some(function (x) { return x.trim(); })) rows.push(row);
        row = [];
      } else cur += c;
    }
    row.push(cur);
    if (row.some(function (x) { return x.trim(); })) rows.push(row);
    if (!rows.length) return [];
    var headers = rows[0].map(normKey);
    return rows.slice(1).map(function (r) {
      var o = {};
      headers.forEach(function (h, i) { o[h] = r[i] === undefined ? "" : r[i]; });
      return o;
    });
  }

  function csvToData(rows, order) {
    var periods = [], flows = [], warnings = [];
    if (!rows.length) return { periods: periods, flows: flows, warnings: ["File vuoto."] };
    var cols = Object.keys(rows[0]);
    var startCol = cols.filter(function (c) { return START_KEYS.indexOf(c) !== -1; })[0];
    var endCol = cols.filter(function (c) { return END_KEYS.indexOf(c) !== -1; })[0];
    if (startCol) {
      rows.forEach(function (r) {
        var s = parseDate(r[startCol], order);
        if (s) periods.push({ start: s, end: endCol ? parseDate(r[endCol], order) : null });
      });
      return { periods: periods, flows: flows, warnings: warnings };
    }
    var dayCol = cols.filter(function (c) { return DAY_KEYS.indexOf(c) !== -1; })[0];
    var indCols = cols.filter(function (c) { return INDICATOR_RE.test(c); });
    if (!dayCol) warnings.push("Nessuna colonna data riconosciuta.");
    else if (!indCols.length) warnings.push("Nessuna colonna con indicatore di mestruazione riconosciuta.");
    else rows.forEach(function (r) {
      var d = parseDate(r[dayCol], order);
      if (!d) return;
      for (var i = 0; i < indCols.length; i++) {
        if (truthy(r[indCols[i]])) { flows.push({ day: d, flow: flowOf(r[indCols[i]]) }); break; }
      }
    });
    return { periods: periods, flows: flows, warnings: warnings };
  }

  function addDays(isoDate, n) {
    var p = isoDate.split("-");
    var d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2] + n));
    return iso(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate());
  }
  function diffDays(a, b) {
    var pa = a.split("-"), pb = b.split("-");
    return Math.round((Date.UTC(+pb[0], +pb[1] - 1, +pb[2]) - Date.UTC(+pa[0], +pa[1] - 1, +pa[2])) / 86400000);
  }

  /** Raggruppa i giorni di flusso in periodi (tolleranza di 1 giorno vuoto). */
  function clusterFlows(flows, includeSpotting) {
    var days = {};
    flows.forEach(function (f) { if (includeSpotting || f.flow !== "spotting") days[f.day] = true; });
    var sorted = Object.keys(days).sort();
    var out = [];
    sorted.forEach(function (d) {
      var last = out[out.length - 1];
      if (last && diffDays(last.end, d) - 1 <= 1) last.end = d;
      else out.push({ start: d, end: d });
    });
    return out.filter(function (p) { return diffDays(p.start, p.end) + 1 <= 15; });
  }

  /** Elimina date future o precedenti al 2000, ordina e rimuove duplicati. */
  function finalize(periods) {
    var today = todayIso(), seen = {};
    return periods
      .filter(function (p) { return p.start >= "2000-01-01" && p.start <= today; })
      .map(function (p) { return { start: p.start, end: p.end && p.end >= p.start && p.end <= today ? p.end : null }; })
      .filter(function (p) { if (seen[p.start]) return false; seen[p.start] = true; return true; })
      .sort(function (a, b) { return a.start < b.start ? -1 : 1; });
  }

  function parseText(text, order, includeSpotting) {
    var t = text.replace(/^﻿/, "").trim();
    var res;
    if (t[0] === "{" || t[0] === "[") {
      try { res = walkJson(JSON.parse(t), order); res.warnings = []; }
      catch (e) { return { periods: [], warnings: ["JSON non valido: " + e.message] }; }
    } else res = csvToData(parseCsvText(t), order);
    var periods = res.periods.concat(clusterFlows(res.flows, includeSpotting));
    var final = finalize(periods);
    var warnings = res.warnings.slice();
    if (!final.length) warnings.push("Nessun periodo riconosciuto: prova il formato CSV generico.");
    return { periods: final, warnings: warnings };
  }

  /** Legge export.xml di Apple Health in streaming (senza caricarlo tutto in memoria). */
  function parseAppleStream(file, order, onProgress) {
    var flows = [];
    var re = /<Record\b[^>]*type="HKCategoryTypeIdentifierMenstrualFlow"[^>]*>/g;
    var reader = file.stream().getReader();
    var decoder = new TextDecoder("utf-8");
    var buf = "", read = 0;
    function handle(final) {
      var lastEnd = 0, m;
      re.lastIndex = 0;
      while ((m = re.exec(buf)) !== null) {
        var tag = m[0];
        lastEnd = re.lastIndex;
        var v = /value="([^"]*)"/.exec(tag), s = /startDate="([^"]*)"/.exec(tag);
        if (!v || !s || /None$/.test(v[1])) continue;
        var day = parseDate(s[1], order);
        var f = /(Light|Medium|Heavy)$/.exec(v[1]);
        if (day) flows.push({ day: day, flow: f ? f[1].toLowerCase() : "unspecified" });
      }
      // Tieni solo la coda che potrebbe contenere un tag incompleto.
      buf = final ? "" : buf.slice(Math.max(lastEnd, buf.length - 2000));
    }
    function pump() {
      return reader.read().then(function (r) {
        if (r.done) { buf += decoder.decode(); handle(true); return finalize(clusterFlows(flows, false)); }
        read += r.value.length;
        buf += decoder.decode(r.value, { stream: true });
        handle(false);
        if (onProgress) onProgress(read / Math.max(file.size, 1));
        return pump();
      });
    }
    return pump();
  }

  function toGeneric(periods) {
    return JSON.stringify({ periods: periods.map(function (p) { return { start: p.start, end: p.end }; }) }, null, 2);
  }

  root.CycleParsers = {
    parseDate: parseDate, walkJson: walkJson, parseCsvText: parseCsvText, csvToData: csvToData,
    clusterFlows: clusterFlows, finalize: finalize, parseText: parseText,
    parseAppleStream: parseAppleStream, toGeneric: toGeneric, addDays: addDays, diffDays: diffDays
  };
  if (typeof module !== "undefined" && module.exports) module.exports = root.CycleParsers;
})(typeof window !== "undefined" ? window : globalThis);
