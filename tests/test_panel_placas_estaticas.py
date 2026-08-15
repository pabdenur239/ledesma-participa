import http.client
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

from motor_noticias.db import Database
from motor_noticias.panel.server import HOST, PanelHandler


class TestPlacasEstaticas(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        Database(self.db_path).close()

        self.directorio_placas = Path(self.tmpdir.name) / "placas"
        self.directorio_placas.mkdir()
        self.archivo_valido = self.directorio_placas / "placa_abc123.png"
        self.archivo_valido.write_bytes(b"\x89PNG\r\n\x1a\ncontenido-de-prueba")

        self.patch_directorio = patch(
            "motor_noticias.panel.server.DIRECTORIO_PLACAS_DEFAULT", self.directorio_placas
        )
        self.patch_directorio.start()

        PanelHandler.db_path = self.db_path
        self.servidor = HTTPServer((HOST, 0), PanelHandler)
        self.puerto = self.servidor.server_address[1]
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)
        self.patch_directorio.stop()
        self.tmpdir.cleanup()

    def _conexion(self):
        return http.client.HTTPConnection(HOST, self.puerto, timeout=5)

    def test_sirve_una_placa_valida(self):
        conn = self._conexion()
        conn.request("GET", "/placas/placa_abc123.png")
        resp = conn.getresponse()
        cuerpo = resp.read()
        conn.close()

        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "image/png")
        self.assertEqual(cuerpo, self.archivo_valido.read_bytes())

    def test_archivo_inexistente_da_404(self):
        conn = self._conexion()
        conn.request("GET", "/placas/placa_noexiste.png")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 404)

    def test_rechaza_recorrido_de_directorios(self):
        conn = self._conexion()
        conn.request("GET", "/placas/..%2F..%2Fetc%2Fpasswd")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 404)

    def test_rechaza_extension_distinta_de_png(self):
        archivo = self.directorio_placas / "placa_abc123.txt"
        archivo.write_text("no debería servirse")
        conn = self._conexion()
        conn.request("GET", "/placas/placa_abc123.txt")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 404)

    def test_rechaza_nombre_que_no_sigue_el_patron_de_placa(self):
        archivo = self.directorio_placas / "otro-nombre.png"
        archivo.write_bytes(b"\x89PNG\r\n\x1a\n")
        conn = self._conexion()
        conn.request("GET", "/placas/otro-nombre.png")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 404)


if __name__ == "__main__":
    unittest.main()
