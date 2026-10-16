/* Menú principal: un solo submenú abierto a la vez; se cierra al tocar fuera
 * o con Escape. Sin JS los <details> siguen funcionando (se abren y cierran a mano). */
(function () {
  "use strict";
  var grupos = Array.prototype.slice.call(document.querySelectorAll(".nav-grupo"));
  if (!grupos.length) return;

  function cerrarTodos(excepto) {
    grupos.forEach(function (g) { if (g !== excepto) g.removeAttribute("open"); });
  }

  grupos.forEach(function (g) {
    g.addEventListener("toggle", function () { if (g.open) cerrarTodos(g); });
  });
  document.addEventListener("click", function (e) {
    if (!e.target.closest || !e.target.closest(".nav-grupo")) cerrarTodos(null);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") cerrarTodos(null);
  });
})();
