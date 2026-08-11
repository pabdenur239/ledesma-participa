import unittest

from motor_noticias.publicacion import puede_publicarse_automaticamente


class TestPuedePublicarseAutomaticamente(unittest.TestCase):
    def test_aprobada_sin_riesgo_devuelve_true(self):
        noticia = {"revision_estado": "aprobada", "requiere_revision_especial": 0}
        self.assertTrue(puede_publicarse_automaticamente(noticia))

    def test_aprobada_con_riesgo_especial_devuelve_false(self):
        noticia = {"revision_estado": "aprobada", "requiere_revision_especial": 1}
        self.assertFalse(puede_publicarse_automaticamente(noticia))

    def test_pendiente_devuelve_false(self):
        noticia = {"revision_estado": "pendiente", "requiere_revision_especial": 0}
        self.assertFalse(puede_publicarse_automaticamente(noticia))

    def test_rechazada_devuelve_false(self):
        noticia = {"revision_estado": "rechazada", "requiere_revision_especial": 0}
        self.assertFalse(puede_publicarse_automaticamente(noticia))


if __name__ == "__main__":
    unittest.main()
