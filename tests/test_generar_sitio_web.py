import json
import tempfile
import unittest
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia, RevisionEstado
from motor_noticias.sitio.generador import generar_sitio


def _noticia(**overrides) -> Noticia:
    base = dict(
        id=None,
        titulo_original="Título original",
        texto_original="Texto original",
        url_fuente="https://ejemplo.test/nota",
        url_normalizada="https://ejemplo.test/nota",
        nombre_fuente="Fuente Ejemplo",
        fecha_fuente="Mon, 17 Aug 2026 10:00:00 -0300",
        fecha_recoleccion="2026-08-17T13:00:00+00:00",
        estado=Estado.PUBLICADA.value,
        hash_contenido="hash-unico",
        titulo_preparado="Título preparado",
        texto_preparado="Texto preparado de la noticia.",
        revision_estado=RevisionEstado.APROBADA.value,
        territorio="local",
    )
    base.update(overrides)
    return Noticia(**base)


class TestGenerarSitioWeb(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        self.salida_dir = Path(self.tmpdir.name) / "salida"
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def _generar(self):
        return generar_sitio(self.db_path, self.salida_dir, base_url="https://ledesmaparticipa.com.ar")

    def test_solo_incluye_noticias_publicadas(self):
        self.db.guardar(_noticia(hash_contenido="h1", estado=Estado.PUBLICADA.value))
        self.db.guardar(_noticia(hash_contenido="h2", estado=Estado.PREPARADA.value))
        self.db.guardar(_noticia(hash_contenido="h3", estado=Estado.ENCONTRADA.value))
        self.db.guardar(_noticia(hash_contenido="h4", estado=Estado.DESCARTADA.value))

        resultado = self._generar()

        self.assertEqual(resultado["noticias"], 1)
        index_html = (self.salida_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("Título preparado", index_html)

    def test_secciones_por_territorio(self):
        self.db.guardar(_noticia(hash_contenido="local", territorio="local", titulo_preparado="Nota Libertador"))
        self.db.guardar(_noticia(hash_contenido="depto", territorio="departamental", titulo_preparado="Nota Ledesma"))
        self.db.guardar(_noticia(hash_contenido="prov", territorio="provincial", titulo_preparado="Nota Jujuy"))
        self.db.guardar(_noticia(hash_contenido="nac", territorio="nacional", titulo_preparado="Nota Nacional"))

        resultado = self._generar()

        self.assertEqual(
            resultado["secciones"],
            {"libertador": 1, "ledesma": 1, "jujuy": 1, "nacionales": 1},
        )
        for slug in ("libertador", "ledesma", "jujuy", "nacionales", "entretenimiento"):
            self.assertTrue((self.salida_dir / "categoria" / slug / "index.html").exists())

    def test_sin_clasificar_cae_en_entretenimiento_o_en_otras(self):
        self.db.guardar(_noticia(
            hash_contenido="ent",
            territorio="sin_clasificar",
            titulo_preparado="Un curioso récord mundial",
            texto_preparado="Una anécdota viral y curiosa que sorprendió a todos.",
        ))
        self.db.guardar(_noticia(
            hash_contenido="otras",
            territorio="sin_clasificar",
            titulo_preparado="Nota sin territorio claro",
            texto_preparado="Contenido genérico que no encaja en ninguna localidad conocida.",
        ))

        resultado = self._generar()

        self.assertEqual(resultado["secciones"].get("entretenimiento"), 1)
        self.assertEqual(resultado["secciones"].get("otras"), 1)
        self.assertTrue((self.salida_dir / "categoria" / "otras" / "index.html").exists())

    def test_escapa_html_potencialmente_malicioso(self):
        self.db.guardar(_noticia(
            hash_contenido="xss",
            titulo_preparado='<script>alert("x")</script>',
            texto_preparado='Texto con <img src=x onerror=alert(1)>.',
        ))

        self._generar()

        index_html = (self.salida_dir / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>alert", index_html)
        self.assertNotIn("<img src=x onerror", index_html)

    def test_imagen_local_se_copia_a_assets_y_url_externa_se_referencia_directo(self):
        imagen_local = Path(self.tmpdir.name) / "placa_prueba.png"
        imagen_local.write_bytes(b"contenido-png-de-prueba")

        self.db.guardar(_noticia(
            hash_contenido="img-local",
            imagen_publicacion_ruta=str(imagen_local),
            tiene_imagen_original=True,
        ))
        self.db.guardar(_noticia(
            hash_contenido="img-url",
            imagen_publicacion_ruta="https://cdn.ejemplo.test/foto.jpg",
            tiene_imagen_original=True,
        ))

        self._generar()

        self.assertTrue((self.salida_dir / "assets" / "img" / "placa_prueba.png").exists())
        index_html = (self.salida_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("assets/img/placa_prueba.png", index_html)
        self.assertIn("https://cdn.ejemplo.test/foto.jpg", index_html)

    def test_fecha_rfc2822_se_formatea_en_espanol(self):
        self.db.guardar(_noticia(hash_contenido="fecha", fecha_fuente="Fri, 14 Aug 2026 16:35:00 -0300"))

        self._generar()

        index_html = (self.salida_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("14 de agosto de 2026", index_html)

    def test_orden_cronologico_correcto_entre_meses_distintos(self):
        # Compara fechas en meses distintos: un ordenamiento por texto crudo
        # (en vez de fecha real) pondría "Feb" antes que "Jan" alfabéticamente,
        # aunque enero sea anterior a febrero.
        self.db.guardar(_noticia(
            hash_contenido="enero",
            fecha_fuente="Mon, 05 Jan 2026 10:00:00 -0300",
            titulo_preparado="Nota de enero",
        ))
        self.db.guardar(_noticia(
            hash_contenido="febrero",
            fecha_fuente="Tue, 03 Feb 2026 10:00:00 -0300",
            titulo_preparado="Nota de febrero",
        ))

        self._generar()

        index_html = (self.salida_dir / "index.html").read_text(encoding="utf-8")
        self.assertLess(
            index_html.index("Nota de febrero"),
            index_html.index("Nota de enero"),
            "La noticia más reciente (febrero) debe listarse antes que la de enero.",
        )

    def test_fecha_incluye_hora_en_horario_de_jujuy(self):
        # "Thu, 13 Aug 2026 10:11:00 -0300" ya está en huso de Jujuy: debe
        # mostrarse tal cual (10:11), no convertida a UTC (13:11).
        self.db.guardar(_noticia(hash_contenido="hora", fecha_fuente="Thu, 13 Aug 2026 10:11:00 -0300"))

        self._generar()

        index_html = (self.salida_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("13 de agosto de 2026, 10:11 hs", index_html)

    def test_sitemap_y_search_index_incluyen_el_articulo(self):
        self.db.guardar(_noticia(hash_contenido="sm", titulo_preparado="Nota para sitemap"))

        self._generar()

        sitemap = (self.salida_dir / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("https://ledesmaparticipa.com.ar/noticias/", sitemap)

        indice = json.loads((self.salida_dir / "assets" / "search-index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(indice), 1)
        self.assertIn("nota para sitemap", indice[0]["buscable"])

    def test_pagina_de_articulo_incluye_fuente_y_enlace_original(self):
        self.db.guardar(_noticia(
            hash_contenido="fuente",
            titulo_preparado="Nota con fuente",
            url_fuente="https://ejemplo.test/nota-original",
            nombre_fuente="Diario Ejemplo",
        ))

        self._generar()

        articulo = next((self.salida_dir / "noticias").glob("*/index.html"))
        contenido = articulo.read_text(encoding="utf-8")
        self.assertIn("Fuente y nota completa:", contenido)
        self.assertIn("https://ejemplo.test/nota-original", contenido)


if __name__ == "__main__":
    unittest.main()
