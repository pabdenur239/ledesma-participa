import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia, OrigenIngreso
from motor_noticias.push_notificaciones import (
    PALABRAS_CLAVE_PUSH_DEFAULT,
    enviar_push_pendientes,
    evaluar_push,
)

AHORA = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


def _noticia_publicada(db, n, **overrides):
    base = dict(
        id=None,
        titulo_original=f"Título {n}",
        texto_original="Texto de la noticia sin palabras clave especiales.",
        url_fuente=f"https://ejemplo.test/nota-{n}",
        url_normalizada=f"https://ejemplo.test/nota-{n}",
        nombre_fuente="Fuente de prueba",
        fecha_fuente="",
        fecha_recoleccion=AHORA.isoformat(),
        estado=Estado.PUBLICADA.value,
        hash_contenido=f"hash-{n}",
        titulo_preparado=f"Título {n}",
        texto_preparado="Texto de la noticia sin palabras clave especiales.",
        territorio="local",
    )
    base.update(overrides)
    noticia_id = db.guardar(Noticia(**base))
    return noticia_id


class TestEvaluarPush(unittest.TestCase):
    def test_no_califica_sin_palabra_clave(self):
        noticia = {
            "titulo_preparado": "Se inauguró una plaza en el barrio",
            "texto_preparado": "El intendente participó del acto.",
            "territorio": "local",
            "origen_ingreso": "automatico",
        }
        self.assertIsNone(evaluar_push(noticia))

    def test_califica_por_accidente_en_texto(self):
        noticia = {
            "titulo_preparado": "Se registró un hecho de tránsito en la ruta 34",
            "texto_preparado": "Un accidente entre dos vehículos dejó heridos leves.",
            "territorio": "local",
            "origen_ingreso": "automatico",
        }
        self.assertEqual(evaluar_push(noticia), "accidente")

    def test_califica_en_territorio_departamental(self):
        noticia = {
            "titulo_preparado": "Corte de agua programado en Fraile Pintado",
            "texto_preparado": "Será desde las 8 hasta las 14 horas.",
            "territorio": "departamental",
            "origen_ingreso": "automatico",
        }
        self.assertEqual(evaluar_push(noticia), "corte de agua")

    def test_no_califica_territorio_provincial(self):
        noticia = {
            "titulo_preparado": "Accidente de tránsito en ruta provincial",
            "texto_preparado": "Un choque provocó demoras.",
            "territorio": "provincial",
            "origen_ingreso": "automatico",
        }
        self.assertIsNone(evaluar_push(noticia))

    def test_nunca_institucional_aunque_tenga_palabra_clave(self):
        noticia = {
            "titulo_preparado": "Alerta: conocé Ledesma Participa",
            "texto_preparado": "La página que te informa sobre emergencia y alerta en la región.",
            "territorio": "institucional",
            "origen_ingreso": OrigenIngreso.INSTITUCIONAL.value,
        }
        self.assertIsNone(evaluar_push(noticia))

    def test_nunca_resumen_del_dia_aunque_tenga_palabra_clave(self):
        noticia = {
            "titulo_preparado": "Resumen del día: accidente, corte de luz y más",
            "texto_preparado": "Repaso de las noticias de hoy.",
            "territorio": "local",
            "origen_ingreso": OrigenIngreso.RESUMEN_DIARIO.value,
        }
        self.assertIsNone(evaluar_push(noticia))

    def test_no_confunde_deporte_rutinario_con_importante(self):
        noticia = {
            "titulo_preparado": "El club local ganó el clásico del fin de semana",
            "texto_preparado": "Un partido sin incidentes ante un rival de la zona.",
            "territorio": "local",
            "origen_ingreso": "automatico",
        }
        self.assertIsNone(evaluar_push(noticia))


