import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from motor_noticias.meta.imagen import (
    ALTO_PLACA,
    ALTO_STORY,
    ANCHO_PLACA,
    ANCHO_STORY,
    _cargar_fuente,
    _envolver_texto,
    _envolver_texto_pixeles,
    _ruta_fuente_unicode,
    generar_imagen_placa_png,
    generar_imagen_story_png,
    generar_placa,
    generar_story,
    generar_svg_placa,
)

FIRMA_PNG = b"\x89PNG\r\n\x1a\n"


class TestEnvolverTexto(unittest.TestCase):
    def test_no_corta_palabras_al_medio(self):
        texto = "Reinauguración Polideportivo del Barrio 18 de Noviembre en Libertador"
        lineas = _envolver_texto(texto, ancho_maximo=20, maximo_lineas=4)
        palabras_originales = set(texto.split())
        for linea in lineas:
            for palabra in linea.rstrip(" …").split():
                self.assertIn(palabra, palabras_originales)

    def test_respeta_el_ancho_maximo_por_linea(self):
        texto = "Palabra " * 50
        lineas = _envolver_texto(texto.strip(), ancho_maximo=24, maximo_lineas=6)
        for linea in lineas:
            self.assertLessEqual(len(linea), 24)

    def test_trunca_con_elipsis_cuando_excede_el_maximo_de_lineas(self):
        texto = "Palabra " * 50
        lineas = _envolver_texto(texto.strip(), ancho_maximo=20, maximo_lineas=2)
        self.assertEqual(len(lineas), 2)
        self.assertTrue(lineas[-1].endswith("…"))

    def test_texto_vacio_no_genera_lineas(self):
        self.assertEqual(_envolver_texto("", 20, 3), [])
        self.assertEqual(_envolver_texto("   ", 20, 3), [])


class TestGenerarSvgPlaca(unittest.TestCase):
    def test_incluye_branding_titulo_fuente_y_localidad(self):
        svg = generar_svg_placa(
            "Título corto",
            "El municipio inauguró la nueva plaza para los vecinos.",
            fuente="Ejemplo Noticias (prueba)",
            localidad="Libertador General San Martín",
        )
        self.assertIn("LEDESMA PARTICIPA", svg)
        self.assertIn("Título corto", svg)
        self.assertIn("Fuente: Ejemplo Noticias (prueba)", svg)
        self.assertIn("Localidad: Libertador General San Martín", svg)
        self.assertTrue(svg.strip().startswith("<svg"))

    def test_escapa_contenido_potencialmente_malicioso(self):
        svg = generar_svg_placa(
            "<script>alert(1)</script>", "Texto normal.", fuente="Fuente", localidad="Jujuy"
        )
        self.assertNotIn("<script>alert", svg)
        self.assertIn("&lt;script&gt;", svg)

    def test_titulo_largo_no_rompe_el_render(self):
        titulo_largo = "Palabra " * 60
        svg = generar_svg_placa(titulo_largo.strip(), "Resumen breve.", "Fuente", "Localidad")
        self.assertTrue(svg.strip().startswith("<svg"))
        self.assertIn("</svg>", svg)

    def test_resumen_largo_no_rompe_el_render(self):
        resumen_largo = "Palabra " * 120
        svg = generar_svg_placa("Título breve", resumen_largo.strip(), "Fuente", "Localidad")
        self.assertTrue(svg.strip().startswith("<svg"))
        self.assertIn("</svg>", svg)

    def test_sin_fuente_ni_localidad_no_rompe_el_render(self):
        svg = generar_svg_placa("Título", "Resumen.")
        self.assertTrue(svg.strip().startswith("<svg"))


class TestEnvolverTextoPixeles(unittest.TestCase):
    def setUp(self):
        imagen = Image.new("RGB", (10, 10))
        self.dibujo = ImageDraw.Draw(imagen)
        self.fuente = ImageFont.load_default(size=32)

    def test_no_corta_palabras_al_medio(self):
        texto = "Reinauguración Polideportivo del Barrio 18 de Noviembre en Libertador"
        lineas = _envolver_texto_pixeles(self.dibujo, texto, self.fuente, 300, 4)
        palabras_originales = set(texto.split())
        for linea in lineas:
            for palabra in linea.rstrip("…").split():
                self.assertIn(palabra, palabras_originales)

    def test_respeta_el_ancho_maximo_en_pixeles(self):
        texto = ("Palabra " * 50).strip()
        ancho_maximo_px = 300
        lineas = _envolver_texto_pixeles(self.dibujo, texto, self.fuente, ancho_maximo_px, 6)
        for linea in lineas:
            self.assertLessEqual(self.dibujo.textlength(linea, font=self.fuente), ancho_maximo_px)

    def test_trunca_con_elipsis_cuando_excede_el_maximo_de_lineas(self):
        texto = ("Palabra " * 50).strip()
        lineas = _envolver_texto_pixeles(self.dibujo, texto, self.fuente, 250, 2)
        self.assertEqual(len(lineas), 2)
        self.assertTrue(lineas[-1].endswith("…"))

    def test_texto_vacio_no_genera_lineas(self):
        self.assertEqual(_envolver_texto_pixeles(self.dibujo, "", self.fuente, 300, 3), [])
        self.assertEqual(_envolver_texto_pixeles(self.dibujo, "   ", self.fuente, 300, 3), [])


