import http.client
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from motor_noticias.db import Database
from motor_noticias.ingreso_manual import (
    LONGITUD_MAXIMA_FUENTE,
    LONGITUD_MAXIMA_OBSERVACION,
    LONGITUD_MAXIMA_TEXTO,
    LONGITUD_MAXIMA_TITULO,
    ErrorIngresoManual,
    cargar_noticia_manual,
)
from motor_noticias.models import Estado, OrigenIngreso, RevisionEstado
from motor_noticias.motor_editorial import ZONA_JUJUY, generar_agenda
from motor_noticias.panel.server import HOST, PanelHandler
from motor_noticias.redaccion.mock import RedactorMock

from tests.test_motor_editorial import AHORA, _crear_noticia

TEXTO_LOCAL = (
    "Vecinos de Libertador General San Martín reclamaron por el estado de una plaza del barrio "
    "y pidieron a la Municipalidad que intervenga antes de que empiecen las lluvias."
)
TEXTO_DEPARTAMENTAL = (
    "Productores de Calilegua, en el Departamento Ledesma, presentaron un proyecto de riego "
    "comunitario ante las autoridades locales durante una reunión vecinal."
)
TEXTO_PROVINCIAL = (
    "La Legislatura de Jujuy debatirá esta semana un proyecto de ley vinculado al turismo "
    "provincial, según informaron fuentes parlamentarias."
)
TEXTO_POLITICO = (
    "El Intendente de Libertador General San Martín anunció junto al Concejo Deliberante un "
    "nuevo programa municipal de obras públicas para el próximo trimestre."
)
TEXTO_INSUFICIENTE_PROVINCIAL = (
    "Publicidad. Suscribite a nuestro canal de Jujuy para más contenido patrocinado."
)


class BaseIngresoManualTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()


