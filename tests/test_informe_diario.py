import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from motor_noticias.db import Database
from motor_noticias.informe_diario import (
    DESCRIPCION_CLIMA_DESCONOCIDA,
    ErrorInformeDiario,
    NOMBRE_SALUD,
    ResultadoInformeDiario,
    _codigo_clima_a_texto,
    generar_informe_diario,
    obtener_clima,
    obtener_dolar,
)
from motor_noticias.models import Estado, RevisionEstado
from motor_noticias.motor_editorial import ZONA_JUJUY

CLIMA_VALIDO = {
    "current": {"time": "2026-08-13T07:15", "temperature_2m": 12.3, "weather_code": 2},
    "daily": {
        "temperature_2m_max": [22.1],
        "temperature_2m_min": [8.4],
        "precipitation_probability_max": [10],
    },
}
DOLAR_OFICIAL_VALIDO = {
    "moneda": "USD",
    "casa": "oficial",
    "nombre": "Oficial",
    "compra": 1495,
    "venta": 1515,
    "fechaActualizacion": "2026-08-13T07:00:00.000Z",
}
DOLAR_BLUE_VALIDO = {
    "moneda": "USD",
    "casa": "blue",
    "nombre": "Blue",
    "compra": 1500,
    "venta": 1540,
    "fechaActualizacion": "2026-08-13T06:50:00.000Z",
}


def _respuesta_falsa(data, status=200):
    respuesta = MagicMock()
    respuesta.status = status
    respuesta.read.return_value = json.dumps(data).encode("utf-8")
    respuesta.__enter__.return_value = respuesta
    respuesta.__exit__.return_value = False
    return respuesta


def _urlopen_fake(clima=CLIMA_VALIDO, oficial=DOLAR_OFICIAL_VALIDO, blue=DOLAR_BLUE_VALIDO):
    def _abrir(peticion, timeout=None):
        url = peticion.full_url
        if "open-meteo" in url:
            return _respuesta_falsa(clima)
        if url.rstrip("/").endswith("/oficial"):
            return _respuesta_falsa(oficial)
        if url.rstrip("/").endswith("/blue"):
            return _respuesta_falsa(blue)
        raise AssertionError(f"URL inesperada: {url}")

    return _abrir


# 3. conversión correcta del código meteorológico a texto
class TestHeadersHttp(unittest.TestCase):
    """Bug real detectado en producción: DolarApi (Cloudflare) devolvía
    HTTP 403 a una petición sin User-Agent. Se verifica explícitamente que
    toda solicitud saliente (clima y dólar, mismo cliente común) incluya
    User-Agent y Accept."""

    def _capturar_peticiones(self, respuesta_data):
        peticiones = []

        def _abrir(peticion, timeout=None):
            peticiones.append(peticion)
            return _respuesta_falsa(respuesta_data)

        return peticiones, _abrir

    def test_clima_envia_user_agent_y_accept(self):
        peticiones, urlopen_fake = self._capturar_peticiones(CLIMA_VALIDO)
        obtener_clima(urlopen=urlopen_fake)

        self.assertEqual(len(peticiones), 1)
        self.assertEqual(peticiones[0].get_header("User-agent"), "Mozilla/5.0 LedesmaParticipa/1.0")
        self.assertEqual(peticiones[0].get_header("Accept"), "application/json")

    def test_dolar_oficial_envia_user_agent_y_accept(self):
        peticiones, urlopen_fake = self._capturar_peticiones(DOLAR_OFICIAL_VALIDO)
        obtener_dolar("oficial", urlopen=urlopen_fake)

        self.assertEqual(len(peticiones), 1)
        self.assertEqual(peticiones[0].get_header("User-agent"), "Mozilla/5.0 LedesmaParticipa/1.0")
        self.assertEqual(peticiones[0].get_header("Accept"), "application/json")

    def test_dolar_blue_envia_user_agent_y_accept(self):
        peticiones, urlopen_fake = self._capturar_peticiones(DOLAR_BLUE_VALIDO)
        obtener_dolar("blue", urlopen=urlopen_fake)

        self.assertEqual(len(peticiones), 1)
        self.assertEqual(peticiones[0].get_header("User-agent"), "Mozilla/5.0 LedesmaParticipa/1.0")
        self.assertEqual(peticiones[0].get_header("Accept"), "application/json")

    def test_generar_informe_diario_envia_headers_en_las_tres_solicitudes(self):
        peticiones = []
        urlopen_original = _urlopen_fake()

        def _urlopen_espia(peticion, timeout=None):
            peticiones.append(peticion)
            return urlopen_original(peticion, timeout=timeout)

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "test.db")
            try:
                generar_informe_diario(db, urlopen=_urlopen_espia)
            finally:
                db.close()

        self.assertEqual(len(peticiones), 3)  # clima + dólar oficial + dólar blue
        for peticion in peticiones:
            with self.subTest(url=peticion.full_url):
                self.assertEqual(peticion.get_header("User-agent"), "Mozilla/5.0 LedesmaParticipa/1.0")
                self.assertEqual(peticion.get_header("Accept"), "application/json")


