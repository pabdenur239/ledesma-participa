import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from motor_noticias.verificacion_fuente import verificar_impacto_local_concreto


def _urlopen_mock(html_crudo: str):
    respuesta = MagicMock()
    respuesta.read.return_value = html_crudo.encode("utf-8")
    respuesta.__enter__.return_value = respuesta
    respuesta.__exit__.return_value = False
    return respuesta


class TestVerificarImpactoLocalConcreto(unittest.TestCase):
    def test_sin_url_no_verifica(self):
        resultado = verificar_impacto_local_concreto("")
        self.assertFalse(resultado.impacto_local)

    def test_mencion_explicita_de_libertador_es_impacto_local(self):
        html_crudo = "<html><body><p>Beneficiarios en Palpalá, Libertador General San Martín y Perico.</p></body></html>"
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            return_value=_urlopen_mock(html_crudo),
        ):
            resultado = verificar_impacto_local_concreto("https://ejemplo.test/nota")
        self.assertTrue(resultado.impacto_local)

    def test_mencion_explicita_de_localidad_de_ledesma_es_impacto_local(self):
        html_crudo = "<html><body><p>La obra se realiza en Fraile Pintado.</p></body></html>"
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            return_value=_urlopen_mock(html_crudo),
        ):
            resultado = verificar_impacto_local_concreto("https://ejemplo.test/nota")
        self.assertTrue(resultado.impacto_local)

    def test_sin_mencion_local_no_es_impacto_local(self):
        html_crudo = "<html><body><p>Noticia general de la provincia de Jujuy.</p></body></html>"
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            return_value=_urlopen_mock(html_crudo),
        ):
            resultado = verificar_impacto_local_concreto("https://ejemplo.test/nota")
        self.assertFalse(resultado.impacto_local)

    def test_texto_de_script_y_style_se_ignora(self):
        html_crudo = (
            "<html><head><style>.libertador { color: red; }</style>"
            "<script>var libertador = true;</script></head>"
            "<body><p>Noticia general de la provincia de Jujuy.</p></body></html>"
        )
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            return_value=_urlopen_mock(html_crudo),
        ):
            resultado = verificar_impacto_local_concreto("https://ejemplo.test/nota")
        self.assertFalse(resultado.impacto_local)

    def test_error_de_red_falla_hacia_no_verificado(self):
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            side_effect=urllib.error.URLError("sin conexión"),
        ):
            resultado = verificar_impacto_local_concreto("https://ejemplo.test/nota")
        self.assertFalse(resultado.impacto_local)

    def test_timeout_falla_hacia_no_verificado(self):
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            side_effect=TimeoutError("tiempo agotado"),
        ):
            resultado = verificar_impacto_local_concreto("https://ejemplo.test/nota")
        self.assertFalse(resultado.impacto_local)


if __name__ == "__main__":
    unittest.main()