# 1. carga manual válida
class TestCargaManualValida(BaseIngresoManualTest):
    def test_carga_manual_valida(self):
        resultado = cargar_noticia_manual(
            self.db,
            self.redactor,
            fuente="Ledesma Soy",
            texto=TEXTO_LOCAL,
            titulo="Reclamo vecinal por una plaza",
            url="https://facebook.com/ledesmasoy/posts/1",
        )
        self.assertIsNotNone(resultado.noticia_id)
        self.assertEqual(resultado.resultado_pipeline, "preparada")
        self.assertFalse(resultado.duplicado)
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertEqual(noticia["origen_ingreso"], OrigenIngreso.MANUAL.value)
        self.assertEqual(noticia["nombre_fuente"], "Ledesma Soy")

    # 2. fuente obligatoria
    def test_fuente_obligatoria(self):
        with self.assertRaises(ErrorIngresoManual):
            cargar_noticia_manual(self.db, self.redactor, fuente="   ", texto=TEXTO_LOCAL)
        self.assertEqual(self.db.listar(), [])

    # 3. texto obligatorio
    def test_texto_obligatorio(self):
        with self.assertRaises(ErrorIngresoManual):
            cargar_noticia_manual(self.db, self.redactor, fuente="Ledesma Soy", texto="   ")
        self.assertEqual(self.db.listar(), [])

    def test_texto_obligatorio_no_alcanza_solo_con_url(self):
        with self.assertRaises(ErrorIngresoManual):
            cargar_noticia_manual(
                self.db, self.redactor, fuente="Ledesma Soy", texto="", url="https://ejemplo.test/nota"
            )

    # 4. URL opcional
    def test_url_opcional(self):
        resultado = cargar_noticia_manual(
            self.db, self.redactor, fuente="Vecino", texto=TEXTO_LOCAL
        )
        self.assertEqual(resultado.resultado_pipeline, "preparada")
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertTrue(noticia["url_fuente"])  # referencia sintética, nunca vacía

    # 5. URL inválida rechazada
    def test_url_invalida_rechazada(self):
        for url_invalida in ("ftp://ejemplo.test/x", "javascript:alert(1)", "no-es-una-url"):
            with self.subTest(url=url_invalida):
                with self.assertRaises(ErrorIngresoManual):
                    cargar_noticia_manual(
                        self.db, self.redactor, fuente="Vecino", texto=TEXTO_LOCAL, url=url_invalida
                    )

    # 6. título opcional
    def test_titulo_opcional(self):
        resultado = cargar_noticia_manual(self.db, self.redactor, fuente="Vecino", texto=TEXTO_LOCAL)
        self.assertTrue(resultado.titulo_original)
        # no se inventa nada: el título es un recorte literal del propio texto
        self.assertTrue(TEXTO_LOCAL.startswith(resultado.titulo_original.rstrip("…").rstrip()))

    # 7. localidad opcional
    def test_localidad_opcional(self):
        resultado = cargar_noticia_manual(
            self.db,
            self.redactor,
            fuente="Vecino",
            texto=TEXTO_LOCAL,
            localidad_informada="Libertador General San Martín",
        )
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertEqual(noticia["localidad_informada"], "Libertador General San Martín")

    # 8. observación interna no entra al contenido público
    def test_observacion_interna_no_entra_al_contenido_publico(self):
        resultado = cargar_noticia_manual(
            self.db,
            self.redactor,
            fuente="Vecino",
            texto=TEXTO_LOCAL,
            observacion_interna="confirmar con otra fuente",
        )
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertEqual(noticia["observacion_interna"], "confirmar con otra fuente")
        self.assertNotIn("confirmar con otra fuente", noticia["titulo_preparado"] or "")
        self.assertNotIn("confirmar con otra fuente", noticia["texto_preparado"] or "")

    # 9. urgente false por defecto
    def test_urgente_false_por_defecto(self):
        resultado = cargar_noticia_manual(self.db, self.redactor, fuente="Vecino", texto=TEXTO_LOCAL)
        self.assertFalse(resultado.urgente)
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertEqual(noticia["urgente"], 0)

    # 10. urgente true persistido
    def test_urgente_true_persistido(self):
        resultado = cargar_noticia_manual(
            self.db, self.redactor, fuente="Vecino", texto=TEXTO_LOCAL, urgente=True
        )
        self.assertTrue(resultado.urgente)
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertEqual(noticia["urgente"], 1)

    # 11. origen manual persistido
    def test_origen_manual_persistido(self):
        resultado = cargar_noticia_manual(self.db, self.redactor, fuente="Vecino", texto=TEXTO_LOCAL)
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertEqual(noticia["origen_ingreso"], "manual")

    # 12. fecha de carga persistida
    def test_fecha_de_carga_persistida(self):
        antes = datetime.now(timezone.utc)
        resultado = cargar_noticia_manual(self.db, self.redactor, fuente="Vecino", texto=TEXTO_LOCAL)
        noticia = self.db.obtener(resultado.noticia_id)
        fecha_recoleccion = datetime.fromisoformat(noticia["fecha_recoleccion"])
        self.assertGreaterEqual(fecha_recoleccion, antes)

    # 13. fecha de origen opcional
    def test_fecha_de_origen_opcional(self):
        resultado = cargar_noticia_manual(
            self.db, self.redactor, fuente="Vecino", texto=TEXTO_LOCAL, fecha_origen="12/08/2026 18:30"
        )
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertEqual(noticia["fecha_fuente"], "12/08/2026 18:30")

        resultado_sin_fecha = cargar_noticia_manual(
            self.db, self.redactor, fuente="Vecino", texto=TEXTO_LOCAL + " Segunda nota distinta."
        )
        noticia_sin_fecha = self.db.obtener(resultado_sin_fecha.noticia_id)
        self.assertEqual(noticia_sin_fecha["fecha_fuente"], "")  # no se inventa fecha de origen


# 14-15. deduplicación
class TestDeduplicacion(BaseIngresoManualTest):
    def test_dedupe_por_url(self):
        cargar_noticia_manual(
            self.db, self.redactor, fuente="Ledesma Soy", texto=TEXTO_LOCAL, url="https://ejemplo.test/nota-1"
        )
        resultado = cargar_noticia_manual(
            self.db,
            self.redactor,
            fuente="Ledesma Soy",
            texto=TEXTO_LOCAL + " (con algo de texto distinto agregado)",
            url="https://ejemplo.test/nota-1",
        )
        self.assertTrue(resultado.duplicado)
        self.assertIsNone(resultado.noticia_id)
        self.assertEqual(len(self.db.listar()), 1)

    def test_dedupe_por_contenido_sin_url(self):
        cargar_noticia_manual(self.db, self.redactor, fuente="Vecino", texto=TEXTO_LOCAL, titulo="Título A")
        resultado = cargar_noticia_manual(
            self.db, self.redactor, fuente="Otro vecino", texto=TEXTO_LOCAL, titulo="Título A"
        )
        self.assertTrue(resultado.duplicado)
        self.assertEqual(len(self.db.listar()), 1)