class TestCodigoClima(unittest.TestCase):
    def test_codigos_conocidos_se_traducen(self):
        self.assertEqual(_codigo_clima_a_texto(0), "despejado")
        self.assertEqual(_codigo_clima_a_texto(2), "parcialmente nublado")
        self.assertEqual(_codigo_clima_a_texto(61), "con lluvia débil")
        self.assertEqual(_codigo_clima_a_texto(95), "con tormenta")

    def test_codigo_desconocido_no_inventa_una_condicion(self):
        self.assertEqual(_codigo_clima_a_texto(12345), DESCRIPCION_CLIMA_DESCONOCIDA)
        self.assertEqual(_codigo_clima_a_texto(None), DESCRIPCION_CLIMA_DESCONOCIDA)


# 1. respuesta válida de clima
class TestObtenerClima(unittest.TestCase):
    def test_respuesta_valida_se_parsea_correctamente(self):
        clima = obtener_clima(urlopen=_urlopen_fake())
        self.assertEqual(clima.descripcion, "parcialmente nublado")
        self.assertEqual(clima.temperatura_actual, 12.3)
        self.assertEqual(clima.temperatura_minima, 8.4)
        self.assertEqual(clima.temperatura_maxima, 22.1)
        self.assertEqual(clima.probabilidad_lluvia_maxima, 10)
        self.assertEqual(clima.actualizado_en, "2026-08-13T07:15")

    # 7. rechazo de datos incompletos
    def test_rechaza_respuesta_sin_current(self):
        clima_incompleto = {"daily": CLIMA_VALIDO["daily"]}
        with self.assertRaises(ErrorInformeDiario):
            obtener_clima(urlopen=_urlopen_fake(clima=clima_incompleto))

    def test_rechaza_respuesta_sin_daily(self):
        clima_incompleto = {"current": CLIMA_VALIDO["current"]}
        with self.assertRaises(ErrorInformeDiario):
            obtener_clima(urlopen=_urlopen_fake(clima=clima_incompleto))

    def test_rechaza_lista_daily_vacia(self):
        clima_vacio = {
            "current": CLIMA_VALIDO["current"],
            "daily": {"temperature_2m_max": [], "temperature_2m_min": [8.4], "precipitation_probability_max": [10]},
        }
        with self.assertRaises(ErrorInformeDiario):
            obtener_clima(urlopen=_urlopen_fake(clima=clima_vacio))

    # 8. rechazo de valores inválidos
    def test_rechaza_temperatura_no_numerica(self):
        clima_invalido = {
            "current": {"time": "2026-08-13T07:15", "temperature_2m": "no es un número", "weather_code": 2},
            "daily": CLIMA_VALIDO["daily"],
        }
        with self.assertRaises(ErrorInformeDiario):
            obtener_clima(urlopen=_urlopen_fake(clima=clima_invalido))

    def test_rechaza_weather_code_no_entero(self):
        clima_invalido = {
            "current": {"time": "2026-08-13T07:15", "temperature_2m": 12.3, "weather_code": "nublado"},
            "daily": CLIMA_VALIDO["daily"],
        }
        with self.assertRaises(ErrorInformeDiario):
            obtener_clima(urlopen=_urlopen_fake(clima=clima_invalido))

    # 9. timeout o error HTTP
    def test_timeout_produce_error_controlado(self):
        def _urlopen_timeout(peticion, timeout=None):
            raise TimeoutError("timed out")

        with self.assertRaises(ErrorInformeDiario):
            obtener_clima(urlopen=_urlopen_timeout)

    def test_http_error_produce_error_controlado(self):
        def _urlopen_http_error(peticion, timeout=None):
            raise urllib.error.HTTPError(url=peticion.full_url, code=503, msg="Service Unavailable", hdrs=None, fp=None)

        with self.assertRaises(ErrorInformeDiario) as contexto:
            obtener_clima(urlopen=_urlopen_http_error)
        self.assertIn("503", str(contexto.exception))

    def test_json_invalido_produce_error_controlado(self):
        def _urlopen_json_invalido(peticion, timeout=None):
            respuesta = MagicMock()
            respuesta.status = 200
            respuesta.read.return_value = b"esto no es json"
            respuesta.__enter__.return_value = respuesta
            respuesta.__exit__.return_value = False
            return respuesta

        with self.assertRaises(ErrorInformeDiario):
            obtener_clima(urlopen=_urlopen_json_invalido)


