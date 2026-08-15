import tempfile
import unittest
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.motor_editorial import generar_agenda
from motor_noticias.pipeline import procesar_noticia
from motor_noticias.redaccion.mock import RedactorMock
from motor_noticias.territorio import clasificar_territorio
from motor_noticias.pipeline import normalizar_noticia


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


class TestClasificacionNacionalMejorada(unittest.TestCase):
    """Corrección: la clasificación nacional real (no vacía) para medios
    nacionales configurados (La Nación, Infobae), sin marcar todo como
    nacional solo por la fuente."""

    # 1. Argentina explícita → nacional
    def test_argentina_explicita_es_nacional(self):
        r = clasificar_territorio(
            "Un show internacional llega a Argentina",
            "La banda confirmó fechas en el país para el próximo año.",
        )
        self.assertEqual(r["territorio"], "nacional")

    # 2. Gobierno Nacional → nacional
    def test_gobierno_nacional_es_nacional(self):
        r = clasificar_territorio(
            "Nuevas medidas económicas",
            "El Gobierno Nacional anunció cambios en la política de subsidios.",
        )
        self.assertEqual(r["territorio"], "nacional")

    # 3. Congreso Nacional → nacional
    def test_congreso_nacional_es_nacional(self):
        r = clasificar_territorio(
            "Sesión clave",
            "El Congreso Nacional debate hoy una nueva ley previsional.",
        )
        self.assertEqual(r["territorio"], "nacional")

    # 4. BCRA → nacional
    def test_bcra_es_nacional(self):
        r = clasificar_territorio(
            "Política monetaria",
            "El BCRA subió la tasa de referencia tras la última licitación.",
        )
        self.assertEqual(r["territorio"], "nacional")

    # 5. ANSES → nacional
    def test_anses_es_nacional(self):
        r = clasificar_territorio(
            "Jubilaciones",
            "ANSES confirmó el cronograma de pagos de agosto.",
        )
        self.assertEqual(r["territorio"], "nacional")

    # 6. URL/sección argentina → nacional (fallback, medio nacional, sin marcador explícito)
    def test_url_seccion_argentina_es_nacional_via_fallback(self):
        r = clasificar_territorio(
            "Ganancias del trimestre",
            "La inflación afectó los balances de varias empresas del sector.",
            nombre_fuente="La Nación",
            url="https://www.lanacion.com.ar/economia/ganancias-del-trimestre-nid1/",
            categoria="Economía",
        )
        self.assertEqual(r["territorio"], "nacional")
        self.assertIn("La Nación", r["motivo_territorio"])

    # 7. La Nación + sección nacional/general + sin geografía extranjera → nacional
    def test_lanacion_seccion_general_sin_geografia_extranjera_es_nacional(self):
        r = clasificar_territorio(
            "Suben las jubilaciones",
            "El haber mínimo tendrá un nuevo incremento a partir del próximo mes.",
            nombre_fuente="La Nación",
            url="https://www.lanacion.com.ar/economia/suben-las-jubilaciones-nid2/",
            categoria="Economía",
        )
        self.assertEqual(r["territorio"], "nacional")

    # 8. Infobae + sección argentina + sin geografía extranjera → nacional
    def test_infobae_seccion_argentina_sin_geografia_extranjera_es_nacional(self):
        r = clasificar_territorio(
            "Cambios en subsidios",
            "El nuevo esquema de subsidios energéticos regirá desde septiembre.",
            nombre_fuente="Infobae",
            url="https://www.infobae.com/economia/2026/08/12/cambios-en-subsidios/",
            categoria=None,
        )
        self.assertEqual(r["territorio"], "nacional")

    # 9. Estados Unidos → no nacional
    def test_estados_unidos_no_es_nacional(self):
        r = clasificar_territorio(
            "Elecciones en Estados Unidos",
            "El resultado de los comicios definirá el rumbo del Congreso norteamericano.",
            nombre_fuente="La Nación",
            url="https://www.lanacion.com.ar/el-mundo/elecciones-en-estados-unidos-nid3/",
            categoria="El Mundo",
        )
        self.assertNotEqual(r["territorio"], "nacional")

    # 10. México → no nacional
    def test_mexico_no_es_nacional(self):
        r = clasificar_territorio(
            "Hecho ocurrido en México",
            "Las autoridades mexicanas investigan lo sucedido en la capital.",
            nombre_fuente="Infobae",
            url="https://www.infobae.com/mexico/2026/08/12/hecho-ocurrido-en-mexico/",
            categoria=None,
        )
        self.assertNotEqual(r["territorio"], "nacional")

    # 11. Noticia internacional genérica → sin_clasificar
    def test_internacional_generica_queda_sin_clasificar(self):
        r = clasificar_territorio(
            "Guerra en Europa",
            "El conflicto en Europa continúa golpeando a la población civil.",
            nombre_fuente="La Nación",
            url="https://www.lanacion.com.ar/el-mundo/guerra-en-europa-nid4/",
            categoria="El Mundo",
        )
        self.assertEqual(r["territorio"], "sin_clasificar")

    # 12. Jujuy en medio nacional → provincial
    def test_jujuy_en_medio_nacional_es_provincial(self):
        r = clasificar_territorio(
            "Turismo en el norte",
            "La provincia de Jujuy presentó su calendario turístico 2027.",
            nombre_fuente="La Nación",
            url="https://www.lanacion.com.ar/sociedad/turismo-jujuy-nid5/",
            categoria="Sociedad",
        )
        self.assertEqual(r["territorio"], "provincial")

    # 13. Libertador en medio nacional → local
    def test_libertador_en_medio_nacional_es_local(self):
        r = clasificar_territorio(
            "Obras en el norte jujeño",
            "El municipio de Libertador General San Martín anunció nuevas obras viales.",
            nombre_fuente="Infobae",
            url="https://www.infobae.com/sociedad/2026/08/12/obras-en-el-norte-jujeno/",
            categoria=None,
        )
        self.assertEqual(r["territorio"], "local")

    # extra: sección ambigua (deportes) sin marcador explícito no se asume nacional
    def test_deportes_extranjero_sin_marcador_no_es_nacional(self):
        r = clasificar_territorio(
            "Nuevo entrenador para la selección",
            "El técnico fue confirmado como nuevo entrenador de la selección de Países Bajos.",
            nombre_fuente="Infobae",
            url="https://www.infobae.com/deportes/2026/08/12/nuevo-entrenador-para-la-seleccion/",
            categoria=None,
        )
        self.assertNotEqual(r["territorio"], "nacional")

    # extra: no marcar nacional solo por el nombre de la fuente cuando hay evidencia internacional
    def test_no_marca_nacional_solo_por_nombre_de_fuente(self):
        r = clasificar_territorio(
            "Nota sobre Brasil",
            "El evento se realizó en San Pablo, Brasil, con más de mil asistentes.",
            nombre_fuente="Infobae",
            url="https://www.infobae.com/brasil/2026/08/12/nota-sobre-brasil/",
            categoria=None,
        )
        self.assertNotEqual(r["territorio"], "nacional")

    # 14. La cascada usa una noticia nacional real (resultante del fallback, sin marcador explícito)
    def test_cascada_usa_noticia_nacional_real_del_fallback(self):
        tmpdir = tempfile.TemporaryDirectory()
        try:
            db = Database(Path(tmpdir.name) / "test.db")
            redactor = RedactorMock()

            noticia_local = normalizar_noticia(
                {
                    "titulo": "Obras en Libertador General San Martín",
                    "texto": "Se realizaron nuevas obras viales en distintos barrios de la ciudad.",
                    "url": "https://www.example.com/local-1/",
                    "fuente": "Prensa Jujuy",
                    "fecha": "Wed, 12 Aug 2026 12:00:00 +0000",
                }
            )
            procesar_noticia(db, noticia_local, redactor)

            # Sin marcador nacional explícito: solo clasifica nacional gracias
            # al fallback de medio nacional (sección argentina, sin evidencia
            # internacional).
            noticia_nacional = normalizar_noticia(
                {
                    "titulo": "Suben las jubilaciones",
                    "texto": "El haber mínimo tendrá un nuevo incremento a partir del próximo mes.",
                    "url": "https://www.lanacion.com.ar/economia/suben-las-jubilaciones-nid9/",
                    "fuente": "La Nación",
                    "fecha": "Wed, 12 Aug 2026 12:00:00 +0000",
                }
            )
            _, resultado = procesar_noticia(db, noticia_nacional, redactor, categoria="Economía")
            self.assertEqual(resultado, "preparada")
            self.assertEqual(noticia_nacional.territorio, "nacional")

            entradas = generar_agenda(db, fecha="2026-08-12", horarios=("08:00", "10:30"))
            territorios = [e.territorio for e in entradas]
            self.assertIn("nacional", territorios)
            self.assertLess(territorios.index("local"), territorios.index("nacional"))
        finally:
            db.close()
            tmpdir.cleanup()

    # 15. suite completa: cubierto por `python3 -m unittest discover -s tests`


if __name__ == "__main__":
    unittest.main()
