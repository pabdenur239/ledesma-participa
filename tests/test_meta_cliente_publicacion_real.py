import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

from motor_noticias.meta.cliente import ClienteMetaGraphAPI, ErrorClienteMeta, ResultadoDryRun
from motor_noticias.meta.contenido import ContenidoFacebook


def _contenido():
    return ContenidoFacebook(
        post_principal="Título\n\nReseña.\n\nInformación completa en el primer comentario.",
        primer_comentario="Texto completo.\n\nFuente: Prueba\n\n#LedesmaParticipa",
        hashtags=["#LedesmaParticipa"],
    )


def _urlopen_mock(cuerpo_json: dict):
    respuesta = MagicMock()
    respuesta.read.return_value = json.dumps(cuerpo_json).encode("utf-8")
    respuesta.__enter__.return_value = respuesta
    respuesta.__exit__.return_value = False
    return MagicMock(return_value=respuesta)


class BaseImagen(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.imagen = Path(self.tmpdir.name) / "placa.png"
        self.imagen.write_bytes(b"\x89PNG\r\n\x1a\nfalso-contenido-de-prueba")

    def tearDown(self):
        self.tmpdir.cleanup()


class TestPublicarFotoFacebook(BaseImagen):
    def test_dry_run_no_llama_a_meta(self):
        urlopen = MagicMock()
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        resultado = cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=True)
        self.assertIsInstance(resultado, ResultadoDryRun)
        urlopen.assert_not_called()

    def test_publicacion_real_devuelve_el_id_confirmado_por_meta(self):
        urlopen = _urlopen_mock({"id": "post-real-123", "post_id": "post-real-123"})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)

        post_id = cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=False)

        self.assertEqual(post_id, "post-real-123")
        urlopen.assert_called_once()

    def test_sin_token_no_intenta_publicar(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token=None, urlopen=MagicMock())
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=False)

    def test_error_de_meta_se_traduce_a_error_controlado(self):
        urlopen = _urlopen_mock({"error": {"message": "Invalid OAuth access token"}})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=False)

    def test_http_error_se_traduce_a_error_controlado_sin_exponer_token(self):
        def urlopen(*args, **kwargs):
            raise urllib.error.HTTPError(
                "url", 400, "Bad Request", {}, __import__("io").BytesIO(b'{"error":{"message":"boom"}}')
            )

        cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta) as ctx:
            cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=False)
        self.assertNotIn("token-secreto", str(ctx.exception))

    def test_respuesta_sin_id_es_error_controlado(self):
        urlopen = _urlopen_mock({})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=False)


class TestPublicarComentarioFacebook(unittest.TestCase):
    def test_dry_run_no_llama_a_meta(self):
        urlopen = MagicMock()
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        resultado = cliente.publicar_comentario_facebook("post-1", "texto", dry_run=True)
        self.assertIsInstance(resultado, ResultadoDryRun)
        urlopen.assert_not_called()

    def test_publicacion_real_devuelve_el_id_del_comentario(self):
        urlopen = _urlopen_mock({"id": "comentario-456"})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        comment_id = cliente.publicar_comentario_facebook("post-1", "texto", dry_run=False)
        self.assertEqual(comment_id, "comentario-456")


class TestPublicarInstagram(BaseImagen):
    def test_dry_run_no_llama_a_meta(self):
        urlopen = MagicMock()
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", ig_user_id="ig-1", urlopen=urlopen)
        resultado = cliente.publicar_instagram("caption", "https://ejemplo.com/placa.png", dry_run=True)
        self.assertIsInstance(resultado, ResultadoDryRun)
        urlopen.assert_not_called()

    def test_publicacion_real_hace_los_dos_pasos_y_devuelve_el_media_id(self):
        respuestas = [{"id": "contenedor-1"}, {"id": "media-real-789"}]
        urlopen = MagicMock(side_effect=[
            _make_ctx(respuestas[0]),
            _make_ctx(respuestas[1]),
        ])
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", ig_user_id="ig-1", urlopen=urlopen)

        media_id = cliente.publicar_instagram("caption", "https://ejemplo.com/placa.png", dry_run=False)

        self.assertEqual(media_id, "media-real-789")
        self.assertEqual(urlopen.call_count, 2)

    def test_sin_ig_user_id_no_intenta_publicar(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", ig_user_id=None, urlopen=MagicMock())
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_instagram("caption", "https://ejemplo.com/placa.png", dry_run=False)

    def test_sin_url_publica_de_imagen_no_intenta_publicar(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", ig_user_id="ig-1", urlopen=MagicMock())
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_instagram("caption", None, dry_run=False)

    def test_falla_creacion_de_contenedor_no_intenta_publicar(self):
        urlopen = MagicMock(return_value=_make_ctx({"error": {"message": "imagen inválida"}}))
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", ig_user_id="ig-1", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_instagram("caption", "https://ejemplo.com/placa.png", dry_run=False)
        self.assertEqual(urlopen.call_count, 1)


def _make_ctx(cuerpo_json: dict):
    respuesta = MagicMock()
    respuesta.read.return_value = json.dumps(cuerpo_json).encode("utf-8")
    respuesta.__enter__.return_value = respuesta
    respuesta.__exit__.return_value = False
    return respuesta


if __name__ == "__main__":
    unittest.main()
