import tempfile
import unittest
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.models import Estado
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock


class ColectorDePrueba:
    def __init__(self, items):
        self.items = items

    def recolectar(self):
        return self.items


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_noticia_local_queda_preparada(self):
        items = [
            {
                "titulo": "Obras en Libertador General San Martín",
                "texto": "El municipio de Libertador General San Martín anunció obras viales.",
                "url": "https://ejemplo.test/libertador-1",
                "fuente": "Prueba",
                "fecha": "2026-08-01",
            }
        ]
        resultados = ejecutar_pipeline(self.db, ColectorDePrueba(items), self.redactor)
        noticia, resultado = resultados[0]
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia.estado, Estado.PREPARADA.value)
        self.assertIsNotNone(noticia.texto_preparado)

    def test_noticia_no_local_queda_descartada(self):
        items = [
            {
                "titulo": "Anuncio económico nacional",
                "texto": "El Gobierno nacional presentó cambios económicos en Buenos Aires.",
                "url": "https://ejemplo.test/nacional-1",
                "fuente": "Prueba",
                "fecha": "2026-08-01",
            }
        ]
        resultados = ejecutar_pipeline(self.db, ColectorDePrueba(items), self.redactor)
        noticia, resultado = resultados[0]
        self.assertEqual(resultado, "descartada")
        self.assertEqual(noticia.estado, Estado.DESCARTADA.value)

    def test_duplicado_no_se_almacena_dos_veces(self):
        base = {
            "titulo": "Obras en Libertador General San Martín",
            "texto": "El municipio de Libertador General San Martín anunció obras viales.",
            "url": "https://ejemplo.test/libertador-1",
            "fuente": "Prueba",
            "fecha": "2026-08-01",
        }
        duplicado = dict(base, url="https://ejemplo.test/libertador-1?utm_source=facebook")
        resultados = ejecutar_pipeline(
            self.db, ColectorDePrueba([base, duplicado]), self.redactor
        )
        self.assertEqual(resultados[1][1], "duplicado")
        self.assertEqual(len(self.db.listar()), 1)


if __name__ == "__main__":
    unittest.main()