# 16-18. clasificación territorial
class TestClasificacionTerritorial(BaseIngresoManualTest):
    def test_manual_local(self):
        resultado = cargar_noticia_manual(self.db, self.redactor, fuente="Vecino", texto=TEXTO_LOCAL)
        self.assertEqual(resultado.territorio, "local")

    def test_manual_departamental(self):
        resultado = cargar_noticia_manual(self.db, self.redactor, fuente="Vecino", texto=TEXTO_DEPARTAMENTAL)
        self.assertEqual(resultado.territorio, "departamental")

    def test_manual_provincial(self):
        resultado = cargar_noticia_manual(self.db, self.redactor, fuente="Vecino", texto=TEXTO_PROVINCIAL)
        self.assertEqual(resultado.territorio, "provincial")

    def test_localidad_informada_no_fuerza_clasificacion_contradictoria(self):
        # Se sugiere "Libertador" como localidad pero el texto no tiene
        # ninguna relación real con Libertador ni Jujuy: no debe forzarse a local.
        resultado = cargar_noticia_manual(
            self.db,
            self.redactor,
            fuente="Vecino",
            texto="Un grupo de científicos de Estados Unidos anunció un hallazgo sobre el clima global.",
            localidad_informada="Libertador General San Martín",
        )
        self.assertNotEqual(resultado.territorio, "local")


# 19. riesgo político preservado
class TestRiesgoEditorial(BaseIngresoManualTest):
    def test_riesgo_politico_preservado(self):
        resultado = cargar_noticia_manual(self.db, self.redactor, fuente="Vecino", texto=TEXTO_POLITICO)
        self.assertTrue(resultado.requiere_revision_especial)
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertTrue(noticia["requiere_revision_especial"])
        self.assertIsNotNone(noticia["categoria_riesgo"])

    # 20. contenido insuficiente no salta elegibilidad
    def test_contenido_insuficiente_no_salta_elegibilidad(self):
        resultado = cargar_noticia_manual(
            self.db, self.redactor, fuente="Vecino", texto=TEXTO_INSUFICIENTE_PROVINCIAL
        )
        self.assertEqual(resultado.territorio, "provincial")  # nivel con gate de elegibilidad
        self.assertEqual(resultado.resultado_pipeline, "descartada")
        self.assertEqual(resultado.estado, Estado.DESCARTADA.value)


# 21-23. integración con revisión y agenda
class TestIntegracionRevisionYAgenda(BaseIngresoManualTest):
    def test_noticia_manual_aparece_en_revision(self):
        cargar_noticia_manual(self.db, self.redactor, fuente="Ledesma Soy", texto=TEXTO_LOCAL)
        pendientes = self.db.listar_preparadas(RevisionEstado.PENDIENTE.value)
        self.assertEqual(len(pendientes), 1)
        self.assertEqual(pendientes[0]["origen_ingreso"], "manual")

    def test_etiqueta_manual_en_revision(self):
        from motor_noticias.panel.server import _lista_html

        cargar_noticia_manual(self.db, self.redactor, fuente="Ledesma Soy", texto=TEXTO_LOCAL)
        html = _lista_html(self.db, "pendientes")
        self.assertIn("MANUAL", html)

    def test_etiqueta_manual_en_agenda(self):
        from motor_noticias.panel.server import _agenda_html

        resultado = cargar_noticia_manual(self.db, self.redactor, fuente="Ledesma Soy", texto=TEXTO_LOCAL)
        hoy = datetime.now(ZONA_JUJUY).strftime("%Y-%m-%d")
        html = _agenda_html(self.db, hoy)
        self.assertIn("MANUAL", html)