# 2. respuesta válida de dólar oficial y blue
class TestObtenerDolar(unittest.TestCase):
    def test_dolar_oficial_valido(self):
        dolar = obtener_dolar("oficial", urlopen=_urlopen_fake())
        self.assertEqual(dolar.compra, 1495)
        self.assertEqual(dolar.venta, 1515)
        self.assertEqual(dolar.actualizado_en, "2026-08-13T07:00:00.000Z")

    def test_dolar_blue_valido(self):
        dolar = obtener_dolar("blue", urlopen=_urlopen_fake())
        self.assertEqual(dolar.compra, 1500)
        self.assertEqual(dolar.venta, 1540)

    # 7/8. datos incompletos / inválidos
    def test_rechaza_dolar_sin_venta(self):
        with self.assertRaises(ErrorInformeDiario):
            obtener_dolar("oficial", urlopen=_urlopen_fake(oficial={"compra": 1495, "fechaActualizacion": "x"}))

    def test_rechaza_dolar_con_compra_no_numerica(self):
        invalido = {"compra": "mil", "venta": 1515, "fechaActualizacion": "2026-08-13T07:00:00.000Z"}
        with self.assertRaises(ErrorInformeDiario):
            obtener_dolar("oficial", urlopen=_urlopen_fake(oficial=invalido))

    def test_rechaza_dolar_sin_fecha_actualizacion(self):
        invalido = {"compra": 1495, "venta": 1515}
        with self.assertRaises(ErrorInformeDiario):
            obtener_dolar("oficial", urlopen=_urlopen_fake(oficial=invalido))


class BaseInformeDiarioTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()


# 4. creación del informe / 5. estado pendiente / 10. timezone local
class TestCreacionDelInforme(BaseInformeDiarioTest):
    def test_genera_el_informe_con_los_datos_esperados(self):
        ahora = datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc)  # 07:30 Jujuy
        resultado = generar_informe_diario(self.db, ahora=ahora, urlopen=_urlopen_fake())

        self.assertEqual(resultado.resultado, "preparada")
        self.assertIsNotNone(resultado.noticia_id)
        self.assertEqual(resultado.fecha_local, "2026-08-13")

        noticia = self.db.obtener(resultado.noticia_id)
        self.assertIn("Libertador", noticia["titulo_preparado"])
        self.assertIn("13/08/2026", noticia["titulo_preparado"])
        self.assertIn("12.3", noticia["texto_preparado"])
        self.assertIn("1495", noticia["texto_preparado"])
        self.assertIn("1540", noticia["texto_preparado"])

    def test_estado_preparada_y_revision_pendiente(self):
        resultado = generar_informe_diario(self.db, urlopen=_urlopen_fake())
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertEqual(noticia["estado"], Estado.PREPARADA.value)
        self.assertEqual(noticia["revision_estado"], RevisionEstado.PENDIENTE.value)

    def test_territorio_local_texto_determinista_sin_ollama(self):
        # El texto ya viene armado por completo; nunca se llama a un
        # redactor con IA para construirlo.
        resultado = generar_informe_diario(self.db, urlopen=_urlopen_fake())
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertEqual(noticia["territorio"], "local")
        # el texto preparado es exactamente el texto original armado
        self.assertEqual(noticia["texto_preparado"], noticia["texto_original"])
        self.assertEqual(noticia["titulo_preparado"], noticia["titulo_original"])

    def test_identifica_el_contenido_como_informe_de_servicio(self):
        resultado = generar_informe_diario(self.db, urlopen=_urlopen_fake())
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertIn("Informe Diario", noticia["nombre_fuente"])
        self.assertIn("generado automáticamente", noticia["texto_preparado"])
        self.assertIn("Open-Meteo", noticia["texto_preparado"])
        self.assertIn("DolarApi", noticia["texto_preparado"])

    # 10. timezone local
    def test_usa_la_fecha_local_de_jujuy_no_utc(self):
        # 2026-08-14 02:00 UTC son las 2026-08-13 23:00 en Jujuy (UTC-3):
        # la fecha del informe debe ser la de Jujuy, no la de UTC.
        ahora_utc_de_madrugada = datetime(2026, 8, 14, 2, 0, tzinfo=timezone.utc)
        resultado = generar_informe_diario(self.db, ahora=ahora_utc_de_madrugada, urlopen=_urlopen_fake())
        self.assertEqual(resultado.fecha_local, "2026-08-13")

    def test_registra_salud_ok_al_generar(self):
        generar_informe_diario(self.db, urlopen=_urlopen_fake())
        salud = self.db.obtener_salud_fuente(NOMBRE_SALUD)
        self.assertEqual(salud["ultimo_resultado"], "ok")
        self.assertEqual(salud["noticias_nuevas"], 1)


