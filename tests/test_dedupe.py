import unittest

from motor_noticias.dedupe import es_mismo_contenido, hash_contenido, normalizar_url, palabras_clave


class TestDedupe(unittest.TestCase):
    def test_normalizar_url_ignora_www_y_barra_final(self):
        a = normalizar_url("https://www.ejemplo.test/nota/1/")
        b = normalizar_url("https://ejemplo.test/nota/1")
        self.assertEqual(a, b)

    def test_normalizar_url_ignora_parametros_de_tracking(self):
        a = normalizar_url("https://ejemplo.test/nota/1?utm_source=facebook&utm_medium=social")
        b = normalizar_url("https://ejemplo.test/nota/1")
        self.assertEqual(a, b)

    def test_normalizar_url_conserva_el_fragmento(self):
        a = normalizar_url("https://ejemplo.test/pagina#actividad-1")
        b = normalizar_url("https://ejemplo.test/pagina#actividad-2")
        c = normalizar_url("https://www.ejemplo.test/pagina/#actividad-1")
        self.assertNotEqual(a, b)
        self.assertEqual(a, c)

    def test_hash_contenido_igual_para_texto_equivalente(self):
        h1 = hash_contenido("Título", "Texto de la noticia.")
        h2 = hash_contenido("título", "texto   de la noticia.")
        self.assertEqual(h1, h2)

    def test_hash_contenido_distinto_para_texto_distinto(self):
        h1 = hash_contenido("Título", "Texto A")
        h2 = hash_contenido("Título", "Texto B")
        self.assertNotEqual(h1, h2)


class TestPalabrasClave(unittest.TestCase):
    def test_ignora_acentos_mayusculas_y_signos_de_puntuacion_espanoles(self):
        a = palabras_clave("¿Cómo afecta la sequía a los pequeños productores de Ledesma?")
        b = palabras_clave("Como afecta la sequia a los pequenos productores de ledesma")
        self.assertEqual(a, b)

    def test_ignora_palabras_vacias_y_muy_cortas(self):
        palabras = palabras_clave("El show de La Renga en Jujuy")
        self.assertNotIn("el", palabras)
        self.assertNotIn("de", palabras)
        self.assertNotIn("la", palabras)
        self.assertNotIn("en", palabras)
        self.assertIn("show", palabras)
        self.assertIn("renga", palabras)
        self.assertIn("jujuy", palabras)

    def test_palabra_con_ene_virgulilla_se_normaliza_igual_que_sin_tilde(self):
        a = palabras_clave("Inversión para las próximas generaciones jujeñas")
        b = palabras_clave("Inversion para las proximas generaciones jujenas")
        self.assertEqual(a, b)


class TestEsMismoContenido(unittest.TestCase):
    def test_mismo_evento_con_titulo_levemente_distinto_se_detecta(self):
        a = palabras_clave(
            "Independiente Rivadavia apuesta por sorprender como local a un Fluminense sin entrenador"
        )
        b = palabras_clave(
            "Independiente Rivadavia busca hacer historia ante Fluminense en la Copa Libertadores"
        )
        self.assertTrue(es_mismo_contenido(a, b))

    def test_titulos_sobre_temas_distintos_no_se_confunden(self):
        a = palabras_clave("Jujuy avanza con más polideportivos y prevé superar los 80 espacios")
        b = palabras_clave("Jujuy avanza con una nueva inversión para sanear basurales en la Zona Valles")
        self.assertFalse(es_mismo_contenido(a, b))

    def test_una_palabra_de_lugar_comun_no_alcanza_para_marcar_duplicado(self):
        # Compartir solo "jujuy" (o "libertador"/"ledesma") nunca alcanza:
        # son palabras de contexto del propio proyecto, aparecen en casi
        # cualquier nota local o provincial y no son evidencia de que dos
        # títulos hablen de la misma noticia.
        a = palabras_clave("Recuperaron 39 celulares durante un operativo de seguridad en Jujuy")
        b = palabras_clave("La Catedral de Jujuy celebrará el Día del Niño en Plaza Belgrano")
        self.assertFalse(es_mismo_contenido(a, b))

    def test_libertador_como_homonimo_no_confunde_noticia_local_con_pelicula(self):
        # "Libertador" nombra tanto a la localidad como, por homonimia, a
        # una película/cortometraje llamada "El Libertador": compartir esa
        # palabra (más "San Martín") no alcanza para tratarlas como la
        # misma noticia.
        local = palabras_clave("Libertador recordó al General San Martín con orgullo")
        pelicula = palabras_clave(
            "Así se creó “El Libertador”, la película de IA sobre el encuentro "
            "entre San Martín y Sarmiento"
        )
        self.assertFalse(es_mismo_contenido(local, pelicula))


if __name__ == "__main__":
    unittest.main()
