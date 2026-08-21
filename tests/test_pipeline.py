import tempfile
import unittest
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.models import Estado
from motor_noticias.pipeline import ejecutar_pipeline, normalizar_noticia
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


class TestNormalizarNoticiaDecodificaEntidadesHTML(unittest.TestCase):
    """Bug real detectado en producción: el collector de Jujuy al día no
    decodificaba entidades HTML, así que `&#8211;`/`&#8217;`/etc. salían tal
    cual en Facebook, Instagram y la web (los tres leen de titulo_preparado/
    texto_preparado, derivados de titulo_original/texto_original vía
    `normalizar_noticia` — ver pipeline.py y sitio/generador.py). La
    decodificación se aplica en ese único punto, común a cualquier
    collector."""

    def test_caso_real_jujuy_al_dia(self):
        cruda = {
            "titulo": "Chat Jujuy al día ® &#8211; ‘Desaparecer’...",
            "texto": "texto de prueba",
            "url": "https://ejemplo.test/nota-1",
        }
        noticia = normalizar_noticia(cruda)
        self.assertEqual(noticia.titulo_original, "Chat Jujuy al día ® – ‘Desaparecer’...")

    def test_decodifica_entidades_estandar_en_titulo_y_texto(self):
        cruda = {
            "titulo": "Riesgo &amp; seguridad: la &quot;alerta&quot; en Libertador",
            "texto": "El intendente dijo: &laquo;vamos a actuar&raquo; &#8211; anunci&oacute; medidas.",
            "url": "https://ejemplo.test/nota-2",
        }
        noticia = normalizar_noticia(cruda)
        self.assertEqual(noticia.titulo_original, 'Riesgo & seguridad: la "alerta" en Libertador')
        self.assertEqual(noticia.texto_original, "El intendente dijo: «vamos a actuar» – anunció medidas.")

    def test_no_altera_contenido_sin_entidades(self):
        cruda = {
            "titulo": "Obras en Libertador General San Martín",
            "texto": "El municipio anunció obras viales para el barrio.",
            "url": "https://ejemplo.test/nota-3",
        }
        noticia = normalizar_noticia(cruda)
        self.assertEqual(noticia.titulo_original, cruda["titulo"])
        self.assertEqual(noticia.texto_original, cruda["texto"])

    def test_nunca_decodifica_la_url(self):
        # Una URL con una entidad de tracking real (poco común, pero
        # válida) no debe alterarse: solo título y texto pasan por
        # html.unescape.
        cruda = {
            "titulo": "Título de prueba",
            "texto": "Texto de prueba",
            "url": "https://ejemplo.test/nota?ref=a&amp;b=1",
        }
        noticia = normalizar_noticia(cruda)
        self.assertEqual(noticia.url_fuente, "https://ejemplo.test/nota?ref=a&amp;b=1")

    def test_llega_decodificado_hasta_titulo_preparado_via_el_pipeline_completo(self):
        # Confirma que la decodificación no queda aislada en
        # normalizar_noticia: se propaga a titulo_preparado/texto_preparado
        # (de ahí en más, el mismo campo que usan Facebook, Instagram y la
        # web — ver meta/contenido.py y sitio/generador.py).
        tmpdir = tempfile.TemporaryDirectory()
        try:
            db = Database(Path(tmpdir.name) / "test.db")
            items = [
                {
                    "titulo": "Chat Jujuy al día ® &#8211; ‘Desaparecer’...",
                    "texto": "El caso &#8211; contin&uacute;a en Libertador General San Mart&iacute;n.",
                    "url": "https://ejemplo.test/nota-4",
                    "fuente": "Jujuy al día",
                    "fecha": "2026-08-01",
                }
            ]
            resultados = ejecutar_pipeline(db, ColectorDePrueba(items), RedactorMock())
            noticia, _ = resultados[0]
            self.assertNotIn("&#8211;", noticia.titulo_preparado)
            self.assertIn("–", noticia.titulo_preparado)
            self.assertNotIn("&#8211;", noticia.texto_preparado)
            self.assertNotIn("&uacute;", noticia.texto_preparado)
            db.close()
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