# 24-29. integración con la agenda automática (franjas)
class TestIntegracionAgendaFranjas(BaseIngresoManualTest):
    def test_carga_local_mejora_franja_futura_provincial(self):
        provincial = _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(self.db, fecha="2026-08-12", horarios=("13:00",), ahora=AHORA)
        item_antes = self.db.obtener_agenda_item("2026-08-12", "13:00")
        self.assertEqual(item_antes["noticia_id"], provincial.id)

        with patch("motor_noticias.ingreso_manual.generar_agenda") as generar_agenda_mock:
            cargar_noticia_manual(self.db, self.redactor, fuente="Ledesma Soy", texto=TEXTO_LOCAL)
        # La función de dominio llama a generar_agenda(db) (hora real); acá
        # verificamos el mismo efecto con horario/ahora controlados, tal
        # como lo haría esa llamada si corriera en el horario simulado.
        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("13:00",), ahora=AHORA)
        self.assertEqual(entradas[0].territorio, "local")

    def test_carga_posterior_no_modifica_franja_pasada(self):
        # Se mockea el generar_agenda(db) interno (hora real) para que la
        # prueba sea determinística sin importar la hora real del entorno:
        # lo que se está probando es el freeze temporal de motor_editorial,
        # con horario/ahora controlados, no el disparo automático en sí
        # (que ya tiene su propia cobertura en test_agenda_automatica.py).
        provincial = _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)  # 08:00 ya pasó (AHORA=09:00)

        with patch("motor_noticias.ingreso_manual.generar_agenda"):
            cargar_noticia_manual(self.db, self.redactor, fuente="Ledesma Soy", texto=TEXTO_LOCAL)

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)
        self.assertEqual(entradas[0].noticia_id, provincial.id)
        self.assertEqual(entradas[0].estado, "existente")

    def test_carga_no_reemplaza_aprobada(self):
        provincial = _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(self.db, fecha="2026-08-12", horarios=("13:00",), ahora=AHORA)
        item = self.db.obtener_agenda_item("2026-08-12", "13:00")
        self.db.actualizar_revision(item["noticia_id"], "aprobada")

        with patch("motor_noticias.ingreso_manual.generar_agenda"):
            cargar_noticia_manual(self.db, self.redactor, fuente="Ledesma Soy", texto=TEXTO_LOCAL)

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("13:00",), ahora=AHORA)
        self.assertEqual(entradas[0].noticia_id, provincial.id)
        self.assertEqual(entradas[0].estado, "existente")

    def test_carga_no_reemplaza_rechazada(self):
        provincial = _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(self.db, fecha="2026-08-12", horarios=("13:00",), ahora=AHORA)
        item = self.db.obtener_agenda_item("2026-08-12", "13:00")
        self.db.actualizar_revision(item["noticia_id"], "rechazada")

        with patch("motor_noticias.ingreso_manual.generar_agenda"):
            cargar_noticia_manual(self.db, self.redactor, fuente="Ledesma Soy", texto=TEXTO_LOCAL)

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("13:00",), ahora=AHORA)
        self.assertEqual(entradas[0].noticia_id, provincial.id)
        self.assertEqual(entradas[0].estado, "existente")

    def test_carga_no_reemplaza_publicada(self):
        publicada = _crear_noticia(
            self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)), estado=Estado.PUBLICADA.value
        )
        creada_en = _iso(timedelta(hours=2))
        self.db.guardar_agenda_item("2026-08-12", "13:00", "normal", "provincial", publicada.id, creada_en)

        with patch("motor_noticias.ingreso_manual.generar_agenda"):
            cargar_noticia_manual(self.db, self.redactor, fuente="Ledesma Soy", texto=TEXTO_LOCAL)

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("13:00",), ahora=AHORA)
        self.assertEqual(entradas[0].noticia_id, publicada.id)
        self.assertEqual(entradas[0].estado, "existente")

    # 29. fallo de agenda no pierde la noticia manual
    def test_fallo_de_agenda_no_pierde_la_noticia_manual(self):
        with patch("motor_noticias.ingreso_manual.generar_agenda", side_effect=RuntimeError("boom")):
            resultado = cargar_noticia_manual(self.db, self.redactor, fuente="Ledesma Soy", texto=TEXTO_LOCAL)

        self.assertIsNotNone(resultado.noticia_id)
        self.assertEqual(resultado.resultado_pipeline, "preparada")
        self.assertFalse(resultado.agenda_actualizada)
        self.assertIn("boom", resultado.agenda_mensaje_error)
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertIsNotNone(noticia)
        self.assertEqual(noticia["estado"], Estado.PREPARADA.value)


def _iso(delta: timedelta = timedelta()) -> str:
    return (AHORA - delta).isoformat()


