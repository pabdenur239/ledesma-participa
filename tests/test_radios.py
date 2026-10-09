"""Etapa 2 — Radios en vivo: datos, verificación de stream (mocks, nunca
radios reales ni red), API estática, páginas web y núcleo del reproductor
web (Node, si está instalado)."""
import json
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from motor_noticias import radios
from motor_noticias.sitio import generador as generador_mod
from motor_noticias.sitio import plantillas
from motor_noticias.sitio.generador import generar_sitio
from motor_noticias.sitio.imagenes_web import ValidadorImagenes

RAIZ = Path(__file__).resolve().parent.parent
AHORA = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)


def _radio(**over):
    base = {
        "id": "radio-test", "nombre": "Radio Test", "dial": "95.5 FM", "localidad": "Libertador General San Martín",
        "zona": "Libertador", "stream_url": "https://stream.test/vivo.mp3", "tipo_stream": "mp3",
        "fuente_autorizacion": "test", "estado": "activa", "activa": True, "orden": 1,
    }
    base.update(over)
    return base


class _Respuesta:
    def __init__(self, status=200, content_type="audio/mpeg"):
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.cerrada = False

    def getcode(self):
        return self.status

    def close(self):
        self.cerrada = True


class TestDatosRadios(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _config(self, lista, nombre="radios.json"):
        ruta = self.tmp / nombre
        ruta.write_text(json.dumps({"radios": lista}), encoding="utf-8")
        return ruta

    def test_config_real_no_inventa_emisoras(self):
        datos = json.loads((RAIZ / "config" / "radios.json").read_text(encoding="utf-8"))
        self.assertEqual(datos["radios"], [])
        self.assertEqual(radios.cargar_radios(incluir_demo=False), [])

    def test_demo_del_archivo_demo_esta_marcado_y_no_apunta_a_radios_reales(self):
        datos = json.loads((RAIZ / "config" / "radios_demo.json").read_text(encoding="utf-8"))
        nombres = {r["nombre"] for r in datos["radios"]}
        self.assertEqual(nombres, {"FM DEMO 95.5", "Radio Demo Jujuy", "Radio Demo Argentina"})
        for r in datos["radios"]:
            self.assertTrue(r["demo"])
            for clave in ("stream_url", "player_url"):
                if r.get(clave):
                    self.assertIn(".invalid/", r[clave])

    def test_activa_inactiva_baja_logica(self):
        ruta = self._config([
            _radio(id="activa"), _radio(id="apagada", activa=False), _radio(id="baja", estado="baja"),
            _radio(id="sin-flag", activa=None),
        ])
        self.assertEqual([r["id"] for r in radios.cargar_radios(ruta, incluir_demo=False)], ["activa"])

    def test_demo_nunca_sale_de_la_config_real_ni_sin_variable(self):
        ruta = self._config([_radio(id="colada", demo=True)])
        demo = self._config([_radio(id="fm-demo", demo=True)], "demo.json")
        self.assertEqual(radios.cargar_radios(ruta, demo_path=demo, incluir_demo=False), [])
        with patch.dict("os.environ", {"LEDESMA_RADIOS_DEMO": ""}):
            self.assertEqual(radios.cargar_radios(ruta, demo_path=demo), [])
        with patch.dict("os.environ", {"LEDESMA_RADIOS_DEMO": "1"}):
            self.assertEqual([r["id"] for r in radios.cargar_radios(ruta, demo_path=demo)], ["fm-demo"])

    def test_zona_invalida_o_datos_minimos_faltantes(self):
        ruta = self._config([_radio(id="x1", zona="Salta"), _radio(id="x2", nombre=""), _radio(id="X MAL")])
        self.assertEqual(radios.cargar_radios(ruta, incluir_demo=False), [])

    def test_orden_por_zona_y_orden(self):
        ruta = self._config([
            _radio(id="arg", zona="Argentina", orden=1), _radio(id="lib-2", orden=2),
            _radio(id="lib-1", orden=1), _radio(id="jujuy", zona="Jujuy"),
        ])
        self.assertEqual([r["id"] for r in radios.cargar_radios(ruta, incluir_demo=False)],
                         ["lib-1", "lib-2", "jujuy", "arg"])

    def test_fuentes_prohibidas_o_http_quedan_sin_boton(self):
        for url in ("https://www.facebook.com/radio/live", "https://youtu.be/abcdefghijk",
                    "https://www.youtube.com/watch?v=abcdefghijk", "http://stream.test/vivo.mp3", "no-es-url"):
            r = radios.normalizar_radio(_radio(stream_url=url))
            self.assertIsNotNone(r)
            self.assertIsNone(r["stream_url"], url)

    def test_sin_fuente_de_autorizacion_no_hay_boton(self):
        r = radios.normalizar_radio(_radio(fuente_autorizacion=""))
        self.assertIsNone(r["stream_url"])


class TestVerificacionStream(unittest.TestCase):
    def test_stream_valido(self):
        resp = _Respuesta(200, "audio/mpeg")
        resultado = radios.verificar_stream("https://stream.test/a", abrir=lambda req, timeout: resp)
        self.assertTrue(resultado["ok"])
        self.assertTrue(resp.cerrada, "no debe quedar descargando audio")

    def test_tipo_no_compatible(self):
        resultado = radios.verificar_stream("https://stream.test/a", abrir=lambda req, timeout: _Respuesta(200, "text/html"))
        self.assertFalse(resultado["ok"])

    def test_error_http_y_timeout_controlados(self):
        def http_404(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 404, "no", {}, None)

        def lento(req, timeout):
            raise TimeoutError()

        self.assertEqual(radios.verificar_stream("https://s.test", abrir=http_404)["error"], "HTTP 404")
        self.assertFalse(radios.verificar_stream("https://s.test", abrir=lento)["ok"])

    def test_hls_y_ogg_compatibles(self):
        for tipo in ("application/vnd.apple.mpegurl", "application/ogg", "audio/aac; charset=x"):
            self.assertTrue(radios.tipo_compatible(tipo), tipo)


class TestEstados(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.estado = self.tmp / "estado.json"
        self.llamadas = []

    def _verificar(self, ok):
        def verificar(url):
            self.llamadas.append(url)
            return {"ok": ok, "error": None if ok else "HTTP 503"}
        return verificar

    def _lista(self, **over):
        return [radios.normalizar_radio(_radio(**over))]

    def test_en_vivo_y_no_disponible(self):
        r = radios.actualizar_estados(self._lista(), ahora=AHORA, estado_path=self.estado, minutos=60, verificar=self._verificar(True))[0]
        self.assertEqual(r["estado_transmision"], radios.EN_VIVO)
        self.assertEqual(r["ultima_verificacion"], AHORA.isoformat())
        self.estado.unlink()
        r = radios.actualizar_estados(self._lista(), ahora=AHORA, estado_path=self.estado, minutos=60, verificar=self._verificar(False))[0]
        self.assertEqual(r["estado_transmision"], radios.NO_DISPONIBLE)

    def test_cache_evita_trafico_excesivo(self):
        for minutos_despues in (0, 10, 59):
            radios.actualizar_estados(self._lista(), ahora=AHORA + timedelta(minutes=minutos_despues),
                                      estado_path=self.estado, minutos=60, verificar=self._verificar(True))
        self.assertEqual(len(self.llamadas), 1)
        radios.actualizar_estados(self._lista(), ahora=AHORA + timedelta(minutes=61), estado_path=self.estado,
                                  minutos=60, verificar=self._verificar(True))
        self.assertEqual(len(self.llamadas), 2)

    def test_cambio_de_url_reverifica(self):
        radios.actualizar_estados(self._lista(), ahora=AHORA, estado_path=self.estado, minutos=60, verificar=self._verificar(True))
        radios.actualizar_estados(self._lista(stream_url="https://stream.test/nuevo.aac"), ahora=AHORA,
                                  estado_path=self.estado, minutos=60, verificar=self._verificar(True))
        self.assertEqual(len(self.llamadas), 2)

    def test_fallback_sin_stream_y_solo_player(self):
        sin = radios.actualizar_estados(self._lista(stream_url=None), ahora=AHORA, estado_path=self.estado,
                                        verificar=self._verificar(True))[0]
        self.assertEqual(sin["estado_transmision"], radios.SIN_TRANSMISION)
        player = radios.actualizar_estados(self._lista(stream_url=None, player_url="https://radio.test/player"),
                                           ahora=AHORA, estado_path=self.estado, verificar=self._verificar(True))[0]
        self.assertEqual(player["estado_transmision"], radios.SIN_VERIFICAR)
        self.assertEqual(self.llamadas, [], "sin stream directo no se consulta nada")

    def test_demo_nunca_se_verifica(self):
        lista = [radios.normalizar_radio(_radio(demo=True), permitir_demo=True)]
        r = radios.actualizar_estados(lista, ahora=AHORA, estado_path=self.estado, verificar=self._verificar(True))[0]
        self.assertEqual(r["estado_transmision"], radios.SIN_VERIFICAR)
        self.assertEqual(self.llamadas, [])


class TestPlantillasRadios(unittest.TestCase):
    def _html(self, **over):
        r = radios.normalizar_radio(_radio(**over))
        r["estado_transmision"] = over.get("_estado", radios.SIN_VERIFICAR)
        return plantillas.tarjeta_radio(r)

    def test_tarjeta_con_stream(self):
        html = self._html()
        self.assertIn('data-stream="https://stream.test/vivo.mp3"', html)
        self.assertIn("Escuchar en vivo", html)
        self.assertIn('aria-label="Escuchar en vivo Radio Test 95.5 FM"', html)
        self.assertNotIn("EN VIVO", html, "sin verificación no se muestra EN VIVO")

    def test_estados_visibles_con_texto(self):
        self.assertIn("EN VIVO", self._html(_estado=radios.EN_VIVO))
        self.assertIn("Transmisión no disponible temporalmente", self._html(_estado=radios.NO_DISPONIBLE))

    def test_sin_transmision_no_tiene_boton(self):
        html = self._html(stream_url=None, _estado=radios.SIN_TRANSMISION)
        self.assertIn("Sin transmisión online disponible", html)
        self.assertNotIn("boton-escuchar", html)

    def test_hls_con_tipo_y_reproductor_oficial_alternativo(self):
        html = self._html(stream_url="https://stream.test/live/playlist.m3u8", tipo_stream="hls",
                          player_url="https://radio.test/player")
        self.assertIn('data-tipo="hls"', html)
        self.assertIn("Reproductor oficial", html)

    def test_solo_player_oficial_abre_enlace(self):
        html = self._html(stream_url=None, player_url="https://radio.test/player")
        self.assertIn('href="https://radio.test/player"', html)
        self.assertNotIn("data-stream", html)

    def test_escapa_texto(self):
        self.assertNotIn("<script>", self._html(nombre="<script>x</script>"))


class TestSitioRadios(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config = self.tmp / "radios.json"
        parches = [
            patch.object(generador_mod, "CACHE_CLASIFICACION_DEFAULT", self.tmp / "clasificacion.json"),
            patch.object(generador_mod, "ValidadorImagenes",
                         lambda: ValidadorImagenes(cache_path=self.tmp / "imagenes.json", consultar=lambda url: True)),
            patch("motor_noticias.informe_diario_datos.DIRECTORIO_DEFAULT", self.tmp / "informe_diario"),
            patch("motor_noticias.radios.CONFIG_PATH_DEFAULT", self.config),
            patch("motor_noticias.radios.ESTADO_PATH_DEFAULT", self.tmp / "radios_estado.json"),
            patch("motor_noticias.radios.verificar_stream", lambda url, **kw: {"ok": url.endswith("ok.mp3"), "error": None}),
            patch.dict("os.environ", {"LEDESMA_RADIOS_DEMO": ""}),
        ]
        for p in parches:
            p.start()
            self.addCleanup(p.stop)
        self.salida = self.tmp / "salida"

    def _generar(self, lista):
        self.config.write_text(json.dumps({"radios": lista}), encoding="utf-8")
        generar_sitio(self.tmp / "test.db", self.salida, base_url="https://ledesmaparticipa.com.ar", ahora=AHORA)

    def _api(self, ruta):
        return json.loads((self.salida / "api" / ruta).read_text(encoding="utf-8"))

    def test_api_y_filtro_por_zona(self):
        self._generar([
            _radio(id="lib", stream_url="https://s.test/ok.mp3"), _radio(id="jujuy", zona="Jujuy", stream_url="https://s.test/caida.mp3"),
            _radio(id="off", activa=False),
        ])
        self.assertEqual([r["id"] for r in self._api("radios.json")], ["lib", "jujuy"])
        self.assertEqual([r["id"] for r in self._api("radios/zona/libertador.json")], ["lib"])
        self.assertEqual([r["id"] for r in self._api("radios/zona/jujuy.json")], ["jujuy"])
        self.assertEqual(self._api("radios/zona/argentina.json"), [])
        self.assertEqual(self._api("radios/lib.json")["estado_transmision"], "en_vivo")
        self.assertEqual(self._api("radios/jujuy/status.json")["estado_transmision"], "no_disponible")
        self.assertFalse((self.salida / "api" / "radios" / "off.json").exists())
        html = (self.salida / "radios" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-zona="libertador"', html)
        self.assertIn("Transmisión no disponible temporalmente", html)
        self.assertIn('href="radios/"', (self.salida / "index.html").read_text(encoding="utf-8"))

    def test_baja_borra_json_viejo(self):
        self._generar([_radio(id="vieja")])
        self.assertTrue((self.salida / "api" / "radios" / "vieja.json").exists())
        self._generar([_radio(id="vieja", estado="baja")])
        self.assertFalse((self.salida / "api" / "radios" / "vieja.json").exists())
        self.assertEqual(self._api("radios.json"), [])

    def test_sin_radios_pagina_vacia_y_multimedia(self):
        self._generar([])
        self.assertEqual(self._api("radios.json"), [])
        html = (self.salida / "radios" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Estamos sumando las radios", html)
        multimedia = (self.salida / "multimedia" / "index.html").read_text(encoding="utf-8")
        for texto in ("Videos", "Radios en vivo", "Entrevistas", "Podcast", "Próximamente"):
            self.assertIn(texto, multimedia)
        self.assertNotIn('href="radios/"', (self.salida / "index.html").read_text(encoding="utf-8"),
                         "sin radios no se agrega el acceso directo al menú")
        self.assertIn('href="multimedia/"', (self.salida / "index.html").read_text(encoding="utf-8"))
        self.assertTrue((self.salida / "assets" / "radio.js").exists())

    def test_demo_no_se_publica_sin_variable(self):
        self._generar([_radio(id="fm-demo", demo=True)])
        self.assertEqual(self._api("radios.json"), [])
        self.assertNotIn("DEMO", json.dumps(self._api("radios.json")))

    def test_falla_de_radios_no_rompe_el_sitio(self):
        with patch("motor_noticias.radios.cargar_radios", side_effect=RuntimeError("x")):
            self._generar([])
        self.assertTrue((self.salida / "index.html").exists())
        self.assertEqual(self._api("radios.json"), [])


@unittest.skipUnless(shutil.which("node"), "Node no instalado")
class TestReproductorWeb(unittest.TestCase):
    """Núcleo del mini reproductor (assets/radio.js) con audio y storage falsos."""

    def test_play_pause_persistencia_y_fallback(self):
        script = r"""
const assert = require("assert");
const { crearControlador, CLAVE } = require(process.argv[2]);
function storage() { const d = {}; return { getItem: k => d[k] ?? null, setItem: (k, v) => { d[k] = String(v); }, removeItem: k => { delete d[k]; }, d }; }
function audio(modo) { return { src: "", volume: 1, pausas: 0, play() { return modo === "ok" ? Promise.resolve() : Promise.reject(Object.assign(new Error("x"), { name: modo })); }, pause() { this.pausas++; }, removeAttribute() { this.src = ""; } }; }
const radio = { id: "r1", nombre: "Radio Test", dial: "95.5 FM", stream: "https://stream.test/a.mp3" };
(async () => {
  const s = storage(), a = audio("ok");
  const c = crearControlador({ storage: s, audio: a });
  await c.reproducir(radio);
  assert.strictEqual(a.src, radio.stream);
  assert.strictEqual(c.estado().reproduciendo, true);
  assert.strictEqual(c.estado().mensaje, "En vivo");
  await c.alternar();
  assert.strictEqual(c.estado().reproduciendo, false);
  assert.strictEqual(a.pausas, 1);
  await c.alternar();
  assert.strictEqual(c.estado().reproduciendo, true);
  c.volumen(0.4);
  // Persistencia: otra página restaura la misma radio y vuelve a sonar.
  const a2 = audio("ok"), c2 = crearControlador({ storage: s, audio: a2 });
  assert.strictEqual(await c2.restaurar(), true);
  assert.strictEqual(c2.estado().radio.id, "r1");
  assert.strictEqual(c2.estado().reproduciendo, true);
  assert.strictEqual(a2.volume, 0.4);
  // Autoplay bloqueado: queda en pausa con aviso, sin estado falso.
  const c3 = crearControlador({ storage: s, audio: audio("NotAllowedError") });
  await c3.restaurar();
  assert.strictEqual(c3.estado().reproduciendo, false);
  assert.match(c3.estado().mensaje, /Tocá Reproducir/);
  // Stream inválido: aviso de no disponible.
  const c4 = crearControlador({ storage: storage(), audio: audio("NotSupportedError") });
  await c4.reproducir(radio);
  assert.strictEqual(c4.estado().mensaje, "Transmisión no disponible temporalmente");
  // HLS en navegador sin soporte nativo: aviso claro, no se intenta ni se convierte.
  const aHls = Object.assign(audio("ok"), { canPlayType: () => "" });
  const cHls = crearControlador({ storage: storage(), audio: aHls });
  await cHls.reproducir(Object.assign({}, radio, { tipo: "hls" }));
  assert.strictEqual(cHls.estado().reproduciendo, false);
  assert.match(cHls.estado().mensaje, /HLS/);
  const cHlsOk = crearControlador({ storage: storage(), audio: Object.assign(audio("ok"), { canPlayType: () => "maybe" }) });
  await cHlsOk.reproducir(Object.assign({}, radio, { tipo: "hls" }));
  assert.strictEqual(cHlsOk.estado().reproduciendo, true);
  // Cerrar: limpia el estado guardado.
  c2.cerrar();
  assert.strictEqual(s.getItem(CLAVE), null);
  assert.strictEqual(await crearControlador({ storage: s, audio: audio("ok") }).restaurar(), false);
  console.log("OK");
})().catch(e => { console.error(e); process.exit(1); });
"""
        ruta_js = RAIZ / "motor_noticias" / "sitio" / "assets_fuente" / "radio.js"
        with tempfile.TemporaryDirectory() as tmp:
            prueba = Path(tmp) / "prueba.js"
            prueba.write_text(script, encoding="utf-8")
            r = subprocess.run(["node", str(prueba), str(ruta_js)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
