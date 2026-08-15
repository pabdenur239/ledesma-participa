import unittest

from motor_noticias.meta.contenido import generar_contenido_facebook, generar_hashtags


def _noticia(**overrides) -> dict:
    base = dict(
        titulo_preparado="Título preparado por IA",
        texto_preparado="Texto preparado por IA con los hechos verificados.",
        titulo_revisado=None,
        texto_revisado=None,
        nombre_fuente="Prensa Jujuy (Gobierno de Jujuy)",
        localidad="Libertador General San Martín",
        url_fuente="https://prensa.jujuy.gob.ar/nota-original",
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
    def test_prioriza_titulo_y_texto_revisados(self):
        noticia = _noticia(
            titulo_revisado="Título revisado por un humano",
            texto_revisado="Texto revisado por un humano con los hechos finales.",
        )
        contenido = generar_contenido_facebook(noticia)
        self.assertIn("Título revisado por un humano", contenido.post_principal)
        self.assertIn("Texto revisado por un humano", contenido.primer_comentario)
        self.assertNotIn("Título preparado por IA", contenido.post_principal)

    def test_usa_preparado_como_fallback(self):
        contenido = generar_contenido_facebook(_noticia())
        self.assertIn("Título preparado por IA", contenido.post_principal)
        self.assertIn("Texto preparado por IA", contenido.primer_comentario)

    def test_post_principal_es_autosuficiente_con_fuente_y_enlace(self):
        contenido = generar_contenido_facebook(_noticia())
        self.assertIn("Fuente y nota completa: https://prensa.jujuy.gob.ar/nota-original", contenido.post_principal)

    def test_post_principal_nunca_promete_informacion_en_el_comentario(self):
        contenido = generar_contenido_facebook(_noticia())
        self.assertNotIn("primer comentario", contenido.post_principal.lower())

    def test_post_principal_sin_url_fuente_no_rompe_ni_promete_comentario(self):
        contenido = generar_contenido_facebook(_noticia(url_fuente=""))
        self.assertNotIn("primer comentario", contenido.post_principal.lower())
        self.assertNotIn("Fuente y nota completa:", contenido.post_principal)

    def test_primer_comentario_incluye_fuente_y_hashtags(self):
        contenido = generar_contenido_facebook(_noticia())
        self.assertIn("Fuente: Prensa Jujuy (Gobierno de Jujuy)", contenido.primer_comentario)
        self.assertIn("#LedesmaParticipa", contenido.primer_comentario)

    def test_no_incluye_menciones_por_defecto(self):
        contenido = generar_contenido_facebook(_noticia(), menciones=["@seguidores"])
        self.assertEqual(contenido.menciones, [])
        self.assertNotIn("@seguidores", contenido.primer_comentario)

    def test_incluye_menciones_solo_si_se_habilitan_explicitamente(self):
        contenido = generar_contenido_facebook(
            _noticia(), incluir_menciones=True, menciones=["@seguidores"]
        )
        self.assertIn("@seguidores", contenido.primer_comentario)

    def test_resena_breve_no_incluye_el_texto_completo_sin_recortar(self):
        texto_largo = ("Palabra " * 100).strip()
        contenido = generar_contenido_facebook(_noticia(texto_preparado=texto_largo))
        self.assertLess(len(contenido.post_principal), len(texto_largo))
        # el texto completo, sin recortar, sigue disponible en el comentario
        self.assertIn(texto_largo, contenido.primer_comentario)

    def test_no_implementa_imagen_todavia(self):
        contenido = generar_contenido_facebook(_noticia())
        self.assertIsNone(contenido.imagen_url)


if __name__ == "__main__":
    unittest.main()
