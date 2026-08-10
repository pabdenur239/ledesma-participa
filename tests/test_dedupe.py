import unittest

from motor_noticias.dedupe import hash_contenido, normalizar_url


class TestDedupe(unittest.TestCase):
    def test_normalizar_url_ignora_www_y_barra_final(self):
        a = normalizar_url("https://www.ejemplo.test/nota/1/")
        b = normalizar_url("https://ejemplo.test/nota/1")
        self.assertEqual(a, b)

    def test_normalizar_url_ignora_parametros_de_tracking(self):
        a = normalizar_url("https://ejemplo.test/nota/1?utm_source=facebook&utm_medium=social")
        b = normalizar_url("https://ejemplo.test/nota/1")
        self.assertEqual(a, b)

    def test_hash_contenido_igual_para_texto_equivalente(self):
        h1 = hash_contenido("Título", "Texto de la noticia.")
        h2 = hash_contenido("título", "texto   de la noticia.")
        self.assertEqual(h1, h2)

    def test_hash_contenido_distinto_para_texto_distinto(self):
        h1 = hash_contenido("Título", "Texto A")
        h2 = hash_contenido("Título", "Texto B")
        self.assertNotEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
