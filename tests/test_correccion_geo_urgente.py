"""Casos reales del 11/10/2026: nota de Sri Lanka clasificada "Jujuy ·
Yala" y nota de EFE sobre salarios en España publicada como "URGENTE |
NACIONAL" con texto repetido."""
import unittest
from datetime import datetime, timezone

from motor_noticias.meta.contenido import parrafos_copy, _titulo_y_texto_finales
from motor_noticias.redaccion.repeticiones import quitar_oraciones_repetidas
from motor_noticias.scoring_editorial import evaluar_noticia, urgente_confirmado
from motor_noticias.territorio import clasificar_territorio

AHORA = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)

SRI_LANKA = {
    "titulo_original": "Sri Lanka en sequía: pozos vacíos, embalses al límite y animales sin agua",
    "texto_original": (
        "El monzón más débil en años dejó al país con sus 74 reservorios al 30% de capacidad, "
        "afectando a comunidades rurales que dependen de camiones cisterna y la fauna del Parque "
        "Nacional Yala al borde de la supervivencia."
    ),
    "nombre_fuente": "Infobae",
    "url_fuente": "https://www.infobae.com/america/medio-ambiente/2026/10/11/sri-lanka-en-sequia-pozos-vacios-embalses-al-limite-y-animales-sin-agua-por-el-nino/",
}

TEXTO_ESPANA_REDACTADO = (
    "Madrid, 11 oct (EFE).- La crisis de inflación de los últimos años y el fuerte encarecimiento "
    "de la vivienda han lastrado la recuperación de los salarios en España que, pese a crecer en "
    "términos nominales, siguen en niveles moderados y por debajo de la media europea. Según los "
    "datos de la Encuesta Anual de Estructura Salarial (EAES) del Instituto Nacional de Estadística "
    "(INE), en 2008 el salario medio anual era de 21.883,42 euros y en 2024 alcanzó 29.540,26 euros, "
    "un aumento nominal del 35 %. En el año 2008, el salario medio anual era de 21.883,42 euros y en "
    "2024 alcanzó 29.540,26 euros, un aumento nominal del 35 %. El salario medio anual en 2024 es de "
    "29.540,26 euros, un aumento nominal del 35 % respecto al año 2008."
)

ESPANA = {
    "titulo_original": "La inflación y la vivienda vuelven a lastrar el avance de unos salarios ya devaluados",
    "texto_original": TEXTO_ESPANA_REDACTADO,
    "titulo_preparado": "La inflación y la vivienda vuelven a lastrar el avance de unos salarios ya devaluados",
    "texto_preparado": TEXTO_ESPANA_REDACTADO,
    "nombre_fuente": "Infobae",
    "url_fuente": "https://www.infobae.com/espana/agencias/2026/10/11/la-inflacion-y-la-vivienda-vuelven-a-lastrar-el-avance-de-unos-salarios-ya-devaluados/",
    "origen_ingreso": "automatico",
    "fecha_recoleccion": "2026-10-11T08:09:00+00:00",
}


def _territorio(n):
    return clasificar_territorio(
        n["titulo_original"], n["texto_original"], nombre_fuente=n.get("nombre_fuente"), url=n.get("url_fuente")
    )


class TestCasoSriLanka(unittest.TestCase):
    def test_es_internacional_y_no_yala(self):
        r = _territorio(SRI_LANKA)
        self.assertEqual(r["territorio"], "internacional")
        self.assertIsNone(r["localidad"])

    def test_sin_seccion_de_url_tampoco_es_jujuy(self):
        r = _territorio({**SRI_LANKA, "url_fuente": None})
        self.assertEqual(r["territorio"], "internacional")

    def test_yala_suelta_en_el_cuerpo_sin_contexto_no_ubica_en_jujuy(self):
        r = clasificar_territorio(
            "Crece la preocupación por la sequía", "La fauna del parque Yala sufre la falta de agua.",
            nombre_fuente="Infobae", url="https://www.infobae.com/sociedad/2026/10/11/x/",
        )
        self.assertNotEqual(r["territorio"], "provincial")
        self.assertIsNone(r["localidad"])