class TestGenerarImagenPlacaPng(unittest.TestCase):
    def test_produce_png_valido(self):
        datos = generar_imagen_placa_png(
            "Título corto",
            "El municipio inauguró la nueva plaza para los vecinos.",
            fuente="Ejemplo Noticias (prueba)",
            localidad="Libertador General San Martín",
        )
        self.assertTrue(datos.startswith(FIRMA_PNG))

    def test_dimensiones_1080x1080(self):
        datos = generar_imagen_placa_png("Título", "Resumen.", "Fuente", "Jujuy")
        with Image.open(io.BytesIO(datos)) as imagen:
            self.assertEqual(imagen.size, (ANCHO_PLACA, ALTO_PLACA))
            self.assertEqual((ANCHO_PLACA, ALTO_PLACA), (1080, 1080))

    def test_titulo_largo_no_rompe_el_render(self):
        titulo_largo = ("Palabra " * 60).strip()
        datos = generar_imagen_placa_png(titulo_largo, "Resumen breve.", "Fuente", "Localidad")
        with Image.open(io.BytesIO(datos)) as imagen:
            self.assertEqual(imagen.size, (ANCHO_PLACA, ALTO_PLACA))

    def test_resumen_largo_no_rompe_el_render(self):
        resumen_largo = ("Palabra " * 120).strip()
        datos = generar_imagen_placa_png("Título breve", resumen_largo, "Fuente", "Localidad")
        with Image.open(io.BytesIO(datos)) as imagen:
            self.assertEqual(imagen.size, (ANCHO_PLACA, ALTO_PLACA))

    def test_sin_fuente_ni_localidad_no_rompe_el_render(self):
        datos = generar_imagen_placa_png("Título", "Resumen.")
        self.assertTrue(datos.startswith(FIRMA_PNG))

    def test_no_rompe_con_caracteres_especiales_en_el_texto(self):
        datos = generar_imagen_placa_png("<script>alert(1)</script>", "Texto normal.", "Fuente", "Jujuy")
        self.assertTrue(datos.startswith(FIRMA_PNG))


class TestFuenteConSoporteDeEspanol(unittest.TestCase):
    """ImageFont.load_default() (la fuente que trae Pillow embebida) no
    tiene los glifos de tildes/ñ/¿/¡: los dibuja como un glifo de
    "faltante" mucho más ancho que una letra real (ver _cargar_fuente en
    motor_noticias.meta.imagen). Estos tests verifican que se resuelve una
    fuente real del sistema y que, con ella, los caracteres especiales del
    español no salen corruptos."""

    @staticmethod
    def _ratio_ancho_caracter_acentuado(fuente):
        imagen = Image.new("RGB", (10, 10))
        dibujo = ImageDraw.Draw(imagen)
        ancho_i = dibujo.textlength("i", font=fuente)
        ancho_i_acentuada = dibujo.textlength("í", font=fuente)
        return ancho_i_acentuada / ancho_i

    def test_se_resuelve_una_fuente_real_del_sistema(self):
        ruta = _ruta_fuente_unicode()
        self.assertIsNotNone(
            ruta, "no se encontró ninguna fuente con soporte de español en este entorno"
        )

    def test_la_fuente_cargada_no_corrompe_caracteres_acentuados(self):
        fuente = _cargar_fuente(48)
        ratio = self._ratio_ancho_caracter_acentuado(fuente)
        # Con ImageFont.load_default() este ratio da ~2.2 (glifo de
        # "faltante", mucho más ancho que una "i" real); con una fuente que
        # sí tiene el glifo de "í" da un ratio cercano a 1.
        self.assertLess(ratio, 1.5)

    def test_placa_con_palabras_acentuadas_reales_no_usa_la_fuente_rota(self):
        # Caso reportado: "rítmica", "participación", "autonomía" y
        # "discapacidad" en la misma placa (noticia real de Libertador).
        datos = generar_imagen_placa_png(
            "Jornada recreativa y rítmica para personas con discapacidad en Libertador",
            "La propuesta generó un espacio de encuentro y participación para "
            "fortalecer habilidades motrices, perceptivas y expresivas, "
            "promoviendo autonomía y bienestar.",
            fuente="Prensa Jujuy (Gobierno de Jujuy)",
            localidad="Libertador",
        )
        self.assertTrue(datos.startswith(FIRMA_PNG))
        with Image.open(io.BytesIO(datos)) as imagen:
            self.assertEqual(imagen.size, (ANCHO_PLACA, ALTO_PLACA))


