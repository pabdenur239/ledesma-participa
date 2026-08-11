import unittest

from motor_noticias.riesgo_editorial import evaluar_riesgo_editorial


class TestRiesgoEditorial(unittest.TestCase):
    def test_noticia_municipal_requiere_revision_especial(self):
        r = evaluar_riesgo_editorial(
            "El Intendente anunció obras en el barrio San José",
            "El Intendente de la Municipalidad presentó un nuevo plan de obras.",
        )
        self.assertTrue(r["requiere_revision_especial"])
        self.assertIsNotNone(r["motivo"])
        self.assertEqual(r["categoria_riesgo"], "institucional_municipal")

    def test_noticia_sobre_concejal_requiere_revision_especial(self):
        r = evaluar_riesgo_editorial(
            "Un concejal presentó un proyecto en el Concejo Deliberante",
            "El concejal expuso su propuesta ante el resto de los ediles.",
        )
        self.assertTrue(r["requiere_revision_especial"])
        self.assertEqual(r["categoria_riesgo"], "institucional_municipal")

    def test_noticia_sobre_pablo_abdenur_requiere_revision_especial(self):
        r = evaluar_riesgo_editorial(
            "Pablo Abdenur participó de una actividad local",
            "Pablo Abdenur estuvo presente en el evento realizado ayer.",
        )
        self.assertTrue(r["requiere_revision_especial"])
        self.assertEqual(r["categoria_riesgo"], "figura_publica_relacionada")

    def test_noticia_partidaria_requiere_revision_especial(self):
        r = evaluar_riesgo_editorial(
            "Un candidato presentó su lista para las elecciones",
            "El candidato del partido político local confirmó su postulación.",
        )
        self.assertTrue(r["requiere_revision_especial"])
        self.assertEqual(r["categoria_riesgo"], "politica_partidaria")

    def test_noticia_deportiva_comun_no_requiere_revision_especial(self):
        r = evaluar_riesgo_editorial(
            "El club local ganó el torneo regional de fútbol",
            "El equipo venció 3 a 1 en la final disputada el sábado.",
        )
        self.assertFalse(r["requiere_revision_especial"])
        self.assertIsNone(r["categoria_riesgo"])
        self.assertIsNone(r["motivo"])

    def test_noticia_comercial_comun_no_requiere_revision_especial(self):
        r = evaluar_riesgo_editorial(
            "Abrió un nuevo supermercado en el centro",
            "El local ofrece productos regionales y horario extendido.",
        )
        self.assertFalse(r["requiere_revision_especial"])
        self.assertIsNone(r["categoria_riesgo"])

    def test_detecta_menciones_en_titulo_preparado_y_texto_preparado(self):
        r = evaluar_riesgo_editorial(
            "Título original sin riesgo",
            "Texto original sin riesgo.",
            titulo_preparado="El intendente confirmó la novedad",
            texto_preparado="Texto preparado sin mención directa.",
        )
        self.assertTrue(r["requiere_revision_especial"])

    def test_detecta_menciones_en_nombre_fuente(self):
        r = evaluar_riesgo_editorial(
            "Título sin riesgo aparente",
            "Texto sin riesgo aparente.",
            nombre_fuente="Municipalidad de Libertador General San Martín",
        )
        self.assertTrue(r["requiere_revision_especial"])


if __name__ == "__main__":
    unittest.main()
