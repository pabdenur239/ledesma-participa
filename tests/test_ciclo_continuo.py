import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from motor_noticias.ciclo_continuo import FUENTES_CONTINUAS, ejecutar_ciclo
from motor_noticias.db import Database
from motor_noticias.redaccion.mock import RedactorMock


class ErrorFuenteDePrueba(RuntimeError):
    """Excepción controlada equivalente a un Error*Recoleccion* real."""


def _cruda(titulo, texto=None, url=None, fuente="Fuente de Prueba", fecha=""):
    return {
        "titulo": titulo,
        "texto": texto or "Contenido de prueba con longitud suficiente para el pipeline.",
        "url": url or f"https://ejemplo.test/{titulo.lower().replace(' ', '-')}",
        "fuente": fuente,
        "fecha": fecha,
    }


def _colector_ok(items):
    """Fábrica de un collector de prueba (constructor sin argumentos, igual
    que los collectors reales) que siempre devuelve `items`."""

    class _ColectorDePrueba:
        def recolectar(self):
            return items

    return _ColectorDePrueba


def _colector_error(mensaje="fallo simulado"):
    class _ColectorDePrueba:
        def recolectar(self):
            raise ErrorFuenteDePrueba(mensaje)

    return _ColectorDePrueba


NOTICIA_LOCAL = _cruda("Obras en Libertador General San Martín continúan en el barrio norte")
NOTICIA_AJENA = _cruda("El Gobierno nacional anunció cambios económicos", url="https://ejemplo.test/ajena")


class TestCicloContinuoEstructura(unittest.TestCase):
    def test_incluye_exactamente_las_fuentes_reales_ya_implementadas(self):
        identificadores = [f[0] for f in FUENTES_CONTINUAS]
        self.assertEqual(
            identificadores,
            [
                "rss-prensa-jujuy",
                "municipio-libertador",
                "infoyungas",
                "jujuy-al-momento",
                "tribuno-jujuy",
                "todojujuy",
                "somos-jujuy",
                "jujuyaldia",
                "canal6-libertador",
                "la-nacion",
                "infobae",
            ],
        )


