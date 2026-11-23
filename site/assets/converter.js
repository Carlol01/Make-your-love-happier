/* Interfaccia del convertitore: tutto avviene nel browser, nessun upload. */
(function () {
  "use strict";
  var P = window.CycleParsers;
  var $ = function (id) { return document.getElementById(id); };
  var current = null;

  function show(result) {
    current = result;
    var out = $("output");
    out.value = result.periods.length ? P.toGeneric(result.periods) : "";
    $("count").textContent = result.periods.length;
    $("warnings").textContent = result.warnings.join(" ");
    $("result").classList.remove("hidden");
    $("download").disabled = $("copy").disabled = !result.periods.length;
  }

  function fail(message) {
    show({ periods: [], warnings: [message] });
  }

  function handle(file) {
    if (!file) return;
    var order = $("order").value;
    $("progress").textContent = "";
    var name = file.name.toLowerCase();
    if (name.endsWith(".zip")) {
      fail("Gli zip non sono supportati qui: estrai prima export.xml (Apple Health) e caricalo.");
      return;
    }
    if (name.endsWith(".xml")) {
      P.parseAppleStream(file, order, function (r) { $("progress").textContent = Math.round(r * 100) + "%"; })
        .then(function (periods) {
          show({ periods: periods, warnings: periods.length ? [] : ["Nessun dato MenstrualFlow trovato nel file."] });
        })
        .catch(function (e) { fail("Lettura non riuscita: " + e.message); });
      return;
    }
    file.text().then(function (text) { show(P.parseText(text, order, false)); })
      .catch(function (e) { fail("Lettura non riuscita: " + e.message); });
  }

  $("file").addEventListener("change", function (e) { handle(e.target.files[0]); });
  $("download").addEventListener("click", function () {
    var blob = new Blob([$("output").value], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "periodi.json";
    a.click();
    URL.revokeObjectURL(a.href);
  });
  $("copy").addEventListener("click", function () {
    $("output").select();
    if (navigator.clipboard) navigator.clipboard.writeText($("output").value);
  });
})();
