import http.client
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia, RevisionEstado
from motor_noticias.panel.server import HOST, PanelHandler, _detalle_html, _lista_html


def _noticia_preparada(**overrides) -> Noticia:
    base = dict(
        id=None,
        titulo_original="Título",
        texto_original="Texto",
        url_fuente="https://ejemplo.test/1",
        url_normalizada="https://ejemplo.test/1",
        nombre_fuente="Fuente",
        fecha_fuente="2026-08-01",
        fecha_recoleccion="2026-08-01T00:00:00",
        estado=Estado.PREPARADA.value,
        hash_contenido="hash-1",
        titulo_preparado="Título preparado",
        texto_preparado="Texto preparado",
    )
    base.update(overrides)
    return Noticia(**base)


class TestEscapeHTML(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_lista_escapa_contenido_potencialmente_malicioso(self):
        noticia = _noticia_preparada(titulo_original='<script>alert("x")</script>')
        self.db.guardar(noticia)

        pagina = _lista_html(self.db, "todas")

        self.assertNotIn("<script>alert", pagina)
        self.assertIn("&lt;script&gt;", pagina)

    def test_detalle_escapa_contenido_potencialmente_malicioso(self):
        noticia_dict = dict(
            id=1,
            titulo_original="<img src=x onerror=alert(1)>",
            texto_original="Texto",
            url_fuente="https://ejemplo.test/1",
            nombre_fuente="Fuente",
            localidad="Libertador General San Martín",
            titulo_preparado="Título preparado",
            texto_preparado="Texto preparado",
            titulo_revisado=None,
            texto_revisado=None,
            revision_estado="pendiente",
        )

        pagina = _detalle_html(noticia_dict)

        self.assertNotIn("<img src=x onerror", pagina)
        self.assertIn("&lt;img", pagina)


class TestAdvertenciaRiesgoEditorial(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_lista_muestra_advertencia_para_noticia_con_riesgo(self):
        noticia = _noticia_preparada(
            requiere_revision_especial=True,
            categoria_riesgo="institucional_municipal",
            motivo_revision_especial="Menciona 'Intendente'.",
        )
        self.db.guardar(noticia)

        pagina = _lista_html(self.db, "todas")

        self.assertIn("REVISIÓN POLÍTICA/INSTITUCIONAL OBLIGATORIA", pagina)
        self.assertIn("institucional_municipal", pagina)

    def test_lista_no_muestra_advertencia_para_noticia_sin_riesgo(self):
        noticia = _noticia_preparada()
        self.db.guardar(noticia)

        pagina = _lista_html(self.db, "todas")

        self.assertNotIn("REVISIÓN POLÍTICA/INSTITUCIONAL OBLIGATORIA", pagina)

    def test_detalle_muestra_advertencia_para_noticia_con_riesgo(self):
        noticia = _noticia_preparada(
            requiere_revision_especial=True,
            categoria_riesgo="figura_publica_relacionada",
            motivo_revision_especial="Menciona 'Pablo Abdenur'.",
        )
        self.db.guardar(noticia)
        guardada = self.db.obtener(noticia.id)

        pagina = _detalle_html(guardada)

        self.assertIn("REVISIÓN POLÍTICA/INSTITUCIONAL OBLIGATORIA", pagina)
        self.assertIn("figura_publica_relacionada", pagina)


class TestVistaPreviaFacebook(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        self.db = Database(self.db_path)

        # Las placas generadas durante la vista previa van a un directorio
        # temporal, no al data/placas real del repositorio.
        self.dir_placas = tempfile.TemporaryDirectory()
        self.parche_placas = patch(
            "motor_noticias.meta.imagen.DIRECTORIO_PLACAS_DEFAULT", Path(self.dir_placas.name)
        )
        self.parche_placas.start()

        PanelHandler.db_path = self.db_path
        self.servidor = HTTPServer((HOST, 0), PanelHandler)
        self.puerto = self.servidor.server_address[1]
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)
        self.db.close()
        self.parche_placas.stop()
        self.dir_placas.cleanup()
        self.tmpdir.cleanup()

    def _conexion(self):
        return http.client.HTTPConnection(HOST, self.puerto, timeout=5)

    def test_enlace_no_aparece_para_noticia_pendiente(self):
        noticia = _noticia_preparada()
        self.db.guardar(noticia)

        pagina_lista = _lista_html(self.db, "todas")
        self.assertNotIn("Preparar publicación Facebook", pagina_lista)

    def test_enlace_aparece_solo_para_noticia_aprobada(self):
        noticia = _noticia_preparada(revision_estado=RevisionEstado.APROBADA.value)
        self.db.guardar(noticia)

        pagina_lista = _lista_html(self.db, "todas")
        self.assertIn(f"/facebook?id={noticia.id}", pagina_lista)

    def test_vista_previa_de_noticia_pendiente_no_disponible(self):
        noticia = _noticia_preparada()
        self.db.guardar(noticia)

        conn = self._conexion()
        conn.request("GET", f"/facebook?id={noticia.id}")
        resp = conn.getresponse()
        cuerpo = resp.read().decode("utf-8")
        conn.close()

        self.assertEqual(resp.status, 400)
        self.assertIn("aprobada", cuerpo)

    def test_vista_previa_de_noticia_aprobada_muestra_modo_prueba(self):
        noticia = _noticia_preparada(
            revision_estado=RevisionEstado.APROBADA.value,
            titulo_preparado="Se inauguró la plaza del barrio",
            texto_preparado="El municipio inauguró la nueva plaza del barrio San José.",
            nombre_fuente="Ejemplo Noticias (prueba)",
        )
        self.db.guardar(noticia)

        conn = self._conexion()
        conn.request("GET", f"/facebook?id={noticia.id}")
        resp = conn.getresponse()
        cuerpo = resp.read().decode("utf-8")
        conn.close()

        self.assertEqual(resp.status, 200)
        self.assertIn("MODO PRUEBA — NO SE PUBLICARÁ NADA", cuerpo)
        self.assertIn("Se inauguró la plaza del barrio", cuerpo)
        self.assertIn("Información completa en el primer comentario.", cuerpo)
        self.assertIn("Fuente: Ejemplo Noticias (prueba)", cuerpo)
        self.assertIn("#LedesmaParticipa", cuerpo)
        # sin imagen de origen: se generó y embebió una placa PNG
        self.assertIn("placa generada automáticamente", cuerpo)
        self.assertIn('<img class="placa-preview" src="data:image/png;base64,', cuerpo)

        guardada = self.db.obtener(noticia.id)
        self.assertTrue(guardada["imagen_generada_automaticamente"])
        self.assertIsNotNone(guardada["imagen_publicacion_ruta"])
        self.assertTrue(guardada["imagen_publicacion_ruta"].endswith(".png"))

    def test_vista_previa_con_imagen_original_no_genera_placa(self):
        noticia = _noticia_preparada(
            revision_estado=RevisionEstado.APROBADA.value,
            tiene_imagen_original=True,
            imagen_publicacion_ruta="https://ejemplo.test/foto-original.jpg",
        )
        self.db.guardar(noticia)

        conn = self._conexion()
        conn.request("GET", f"/facebook?id={noticia.id}")
        resp = conn.getresponse()
        cuerpo = resp.read().decode("utf-8")
        conn.close()

        self.assertEqual(resp.status, 200)
        self.assertIn("imagen original", cuerpo)
        self.assertIn("https://ejemplo.test/foto-original.jpg", cuerpo)
        self.assertNotIn("placa generada automáticamente", cuerpo)

    def test_vista_previa_de_noticia_con_riesgo_politico_sigue_siendo_dry_run(self):
        noticia = _noticia_preparada(
            revision_estado=RevisionEstado.APROBADA.value,
            requiere_revision_especial=True,
            categoria_riesgo="institucional_municipal",
            motivo_revision_especial="Menciona 'Intendente'.",
        )
        self.db.guardar(noticia)

        conn = self._conexion()
        conn.request("GET", f"/facebook?id={noticia.id}")
        resp = conn.getresponse()
        cuerpo = resp.read().decode("utf-8")
        conn.close()

        self.assertEqual(resp.status, 200)
        self.assertIn("MODO PRUEBA — NO SE PUBLICARÁ NADA", cuerpo)
        self.assertIn("REVISIÓN POLÍTICA/INSTITUCIONAL OBLIGATORIA", cuerpo)
        # la placa se genera igual para la vista previa, sin habilitar publicación real
        self.assertIn("placa generada automáticamente", cuerpo)


class TestServidorLocalhost(unittest.TestCase):
    def test_host_configurado_exclusivamente_en_loopback(self):
        self.assertEqual(HOST, "127.0.0.1")

    def test_servidor_solo_se_enlaza_a_127_0_0_1(self):
        servidor = HTTPServer((HOST, 0), PanelHandler)
        try:
            self.assertEqual(servidor.server_address[0], "127.0.0.1")
        finally:
            servidor.server_close()


class TestPanelHTTPIntegracion(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        db = Database(self.db_path)
        self.noticia = _noticia_preparada()
        db.guardar(self.noticia)
        db.close()

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

    def test_lista_muestra_noticia_pendiente(self):
        conn = self._conexion()
        conn.request("GET", "/?filtro=pendientes")
        resp = conn.getresponse()
        cuerpo = resp.read().decode("utf-8")
        conn.close()

        self.assertEqual(resp.status, 200)
        self.assertIn(self.noticia.titulo_original, cuerpo)

    def test_detalle_muestra_formulario_de_edicion(self):
        conn = self._conexion()
        conn.request("GET", f"/noticia?id={self.noticia.id}")
        resp = conn.getresponse()
        cuerpo = resp.read().decode("utf-8")
        conn.close()

        self.assertEqual(resp.status, 200)
        self.assertIn("titulo_revisado", cuerpo)
        self.assertIn("texto_revisado", cuerpo)

    def test_aprobar_actualiza_revision_estado_y_guarda_edicion(self):
        cuerpo_form = urlencode(
            {
                "accion": "aprobar",
                "titulo_revisado": "Título aprobado a mano",
                "texto_revisado": "Texto aprobado a mano",
            }
        )
        conn = self._conexion()
        conn.request(
            "POST",
            f"/noticia?id={self.noticia.id}",
            body=cuerpo_form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = conn.getresponse()
        resp.read()
        conn.close()

        self.assertEqual(resp.status, 303)

        db = Database(self.db_path)
        guardada = db.obtener(self.noticia.id)
        db.close()
        self.assertEqual(guardada["revision_estado"], "aprobada")
        self.assertEqual(guardada["titulo_revisado"], "Título aprobado a mano")
        self.assertEqual(guardada["texto_revisado"], "Texto aprobado a mano")
        # aprobar nunca publica: el estado principal sigue siendo preparada
        self.assertEqual(guardada["estado"], "preparada")

    def test_rechazar_actualiza_revision_estado(self):
        cuerpo_form = urlencode({"accion": "rechazar"})
        conn = self._conexion()
        conn.request(
            "POST",
            f"/noticia?id={self.noticia.id}",
            body=cuerpo_form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = conn.getresponse()
        resp.read()
        conn.close()

        db = Database(self.db_path)
        guardada = db.obtener(self.noticia.id)
        db.close()
        self.assertEqual(guardada["revision_estado"], "rechazada")
        self.assertEqual(guardada["estado"], "preparada")

    def test_guardar_edita_sin_cambiar_revision_estado(self):
        cuerpo_form = urlencode(
            {
                "accion": "guardar",
                "titulo_revisado": "Corrección menor",
                "texto_revisado": "Texto con una corrección menor.",
            }
        )
        conn = self._conexion()
        conn.request(
            "POST",
            f"/noticia?id={self.noticia.id}",
            body=cuerpo_form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = conn.getresponse()
        resp.read()
        conn.close()

        db = Database(self.db_path)
        guardada = db.obtener(self.noticia.id)
        db.close()
        self.assertEqual(guardada["revision_estado"], "pendiente")
        self.assertEqual(guardada["titulo_revisado"], "Corrección menor")

    def test_filtro_aprobadas_no_incluye_pendientes(self):
        conn = self._conexion()
        conn.request("GET", "/?filtro=aprobadas")
        resp = conn.getresponse()
        cuerpo = resp.read().decode("utf-8")
        conn.close()

        self.assertNotIn(self.noticia.titulo_original, cuerpo)


class TestEstadoDelSistema(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        self.db = Database(self.db_path)
        self.lock_path = Path(self.tmpdir.name) / "run_continuo.lock"

        PanelHandler.db_path = self.db_path
        PanelHandler.lock_path = self.lock_path
        self.servidor = HTTPServer((HOST, 0), PanelHandler)
        self.puerto = self.servidor.server_address[1]
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)
        self.db.close()
        self.tmpdir.cleanup()

    def _conexion(self):
        return http.client.HTTPConnection(HOST, self.puerto, timeout=5)

    def _get(self, ruta):
        conn = self._conexion()
        conn.request("GET", ruta)
        resp = conn.getresponse()
        cuerpo = resp.read().decode("utf-8")
        conn.close()
        return resp.status, cuerpo

    def test_pagina_principal_enlaza_al_estado_del_sistema(self):
        status, cuerpo = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn('href="/estado"', cuerpo)

    def test_estado_sin_ciclos_previos_indica_sin_datos(self):
        status, cuerpo = self._get("/estado")
        self.assertEqual(status, 200)
        self.assertIn("Estado del sistema", cuerpo)
        self.assertIn("inactivo", cuerpo)
        self.assertIn("sin datos aún", cuerpo)

    def test_estado_muestra_motor_activo_cuando_existe_el_lock(self):
        self.lock_path.write_text("12345")

        _, cuerpo = self._get("/estado")

        self.assertIn("<strong>Motor continuo:</strong> activo", cuerpo)

    def test_estado_muestra_ultimo_ciclo_y_totales(self):
        self.db.registrar_ciclo(
            "2026-08-12T10:00:00+00:00",
            "2026-08-12T10:00:05+00:00",
            total_fuentes=7,
            total_noticias_nuevas=3,
            total_errores=1,
            intervalo_segundos=1800,
        )

        _, cuerpo = self._get("/estado")

        self.assertIn("2026-08-12T10:00:05+00:00", cuerpo)
        self.assertIn("Noticias nuevas en última ejecución:</strong> 3", cuerpo)

    def test_estado_muestra_indicador_ok_para_fuente_sana(self):
        self.db.registrar_salud_fuente("infoyungas", "ok", elementos_obtenidos=2, noticias_nuevas=1)

        _, cuerpo = self._get("/estado")

        self.assertIn("infoyungas", cuerpo)
        self.assertIn("indicador-ok", cuerpo)

    def test_estado_muestra_indicador_error_para_fuente_caida(self):
        self.db.registrar_salud_fuente("infoyungas", "error", mensaje_error="HTTP 500")

        _, cuerpo = self._get("/estado")

        self.assertIn("indicador-error", cuerpo)
        self.assertIn("HTTP 500", cuerpo)

    def test_estado_muestra_alerta_activa_tras_tres_fallos(self):
        for _ in range(3):
            self.db.registrar_salud_fuente("infoyungas", "error", mensaje_error="HTTP 500")

        _, cuerpo = self._get("/estado")

        self.assertIn("Alertas activas", cuerpo)
        self.assertIn("3 fallos consecutivos", cuerpo)

    def test_estado_sin_alertas_lo_indica_explicitamente(self):
        self.db.registrar_salud_fuente("infoyungas", "ok", elementos_obtenidos=1, noticias_nuevas=1)
        noticia = Noticia(
            id=None,
            titulo_original="Obras en Libertador General San Martín",
            texto_original="Texto",
            url_fuente="https://ejemplo.test/1",
            url_normalizada="https://ejemplo.test/1",
            nombre_fuente="infoyungas",
            fecha_fuente="",
            fecha_recoleccion=datetime.now(timezone.utc).isoformat(),
            estado=Estado.PREPARADA.value,
            hash_contenido="hash-1",
            relevancia_local=True,
        )
        self.db.guardar(noticia)

        _, cuerpo = self._get("/estado")

        self.assertIn("Sin alertas activas.", cuerpo)


if __name__ == "__main__":
    unittest.main()