class TestEjecutarCiclo(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_ciclo_normal_procesa_todas_las_fuentes(self):
        fuentes_prueba = (
            ("fuente-a", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),
            ("fuente-b", _colector_ok([NOTICIA_AJENA]), ErrorFuenteDePrueba),
        )
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            resumen = ejecutar_ciclo(self.db, self.redactor)

        self.assertEqual(len(resumen.resultados), 2)
        self.assertEqual(resumen.total_errores, 0)

    def test_fuente_exitosa_registra_salud_ok(self):
        fuentes_prueba = (("fuente-a", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),)
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            ejecutar_ciclo(self.db, self.redactor)

        salud = self.db.obtener_salud_fuente("fuente-a")
        self.assertEqual(salud["ultimo_resultado"], "ok")
        self.assertEqual(salud["elementos_obtenidos"], 1)
        self.assertEqual(salud["noticias_nuevas"], 1)
        self.assertIsNone(salud["ultimo_error"])
        self.assertEqual(salud["fallos_consecutivos"], 0)
        self.assertIsNotNone(salud["ultima_noticia_fecha"])

    def test_fuente_con_error_registra_salud_error(self):
        fuentes_prueba = (("fuente-b", _colector_error("HTTP 500"), ErrorFuenteDePrueba),)
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            resumen = ejecutar_ciclo(self.db, self.redactor)

        self.assertEqual(resumen.total_errores, 1)
        salud = self.db.obtener_salud_fuente("fuente-b")
        self.assertEqual(salud["ultimo_resultado"], "error")
        self.assertEqual(salud["ultimo_error"], "HTTP 500")
        self.assertEqual(salud["elementos_obtenidos"], 0)
        self.assertEqual(salud["noticias_nuevas"], 0)
        self.assertEqual(salud["fallos_consecutivos"], 1)

    def test_una_fuente_falla_las_demas_continuan(self):
        fuentes_prueba = (
            ("fuente-ok-1", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),
            ("fuente-rota", _colector_error(), ErrorFuenteDePrueba),
            (
                "fuente-ok-2",
                _colector_ok([_cruda("Fraile Pintado inauguró un centro vecinal")]),
                ErrorFuenteDePrueba,
            ),
        )
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            resumen = ejecutar_ciclo(self.db, self.redactor)

        self.assertEqual(len(resumen.resultados), 3)
        self.assertEqual(resumen.total_errores, 1)
        resultados_por_id = {r.identificador: r for r in resumen.resultados}
        self.assertEqual(resultados_por_id["fuente-ok-1"].resultado, "ok")
        self.assertEqual(resultados_por_id["fuente-rota"].resultado, "error")
        self.assertEqual(resultados_por_id["fuente-ok-2"].resultado, "ok")
        # las dos fuentes sanas quedaron registradas igual
        self.assertIsNotNone(self.db.obtener_salud_fuente("fuente-ok-1"))
        self.assertIsNotNone(self.db.obtener_salud_fuente("fuente-ok-2"))

    def test_fallos_consecutivos_se_acumulan(self):
        fuentes_prueba = (("fuente-b", _colector_error(), ErrorFuenteDePrueba),)
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            ejecutar_ciclo(self.db, self.redactor)
            ejecutar_ciclo(self.db, self.redactor)
            ejecutar_ciclo(self.db, self.redactor)

        salud = self.db.obtener_salud_fuente("fuente-b")
        self.assertEqual(salud["fallos_consecutivos"], 3)

    def test_fuente_se_recupera_resetea_fallos_consecutivos(self):
        fuentes_falla = (("fuente-b", _colector_error(), ErrorFuenteDePrueba),)
        fuentes_ok = (("fuente-b", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),)

        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_falla):
            ejecutar_ciclo(self.db, self.redactor)
            ejecutar_ciclo(self.db, self.redactor)
        self.assertEqual(self.db.obtener_salud_fuente("fuente-b")["fallos_consecutivos"], 2)

        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_ok):
            ejecutar_ciclo(self.db, self.redactor)

        salud = self.db.obtener_salud_fuente("fuente-b")
        self.assertEqual(salud["ultimo_resultado"], "ok")
        self.assertEqual(salud["fallos_consecutivos"], 0)

    def test_deduplicacion_entre_ciclos(self):
        fuentes_prueba = (("fuente-a", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),)
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            primer_ciclo = ejecutar_ciclo(self.db, self.redactor)
            segundo_ciclo = ejecutar_ciclo(self.db, self.redactor)

        self.assertEqual(primer_ciclo.total_noticias_nuevas, 1)
        self.assertEqual(segundo_ciclo.total_noticias_nuevas, 0)
        salud = self.db.obtener_salud_fuente("fuente-a")
        self.assertEqual(salud["noticias_nuevas"], 0)
        self.assertEqual(len(self.db.listar()), 1)

    def test_registra_resumen_del_ciclo(self):
        fuentes_prueba = (
            ("fuente-a", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),
            ("fuente-b", _colector_error(), ErrorFuenteDePrueba),
        )
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            ejecutar_ciclo(self.db, self.redactor, intervalo_segundos=900)

        ciclo = self.db.ultimo_ciclo()
        self.assertEqual(ciclo["total_fuentes"], 2)
        self.assertEqual(ciclo["total_noticias_nuevas"], 1)
        self.assertEqual(ciclo["total_errores"], 1)
        self.assertEqual(ciclo["intervalo_segundos"], 900)

    def test_persistencia_de_estado_en_sqlite(self):
        fuentes_prueba = (("fuente-a", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),)
        db_path = Path(self.tmpdir.name) / "persistencia.db"
        db1 = Database(db_path)
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            ejecutar_ciclo(db1, self.redactor)
        db1.close()

        db2 = Database(db_path)
        try:
            salud = db2.obtener_salud_fuente("fuente-a")
            self.assertIsNotNone(salud)
            self.assertEqual(salud["ultimo_resultado"], "ok")
            self.assertIsNotNone(db2.ultimo_ciclo())
            self.assertEqual(len(db2.listar()), 1)
        finally:
            db2.close()


if __name__ == "__main__":
    unittest.main()
