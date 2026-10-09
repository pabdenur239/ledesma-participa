"""Etapa 1: territorio, categoría y urgente separados, con confianza.

Incluye los errores reales reportados que no deben volver: banco →
Gastronomía, jubilados → Gastronomía, accidente → Salud, Jujuy →
Internacional, fútbol argentino → Internacional."""
import unittest
from unittest.mock import patch

from motor_noticias.categorias import (
    CATEGORIA_GENERAL,
    cargar_config,
    clasificar_categoria,
    resolver_categoria,
    territorio_vigente_con_confianza,
)
from motor_noticias.clasificacion import clasificar_noticia
from motor_noticias.territorio import clasificar_territorio


def _nota(titulo, texto="", fuente="Jujuy al día", url="https://www.jujuyaldia.com.ar/nota", **extra):
    base = {
        "id": 1, "titulo_original": titulo, "titulo_preparado": titulo, "texto_original": texto,
        "texto_preparado": texto, "nombre_fuente": fuente, "url_fuente": url, "origen_ingreso": "automatico",
        "fecha_recoleccion": "2026-10-08T12:00:00+00:00",
    }
    base.update(extra)
    return base


class TestCasosConocidosIncorrectos(unittest.TestCase):
    def test_banco_no_es_gastronomia(self):
        nota = _nota("El Banco Nación lanzó descuentos en restaurantes y supermercados",
                     "Los clientes del banco tendrán reintegros en comercios gastronómicos.")
        self.assertNotEqual(clasificar_categoria(nota)["valor"], "gastronomia")

    def test_jubilados_buscando_alimentos_no_es_gastronomia(self):
        nota = _nota("Jubilados hacen fila para conseguir alimentos en un comedor de Libertador",
                     "Decenas de jubilados buscan comida y bolsones en el comedor del barrio.")
        self.assertNotEqual(clasificar_categoria(nota)["valor"], "gastronomia")

    def test_accidente_no_es_salud_por_defecto(self):
        nota = _nota("Choque en la Ruta 34: dos heridos fueron trasladados al hospital",
                     "Un auto y una moto chocaron. Los heridos fueron atendidos en el hospital Oscar Orías.")
        categoria = clasificar_categoria(nota)
        self.assertNotEqual(categoria["valor"], "salud")
        self.assertEqual(categoria["candidata"], "policiales")

    def test_noticia_de_jujuy_no_es_internacional(self):
        # Bug real: "Sadir desde París" quedaba internacional.
        resultado = clasificar_territorio(
            "Sadir desde París: 'La idea es seguir en este camino y buscar nuevas inversiones'",
            "El gobernador presentó las oportunidades de la provincia en Francia.",
            nombre_fuente="Somos Jujuy",
        )
        self.assertEqual(resultado["territorio"], "provincial")

    def test_futbol_argentino_no_es_internacional(self):
        nota = _nota(
            "El emotivo último partido en el que Messi se despidió de la selección argentina",
            "La AFA organizó la despedida ante Brasil.", fuente="BBC Mundo",
            url="https://www.bbc.com/mundo/articles/x", categoria_tematica="internacional",
        )
        territorio, _ = territorio_vigente_con_confianza(nota)
        self.assertEqual(territorio, "nacional")
        self.assertEqual(clasificar_categoria(nota)["valor"], "deportes")

    def test_eleccion_con_partido_no_es_deportes(self):
        # Bug real: "Partido Colorado" → Deportes por la palabra "partido".
        nota = _nota("Partido Colorado gana en mayoría de distritos paraguayos", fuente="Infobae")
        self.assertNotEqual(clasificar_categoria(nota)["valor"], "deportes")

    def test_marcador_nacional_generico_no_le_gana_a_un_pais_extranjero(self):
        resultado = clasificar_territorio(
            "El banco central de Colombia aumenta la tasa de interés para frenar la inflación", "",
            nombre_fuente="France 24 Español",
        )
        self.assertEqual(resultado["territorio"], "internacional")


