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

    def test_noticia_nacional_sin_relevancia_local_queda_preparada(self):
        # El Motor Editorial en cascada necesita poder usar contenido
        # nacional cuando no hay nada local/departamental disponible:
        # relevancia_local sigue en False (sigue significando "no es local"),
        # pero el territorio "nacional" y la elegibilidad editorial permiten
        # que de todos modos se prepare.
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
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia.estado, Estado.PREPARADA.value)
        self.assertEqual(noticia.territorio, "nacional")
        self.assertFalse(noticia.relevancia_local)

    def test_noticia_sin_clasificar_queda_descartada(self):
        # Sin relación con Libertador, Ledesma, Jujuy ni referencias
        # nacionales explícitas: nunca se prepara automáticamente.
        items = [
            {
                "titulo": "Estrenó su nuevo disco el músico internacional",
                "texto": (
                    "El artista presentó su nuevo álbum en una gira mundial "
                    "sin fechas confirmadas todavía."
                ),
                "url": "https://ejemplo.test/sin-clasificar-1",
                "fuente": "Prueba",
                "fecha": "2026-08-01",
            }
        ]
        resultados = ejecutar_pipeline(self.db, ColectorDePrueba(items), self.redactor)
        noticia, resultado = resultados[0]
        self.assertEqual(resultado, "descartada")
        self.assertEqual(noticia.estado, Estado.DESCARTADA.value)
        self.assertEqual(noticia.territorio, "sin_clasificar")

    def test_noticia_sin_clasificar_de_entretenimiento_se_prepara_como_ultimo_recurso(self):
        # sin_clasificar, pero de entretenimiento/curiosidad: se prepara para
        # poder usarse como último nivel de la cascada editorial.
        items = [
            {
                "titulo": "Un video insólito se hizo viral en las redes sociales",
                "texto": (
                    "El curioso momento fue grabado por un usuario y generó furor en redes, "
                    "acumulando millones de reproducciones en pocas horas."
                ),
                "url": "https://ejemplo.test/sin-clasificar-viral-1",
                "fuente": "Prueba",
                "fecha": "2026-08-01",
            }
        ]
        resultados = ejecutar_pipeline(self.db, ColectorDePrueba(items), self.redactor)
        noticia, resultado = resultados[0]
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia.estado, Estado.PREPARADA.value)
        self.assertEqual(noticia.territorio, "sin_clasificar")

    def test_noticia_municipal_requiere_revision_especial(self):
        items = [
            {
                "titulo": "El Intendente de Libertador General San Martín anunció obras",
                "texto": "El Intendente presentó el plan de obras para el barrio.",
                "url": "https://ejemplo.test/intendente-1",
                "fuente": "Prueba",
                "fecha": "2026-08-01",
            }
        ]
        resultados = ejecutar_pipeline(self.db, ColectorDePrueba(items), self.redactor)
        noticia, resultado = resultados[0]
        self.assertEqual(resultado, "preparada")
        self.assertTrue(noticia.requiere_revision_especial)
        self.assertIsNotNone(noticia.categoria_riesgo)
        self.assertIsNotNone(noticia.motivo_revision_especial)

    def test_noticia_deportiva_local_no_requiere_revision_especial(self):
        items = [
            {
                "titulo": "El club de Libertador General San Martín ganó el torneo",
                "texto": "El equipo de Libertador General San Martín venció 2 a 0 en la final.",
                "url": "https://ejemplo.test/deporte-1",
                "fuente": "Prueba",
                "fecha": "2026-08-01",
            }
        ]
        resultados = ejecutar_pipeline(self.db, ColectorDePrueba(items), self.redactor)
        noticia, resultado = resultados[0]
        self.assertEqual(resultado, "preparada")
        self.assertFalse(noticia.requiere_revision_especial)
        self.assertIsNone(noticia.categoria_riesgo)

    def test_riesgo_editorial_se_preserva_en_noticia_nacional_preparada(self):
        # El control de riesgo político/institucional (sin modificar) sigue
        # aplicándose igual aunque la noticia sea nacional/sin relevancia_local.
        items = [
            {
                "titulo": "Un diputado presentó un proyecto en el Congreso",
                "texto": "El Gobierno nacional recibió el proyecto presentado por el diputado.",
                "url": "https://ejemplo.test/nacional-riesgo-1",
                "fuente": "Prueba",
                "fecha": "2026-08-01",
            }
        ]
        resultados = ejecutar_pipeline(self.db, ColectorDePrueba(items), self.redactor)
        noticia, resultado = resultados[0]
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia.territorio, "nacional")
        self.assertTrue(noticia.requiere_revision_especial)
        self.assertEqual(noticia.categoria_riesgo, "politica_partidaria")

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
