(function () {
  "use strict";

  function porClase(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }
  function marco(src, titulo) {
    var f = document.createElement("iframe");
    f.src = src;
    f.title = titulo;
    f.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    f.setAttribute("allowfullscreen", "");
    f.referrerPolicy = "strict-origin-when-cross-origin";
    return f;
  }
  function youtubeEnVivo(canal, titulo) {
    return marco("https://www.youtube.com/embed/live_stream?autoplay=1&channel=" + encodeURIComponent(canal), titulo);
  }

  // Portada: filtros geográfico y temático (se combinan; sin recargar).
  var grilla = document.getElementById("grilla-noticias");
  if (grilla) {
    var activos = { geo: "", tema: "" };
    var vacio = document.getElementById("filtro-vacio");
    var aplicar = function () {
      var visibles = 0;
      porClase("article", grilla).forEach(function (a) {
        var ok = (!activos.geo || a.getAttribute("data-geo") === activos.geo) &&
                 (!activos.tema || a.getAttribute("data-tema") === activos.tema);
        a.hidden = !ok;
        if (ok) visibles++;
      });
      if (vacio) vacio.hidden = visibles > 0;
    };
    porClase(".filtro[data-filtro]").forEach(function (grupo) {
      var clave = grupo.getAttribute("data-filtro");
      grupo.addEventListener("click", function (e) {
        var chip = e.target.closest(".chip");
        if (!chip) return;
        porClase(".chip", grupo).forEach(function (c) { c.classList.remove("activo"); });
        chip.classList.add("activo");
        activos[clave] = chip.getAttribute("data-" + clave) || "";
        aplicar();
      });
    });
  }

  // Guía Comercial: filtro por rubro.
  var guia = document.getElementById("grilla-guia");
  var filtroRubro = document.querySelector(".filtro-rubro");
  if (guia && filtroRubro) {
    filtroRubro.addEventListener("click", function (e) {
      var chip = e.target.closest(".chip");
      if (!chip) return;
      porClase(".chip", filtroRubro).forEach(function (c) { c.classList.remove("activo"); });
      chip.classList.add("activo");
      var rubro = chip.getAttribute("data-rubro");
      porClase("article", guia).forEach(function (a) { a.hidden = !!rubro && a.getAttribute("data-rubro") !== rubro; });
    });
  }

  // Radio en vivo: una sola emisora a la vez.
  var panelRadio = document.getElementById("reproductor-radio");
  if (panelRadio) {
    var audio = document.getElementById("radio-audio");
    var yt = document.getElementById("radio-youtube");
    var rotulo = document.getElementById("radio-sonando");
    porClase(".radio").forEach(function (tarjeta) {
      tarjeta.querySelector(".boton-radio").addEventListener("click", function () {
        porClase(".radio").forEach(function (t) { t.classList.remove("sonando"); });
        tarjeta.classList.add("sonando");
        var nombre = tarjeta.getAttribute("data-nombre");
        var fuente = tarjeta.getAttribute("data-fuente");
        panelRadio.hidden = false;
        rotulo.textContent = "Escuchando: " + nombre;
        yt.textContent = "";
        audio.pause();
        if (tarjeta.getAttribute("data-radio-tipo") === "youtube") {
          audio.removeAttribute("src");
          audio.hidden = true;
          yt.appendChild(youtubeEnVivo(fuente, nombre + " en vivo"));
        } else {
          audio.hidden = false;
          audio.src = fuente;
          var p = audio.play();
          if (p && p.catch) p.catch(function () { rotulo.textContent = nombre + ": tocá play para escuchar."; });
        }
      });
    });
    audio.addEventListener("error", function () {
      if (audio.getAttribute("src")) rotulo.textContent = "La señal no está disponible en este momento. Probá con otra radio.";
    });
  }

  // TV en vivo: un solo reproductor, se carga al elegir canal.
  var panelTv = document.getElementById("reproductor-tv");
  if (panelTv) {
    var contenedor = document.getElementById("tv-marco");
    var viendo = document.getElementById("tv-viendo");
    porClase(".boton-tv").forEach(function (b) {
      b.addEventListener("click", function () {
        porClase(".boton-tv").forEach(function (x) { x.classList.remove("activo"); });
        b.classList.add("activo");
        var nombre = b.getAttribute("data-nombre");
        var fuente = b.getAttribute("data-fuente");
        panelTv.hidden = false;
        viendo.textContent = "Viendo: " + nombre;
        contenedor.textContent = "";
        contenedor.appendChild(b.getAttribute("data-tv-tipo") === "youtube" ? youtubeEnVivo(fuente, nombre + " en vivo") : marco(fuente, nombre + " en vivo"));
        panelTv.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    });
  }
})();
