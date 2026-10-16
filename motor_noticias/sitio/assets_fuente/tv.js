/* TV en vivo: un solo reproductor oficial (YouTube del canal o iframe oficial),
 * cargado recién al elegir el canal. */
(function () {
  "use strict";
  var panel = document.getElementById("reproductor-tv");
  if (!panel) return;
  var marco = document.getElementById("tv-marco");
  var viendo = document.getElementById("tv-viendo");
  var botones = Array.prototype.slice.call(document.querySelectorAll(".boton-tv"));

  function iframe(src, titulo) {
    var f = document.createElement("iframe");
    f.src = src;
    f.title = titulo;
    f.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    f.setAttribute("allowfullscreen", "");
    f.referrerPolicy = "strict-origin-when-cross-origin";
    return f;
  }

  botones.forEach(function (b) {
    b.addEventListener("click", function () {
      botones.forEach(function (x) { x.classList.remove("activo"); x.setAttribute("aria-pressed", "false"); });
      b.classList.add("activo");
      b.setAttribute("aria-pressed", "true");
      var nombre = b.getAttribute("data-nombre");
      var fuente = b.getAttribute("data-fuente");
      var src = b.getAttribute("data-tv-tipo") === "youtube"
        ? "https://www.youtube.com/embed/live_stream?autoplay=1&channel=" + encodeURIComponent(fuente)
        : fuente;
      panel.hidden = false;
      viendo.textContent = "Viendo: " + nombre;
      marco.textContent = "";
      marco.appendChild(iframe(src, nombre + " en vivo"));
      if (panel.scrollIntoView) panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  });
})();
