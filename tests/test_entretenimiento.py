import unittest

from motor_noticias.entretenimiento import es_entretenimiento_o_curiosidad


class TestEsEntretenimientoOCuriosidad(unittest.TestCase):
    def test_titulo_con_viral_es_entretenimiento(self):
        self.assertTrue(
            es_entretenimiento_o_curiosidad("Un video se hizo viral en las redes sociales", "")
        )

    def test_texto_con_espectaculos_es_entretenimiento(self):
        self.assertTrue(
            es_entretenimiento_o_curiosidad("Título neutro", "Nota de la sección espectáculos de hoy.")
        )

    def test_curiosidad_es_entretenimiento(self):
        self.assertTrue(es_entretenimiento_o_curiosidad("Una curiosidad sobre el espacio", ""))

    def test_sin_palabras_clave_no_es_entretenimiento(self):
        self.assertFalse(
            es_entretenimiento_o_curiosidad(
                "El gobierno anunció nuevas medidas económicas", "Detalle de la medida."
            )
        )

    def test_no_distingue_mayusculas_ni_acentos(self):
        self.assertTrue(es_entretenimiento_o_curiosidad("INSOLITO caso en el pueblo", ""))


if __name__ == "__main__":
    unittest.main()
