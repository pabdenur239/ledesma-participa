import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_genera_pagina_de_contacto_publica_enlazada_desde_el_pie(self):
        self.db.guardar(_noticia(hash_contenido="c1"))
        self._generar()

        contacto = self.salida_dir / "contacto" / "index.html"
        self.assertTrue(contacto.exists())
        contenido = contacto.read_text(encoding="utf-8")
        self.assertIn("Contacto", contenido)
        self.assertIn("ledesmaparticipa@gmail.com", contenido)

        index_html = (self.salida_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="contacto/"', index_html)

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


class TestCliDespliegaDespuesDeGenerar(unittest.TestCase):
    """Bug real corregido: la tarea Windows SitioWeb invoca este script
    directamente (no la función `generar_sitio` en sí), y hasta ahora solo
    regeneraba `docs/` en el disco local sin nunca desplegarla — el deploy
    solo vivía en el respaldo del Motor Continuo. Ahora el propio CLI
    también despliega, así la cadencia de 15 minutos de la tarea SitioWeb
    (más rápida que los 30 minutos del Motor) alcanza para publicar."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        db = Database(self.db_path)
        db.close()

    def tearDown(self):
        self.tmpdir.cleanup()

    @patch("generar_sitio_web.desplegar_sitio")
    @patch("generar_sitio_web.deploy_automatico_habilitado", return_value=True)
    def test_deploy_habilitado_despliega_despues_de_generar(self, _habilitado_mock, desplegar_mock):
        import generar_sitio_web
        from motor_noticias.sitio.deploy import ResultadoDeploy

        desplegar_mock.return_value = ResultadoDeploy("desplegado")
        argv = ["generar_sitio_web.py", "--db", str(self.db_path), "--salida", str(Path(self.tmpdir.name) / "salida")]
        with patch.object(sys, "argv", argv):
            generar_sitio_web.main()

        desplegar_mock.assert_called_once()

    @patch("generar_sitio_web.desplegar_sitio")
    @patch("generar_sitio_web.deploy_automatico_habilitado", return_value=False)
    def test_deploy_deshabilitado_no_llama_git(self, _habilitado_mock, desplegar_mock):
        import generar_sitio_web

        argv = ["generar_sitio_web.py", "--db", str(self.db_path), "--salida", str(Path(self.tmpdir.name) / "salida")]
        with patch.object(sys, "argv", argv):
            generar_sitio_web.main()

        desplegar_mock.assert_not_called()


class TestApiJson(unittest.TestCase):
    """API JSON de solo lectura bajo docs/api/ — pensada para la app móvil,
    sin servidor nuevo: mismos datos ya públicos en el sitio HTML,
    desplegados por el mismo mecanismo (GitHub Pages)."""

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

    def _leer_json(self, *partes):
        return json.loads((self.salida_dir / "api" / Path(*partes)).read_text(encoding="utf-8"))

    def test_feed_incluye_solo_publicadas_con_esquema_esperado(self):
        self.db.guardar(_noticia(hash_contenido="h1", territorio="local"))
        self.db.guardar(_noticia(hash_contenido="h2", estado=Estado.PREPARADA.value))
        self._generar()

        feed = self._leer_json("feed.json")
        self.assertEqual(len(feed), 1)
        item = feed[0]
        for campo in ("id", "titulo", "bajada", "imagen", "fecha_iso", "categoria_slug", "urgente", "url"):
            self.assertIn(campo, item)
        self.assertTrue(item["url"].startswith("https://ledesmaparticipa.com.ar/"))

    def test_feed_respeta_prioridad_local_antes_que_nacional_aunque_sea_mas_viejo(self):
        self.db.guardar(_noticia(
            hash_contenido="nacional", territorio="nacional",
            titulo_original="Nota nacional más nueva", fecha_recoleccion="2026-08-18T13:00:00+00:00",
        ))
        self.db.guardar(_noticia(
            hash_contenido="local", territorio="local",
            titulo_original="Nota local más vieja", fecha_recoleccion="2026-08-17T13:00:00+00:00",
        ))
        self._generar()

        feed = self._leer_json("feed.json")
        self.assertEqual(feed[0]["titulo"], "Título preparado")  # ambas comparten titulo_preparado
        self.assertEqual(feed[0]["categoria_slug"], "libertador")  # la local va primero

    def test_urgentes_solo_incluye_marcadas_urgentes(self):
        self.db.guardar(_noticia(hash_contenido="u1", urgente=True))
        self.db.guardar(_noticia(hash_contenido="u2", urgente=False))
        self._generar()

        urgentes = self._leer_json("urgentes.json")
        self.assertEqual(len(urgentes), 1)
        self.assertTrue(urgentes[0]["urgente"])

    def test_categorias_reales_incluyen_tematica_y_las_vacias_quedan_vacias(self):
        self.db.guardar(_noticia(hash_contenido="c1", territorio="local"))
        self.db.guardar(_noticia(hash_contenido="c2", territorio="provincial"))
        self.db.guardar(_noticia(
            hash_contenido="c3", territorio="sin_clasificar", categoria_tematica="salud",
            titulo_original="Nota de salud", texto_original="Contenido sobre salud pública.",
        ))
        self._generar()

        self.assertEqual(len(self._leer_json("categoria", "locales.json")), 1)
        self.assertEqual(len(self._leer_json("categoria", "provinciales.json")), 1)
        self.assertEqual(len(self._leer_json("categoria", "salud.json")), 1)
        # Policiales/Deportes: sin clasificación real hoy — vacías a
        # propósito, nunca inventadas.
        self.assertEqual(self._leer_json("categoria", "policiales.json"), [])
        self.assertEqual(self._leer_json("categoria", "deportes.json"), [])

        categorias = self._leer_json("categorias.json")
        slugs = {c["slug"] for c in categorias}
        self.assertEqual(
            slugs,
            {"locales", "provinciales", "nacionales", "internacionales", "policiales",
             "espectaculos", "salud", "gastronomia", "deportes"},
        )

    def test_imagen_externa_no_queda_rota_con_el_base_url_antepuesto(self):
        # Bug real detectado probando la API contra datos reales: una
        # imagen externa (imagen_web ya absoluta) quedaba con base_url
        # antepuesto igual, produciendo una URL rota tipo
        # "https://ledesmaparticipa.com.ar/https://otro-dominio/foto.jpg".
        self.db.guardar(_noticia(
            hash_contenido="ext1", imagen_publicacion_ruta="https://cdn.ejemplo.test/foto.jpg",
            tiene_imagen_original=True,
        ))
        self._generar()

        item = self._leer_json("feed.json")[0]
        self.assertEqual(item["imagen"], "https://cdn.ejemplo.test/foto.jpg")

    def test_detalle_de_noticia_incluye_texto_completo_y_fuente(self):
        noticia_id = self.db.guardar(_noticia(
            hash_contenido="d1", nombre_fuente="Fuente Real",
            url_fuente="https://fuente-real.test/nota-original",
        ))
        self._generar()

        detalle = self._leer_json("noticia", f"{noticia_id}.json")
        self.assertEqual(detalle["fuente_nombre"], "Fuente Real")
        self.assertEqual(detalle["fuente_url"], "https://fuente-real.test/nota-original")
        self.assertIsInstance(detalle["texto_parrafos"], list)
        self.assertTrue(len(detalle["texto_parrafos"]) > 0)

    def test_feed_de_la_app_excluye_noticias_de_mas_de_90_dias(self):
        from datetime import datetime, timedelta, timezone

        reciente = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        vieja = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        self.db.guardar(_noticia(
            hash_contenido="reciente", titulo_preparado="Nota reciente",
            fecha_fuente=reciente, fecha_recoleccion=reciente,
        ))
        vieja_id = self.db.guardar(_noticia(
            hash_contenido="vieja", titulo_preparado="Nota vieja",
            fecha_fuente=vieja, fecha_recoleccion=vieja,
        ))
        self._generar()

        feed = self._leer_json("feed.json")
        self.assertEqual([item["titulo"] for item in feed], ["Nota reciente"])
        # El detalle por id se sigue generando (deep links / notificaciones).
        self.assertTrue((self.salida_dir / "api" / "noticia" / f"{vieja_id}.json").exists())

    def test_toda_noticia_de_la_api_muestra_una_fuente(self):
        self.db.guardar(_noticia(hash_contenido="propia", nombre_fuente=""))
        self._generar()

        feed = self._leer_json("feed.json")
        self.assertEqual(feed[0]["fuente_nombre"], "Ledesma Participa")

    def test_nunca_expone_campos_de_trabajo_interno(self):
        self.db.guardar(_noticia(
            hash_contenido="i1", observacion_interna="nota interna sensible",
            revision_estado=RevisionEstado.APROBADA.value,
        ))
        self._generar()

        feed_crudo = (self.salida_dir / "api" / "feed.json").read_text(encoding="utf-8")
        self.assertNotIn("observacion_interna", feed_crudo)
        self.assertNotIn("nota interna sensible", feed_crudo)
        self.assertNotIn("revision_estado", feed_crudo)


if __name__ == "__main__":
    unittest.main()
