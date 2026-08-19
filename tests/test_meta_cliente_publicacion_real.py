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

    def test_publicacion_real_sube_foto_sin_publicar_y_crea_post_de_feed(self):
        urlopen = MagicMock(side_effect=[
            _make_ctx({"id": "photo-real-999"}),
            _make_ctx({"id": "123_post-real-123"}),
        ])
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)

        resultado = cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=False)

        self.assertEqual(resultado.photo_id, "photo-real-999")
        self.assertEqual(resultado.post_id, "123_post-real-123")
        self.assertEqual(urlopen.call_count, 2)

        peticion_foto = urlopen.call_args_list[0][0][0]
        self.assertIn("123/photos", peticion_foto.full_url)
        self.assertIn(b'name="published"\r\n\r\nfalse', peticion_foto.data)
        self.assertNotIn(b'name="caption"', peticion_foto.data)

        peticion_post = urlopen.call_args_list[1][0][0]
        self.assertIn("123/feed", peticion_post.full_url)
        self.assertIn(b'name="message"', peticion_post.data)
        self.assertIn(b'"media_fbid": "photo-real-999"', peticion_post.data)

    def test_sin_token_no_intenta_publicar(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token=None, urlopen=MagicMock())
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=False)

    def test_error_de_meta_al_subir_la_foto_se_traduce_a_error_controlado(self):
        urlopen = _urlopen_mock({"error": {"message": "Invalid OAuth access token"}})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=False)

    def test_error_de_meta_al_crear_el_post_se_traduce_a_error_controlado(self):
        urlopen = MagicMock(side_effect=[
            _make_ctx({"id": "photo-real-999"}),
            _make_ctx({"error": {"message": "attached_media inválido"}}),
        ])
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=False)
        self.assertEqual(urlopen.call_count, 2)

    def test_http_error_se_traduce_a_error_controlado_sin_exponer_token(self):
        def urlopen(*args, **kwargs):
            raise urllib.error.HTTPError(
                "url", 400, "Bad Request", {}, __import__("io").BytesIO(b'{"error":{"message":"boom"}}')
            )

        cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta) as ctx:
            cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=False)
        self.assertNotIn("token-secreto", str(ctx.exception))

    def test_respuesta_sin_id_de_foto_es_error_controlado(self):
        urlopen = _urlopen_mock({})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=False)

    def test_respuesta_sin_id_de_post_es_error_controlado(self):
        urlopen = MagicMock(side_effect=[
            _make_ctx({"id": "photo-real-999"}),
            _make_ctx({}),
        ])
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_foto_facebook(_contenido(), self.imagen, dry_run=False)


class TestPublicarFotoFacebookPorUrl(unittest.TestCase):
    def test_publicacion_real_sube_foto_sin_publicar_por_url_y_crea_post_de_feed(self):
        urlopen = MagicMock(side_effect=[
            _make_ctx({"id": "photo-real-999"}),
            _make_ctx({"id": "123_post-real-123"}),
        ])
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)

        resultado = cliente.publicar_foto_facebook_por_url(
            _contenido(), "https://ejemplo.com/foto-original.jpg", dry_run=False
        )

        self.assertEqual(resultado.photo_id, "photo-real-999")
        self.assertEqual(resultado.post_id, "123_post-real-123")
        self.assertEqual(urlopen.call_count, 2)

        peticion_foto = urlopen.call_args_list[0][0][0]
        self.assertIn("123/photos", peticion_foto.full_url)
        self.assertIn(b"https://ejemplo.com/foto-original.jpg", peticion_foto.data)
        self.assertIn(b'name="published"\r\n\r\nfalse', peticion_foto.data)

        peticion_post = urlopen.call_args_list[1][0][0]
        self.assertIn("123/feed", peticion_post.full_url)
        self.assertIn(b'"media_fbid": "photo-real-999"', peticion_post.data)


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