class TestEnviarPushPendientes(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_dry_run_no_llama_a_fcm_ni_marca_enviado(self):
        noticia_id = _noticia_publicada(
            self.db, 1,
            titulo_original="Corte de luz programado en el centro",
            titulo_preparado="Corte de luz programado en el centro",
        )
        with patch("motor_noticias.push_notificaciones._enviar_mensaje_fcm") as mock_enviar:
            resultados = enviar_push_pendientes(self.db, ahora=AHORA, dry_run=True)

        mock_enviar.assert_not_called()
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0].resultado, "enviado")
        noticia = self.db.obtener(noticia_id)
        self.assertIsNone(noticia["push_enviado_en"])  # dry-run no marca nada

    def test_envio_real_marca_push_enviado_y_no_se_repite(self):
        noticia_id = _noticia_publicada(
            self.db, 1,
            titulo_original="Corte de luz programado en el centro",
            titulo_preparado="Corte de luz programado en el centro",
        )
        with patch("motor_noticias.push_notificaciones._construir_app_firebase"), \
             patch("motor_noticias.push_notificaciones._enviar_mensaje_fcm", return_value="msg-id-123") as mock_enviar:
            primera = enviar_push_pendientes(self.db, ahora=AHORA)
            segunda = enviar_push_pendientes(self.db, ahora=AHORA)

        self.assertEqual(len(primera), 1)
        self.assertEqual(primera[0].resultado, "enviado")
        mock_enviar.assert_called_once()  # nunca se llama una segunda vez para la misma noticia
        self.assertEqual(segunda, [])  # ya no queda como candidata

        noticia = self.db.obtener(noticia_id)
        self.assertIsNotNone(noticia["push_enviado_en"])

    def test_noticia_sin_palabra_clave_no_genera_push(self):
        _noticia_publicada(self.db, 1)  # texto genérico, sin palabras clave
        with patch("motor_noticias.push_notificaciones._enviar_mensaje_fcm") as mock_enviar:
            resultados = enviar_push_pendientes(self.db, ahora=AHORA)

        mock_enviar.assert_not_called()
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0].resultado, "no_califica")

    def test_error_de_fcm_no_marca_enviado_queda_disponible_para_reintentar(self):
        _noticia_publicada(
            self.db, 1,
            titulo_original="Accidente de tránsito con heridos",
            titulo_preparado="Accidente de tránsito con heridos",
        )
        with patch("motor_noticias.push_notificaciones._construir_app_firebase"), \
             patch("motor_noticias.push_notificaciones._enviar_mensaje_fcm", side_effect=RuntimeError("fallo simulado de FCM")):
            resultados = enviar_push_pendientes(self.db, ahora=AHORA)

        self.assertEqual(resultados[0].resultado, "error")
        # No quedó marcada: la próxima corrida la vuelve a intentar.
        candidatas = self.db.noticias_candidatas_a_push("2000-01-01T00:00:00+00:00")
        self.assertEqual(len(candidatas), 1)

    def test_forzar_noticia_id_prueba_controlada_con_noticia_real(self):
        # Simula el mecanismo de prueba controlada pedido: una noticia real
        # ya publicada, sin crear contenido falso, forzada aunque quede
        # fuera de la ventana normal de candidatas.
        noticia_id = _noticia_publicada(
            self.db, 1,
            titulo_original="Alerta meteorológica para la región",
            titulo_preparado="Alerta meteorológica para la región",
            fecha_recoleccion="2020-01-01T00:00:00+00:00",  # muy vieja, fuera de ventana normal
        )
        with patch("motor_noticias.push_notificaciones._construir_app_firebase"), \
             patch("motor_noticias.push_notificaciones._enviar_mensaje_fcm", return_value="msg-id-456") as mock_enviar:
            resultados = enviar_push_pendientes(self.db, ahora=AHORA, forzar_noticia_id=noticia_id)

        mock_enviar.assert_called_once()
        self.assertEqual(resultados[0].resultado, "enviado")

    def test_palabras_clave_por_defecto_no_estan_vacias(self):
        self.assertGreater(len(PALABRAS_CLAVE_PUSH_DEFAULT), 5)


if __name__ == "__main__":
    unittest.main()
