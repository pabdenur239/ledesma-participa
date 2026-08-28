import unittest

from motor_noticias.relevancia import clasificar_relevancia


class TestRelevancia(unittest.TestCase):
    def test_libertador_es_relevante(self):
        r = clasificar_relevancia(
            "Obras en Libertador General San Martín", "Se anunciaron nuevas obras viales."
        )
        self.assertTrue(r["relevante"])

    def test_departamento_ledesma_es_relevante(self):
        r = clasificar_relevancia(
            "Novedades en Calilegua", "Vecinos de Calilegua, en el Departamento Ledesma."
        )
        self.assertTrue(r["relevante"])

    def test_jujuy_sin_relacion_no_es_relevante(self):
        r = clasificar_relevancia(
            "Turismo en Jujuy", "La provincia de Jujuy presentó su calendario turístico."
        )
        self.assertFalse(r["relevante"])

    def test_noticia_sin_relacion_geografica_no_es_relevante(self):
        r = clasificar_relevancia(
            "Economía nacional", "El Gobierno nacional anunció cambios en Buenos Aires."
        )
        self.assertFalse(r["relevante"])
        self.assertIsNotNone(r["motivo"])

    def test_copa_libertadores_no_es_relevante(self):
        r = clasificar_relevancia(
            "Flamengo le ganó a Cruzeiro y avanzó en la Copa Libertadores",
            "El equipo brasileño se clasificó a los cuartos de final del torneo continental.",
        )
        self.assertFalse(r["relevante"])

    def test_firma_ledesma_participa_no_clasifica_como_departamental(self):
        # La firma "Nota propia de Ledesma Participa..." de toda nota de
        # contenido propio no debe contar como referencia geográfica.
        r = clasificar_relevancia(
            "Alerta: novedad del Ministerio de Salud de la Nación",
            "El Hospital El Cruce funcionará como Centro de Coordinación Regional. "
            "Nota propia de Ledesma Participa a partir de información oficial pública.",
        )
        self.assertFalse(r["relevante"])
        self.assertIsNone(r["localidad"])

    def test_mencion_real_de_ledesma_sigue_siendo_relevante_pese_a_la_firma(self):
        r = clasificar_relevancia(
            "Obras viales en la ciudad",
            "Se pavimentaron calles en Ledesma esta semana. "
            "Nota propia de Ledesma Participa a partir de información oficial pública.",
        )
        self.assertTrue(r["relevante"])
        self.assertEqual(r["localidad"], "Ledesma")

    def test_localidad_de_fuente_institucional_es_relevante_sin_mencion_en_el_texto(self):
        r = clasificar_relevancia(
            "Ing. Oscar Jayat nuevo Presidente del BRIPAEM",
            "En una asamblea extraordinaria realizada en la ciudad de Buenos Aires, "
            "asumió como Presidente del BRIPAEM por el periodo 2026-2028.",
            localidad="Libertador General San Martín",
        )
        self.assertTrue(r["relevante"])


if __name__ == "__main__":
    unittest.main()