class TestEditarCaptionFotoFacebook(unittest.TestCase):
    def test_dry_run_no_llama_a_meta(self):
        urlopen = MagicMock()
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        resultado = cliente.editar_caption_foto_facebook("photo-1", "caption nuevo", dry_run=True)
        self.assertIsInstance(resultado, ResultadoDryRun)
        urlopen.assert_not_called()

    def test_edicion_real_confirmada_devuelve_true(self):
        urlopen = _urlopen_mock({"success": True})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)

        resultado = cliente.editar_caption_foto_facebook("photo-1", "caption nuevo", dry_run=False)

        self.assertTrue(resultado)
        peticion = urlopen.call_args[0][0]
        self.assertIn("photo-1", peticion.full_url)
        self.assertEqual(peticion.get_method(), "POST")

    def test_sin_token_no_intenta_editar(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token=None, urlopen=MagicMock())
        with self.assertRaises(ErrorClienteMeta):
            cliente.editar_caption_foto_facebook("photo-1", "caption nuevo", dry_run=False)

    def test_respuesta_sin_success_es_error_controlado(self):
        urlopen = _urlopen_mock({"success": False})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta):
            cliente.editar_caption_foto_facebook("photo-1", "caption nuevo", dry_run=False)

    def test_error_de_meta_no_expone_token(self):
        urlopen = _urlopen_mock({"error": {"message": "permiso insuficiente"}})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta) as ctx:
            cliente.editar_caption_foto_facebook("photo-1", "caption nuevo", dry_run=False)
        self.assertNotIn("token-secreto", str(ctx.exception))


class TestVerificarPublicacion(unittest.TestCase):
    def test_confirma_publicacion_existente(self):
        urlopen = _urlopen_mock({"id": "post-real-123"})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)

        self.assertTrue(cliente.verificar_publicacion("post-real-123"))
        peticion = urlopen.call_args[0][0]
        self.assertEqual(peticion.get_method(), "GET")
        self.assertIn("post-real-123", peticion.full_url)

    def test_respuesta_sin_id_no_confirma(self):
        urlopen = _urlopen_mock({})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        self.assertFalse(cliente.verificar_publicacion("post-inexistente"))

    def test_sin_token_no_intenta_verificar(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token=None, urlopen=MagicMock())
        with self.assertRaises(ErrorClienteMeta):
            cliente.verificar_publicacion("post-1")

    def test_error_de_meta_se_traduce_a_error_controlado(self):
        urlopen = _urlopen_mock({"error": {"message": "publicación no encontrada"}})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta):
            cliente.verificar_publicacion("post-1")


class TestObtenerUrlPublicaFoto(unittest.TestCase):
    def test_devuelve_la_url_de_mayor_resolucion(self):
        urlopen = _urlopen_mock(
            {"images": [{"source": "https://scontent.fb/grande.jpg"}, {"source": "https://scontent.fb/chica.jpg"}]}
        )
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)

        url = cliente.obtener_url_publica_foto("photo-1")

        self.assertEqual(url, "https://scontent.fb/grande.jpg")
        urlopen.assert_called_once()

    def test_hace_una_peticion_get_no_post(self):
        urlopen = _urlopen_mock({"images": [{"source": "https://scontent.fb/grande.jpg"}]})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)

        cliente.obtener_url_publica_foto("photo-1")

        peticion = urlopen.call_args[0][0]
        self.assertEqual(peticion.get_method(), "GET")
        self.assertIn("photo-1", peticion.full_url)

    def test_sin_token_no_intenta_consultar(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token=None, urlopen=MagicMock())
        with self.assertRaises(ErrorClienteMeta):
            cliente.obtener_url_publica_foto("photo-1")

    def test_sin_imagenes_es_error_controlado(self):
        urlopen = _urlopen_mock({"images": []})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta):
            cliente.obtener_url_publica_foto("photo-1")

    def test_respuesta_sin_campo_images_es_error_controlado(self):
        urlopen = _urlopen_mock({})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta):
            cliente.obtener_url_publica_foto("photo-1")

    def test_error_de_meta_se_traduce_a_error_controlado(self):
        urlopen = _urlopen_mock({"error": {"message": "foto no encontrada"}})
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="tok", urlopen=urlopen)
        with self.assertRaises(ErrorClienteMeta):
            cliente.obtener_url_publica_foto("photo-inexistente")


def _make_ctx(cuerpo_json: dict):
    respuesta = MagicMock()
    respuesta.read.return_value = json.dumps(cuerpo_json).encode("utf-8")
    respuesta.__enter__.return_value = respuesta
    respuesta.__exit__.return_value = False
    return respuesta


if __name__ == "__main__":
    unittest.main()