class TestGenerarPlaca(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.directorio = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_genera_archivo_png_valido(self):
        ruta = generar_placa(
            "Título", "Resumen.", fuente="Fuente", localidad="Jujuy", directorio_salida=self.directorio
        )
        self.assertTrue(ruta.exists())
        self.assertEqual(ruta.suffix, ".png")
        self.assertTrue(ruta.read_bytes().startswith(FIRMA_PNG))

    def test_dimensiones_del_archivo_generado(self):
        ruta = generar_placa("Título", "Resumen.", "Fuente", "Jujuy", self.directorio)
        with Image.open(ruta) as imagen:
            self.assertEqual(imagen.size, (1080, 1080))

    def test_mismo_contenido_reutiliza_el_mismo_archivo_sin_regenerarlo(self):
        ruta1 = generar_placa("Título", "Resumen.", "Fuente", "Jujuy", self.directorio)
        mtime_original = ruta1.stat().st_mtime_ns

        ruta2 = generar_placa("Título", "Resumen.", "Fuente", "Jujuy", self.directorio)

        self.assertEqual(ruta1, ruta2)
        self.assertEqual(ruta2.stat().st_mtime_ns, mtime_original)

    def test_contenido_distinto_genera_archivo_distinto(self):
        ruta1 = generar_placa("Título A", "Resumen A.", "Fuente", "Jujuy", self.directorio)
        ruta2 = generar_placa("Título B", "Resumen B.", "Fuente", "Jujuy", self.directorio)
        self.assertNotEqual(ruta1, ruta2)


class TestGenerarImagenStoryPng(unittest.TestCase):
    def test_produce_png_valido(self):
        datos = generar_imagen_story_png(
            "Título corto",
            "El municipio inauguró la nueva plaza para los vecinos.",
            fuente="Ejemplo Noticias (prueba)",
            localidad="Libertador General San Martín",
        )
        self.assertTrue(datos.startswith(FIRMA_PNG))

    def test_dimensiones_1080x1920_formato_9_16(self):
        datos = generar_imagen_story_png("Título", "Resumen.", "Fuente", "Jujuy")
        with Image.open(io.BytesIO(datos)) as imagen:
            self.assertEqual(imagen.size, (ANCHO_STORY, ALTO_STORY))
            self.assertEqual((ANCHO_STORY, ALTO_STORY), (1080, 1920))

    def test_es_un_formato_distinto_al_de_la_placa_de_feed(self):
        self.assertNotEqual((ANCHO_STORY, ALTO_STORY), (ANCHO_PLACA, ALTO_PLACA))

    def test_titulo_y_resumen_largos_no_rompen_el_render(self):
        titulo_largo = ("Palabra " * 60).strip()
        resumen_largo = ("Palabra " * 120).strip()
        datos = generar_imagen_story_png(titulo_largo, resumen_largo, "Fuente", "Localidad")
        with Image.open(io.BytesIO(datos)) as imagen:
            self.assertEqual(imagen.size, (ANCHO_STORY, ALTO_STORY))

    def test_sin_fuente_ni_localidad_no_rompe_el_render(self):
        datos = generar_imagen_story_png("Título", "Resumen.")
        self.assertTrue(datos.startswith(FIRMA_PNG))


class TestGenerarStory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.directorio = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_genera_archivo_png_valido(self):
        ruta = generar_story(
            "Título", "Resumen.", fuente="Fuente", localidad="Jujuy", directorio_salida=self.directorio
        )
        self.assertTrue(ruta.exists())
        self.assertEqual(ruta.suffix, ".png")
        self.assertTrue(ruta.name.startswith("story_"))
        self.assertTrue(ruta.read_bytes().startswith(FIRMA_PNG))

    def test_dimensiones_del_archivo_generado(self):
        ruta = generar_story("Título", "Resumen.", "Fuente", "Jujuy", self.directorio)
        with Image.open(ruta) as imagen:
            self.assertEqual(imagen.size, (1080, 1920))

    def test_mismo_contenido_reutiliza_el_mismo_archivo_sin_regenerarlo(self):
        ruta1 = generar_story("Título", "Resumen.", "Fuente", "Jujuy", self.directorio)
        mtime_original = ruta1.stat().st_mtime_ns

        ruta2 = generar_story("Título", "Resumen.", "Fuente", "Jujuy", self.directorio)

        self.assertEqual(ruta1, ruta2)
        self.assertEqual(ruta2.stat().st_mtime_ns, mtime_original)

    def test_no_colisiona_con_la_placa_de_feed_del_mismo_contenido(self):
        ruta_story = generar_story("Título", "Resumen.", "Fuente", "Jujuy", self.directorio)
        ruta_placa = generar_placa("Título", "Resumen.", "Fuente", "Jujuy", self.directorio)
        self.assertNotEqual(ruta_story, ruta_placa)
        self.assertTrue(ruta_story.exists())
        self.assertTrue(ruta_placa.exists())


if __name__ == "__main__":
    unittest.main()