# 6. idempotencia diaria
class TestIdempotenciaDiaria(BaseInformeDiarioTest):
    def test_segunda_generacion_el_mismo_dia_no_duplica(self):
        ahora = datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc)
        r1 = generar_informe_diario(self.db, ahora=ahora, urlopen=_urlopen_fake())
        r2 = generar_informe_diario(self.db, ahora=ahora, urlopen=_urlopen_fake())

        self.assertEqual(r1.resultado, "preparada")
        self.assertEqual(r2.resultado, "duplicado")
        self.assertIsNone(r2.noticia_id)
        self.assertEqual(len(self.db.listar()), 1)

    def test_segunda_generacion_el_mismo_dia_con_valores_distintos_tampoco_duplica(self):
        # Aunque los valores de clima/dólar cambien levemente entre
        # reintentos (p.ej. tras un reintento de la tarea programada), debe
        # seguir siendo como máximo un informe por fecha local.
        ahora = datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc)
        r1 = generar_informe_diario(self.db, ahora=ahora, urlopen=_urlopen_fake())

        clima_distinto = dict(CLIMA_VALIDO)
        clima_distinto["current"] = {**CLIMA_VALIDO["current"], "temperature_2m": 15.9}
        r2 = generar_informe_diario(
            self.db, ahora=ahora, urlopen=_urlopen_fake(clima=clima_distinto)
        )

        self.assertEqual(r1.resultado, "preparada")
        self.assertEqual(r2.resultado, "duplicado")
        self.assertEqual(len(self.db.listar()), 1)

    def test_dias_distintos_generan_informes_distintos(self):
        ahora_dia1 = datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc)
        ahora_dia2 = datetime(2026, 8, 14, 10, 30, tzinfo=timezone.utc)

        r1 = generar_informe_diario(self.db, ahora=ahora_dia1, urlopen=_urlopen_fake())
        r2 = generar_informe_diario(self.db, ahora=ahora_dia2, urlopen=_urlopen_fake())

        self.assertEqual(r1.resultado, "preparada")
        self.assertEqual(r2.resultado, "preparada")
        self.assertNotEqual(r1.noticia_id, r2.noticia_id)
        self.assertEqual(len(self.db.listar()), 2)

    def test_duplicado_registra_salud_ok_sin_noticias_nuevas(self):
        ahora = datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc)
        generar_informe_diario(self.db, ahora=ahora, urlopen=_urlopen_fake())
        generar_informe_diario(self.db, ahora=ahora, urlopen=_urlopen_fake())

        salud = self.db.obtener_salud_fuente(NOMBRE_SALUD)
        self.assertEqual(salud["ultimo_resultado"], "ok")
        self.assertEqual(salud["noticias_nuevas"], 0)


# 7/8/9. no crea informe incompleto/engañoso ante error de cualquiera de las dos fuentes
class TestErroresNoCreanInformeIncompleto(BaseInformeDiarioTest):
    def test_falla_clima_no_crea_ningun_informe(self):
        def _urlopen_clima_caido(peticion, timeout=None):
            if "open-meteo" in peticion.full_url:
                raise urllib.error.URLError("conexión rechazada")
            return _respuesta_falsa(DOLAR_OFICIAL_VALIDO)

        resultado = generar_informe_diario(self.db, urlopen=_urlopen_clima_caido)

        self.assertEqual(resultado.resultado, "error")
        self.assertIsNotNone(resultado.mensaje_error)
        self.assertEqual(self.db.listar(), [])

    def test_falla_dolar_no_crea_ningun_informe(self):
        def _urlopen_dolar_caido(peticion, timeout=None):
            if "open-meteo" in peticion.full_url:
                return _respuesta_falsa(CLIMA_VALIDO)
            raise urllib.error.URLError("conexión rechazada")

        resultado = generar_informe_diario(self.db, urlopen=_urlopen_dolar_caido)

        self.assertEqual(resultado.resultado, "error")
        self.assertEqual(self.db.listar(), [])

    def test_error_permite_reintento_posterior_exitoso(self):
        def _urlopen_falla_siempre(peticion, timeout=None):
            raise urllib.error.URLError("conexión rechazada")

        r1 = generar_informe_diario(self.db, urlopen=_urlopen_falla_siempre)
        self.assertEqual(r1.resultado, "error")

        r2 = generar_informe_diario(self.db, urlopen=_urlopen_fake())
        self.assertEqual(r2.resultado, "preparada")

    def test_error_registra_salud_error_con_mensaje(self):
        def _urlopen_falla(peticion, timeout=None):
            raise urllib.error.URLError("conexión rechazada")

        generar_informe_diario(self.db, urlopen=_urlopen_falla)

        salud = self.db.obtener_salud_fuente(NOMBRE_SALUD)
        self.assertEqual(salud["ultimo_resultado"], "error")
        self.assertIsNotNone(salud["ultimo_error"])


if __name__ == "__main__":
    unittest.main()
