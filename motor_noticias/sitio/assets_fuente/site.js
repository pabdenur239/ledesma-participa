(function () {
  "use strict";

  var script = document.currentScript;
  var raiz = (script && script.getAttribute("data-base")) || "/";
  var input = document.getElementById("buscador-input");
  var resultados = document.getElementById("buscador-resultados");
  var vacio = document.getElementById("buscador-vacio");
  if (!input || !resultados) return;

  var indice = null;

  function cargarIndice() {
    if (indice) return Promise.resolve(indice);
    return fetch(raiz + "assets/search-index.json")
      .then(function (r) { return r.json(); })
      .then(function (datos) {
        indice = datos;
        return indice;
      });
  }

  function normalizar(texto) {
    return (texto || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "");
  }

  function renderizar(items) {
    resultados.innerHTML = "";
    vacio.hidden = items.length > 0;
    items.forEach(function (n) {
      var art = document.createElement("article");
      art.className = "tarjeta";
      var media = n.imagen
        ? '<img src="' + n.imagen + '" alt="" loading="lazy">'
        : '<div class="tarjeta-sin-imagen" aria-hidden="true">LP</div>';
      art.innerHTML =
        '<a class="tarjeta-enlace" href="' + raiz + n.url + '">' +
        '<div class="tarjeta-media">' + media +
        '<span class="etiqueta-seccion">' + n.seccion + "</span></div>" +
        '<div class="tarjeta-cuerpo"><h2 class="tarjeta-titulo">' + n.titulo + "</h2>" +
        '<p class="tarjeta-resumen">' + n.resumen + "</p>" +
        '<p class="tarjeta-meta">' + n.fecha + "</p></div></a>";
      resultados.appendChild(art);
    });
  }

  input.addEventListener("input", function () {
    var consulta = normalizar(input.value.trim());
    if (!consulta) {
      resultados.innerHTML = "";
      vacio.hidden = true;
      return;
    }
    cargarIndice().then(function (items) {
      var filtrados = items.filter(function (n) {
        return n.buscable.indexOf(consulta) !== -1;
      });
      renderizar(filtrados.slice(0, 40));
    });
  });
})();
