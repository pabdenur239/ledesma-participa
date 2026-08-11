import http.client
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
