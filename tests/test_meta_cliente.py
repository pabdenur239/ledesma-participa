import io
import json
import os
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from motor_noticias.meta.cliente import (
    GRAPH_API_BASE,
    PAGE_ID_DEFAULT,
    ClienteMetaGraphAPI,
    ErrorClienteMeta,
)
from motor_noticias.meta.contenido import ContenidoFacebook


def _contenido() -> ContenidoFacebook:
    return ContenidoFacebook(
        post_principal="Título\n\nReseña breve.\n\nInformación completa en el primer comentario.",
        primer_comentario="Texto completo.\n\nFuente: Prueba\n\n#LedesmaParticipa",
        hashtags=["#LedesmaParticipa"],
    )


class TestClienteMetaDryRun(unittest.TestCase):
    def test_dry_run_es_el_comportamiento_por_defecto(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto")
        resultado = cliente.publicar_post_principal(_contenido())
        self.assertTrue(resultado.dry_run)

    def test_dry_run_muestra_page_id_endpoint_y_textos(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto")
        contenido = _contenido()

        resultado = cliente.publicar_post_principal(contenido)

        self.assertEqual(resultado.page_id, "123")
        self.assertIn("123/feed", resultado.endpoint_post)
        self.assertEqual(resultado.texto_post_principal, contenido.post_principal)
        self.assertEqual(resultado.texto_primer_comentario, contenido.primer_comentario)

    def test_dry_run_comentario_muestra_endpoint_correcto(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto")
        resultado = cliente.publicar_primer_comentario("post-987", _contenido())
        self.assertIn("post-987/comments", resultado.endpoint_comentario)

    def test_dry_run_no_requiere_token_configurado(self):
        with patch.dict(os.environ, {}, clear=True):
            cliente = ClienteMetaGraphAPI()
            self.assertFalse(cliente.tiene_token_configurado())
            resultado = cliente.publicar_post_principal(_contenido())
            self.assertTrue(resultado.dry_run)
            self.assertEqual(resultado.page_id, PAGE_ID_DEFAULT)

    def test_comentario_real_no_habilitado_todavia(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto")
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_primer_comentario("post-987", _contenido(), dry_run=False)

    def test_dry_run_nunca_llama_a_meta(self):
        with patch("motor_noticias.meta.cliente.urllib.request.urlopen") as urlopen_mock:
            cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto")
            cliente.publicar_post_principal(_contenido())
            cliente.publicar_primer_comentario("post-987", _contenido())
            urlopen_mock.assert_not_called()

    def test_token_nunca_aparece_en_la_salida_del_dry_run(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto-xyz")
        resultado = cliente.publicar_post_principal(_contenido())
        self.assertNotIn("token-secreto-xyz", repr(resultado))

    def test_token_nunca_aparece_en_stdout(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto-xyz")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            resultado = cliente.publicar_post_principal(_contenido())
            print(resultado)
        self.assertNotIn("token-secreto-xyz", buffer.getvalue())


def _respuesta_mock(cuerpo: dict) -> MagicMock:
    respuesta = MagicMock()
    respuesta.read.return_value = json.dumps(cuerpo).encode("utf-8")
    contexto = MagicMock()
    contexto.__enter__.return_value = respuesta
    contexto.__exit__.return_value = False
    return contexto


class TestClienteMetaPublicacionReal(unittest.TestCase):
    def test_publicacion_real_hace_post_al_endpoint_correcto(self):
        with patch("motor_noticias.meta.cliente.urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value = _respuesta_mock({"id": "123_456"})
            cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto")

            resultado = cliente.publicar_post_principal(
                _contenido(), dry_run=False, url_fuente="https://fuente.example/nota"
            )

            self.assertFalse(resultado.dry_run)
            self.assertEqual(resultado.post_id, "123_456")
            self.assertEqual(resultado.page_id, "123")
            self.assertEqual(resultado.endpoint_post, f"{GRAPH_API_BASE}/123/feed")

            peticion = urlopen_mock.call_args[0][0]
            self.assertEqual(peticion.full_url, f"{GRAPH_API_BASE}/123/feed")
            self.assertEqual(peticion.get_method(), "POST")
            self.assertEqual(peticion.get_header("Authorization"), "Bearer token-secreto")
            cuerpo_enviado = peticion.data.decode("utf-8")
            self.assertIn("message=", cuerpo_enviado)
            self.assertIn("link=", cuerpo_enviado)
            self.assertNotIn("token-secreto", cuerpo_enviado)
            self.assertNotIn("token-secreto", peticion.full_url)

    def test_publicacion_real_sin_link_no_envia_campo_link(self):
        with patch("motor_noticias.meta.cliente.urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value = _respuesta_mock({"id": "123_456"})
            cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto")

            cliente.publicar_post_principal(_contenido(), dry_run=False)

            peticion = urlopen_mock.call_args[0][0]
            self.assertNotIn("link=", peticion.data.decode("utf-8"))

    def test_publicacion_real_requiere_token_configurado(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("motor_noticias.meta.cliente.urllib.request.urlopen") as urlopen_mock:
                cliente = ClienteMetaGraphAPI(page_id="123")
                with self.assertRaises(ErrorClienteMeta):
                    cliente.publicar_post_principal(_contenido(), dry_run=False)
                urlopen_mock.assert_not_called()

    def test_publicacion_real_sin_id_en_respuesta_es_error_controlado(self):
        with patch("motor_noticias.meta.cliente.urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value = _respuesta_mock({})
            cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto")
            with self.assertRaises(ErrorClienteMeta):
                cliente.publicar_post_principal(_contenido(), dry_run=False)

    def test_publicacion_real_error_http_no_revela_token(self):
        with patch("motor_noticias.meta.cliente.urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.side_effect = urllib.error.HTTPError(
                url=f"{GRAPH_API_BASE}/123/feed",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=io.BytesIO(b'{"error": {"message": "invalid"}}'),
            )
            cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto-xyz")
            with self.assertRaises(ErrorClienteMeta) as contexto:
                cliente.publicar_post_principal(_contenido(), dry_run=False)
            self.assertNotIn("token-secreto-xyz", str(contexto.exception))

    def test_publicacion_real_error_conexion_no_revela_token(self):
        with patch("motor_noticias.meta.cliente.urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.side_effect = urllib.error.URLError("sin conexión")
            cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto-xyz")
            with self.assertRaises(ErrorClienteMeta) as contexto:
                cliente.publicar_post_principal(_contenido(), dry_run=False)
            self.assertNotIn("token-secreto-xyz", str(contexto.exception))

    def test_publicacion_real_token_nunca_aparece_en_repr_del_resultado(self):
        with patch("motor_noticias.meta.cliente.urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value = _respuesta_mock({"id": "123_456"})
            cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto-xyz")
            resultado = cliente.publicar_post_principal(_contenido(), dry_run=False)
            self.assertNotIn("token-secreto-xyz", repr(resultado))


if __name__ == "__main__":
    unittest.main()
