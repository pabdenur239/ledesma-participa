import unittest
from datetime import datetime, timedelta, timezone

from motor_noticias.meta.elegibilidad_automatica import evaluar_elegibilidad_publicacion_automatica
from motor_noticias.motor_editorial import ANTIGUEDAD_MAXIMA_HORAS

AHORA = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)


def _noticia(**overrides):
    base = {
        "estado": "preparada",
        "revision_estado": "pendiente",
        "requiere_revision_especial": 0,
        "categoria_riesgo": None,
        "titulo_preparado": "Título",
        "texto_preparado": "Texto completo de la noticia.",
        "nombre_fuente": "Prensa Jujuy",
        "territorio": "local",
        "fecha_recoleccion": AHORA.isoformat(),
    }
    base.update(overrides)
    return base


class TestElegibilidadAutomatica(unittest.TestCase):
    def test_noticia_completa_es_elegible(self):
        r = evaluar_elegibilidad_publicacion_automatica(_noticia(), ahora=AHORA)
        self.assertTrue(r.elegible)
        self.assertEqual(r.motivos_bloqueo, [])

    def test_no_preparada_no_es_elegible(self):
        r = evaluar_elegibilidad_publicacion_automatica(_noticia(estado="descartada"), ahora=AHORA)
        self.assertFalse(r.elegible)

    def test_rechazada_no_es_elegible(self):
        r = evaluar_elegibilidad_publicacion_automatica(_noticia(revision_estado="rechazada"), ahora=AHORA)
        self.assertFalse(r.elegible)

    def test_riesgo_editorial_bloquea(self):
        r = evaluar_elegibilidad_publicacion_automatica(
            _noticia(requiere_revision_especial=1, categoria_riesgo="judicial"), ahora=AHORA
        )
        self.assertFalse(r.elegible)
        self.assertTrue(any("judicial" in m for m in r.motivos_bloqueo))

    def test_sin_titulo_preparado_no_es_elegible(self):
        r = evaluar_elegibilidad_publicacion_automatica(_noticia(titulo_preparado=""), ahora=AHORA)
        self.assertFalse(r.elegible)

    def test_sin_texto_preparado_no_es_elegible(self):
        r = evaluar_elegibilidad_publicacion_automatica(_noticia(texto_preparado=None), ahora=AHORA)
        self.assertFalse(r.elegible)

    def test_sin_fuente_no_es_elegible(self):
        r = evaluar_elegibilidad_publicacion_automatica(_noticia(nombre_fuente=""), ahora=AHORA)
        self.assertFalse(r.elegible)

    def test_territorio_sin_clasificar_es_elegible_como_ultimo_recurso(self):
        # sin_clasificar solo llega a 'preparada' vía el gate de
        # entretenimiento/curiosidad (pipeline.py): si llegó hasta acá, es
        # válido como último nivel de la cascada editorial.
        r = evaluar_elegibilidad_publicacion_automatica(_noticia(territorio="sin_clasificar"), ahora=AHORA)
        self.assertTrue(r.elegible)

    def test_territorio_desconocido_no_es_elegible(self):
        r = evaluar_elegibilidad_publicacion_automatica(_noticia(territorio="territorio-invalido"), ahora=AHORA)
        self.assertFalse(r.elegible)

    def test_territorio_ausente_no_es_elegible(self):
        r = evaluar_elegibilidad_publicacion_automatica(_noticia(territorio=None), ahora=AHORA)
        self.assertFalse(r.elegible)

    def test_contenido_vencido_no_es_elegible(self):
        vieja = (AHORA - timedelta(hours=ANTIGUEDAD_MAXIMA_HORAS + 1)).isoformat()
        r = evaluar_elegibilidad_publicacion_automatica(_noticia(fecha_recoleccion=vieja), ahora=AHORA)
        self.assertFalse(r.elegible)

    def test_contenido_dentro_de_la_antiguedad_maxima_es_elegible(self):
        reciente = (AHORA - timedelta(hours=ANTIGUEDAD_MAXIMA_HORAS - 1)).isoformat()
        r = evaluar_elegibilidad_publicacion_automatica(_noticia(fecha_recoleccion=reciente), ahora=AHORA)
        self.assertTrue(r.elegible)

    def test_sin_fecha_recoleccion_no_es_elegible(self):
        r = evaluar_elegibilidad_publicacion_automatica(_noticia(fecha_recoleccion=None), ahora=AHORA)
        self.assertFalse(r.elegible)

    def test_acumula_todos_los_motivos_de_bloqueo(self):
        r = evaluar_elegibilidad_publicacion_automatica(
            _noticia(titulo_preparado="", texto_preparado="", nombre_fuente=""), ahora=AHORA
        )
        self.assertFalse(r.elegible)
        self.assertGreaterEqual(len(r.motivos_bloqueo), 3)


if __name__ == "__main__":
    unittest.main()
