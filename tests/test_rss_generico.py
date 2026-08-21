import unittest

from motor_noticias.collectors._rss_generico import parsear_rss_generico

FEED_WORDPRESS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0">
<channel><title>ejemplo</title>
<item>
<title>Receta de tarta de manzana</title>
<link>https://ejemplo.test/tarta-manzana/</link>
<description><![CDATA[<p><img src="https://ejemplo.test/img/tarta.jpg" />Una receta clásica de tarta de manzana casera.</p>
<p>La entrada <a href="https://ejemplo.test/tarta-manzana/">Receta de tarta de manzana</a> se publicó primero en <a href="https://ejemplo.test">ejemplo.test</a>.</p>]]></description>
<pubDate>Mon, 17 Aug 2026 11:00:00 +0000</pubDate>
</item>
</channel></rss>"""

FEED_SIN_WORDPRESS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"
xmlns:media="http://search.yahoo.com/mrss/">
<channel><title>ejemplo</title>
<item>
<title>Nueva campaña de vacunación antigripal</title>
<link>https://ejemplo.test/vacunacion/</link>
<description>El Ministerio anunció el inicio de la campaña de vacunación antigripal gratuita.</description>
<media:content url="https://ejemplo.test/img/vacuna.jpg" />
<pubDate>Mon, 17 Aug 2026 09:00:00 +0000</pubDate>
</item>
</channel></rss>"""

FEED_SIN_TITULO = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0">
<channel><title>ejemplo</title>
<item><link>https://ejemplo.test/sin-titulo/</link><description>texto</description></item>
</channel></rss>"""

# Bug real visto en producción (argentina.gob.ar/salud): el feed llega con
# un salto de línea + espacio antes de la declaración XML, lo que rompe
# ET.fromstring por sí solo (exige la declaración exactamente al principio).
FEED_CON_ESPACIO_ANTES_DE_XML = (
    '\n <?xml version="1.0" encoding="UTF-8"?><rss version="2.0">'
    "<channel><title>ejemplo</title>"
    "<item><title>Campaña de vacunación</title>"
    "<link>https://ejemplo.test/vacunacion/</link>"
    "<description>Información sobre la campaña.</description></item>"
    "</channel></rss>"
).encode("utf-8")

# Bug real visto en producción (Fundación Favaloro): un \x03 (carácter de
# control ilegal en XML 1.0) incrustado en el texto de un ítem rompe el
# parseo estricto de TODO el feed.
FEED_CON_CARACTER_XML_ILEGAL = (
    '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0">'
    "<channel><title>ejemplo</title>"
    "<item><title>Nota con \x03 caracter ilegal</title>"
    "<link>https://ejemplo.test/nota/</link>"
    "<description>Texto con \x03 un caracter de control inválido.</description></item>"
    "</channel></rss>"
).encode("utf-8")


class TestParsearRSSGenerico(unittest.TestCase):
    def test_extrae_titulo_texto_url_fecha_imagen_y_categoria(self):
        noticias = parsear_rss_generico(FEED_WORDPRESS, "Ejemplo", "gastronomia")
        self.assertEqual(len(noticias), 1)
        n = noticias[0]
        self.assertEqual(n["titulo"], "Receta de tarta de manzana")
        self.assertEqual(n["url"], "https://ejemplo.test/tarta-manzana/")
        self.assertEqual(n["fuente"], "Ejemplo")
        self.assertEqual(n["fecha"], "Mon, 17 Aug 2026 11:00:00 +0000")
        self.assertEqual(n["imagen_url"], "https://ejemplo.test/img/tarta.jpg")
        self.assertEqual(n["categoria_tematica"], "gastronomia")
        self.assertIn("receta clásica", n["texto"])

    def test_descarta_boilerplate_wordpress_cuando_corresponde(self):
        noticias = parsear_rss_generico(FEED_WORDPRESS, "Ejemplo", "gastronomia")
        self.assertNotIn("La entrada", noticias[0]["texto"])
        self.assertNotIn("se publicó primero en", noticias[0]["texto"])

    def test_no_wordpress_no_requiere_stripping_y_usa_media_content(self):
        noticias = parsear_rss_generico(
            FEED_SIN_WORDPRESS, "Ejemplo Salud", "salud", quitar_boilerplate_wordpress=False
        )
        self.assertEqual(len(noticias), 1)
        n = noticias[0]
        self.assertEqual(n["categoria_tematica"], "salud")
        self.assertEqual(n["imagen_url"], "https://ejemplo.test/img/vacuna.jpg")
        self.assertIn("vacunación antigripal", n["texto"])

    def test_item_sin_titulo_o_url_se_descarta(self):
        noticias = parsear_rss_generico(FEED_SIN_TITULO, "Ejemplo", "salud")
        self.assertEqual(noticias, [])

    def test_tolera_espacio_antes_de_la_declaracion_xml(self):
        noticias = parsear_rss_generico(
            FEED_CON_ESPACIO_ANTES_DE_XML, "Ministerio de Salud", "salud", quitar_boilerplate_wordpress=False
        )
        self.assertEqual(len(noticias), 1)
        self.assertEqual(noticias[0]["titulo"], "Campaña de vacunación")

    def test_tolera_caracter_de_control_ilegal_en_xml(self):
        noticias = parsear_rss_generico(
            FEED_CON_CARACTER_XML_ILEGAL, "Fundación Favaloro", "salud", quitar_boilerplate_wordpress=False
        )
        self.assertEqual(len(noticias), 1)
        self.assertEqual(noticias[0]["titulo"], "Nota con  caracter ilegal")


if __name__ == "__main__":
    unittest.main()
