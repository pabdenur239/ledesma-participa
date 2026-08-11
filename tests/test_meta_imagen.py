import tempfile
import unittest
from pathlib import Path

from motor_noticias.meta.imagen import _envolver_texto, generar_placa, generar_svg_placa


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


class TestGenerarPlaca(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.directorio = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_genera_archivo_svg(self):
        ruta = generar_placa(
            "Título", "Resumen.", fuente="Fuente", localidad="Jujuy", directorio_salida=self.directorio
        )
        self.assertTrue(ruta.exists())
        self.assertEqual(ruta.suffix, ".svg")

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


if __name__ == "__main__":
    unittest.main()
