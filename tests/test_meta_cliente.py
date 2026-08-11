import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from motor_noticias.meta.cliente import PAGE_ID_DEFAULT, ClienteMetaGraphAPI, ErrorClienteMeta
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

    def test_publicacion_real_no_habilitada_en_esta_fase(self):
        cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto")
        with self.assertRaises(ErrorClienteMeta):
            cliente.publicar_post_principal(_contenido(), dry_run=False)

    def test_ninguna_llamada_real_ocurre(self):
        with patch("urllib.request.urlopen") as urlopen_mock:
            cliente = ClienteMetaGraphAPI(page_id="123", access_token="token-secreto")
            cliente.publicar_post_principal(_contenido())
            try:
                cliente.publicar_post_principal(_contenido(), dry_run=False)
            except ErrorClienteMeta:
                pass
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


if __name__ == "__main__":
    unittest.main()
