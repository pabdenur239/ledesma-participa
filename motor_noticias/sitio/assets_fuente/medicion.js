/* Medición propia, anónima y agregada (Etapa 3).
 *
 * Solo cuenta eventos (visita a portada, apertura de nota, clics a redes,
 * Guía Comercial, radios…) y los envía al receptor propio configurado en
 * data-endpoint. Sin cookies, sin almacenamiento local, sin identificadores
 * de persona o dispositivo, sin terceros. Respeta "Do Not Track".
 * Si no hay endpoint o el envío falla, no pasa nada: la página funciona igual.
 */
(function (global) {
  "use strict";

  var script = global.document && global.document.currentScript;
  var endpoint = script && script.getAttribute("data-endpoint");
  var pagina = (script && script.getAttribute("data-pagina")) || "";
  var clavePagina = (script && script.getAttribute("data-clave")) || "";
  var nav = global.navigator || {};
  var desactivada = !endpoint || nav.doNotTrack === "1" || global.doNotTrack === "1";

  var CLAVE_VALIDA = /^[a-z0-9][a-z0-9_\-]{0,79}$/;

  function evento(nombre, clave, valor) {
    if (desactivada || !nombre) return;
    var k = String(clave || "").toLowerCase();
    if (k && !CLAVE_VALIDA.test(k)) k = "";
    var cuerpo = JSON.stringify({ o: "web", e: nombre, k: k, v: valor || 1 });
    try {
      // text/plain: petición simple, sin preflight CORS ni cookies.
      if (nav.sendBeacon && nav.sendBeacon(endpoint, new Blob([cuerpo], { type: "text/plain" }))) return;
      if (global.fetch) global.fetch(endpoint, { method: "POST", body: cuerpo, keepalive: true, mode: "no-cors", credentials: "omit" }).catch(function () {});
    } catch (e) { /* nunca afecta la lectura */ }
  }

  global.LPMedicion = { evento: evento };
  if (desactivada) return;

  var VISTA = {
    home: "home_view", article: "article_open", category: "category_open",
    guia: "guia_open", commercial: "commercial_view", video: "video_open"
  };
  if (VISTA[pagina]) evento(VISTA[pagina], clavePagina);

  function redSocial(href) {
    if (/\/\/([a-z0-9-]+\.)*facebook\.com\//i.test(href) && href.indexOf("sharer") === -1) return "facebook";
    if (/\/\/([a-z0-9-]+\.)*instagram\.com\//i.test(href)) return "instagram";
    return "";
  }

  global.document.addEventListener("click", function (ev) {
    var el = ev.target && ev.target.closest ? ev.target.closest("a, button") : null;
    if (!el) return;
    var explicito = el.getAttribute("data-ev");
    if (explicito) { evento(explicito, el.getAttribute("data-k") || ""); return; }
    var href = el.getAttribute("href") || "";
    var red = redSocial(href);
    if (red) { evento("social_click", red); return; }
    if (pagina === "home") {
      var m = /noticias\/(\d+)-/.exec(href);
      if (m) evento("home_article_click", m[1]);
    }
  }, true);
})(this);
