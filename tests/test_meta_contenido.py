import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from motor_noticias.meta.contenido import cta_para, generar_caption_instagram, generar_contenido_facebook, generar_hashtags


def _noticia(**overrides) -> dict:
    base = dict(
        titulo_preparado="Título preparado por IA",
        texto_preparado="Texto preparado por IA con los hechos verificados.",
        titulo_revisado=None,
        texto_revisado=None,
        nombre_fuente="Prensa Jujuy (Gobierno de Jujuy)",
        localidad="Libertador General San Martín",
        url_fuente="https://prensa.jujuy.gob.ar/nota-original",
        titulo_original="Corte de agua en Libertador General San Martín",
        texto_original="",
    )
    base.update(overrides)
    return base


class TestGenerarHashtags(unittest.TestCase):
    def test_localidad_libertador_agrega_hashtag_especifico(self):
        hashtags = generar_hashtags("Libertador General San Martín")
        self.assertIn("#LedesmaParticipa", hashtags)
        self.assertIn("#LibertadorGeneralSanMartín", hashtags)
        self.assertNotIn("#Jujuy", hashtags)

    def test_localidad_departamento_ledesma_agrega_hashtag_ledesma(self):
        hashtags = generar_hashtags("Calilegua")
        self.assertIn("#LedesmaParticipa", hashtags)
        self.assertIn("#Ledesma", hashtags)

    def test_localidad_jujuy_agrega_hashtag_jujuy(self):
        hashtags = generar_hashtags("Jujuy")
        self.assertIn("#Jujuy", hashtags)

    def test_sin_localidad_solo_hashtag_base(self):
        self.assertEqual(generar_hashtags(None), ["#LedesmaParticipa"])

    def test_no_genera_listas_excesivas(self):
        hashtags = generar_hashtags("Libertador General San Martín")
        self.assertLessEqual(len(hashtags), 2)