class TestCasoEspana(unittest.TestCase):
    def test_es_internacional(self):
        self.assertEqual(_territorio(ESPANA)["territorio"], "internacional")

    def test_no_es_urgente(self):
        noticia = {**ESPANA, "territorio": _territorio(ESPANA)["territorio"]}
        self.assertNotEqual(evaluar_noticia(noticia, AHORA)["clasificacion"], "urgente")

    def test_registro_guardado_como_nacional_urgente_ya_no_se_confirma(self):
        # Registro de producción: territorio "nacional" y urgente=1 guardados.
        self.assertFalse(urgente_confirmado({**ESPANA, "territorio": "nacional", "urgente": 1}))

    def test_adjetivo_devaluados_no_es_senal_de_devaluacion(self):
        r = evaluar_noticia({**ESPANA, "territorio": "nacional"}, AHORA)
        self.assertNotIn("economia_inmediata", r["senales"])

    def test_texto_sin_repeticiones_conserva_datos_y_fuente(self):
        _, texto = _titulo_y_texto_finales(ESPANA)
        self.assertEqual(texto.count("21.883,42"), 1)
        self.assertEqual(texto.count("29.540,26"), 1)
        self.assertIn("35 %", texto)
        self.assertIn("por debajo de la media europea", texto)
        self.assertEqual(len(parrafos_copy(texto)), 2)

    def test_oracion_con_dato_nuevo_se_conserva(self):
        texto = (
            "En 2024 el salario medio anual alcanzó 29.540 euros en España. "
            "En 2024 el salario medio anual alcanzó 29.540 euros, y en 2025 subió a 30.100 euros."
        )
        self.assertEqual(quitar_oraciones_repetidas(texto), texto)

    def test_conserva_linea_fuente(self):
        texto = "Hubo un corte de agua en el barrio centro.\n\nFuente: Todo Jujuy"
        self.assertEqual(quitar_oraciones_repetidas(texto), texto)


class TestNoticiasLegitimasSiguenIgual(unittest.TestCase):
    def test_yala_de_medio_jujeno_es_provincial(self):
        r = clasificar_territorio(
            "Choque en Yala deja dos heridos", "El accidente ocurrió sobre la ruta 9.", nombre_fuente="Todo Jujuy"
        )
        self.assertEqual((r["territorio"], r["localidad"]), ("provincial", "Yala"))

    def test_perico_con_jujuy_en_el_texto_es_provincial(self):
        r = clasificar_territorio(
            "Corte de agua en Perico", "Agua Potable de Jujuy informó trabajos en la red.", nombre_fuente="Infobae",
            url="https://www.infobae.com/sociedad/2026/10/11/x/",
        )
        self.assertEqual(r["territorio"], "provincial")

    def test_yala_en_titulo_sin_evidencia_extranjera_es_provincial(self):
        r = clasificar_territorio("Yala: habilitan el nuevo camping", "Abre este fin de semana.", nombre_fuente="Infobae")
        self.assertEqual(r["territorio"], "provincial")

    def test_libertador_sigue_local(self):
        r = clasificar_territorio(
            "Corte de luz en Libertador General San Martín", "Afecta a varios barrios.", nombre_fuente="InfoYungas"
        )
        self.assertEqual(r["territorio"], "local")

    def test_inflacion_argentina_sigue_nacional(self):
        r = clasificar_territorio(
            "La inflación de septiembre fue de 2,1%, informó el INDEC", "El índice de precios al consumidor…",
            nombre_fuente="Infobae", url="https://www.infobae.com/economia/2026/10/11/x/",
        )
        self.assertEqual(r["territorio"], "nacional")

    def test_inflacion_sin_marcador_fuerte_en_medio_nacional_sigue_nacional(self):
        r = clasificar_territorio(
            "La inflación y la vivienda presionan a los salarios", "Los ingresos crecen por debajo de los precios.",
            nombre_fuente="Infobae", url="https://www.infobae.com/economia/2026/10/11/x/",
        )
        self.assertEqual(r["territorio"], "nacional")

    def test_devaluacion_argentina_sigue_siendo_senal_fuerte(self):
        noticia = {
            "titulo_original": "El Gobierno devaluó el peso un 20% y cambia el régimen cambiario",
            "texto_original": "La medida rige desde mañana.", "territorio": "nacional",
            "origen_ingreso": "automatico", "fecha_recoleccion": "2026-10-11T08:30:00+00:00",
        }
        self.assertIn("economia_inmediata", evaluar_noticia(noticia, AHORA)["senales"])


if __name__ == "__main__":
    unittest.main()
