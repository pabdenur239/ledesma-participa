import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from motor_noticias.verificacion_fuente import (
    LONGITUD_VENTANA_ARTICULO,
    verificar_impacto_local_concreto,
)

TITULO = "Se realizó un encuentro provincial de capacitación docente"


def _urlopen_mock(html_crudo: str):
    respuesta = MagicMock()
    respuesta.read.return_value = html_crudo.encode("utf-8")
    respuesta.__enter__.return_value = respuesta
    respuesta.__exit__.return_value = False
    return respuesta


def _pagina(cuerpo: str, despues_del_cuerpo: str = "") -> str:
    return f"<html><body><h1>{TITULO}</h1><p>{cuerpo}</p>{despues_del_cuerpo}</body></html>"


class TestVerificarImpactoLocalConcreto(unittest.TestCase):
    def test_sin_url_no_verifica(self):
        resultado = verificar_impacto_local_concreto(TITULO, "")
        self.assertFalse(resultado.impacto_local)

    def test_mencion_explicita_de_libertador_en_el_cuerpo_es_impacto_local(self):
        html_crudo = _pagina("Beneficiarios en Palpalá, Libertador General San Martín y Perico.")
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            return_value=_urlopen_mock(html_crudo),
        ):
            resultado = verificar_impacto_local_concreto(TITULO, "https://ejemplo.test/nota")
        self.assertTrue(resultado.impacto_local)

    def test_mencion_explicita_de_localidad_de_ledesma_en_el_cuerpo_es_impacto_local(self):
        html_crudo = _pagina("La obra se realiza en Fraile Pintado.")
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            return_value=_urlopen_mock(html_crudo),
        ):
            resultado = verificar_impacto_local_concreto(TITULO, "https://ejemplo.test/nota")
        self.assertTrue(resultado.impacto_local)

    def test_sin_mencion_local_en_el_cuerpo_no_es_impacto_local(self):
        html_crudo = _pagina("Noticia general de la provincia de Jujuy.")
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            return_value=_urlopen_mock(html_crudo),
        ):
            resultado = verificar_impacto_local_concreto(TITULO, "https://ejemplo.test/nota")
        self.assertFalse(resultado.impacto_local)

    def test_mencion_en_notas_relacionadas_lejos_del_cuerpo_no_cuenta(self):
        # Reproduce el falso positivo real que motivó este ajuste: un widget
        # de "Te puede interesar" con el título de OTRA nota que sí menciona
        # Libertador, bien después de la ventana del cuerpo del artículo.
        relleno = "Párrafo de relleno del cuerpo real. " * 120  # > LONGITUD_VENTANA_ARTICULO
        despues = "<div>Te puede interesar: Obras en Libertador General San Martín continúan</div>"
        html_crudo = _pagina(relleno, despues)
        self.assertGreater(len(relleno), LONGITUD_VENTANA_ARTICULO)
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            return_value=_urlopen_mock(html_crudo),
        ):
            resultado = verificar_impacto_local_concreto(TITULO, "https://ejemplo.test/nota")
        self.assertFalse(resultado.impacto_local)

    def test_titulo_no_encontrado_en_la_pagina_no_verifica(self):
        html_crudo = "<html><body><p>Página sin el título esperado.</p></body></html>"
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            return_value=_urlopen_mock(html_crudo),
        ):
            resultado = verificar_impacto_local_concreto(TITULO, "https://ejemplo.test/nota")
        self.assertFalse(resultado.impacto_local)

    def test_texto_de_script_y_style_se_ignora(self):
        html_crudo = (
            f"<html><head><style>.libertador {{ color: red; }}</style>"
            f"<script>var libertador = true;</script></head>"
            f"<body><h1>{TITULO}</h1><p>Noticia general de la provincia de Jujuy.</p></body></html>"
        )
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            return_value=_urlopen_mock(html_crudo),
        ):
            resultado = verificar_impacto_local_concreto(TITULO, "https://ejemplo.test/nota")
        self.assertFalse(resultado.impacto_local)

    def test_error_de_red_falla_hacia_no_verificado(self):
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            side_effect=urllib.error.URLError("sin conexión"),
        ):
            resultado = verificar_impacto_local_concreto(TITULO, "https://ejemplo.test/nota")
        self.assertFalse(resultado.impacto_local)

    def test_timeout_falla_hacia_no_verificado(self):
        with patch(
            "motor_noticias.verificacion_fuente.urllib.request.urlopen",
            side_effect=TimeoutError("tiempo agotado"),
        ):
            resultado = verificar_impacto_local_concreto(TITULO, "https://ejemplo.test/nota")
        self.assertFalse(resultado.impacto_local)


if __name__ == "__main__":
    unittest.main()