# 30-32. seguridad
class TestSeguridad(BaseIngresoManualTest):
    def test_escape_html_xss(self):
        texto_malicioso = TEXTO_LOCAL + ' <script>alert("xss")</script>'
        resultado = cargar_noticia_manual(
            self.db,
            self.redactor,
            fuente="Vecino",
            texto=texto_malicioso,
            titulo='<img src=x onerror=alert(1)>Título',
        )
        from motor_noticias.panel.server import _lista_html

        html = _lista_html(self.db, "pendientes")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src=x", html)  # el tag va escapado, nunca se interpreta como HTML
        self.assertIn("&lt;script&gt;", html)
        noticia = self.db.obtener(resultado.noticia_id)
        # el contenido crudo se conserva tal cual en la base (no se altera el dato)
        self.assertIn("<script>", noticia["texto_original"])

    def test_limites_de_longitud(self):
        with self.assertRaises(ErrorIngresoManual):
            cargar_noticia_manual(
                self.db, self.redactor, fuente="X" * (LONGITUD_MAXIMA_FUENTE + 1), texto=TEXTO_LOCAL
            )
        with self.assertRaises(ErrorIngresoManual):
            cargar_noticia_manual(
                self.db, self.redactor, fuente="Vecino", texto="X" * (LONGITUD_MAXIMA_TEXTO + 1)
            )
        with self.assertRaises(ErrorIngresoManual):
            cargar_noticia_manual(
                self.db,
                self.redactor,
                fuente="Vecino",
                texto=TEXTO_LOCAL,
                titulo="X" * (LONGITUD_MAXIMA_TITULO + 1),
            )
        with self.assertRaises(ErrorIngresoManual):
            cargar_noticia_manual(
                self.db,
                self.redactor,
                fuente="Vecino",
                texto=TEXTO_LOCAL,
                observacion_interna="X" * (LONGITUD_MAXIMA_OBSERVACION + 1),
            )
        # dentro del límite: no debe fallar
        cargar_noticia_manual(self.db, self.redactor, fuente="Vecino", texto=TEXTO_LOCAL)

    # 32. no se realiza request HTTP al URL pegado
    def test_no_se_realiza_request_http_a_la_url_pegada(self):
        with patch("urllib.request.urlopen") as urlopen_mock:
            resultado = cargar_noticia_manual(
                self.db,
                self.redactor,
                fuente="Ledesma Soy",
                texto=TEXTO_LOCAL,
                url="https://facebook.com/ledesmasoy/posts/999",
            )
        urlopen_mock.assert_not_called()
        self.assertEqual(resultado.resultado_pipeline, "preparada")


# 33-34. panel HTTP real
class TestPanelCargaNoticiaHTTP(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        Database(self.db_path).close()

        PanelHandler.db_path = self.db_path
        self.servidor = HTTPServer((HOST, 0), PanelHandler)
        self.puerto = self.servidor.server_address[1]
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)
        self.tmpdir.cleanup()

    def _conexion(self):
        return http.client.HTTPConnection(HOST, self.puerto, timeout=5)

    # 33. panel carga formulario
    def test_panel_carga_formulario(self):
        conn = self._conexion()
        conn.request("GET", "/cargar-noticia")
        resp = conn.getresponse()
        cuerpo = resp.read().decode("utf-8")
        conn.close()

        self.assertEqual(resp.status, 200)
        self.assertIn('name="fuente"', cuerpo)
        self.assertIn('name="texto"', cuerpo)
        self.assertIn("Cargar noticia", cuerpo)

    # 34. panel procesa POST
    def test_panel_procesa_post(self):
        cuerpo_form = urlencode(
            {
                "fuente": "Ledesma Soy",
                "texto": TEXTO_LOCAL,
                "titulo": "Reclamo vecinal",
                "url": "https://facebook.com/ledesmasoy/posts/42",
            }
        )
        conn = self._conexion()
        conn.request(
            "POST",
            "/cargar-noticia",
            body=cuerpo_form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = conn.getresponse()
        cuerpo = resp.read().decode("utf-8")
        conn.close()

        self.assertEqual(resp.status, 200)
        self.assertIn("MANUAL", cuerpo)
        self.assertIn("local", cuerpo)

        db = Database(self.db_path)
        try:
            noticias = db.listar()
            self.assertEqual(len(noticias), 1)
            self.assertEqual(noticias[0]["origen_ingreso"], "manual")
        finally:
            db.close()

    def test_panel_post_con_error_muestra_formulario_de_nuevo(self):
        cuerpo_form = urlencode({"fuente": "", "texto": TEXTO_LOCAL})
        conn = self._conexion()
        conn.request(
            "POST",
            "/cargar-noticia",
            body=cuerpo_form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = conn.getresponse()
        cuerpo = resp.read().decode("utf-8")
        conn.close()

        self.assertEqual(resp.status, 400)
        self.assertIn("obligatorio", cuerpo)

    def test_panel_post_duplicado_muestra_mensaje_claro(self):
        cuerpo_form = urlencode({"fuente": "Ledesma Soy", "texto": TEXTO_LOCAL})
        conn = self._conexion()
        conn.request(
            "POST", "/cargar-noticia", body=cuerpo_form, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        conn.getresponse().read()
        conn.close()

        conn = self._conexion()
        conn.request(
            "POST", "/cargar-noticia", body=cuerpo_form, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        resp = conn.getresponse()
        cuerpo = resp.read().decode("utf-8")
        conn.close()

        self.assertEqual(resp.status, 200)
        self.assertIn("ya existe o coincide", cuerpo)


if __name__ == "__main__":
    unittest.main()
