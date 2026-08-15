import tempfile
import unittest
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def _noticia(self, **overrides) -> Noticia:
        base = dict(
            id=None,
            titulo_original="Título",
            texto_original="Texto",
            url_fuente="https://ejemplo.test/1",
            url_normalizada="https://ejemplo.test/1",
            nombre_fuente="Fuente",
            fecha_fuente="2026-08-01",
            fecha_recoleccion="2026-08-01T00:00:00",
            estado=Estado.ENCONTRADA.value,
            hash_contenido="hash-1",
        )
        base.update(overrides)
        return Noticia(**base)

    def test_crea_base_de_datos_si_no_existe(self):
        self.assertTrue(self.db_path.exists())

    def test_guardar_y_listar(self):
        noticia = self._noticia()
        self.db.guardar(noticia)
        self.assertIsNotNone(noticia.id)
        self.assertEqual(len(self.db.listar()), 1)

    def test_existe_duplicado_por_hash(self):
        self.db.guardar(self._noticia())
        self.assertTrue(self.db.existe_duplicado("https://otra.test/x", "hash-1"))

    def test_existe_duplicado_por_url_normalizada(self):
        self.db.guardar(self._noticia())
        self.assertTrue(self.db.existe_duplicado("https://ejemplo.test/1", "otro-hash"))

    def test_no_existe_duplicado(self):
        self.db.guardar(self._noticia())
        self.assertFalse(self.db.existe_duplicado("https://otra.test/x", "otro-hash"))

    def test_marcar_publicada(self):
        noticia = self._noticia(estado=Estado.PREPARADA.value)
        self.db.guardar(noticia)
        self.db.marcar_publicada(noticia.id)
        self.assertEqual(self.db.obtener(noticia.id)["estado"], Estado.PUBLICADA.value)


if __name__ == "__main__":
    unittest.main()