class TestConfianzaYUmbrales(unittest.TestCase):
    def test_libertador_96_salud_62_va_a_general(self):
        # Caso pedido: territorio Libertador 96 %, categoría Salud 62 %.
        # Resultado: territorio Libertador, categoría General / Últimas.
        candidata = {"valor": resolver_categoria("salud", 0.62), "etiqueta": "General / Últimas",
                     "confianza": 0.62, "candidata": "salud", "puntajes": {}}
        with patch("motor_noticias.clasificacion.territorio_vigente_con_confianza", return_value=("local", 0.96)),                 patch("motor_noticias.clasificacion.clasificar_categoria", return_value=candidata):
            resultado = clasificar_noticia(_nota("Nota de prueba"), urgente=False)
        self.assertEqual(resultado["territorio"]["valor"], "libertador")
        self.assertEqual(resultado["territorio"]["confianza"], 0.96)
        self.assertEqual(resultado["categoria"]["valor"], CATEGORIA_GENERAL)
        self.assertEqual(resultado["categoria"]["confianza"], 0.62)

    def test_umbrales(self):
        self.assertEqual(resolver_categoria("salud", 0.86), "salud")
        self.assertEqual(resolver_categoria("salud", 0.85), CATEGORIA_GENERAL)
        self.assertEqual(resolver_categoria("salud", 0.50), CATEGORIA_GENERAL)
        self.assertIsNone(resolver_categoria("salud", 0.49))

    def test_una_sola_palabra_en_el_titulo_no_alcanza_para_categoria_automatica(self):
        categoria = clasificar_categoria(_nota("Jornada de vacunación en el barrio"))
        self.assertEqual(categoria["candidata"], "salud")
        self.assertLess(categoria["confianza"], cargar_config()["umbral_automatico"] + 0.0001)
        self.assertEqual(categoria["valor"], CATEGORIA_GENERAL)

    def test_tema_principal_con_evidencia_clara_se_asigna(self):
        nota = _nota("Detuvieron a dos hombres por un robo en Libertador",
                     "La Policía allanó una vivienda y recuperó los objetos robados. Los detenidos quedaron en la comisaría.")
        categoria = clasificar_categoria(nota)
        self.assertEqual(categoria["valor"], "policiales")
        self.assertGreater(categoria["confianza"], 0.85)

    def test_sin_evidencia_no_tiene_categoria(self):
        categoria = clasificar_categoria(_nota("Reunión vecinal en el centro"))
        self.assertIsNone(categoria["valor"])
        self.assertEqual(categoria["confianza"], 0.0)

    def test_territorio_tiene_confianza_propia(self):
        resultado = clasificar_territorio("Corte de agua en Libertador General San Martín", "")
        self.assertEqual(resultado["territorio"], "local")
        self.assertGreaterEqual(resultado["confianza"], 0.9)
        sin = clasificar_territorio("Una nota sin lugar", "")
        self.assertEqual(sin["confianza"], 0.0)

    def test_informe_diario_es_servicios_con_territorio_fijo(self):
        nota = _nota("Clima + Dólar | Informe de la mañana", territorio="local",
                     url_normalizada="https://ledesma-participa.local/informe-diario/2026-10-09")
        resultado = clasificar_noticia(nota, urgente=False)
        self.assertEqual(resultado["categoria"]["valor"], "servicios")
        self.assertEqual(resultado["territorio"]["valor"], "libertador")


class TestUrgenteNoEsCategoria(unittest.TestCase):
    def test_urgente_es_dimension_aparte(self):
        nota = _nota("Detuvieron a dos hombres por un robo en Libertador",
                     "La Policía allanó una vivienda. Los detenidos quedaron en la comisaría.")
        with patch("motor_noticias.clasificacion.urgente_confirmado", return_value=True):
            resultado = clasificar_noticia(nota)
        self.assertTrue(resultado["urgente"])
        self.assertEqual(resultado["categoria"]["valor"], "policiales")
        self.assertNotIn("urgente", cargar_config()["categorias"])

    def test_urgente_lo_decide_el_scoring_no_la_fecha(self):
        nota = _nota("Inauguraron una muestra de arte en Libertador", urgente=1)
        self.assertFalse(clasificar_noticia(nota)["urgente"])


if __name__ == "__main__":
    unittest.main()
