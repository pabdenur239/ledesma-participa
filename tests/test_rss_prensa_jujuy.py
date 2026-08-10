import tempfile
import unittest
from pathlib import Path

from motor_noticias.collectors.rss_prensa_jujuy import parsear_rss
from motor_noticias.db import Database
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "fixtures"
    / "prensa_jujuy_rss_prueba.xml"
)
NOMBRE_FUENTE = "Prensa Jujuy (Gobierno de Jujuy)"


class ColectorRSSDePrueba:
    """Envuelve el fixture XML local. No realiza ninguna conexión de red."""

    def __init__(self, contenido):
        self.contenido = contenido

    def recolectar(self):
        return parsear_rss(self.contenido, NOMBRE_FUENTE)


class TestParsearRSS(unittest.TestCase):
    def setUp(self):
        self.contenido = FIXTURE_PATH.read_bytes()

    def test_parsea_los_items_del_fixture(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        self.assertEqual(len(noticias), 3)

    def test_extrae_los_campos_minimos(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        primera = noticias[0]
        self.assertIn("Libertador", primera["titulo"])
        self.assertTrue(primera["url"].startswith("https://"))
        self.assertEqual(primera["fuente"], NOMBRE_FUENTE)
        self.assertTrue(primera["fecha"])
        self.assertTrue(primera["texto"])
        self.assertNotIn("<p>", primera["texto"])


class TestPipelineConFixtureRSS(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()
        self.collector = ColectorRSSDePrueba(FIXTURE_PATH.read_bytes())

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_pipeline_offline_sobre_fixture_rss(self):
        resultados = ejecutar_pipeline(self.db, self.collector, self.redactor)
        self.assertEqual(len(resultados), 3)

        self.assertEqual(resultados[0][1], "preparada")
        self.assertEqual(resultados[1][1], "descartada")
        self.assertEqual(resultados[2][1], "duplicado")

        self.assertEqual(len(self.db.listar()), 2)


if __name__ == "__main__":
    unittest.main()
