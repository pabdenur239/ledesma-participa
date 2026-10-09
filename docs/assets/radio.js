/* Radios en vivo (Etapa 2): mini reproductor persistente + filtros de /radios/.
 *
 * El sitio es HTML estático (cada nota es una página completa), así que el
 * audio no puede seguir sonando sin corte al cambiar de página. Mejor
 * alternativa sin redefinir la arquitectura: la radio elegida, el volumen y
 * si estaba sonando se guardan en sessionStorage; cada página vuelve a
 * mostrar el mini reproductor y retoma la transmisión. Si el navegador
 * bloquea la reproducción automática, queda en pausa con el aviso
 * "Tocá Reproducir para seguir escuchando". Solo reproduce la URL oficial
 * cargada en config/radios.json: no hay proxy ni grabación.
 */
(function (global) {
  "use strict";

  var CLAVE = "lp-radio";
  var HLS_NO_SOPORTADO = "Este navegador no reproduce esta transmisión (HLS). Probá desde el celular, Safari o el reproductor oficial.";

  // HLS sin soporte nativo (p. ej. Firefox o Chrome de escritorio viejo):
  // no se convierte ni se retransmite el stream; se avisa claramente.
  function hlsIncompatible(radio, audio) {
    if (radio.tipo !== "hls" || typeof audio.canPlayType !== "function") return false;
    return !audio.canPlayType("application/vnd.apple.mpegurl");
  }

  // Núcleo sin DOM (probado con Node en tests/test_radio_js.py).
  function crearControlador(opciones) {
    var storage = opciones.storage;
    var audio = opciones.audio;
    var alCambiar = opciones.alCambiar || function () {};
    var estado = { radio: null, reproduciendo: false, volumen: 1, mensaje: "" };

    function guardar() {
      try {
        if (!estado.radio) storage.removeItem(CLAVE);
        else storage.setItem(CLAVE, JSON.stringify({ radio: estado.radio, reproduciendo: estado.reproduciendo, volumen: estado.volumen }));
      } catch (e) { /* almacenamiento bloqueado: el reproductor igual funciona en esta página */ }
    }

    function notificar() { guardar(); alCambiar(estado); }

    function sonar() {
      estado.mensaje = "Conectando…";
      notificar();
      var promesa;
      try { promesa = audio.play(); } catch (e) { promesa = Promise.reject(e); }
      return Promise.resolve(promesa).then(function () {
        estado.reproduciendo = true;
        estado.mensaje = "En vivo";
        notificar();
      }, function (error) {
        estado.reproduciendo = false;
        estado.mensaje = error && error.name === "NotAllowedError"
          ? "Tocá Reproducir para seguir escuchando"
          : "Transmisión no disponible temporalmente";
        notificar();
      });
    }

    function cargar(radio) {
      estado.radio = { id: radio.id, nombre: radio.nombre, dial: radio.dial || "", stream: radio.stream, tipo: radio.tipo || "" };
      audio.src = radio.stream;
      audio.volume = estado.volumen;
    }

    return {
      estado: function () { return estado; },
      reproducir: function (radio) {
        if (estado.radio && estado.radio.id === radio.id && estado.reproduciendo) return Promise.resolve();
        if (!estado.radio || estado.radio.id !== radio.id) cargar(radio);
        if (hlsIncompatible(estado.radio, audio)) {
          estado.reproduciendo = false;
          estado.mensaje = HLS_NO_SOPORTADO;
          notificar();
          return Promise.resolve();
        }
        return sonar();
      },
      pausar: function () {
        audio.pause();
        estado.reproduciendo = false;
        estado.mensaje = "En pausa";
        notificar();
      },
      alternar: function () {
        if (!estado.radio) return Promise.resolve();
        if (estado.reproduciendo) { this.pausar(); return Promise.resolve(); }
        // Transmisión en vivo: al reanudar se reconecta al momento actual.
        if (hlsIncompatible(estado.radio, audio)) return this.reproducir(estado.radio);
        audio.src = estado.radio.stream;
        return sonar();
      },
      volumen: function (valor) {
        estado.volumen = Math.max(0, Math.min(1, Number(valor)));
        audio.volume = estado.volumen;
        guardar();
      },
      cerrar: function () {
        audio.pause();
        audio.removeAttribute ? audio.removeAttribute("src") : (audio.src = "");
        estado.radio = null;
        estado.reproduciendo = false;
        estado.mensaje = "";
        notificar();
      },
      falla: function () {
        estado.reproduciendo = false;
        estado.mensaje = "Transmisión no disponible temporalmente";
        notificar();
      },
      restaurar: function () {
        var guardado = null;
        try { guardado = JSON.parse(storage.getItem(CLAVE) || "null"); } catch (e) { guardado = null; }
        if (!guardado || !guardado.radio || !guardado.radio.stream) return Promise.resolve(false);
        estado.volumen = typeof guardado.volumen === "number" ? guardado.volumen : 1;
        cargar(guardado.radio);
        if (!guardado.reproduciendo) {
          estado.mensaje = "En pausa";
          notificar();
          return Promise.resolve(true);
        }
        return sonar().then(function () { return true; });
      }
    };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { crearControlador: crearControlador, CLAVE: CLAVE };
    return;
  }

  var documento = global.document;
  if (!documento) return;

  function almacenamiento() {
    try { return global.sessionStorage; } catch (e) { return { getItem: function () { return null; }, setItem: function () {}, removeItem: function () {} }; }
  }

  function iniciar() {
    var audio = new global.Audio();
    audio.preload = "none";
    var barra = null;
    var ui = {};

    function crearBarra() {
      barra = documento.createElement("section");
      barra.className = "mini-reproductor";
      barra.setAttribute("aria-label", "Reproductor de radio");
      barra.innerHTML =
        '<button type="button" class="mr-play" aria-pressed="false"><span class="mr-icono" aria-hidden="true">&#9654;</span> <span class="mr-texto">Reproducir</span></button>' +
        '<div class="mr-info"><strong class="mr-nombre"></strong> <span class="mr-dial"></span>' +
        '<span class="mr-estado" role="status" aria-live="polite"></span></div>' +
        '<label class="mr-volumen"><span class="solo-lectores">Volumen</span><input type="range" min="0" max="1" step="0.05"></label>' +
        '<button type="button" class="mr-cerrar" aria-label="Cerrar reproductor">&#10005;</button>';
      documento.body.appendChild(barra);
      ui = {
        play: barra.querySelector(".mr-play"), icono: barra.querySelector(".mr-icono"), texto: barra.querySelector(".mr-texto"),
        nombre: barra.querySelector(".mr-nombre"), dial: barra.querySelector(".mr-dial"), estado: barra.querySelector(".mr-estado"),
        volumen: barra.querySelector(".mr-volumen input"), cerrar: barra.querySelector(".mr-cerrar")
      };
      ui.play.addEventListener("click", function () {
        var e = control.estado();
        if (e.radio) medir(e.reproduciendo ? "radio_pause" : "radio_play", e.radio.id);
        control.alternar();
      });
      ui.cerrar.addEventListener("click", function () { control.cerrar(); });
      ui.volumen.addEventListener("input", function () { control.volumen(ui.volumen.value); });
    }

    function pintar(estado) {
      documento.body.classList.toggle("con-reproductor", !!estado.radio);
      if (!estado.radio) { if (barra) barra.hidden = true; marcarBotones(null, false); return; }
      if (!barra) crearBarra();
      barra.hidden = false;
      ui.nombre.textContent = estado.radio.nombre;
      ui.dial.textContent = estado.radio.dial;
      ui.estado.textContent = estado.mensaje;
      ui.icono.innerHTML = estado.reproduciendo ? "&#10074;&#10074;" : "&#9654;";
      ui.texto.textContent = estado.reproduciendo ? "Pausa" : "Reproducir";
      ui.play.setAttribute("aria-pressed", estado.reproduciendo ? "true" : "false");
      ui.play.setAttribute("aria-label", (estado.reproduciendo ? "Pausar " : "Reproducir ") + estado.radio.nombre);
      ui.volumen.value = String(estado.volumen);
      marcarBotones(estado.radio.id, estado.reproduciendo);
    }

    function marcarBotones(id, sonando) {
      var botones = documento.querySelectorAll("button.boton-escuchar[data-radio-id]");
      for (var i = 0; i < botones.length; i++) {
        var activo = botones[i].getAttribute("data-radio-id") === id && sonando;
        botones[i].classList.toggle("escuchando", activo);
        botones[i].innerHTML = activo ? "&#9679; Escuchando" : "&#9654; Escuchar en vivo";
      }
    }

    var control = crearControlador({ storage: almacenamiento(), audio: audio, alCambiar: pintar });
    audio.addEventListener("error", function () { if (control.estado().radio) control.falla(); });

    var botones = documento.querySelectorAll("button.boton-escuchar[data-stream]");
    for (var i = 0; i < botones.length; i++) {
      botones[i].addEventListener("click", function (evento) {
        var b = evento.currentTarget;
        // Un HLS en un navegador sin soporte nativo dispara "error" y se ve el aviso de no disponible.
        var radio = { id: b.getAttribute("data-radio-id"), nombre: b.getAttribute("data-nombre"), dial: b.getAttribute("data-dial"), stream: b.getAttribute("data-stream"), tipo: b.getAttribute("data-tipo") || "" };
        var e = control.estado();
        if (e.radio && e.radio.id === radio.id && e.reproduciendo) { medir("radio_pause", radio.id); control.pausar(); }
        else { medir("radio_select", radio.id); medir("radio_play", radio.id); control.reproducir(radio); }
      });
    }

    // Medición agregada (Etapa 3): minutos aproximados escuchados, en
    // bloques de 5 (y el resto al salir de la página). Sin identificadores.
    var minutos = 0;
    function enviarMinutos() {
      var r = control.estado().radio;
      if (minutos > 0 && r) medir("radio_listen_minutes", r.id, minutos);
      minutos = 0;
    }
    global.setInterval(function () {
      if (!audio.paused && control.estado().radio) { minutos++; if (minutos >= 5) enviarMinutos(); }
    }, 60000);
    global.addEventListener("pagehide", enviarMinutos);

    iniciarFiltros();
    control.restaurar();
  }

  function medir(evento, clave, valor) {
    try { if (global.LPMedicion) global.LPMedicion.evento(evento, clave, valor); } catch (e) { /* la medición nunca afecta al reproductor */ }
  }

  function iniciarFiltros() {
    var lista = documento.getElementById("radios-lista");
    if (!lista) return;
    var chips = documento.querySelectorAll(".chip-zona");
    var buscador = documento.getElementById("radios-buscar");
    var sinResultados = documento.getElementById("radios-sin-resultados");
    var zona = "";

    function normalizar(t) { return (t || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }

    function aplicar() {
      var consulta = normalizar(buscador ? buscador.value.trim() : "");
      var tarjetas = lista.querySelectorAll(".tarjeta-radio");
      var visibles = 0;
      for (var i = 0; i < tarjetas.length; i++) {
        var t = tarjetas[i];
        var ok = (!zona || t.getAttribute("data-zona") === zona) &&
          (!consulta || normalizar(t.getAttribute("data-buscable")).indexOf(consulta) !== -1);
        t.hidden = !ok;
        if (ok) visibles++;
      }
      if (sinResultados) sinResultados.hidden = visibles > 0;
    }

    for (var i = 0; i < chips.length; i++) {
      chips[i].addEventListener("click", function (evento) {
        zona = evento.currentTarget.getAttribute("data-zona") || "";
        for (var j = 0; j < chips.length; j++) chips[j].setAttribute("aria-pressed", chips[j] === evento.currentTarget ? "true" : "false");
        aplicar();
      });
    }
    if (buscador) buscador.addEventListener("input", aplicar);
  }

  if (documento.readyState === "loading") documento.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})(this);