class TestGenerarContenidoFacebook(unittest.TestCase):
    """Formato de copy de la Etapa 1: [TERRITORIO] | TITULAR, párrafos con
    oraciones completas, Fuente, CTA variable, enlace propio."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        parche = patch("motor_noticias.sitio.urls.SALIDA_DEFAULT", Path(self.tmp.name))
        parche.start()
        self.addCleanup(parche.stop)

    def _crear_pagina_propia(self, noticia):
        from motor_noticias.sitio.urls import url_relativa_noticia

        ruta = Path(self.tmp.name) / url_relativa_noticia(noticia) / "index.html"
        ruta.parent.mkdir(parents=True)
        ruta.write_text("ok", encoding="utf-8")

    def test_encabezado_territorio_y_titular_en_mayusculas(self):
        contenido = generar_contenido_facebook(_noticia(titulo_original="Corte de agua en Libertador General San Martín"))
        primera_linea = contenido.post_principal.split("\n")[0]
        self.assertEqual(primera_linea, "LIBERTADOR | TÍTULO PREPARADO POR IA")

    def test_prioriza_titulo_y_texto_revisados(self):
        noticia = _noticia(
            titulo_revisado="Título revisado por un humano",
            texto_revisado="Texto revisado por un humano con los hechos finales.",
        )
        contenido = generar_contenido_facebook(noticia)
        self.assertIn("TÍTULO REVISADO POR UN HUMANO", contenido.post_principal)
        self.assertIn("Texto revisado por un humano", contenido.post_principal)
        self.assertNotIn("PREPARADO POR IA", contenido.post_principal)

    def test_usa_preparado_como_fallback(self):
        contenido = generar_contenido_facebook(_noticia())
        self.assertIn("TÍTULO PREPARADO POR IA", contenido.post_principal)
        self.assertIn("Texto preparado por IA", contenido.post_principal)

    def test_sin_nota_propia_mantiene_enlace_a_la_nota_original(self):
        contenido = generar_contenido_facebook(_noticia())
        self.assertIn("Fuente: Prensa Jujuy (Gobierno de Jujuy)", contenido.post_principal)
        self.assertIn("Nota original: https://prensa.jujuy.gob.ar/nota-original", contenido.post_principal)
        self.assertNotIn("ledesmaparticipa.com.ar", contenido.post_principal)

    def test_con_nota_propia_enlaza_a_ledesmaparticipa_sin_url_externa(self):
        noticia = _noticia(id=42)
        self._crear_pagina_propia(noticia)
        contenido = generar_contenido_facebook(noticia)
        self.assertIn("https://ledesmaparticipa.com.ar/noticias/42-titulo-preparado-por-ia/", contenido.post_principal)
        self.assertNotIn("prensa.jujuy.gob.ar", contenido.post_principal)
        self.assertIn("Fuente: Prensa Jujuy (Gobierno de Jujuy)", contenido.post_principal)

    def test_quita_urls_y_lineas_fuente_del_cuerpo(self):
        texto = "Primer hecho en el barrio. Segundo dato.\nFuente: TodoJujuy — https://www.todojujuy.com/una/nota/muy/larga"
        contenido = generar_contenido_facebook(_noticia(texto_preparado=texto, url_fuente=""))
        self.assertNotIn("todojujuy.com", contenido.post_principal)
        self.assertEqual(contenido.post_principal.count("Fuente:"), 1)

    def test_nunca_trunca_una_oracion(self):
        texto = " ".join(f"Oración número {i} con información completa." for i in range(60))
        contenido = generar_contenido_facebook(_noticia(texto_preparado=texto))
        self.assertNotIn("…", contenido.post_principal)
        cuerpo = contenido.post_principal.split("\n\n")[1:5]
        self.assertLessEqual(len(cuerpo), 4)
        for parrafo in cuerpo:
            self.assertTrue(parrafo.endswith("."), parrafo)

    def test_cta_variable_y_estable_por_noticia(self):
        ctas = {cta_para({"id": i}) for i in range(8)}
        self.assertGreater(len(ctas), 1)
        self.assertEqual(cta_para({"id": 3}), cta_para({"id": 3}))
        self.assertTrue(all("ledesmaparticipa.com.ar" not in cta_para({"id": i}, hay_nota_propia=False) for i in range(8)))

    def test_urgente_lo_indica_en_el_encabezado(self):
        contenido = generar_contenido_facebook(_noticia(), urgente=True)
        self.assertTrue(contenido.post_principal.startswith("URGENTE | "))

    def test_post_principal_nunca_promete_informacion_en_el_comentario(self):
        contenido = generar_contenido_facebook(_noticia())
        self.assertNotIn("primer comentario", contenido.post_principal.lower())
        self.assertEqual(contenido.primer_comentario, "")

    def test_hashtags_cortos_al_final(self):
        contenido = generar_contenido_facebook(_noticia())
        self.assertTrue(contenido.post_principal.endswith("#LedesmaParticipa #LibertadorGeneralSanMartín"))

    def test_no_incluye_menciones_por_defecto(self):
        contenido = generar_contenido_facebook(_noticia(), menciones=["@seguidores"])
        self.assertEqual(contenido.menciones, [])
        self.assertNotIn("@seguidores", contenido.post_principal)

    def test_incluye_menciones_solo_si_se_habilitan_explicitamente(self):
        contenido = generar_contenido_facebook(
            _noticia(), incluir_menciones=True, menciones=["@seguidores"]
        )
        self.assertIn("@seguidores", contenido.post_principal)

    def test_caption_instagram_sin_url(self):
        caption = generar_caption_instagram(_noticia())
        self.assertNotIn("https://", caption)
        self.assertIn("Fuente: Prensa Jujuy (Gobierno de Jujuy)", caption)

    def test_no_implementa_imagen_todavia(self):
        contenido = generar_contenido_facebook(_noticia())
        self.assertIsNone(contenido.imagen_url)


if __name__ == "__main__":
    unittest.main()
