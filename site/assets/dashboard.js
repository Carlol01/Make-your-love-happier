/* Dashboard locale: apri data/cycles.json dal tuo computer. Nessun dato viene inviato. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var NS = "http://www.w3.org/2000/svg";

  function days(a, b) {
    var pa = a.split("-"), pb = b.split("-");
    return Math.round((Date.UTC(+pb[0], +pb[1] - 1, +pb[2]) - Date.UTC(+pa[0], +pa[1] - 1, +pa[2])) / 86400000);
  }
  function mean(a) { return a.reduce(function (x, y) { return x + y; }, 0) / a.length; }
  function sd(a) { var m = mean(a); return Math.sqrt(mean(a.map(function (x) { return (x - m) * (x - m); }))); }
  function el(name, attrs, text) {
    var e = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text) e.textContent = text;
    return e;
  }

  function stats(periods) {
    var starts = periods.map(function (p) { return p.start; }).sort();
    var lengths = [];
    for (var i = 1; i < starts.length; i++) {
      var n = days(starts[i - 1], starts[i]);
      if (n >= 21 && n <= 45) lengths.push(n);
    }
    var recent = lengths.slice(-6);
    var durs = periods.filter(function (p) { return p.end && !p.end_estimated; })
      .map(function (p) { return days(p.start, p.end) + 1; })
      .filter(function (n) { return n >= 2 && n <= 10; }).slice(-6);
    return {
      n: periods.length,
      avgCycle: recent.length ? mean(recent) : null,
      sd: recent.length > 1 ? sd(recent) : null,
      avgDur: durs.length ? mean(durs) : null,
      last: starts.length ? starts[starts.length - 1] : null
    };
  }

  function timeline(periods) {
    var svg = $("timeline");
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    if (!periods.length) return;
    var sorted = periods.slice().sort(function (a, b) { return a.start < b.start ? -1 : 1; });
    var first = sorted[0].start, lastP = sorted[sorted.length - 1];
    var span = Math.max(days(first, lastP.end || lastP.start) + 1, 30);
    var W = 800, H = 90, L = 10, R = 10, x = function (d) { return L + (days(first, d) / span) * (W - L - R); };
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.appendChild(el("line", { x1: L, x2: W - R, y1: 55, y2: 55, "class": "axis" }));
    sorted.forEach(function (p, i) {
      var x0 = x(p.start), x1 = x(p.end || p.start) + 3;
      svg.appendChild(el("rect", { x: x0, y: 35, width: Math.max(x1 - x0, 4), height: 20, rx: 3, "class": "bar" }));
      if (i > 0) {
        var gap = days(sorted[i - 1].start, p.start);
        svg.appendChild(el("text", { x: (x(sorted[i - 1].start) + x0) / 2, y: 28, "text-anchor": "middle" }, gap + " g"));
      }
    });
    svg.appendChild(el("text", { x: L, y: 78 }, first));
    svg.appendChild(el("text", { x: W - R, y: 78, "text-anchor": "end" }, lastP.end || lastP.start));
  }

  function render(data) {
    var periods = data.periods || [];
    var s = stats(periods);
    $("s-n").textContent = s.n;
    $("s-cycle").textContent = s.avgCycle ? s.avgCycle.toFixed(1) + " g" : "n/d";
    $("s-sd").textContent = s.sd !== null ? "±" + s.sd.toFixed(1) + " g" : "n/d";
    $("s-dur").textContent = s.avgDur ? s.avgDur.toFixed(1) + " g" : "n/d";
    $("s-last").textContent = s.last || "n/d";
    timeline(periods);
    $("dash").classList.remove("hidden");
    $("error").textContent = "";
  }

  $("file").addEventListener("change", function (e) {
    var f = e.target.files[0];
    if (!f) return;
    if (/\.enc$/.test(f.name)) { $("error").textContent = "Il file è cifrato: esegui prima `python -m cycle_notifier decrypt` in locale."; return; }
    f.text().then(function (t) { render(JSON.parse(t)); })
      .catch(function (err) { $("error").textContent = "File non valido: " + err.message; });
  });
})();
