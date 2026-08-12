import unittest

from motor_noticias.territorio import clasificar_territorio


class TestClasificacionTerritorial(unittest.TestCase):
    def test_local(self):
        r = clasificar_territorio(
            "Obras en Libertador General San Martín",
            "El municipio anunció obras viales en distintos barrios.",
        )
        self.assertEqual(r["territorio"], "local")
        self.assertTrue(r["relevante"])
        self.assertIsNotNone(r["motivo_territorio"])

    def test_departamental(self):
        r = clasificar_territorio(
            "Novedades en Calilegua", "Vecinos de Calilegua, en el Departamento Ledesma."
        )
        self.assertEqual(r["territorio"], "departamental")
        self.assertTrue(r["relevante"])

    def test_provincial(self):
        r = clasificar_territorio(
            "Turismo en Jujuy", "La provincia de Jujuy presentó su calendario turístico."
        )
        self.assertEqual(r["territorio"], "provincial")
        self.assertFalse(r["relevante"])

    def test_nacional(self):
        r = clasificar_territorio(
            "Economía nacional", "El Gobierno nacional anunció cambios en Buenos Aires."
        )
        self.assertEqual(r["territorio"], "nacional")
        self.assertFalse(r["relevante"])

    def test_sin_clasificar(self):
        r = clasificar_territorio(
            "El artista lanzó su nuevo disco",
            "El músico presentó su nuevo álbum en una gira internacional.",
        )
        self.assertEqual(r["territorio"], "sin_clasificar")
        self.assertFalse(r["relevante"])
        self.assertIsNone(r["localidad"])

    def test_variantes_de_libertador(self):
        variantes = (
            "Libertador General San Martín",
            "Libertador Gral. San Martín",
            "Libertador San Martín",
            "Libertador",
        )
        for variante in variantes:
            with self.subTest(variante=variante):
                r = clasificar_territorio(f"Obras en {variante}", f"El municipio de {variante} informó novedades.")
                self.assertEqual(r["territorio"], "local")

    def test_clasificacion_es_auditable_con_motivo_explicito(self):
        for titulo, texto in (
            ("Obras en Libertador General San Martín", "Novedades del municipio."),
            ("Novedades en Yuto", "Vecinos de Yuto, en el Departamento Ledesma."),
            ("Turismo en Jujuy", "La provincia presentó su calendario."),
            ("Anuncio nacional", "El Gobierno nacional presentó medidas."),
            ("Nota sin relación geográfica", "Contenido sin ninguna referencia territorial."),
        ):
            r = clasificar_territorio(titulo, texto)
            self.assertTrue(r["motivo_territorio"])
            self.assertIn(r["territorio"], ("local", "departamental", "provincial", "nacional", "sin_clasificar"))


if __name__ == "__main__":
    unittest.main()
