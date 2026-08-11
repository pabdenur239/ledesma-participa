import json
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

from motor_noticias.models import Estado, Noticia
from motor_noticias.redaccion.mock import RedactorMock
from motor_noticias.redaccion.ollama import (
    ENDPOINT_DEFAULT,
    ESQUEMA_RESPUESTA,
    MODELO_DEFAULT,
    ErrorRedaccionOllama,
    RedactorOllama,
)


def _noticia_de_prueba(**overrides) -> Noticia:
    base = dict(
        id=None,
        titulo_original="Ing. Oscar Jayat nuevo Presidente del BRIPAEM",
        texto_original=(
            "En una asamblea extraordinaria realizada en la ciudad de Buenos Aires, "
            "asumió como Presidente del BRIPAEM por el periodo 2026-2028."
        ),
        url_fuente="https://municipiolgsmjujuy.gob.ar/actividades-intendente#lp-abc123",
        nombre_fuente="Municipalidad de Libertador General San Martín",
        fecha_fuente="",
        fecha_recoleccion="2026-08-11T00:00:00",
        estado=Estado.ENCONTRADA.value,
        hash_contenido="hash-1",
        localidad="Libertador General San Martín",
    )
    base.update(overrides)
    return Noticia(**base)


def _respuesta_ollama(titulo="Título breve", texto="Texto redactado con los hechos."):
    cuerpo = {
        "model": MODELO_DEFAULT,
        "created_at": "2026-08-11T00:00:00Z",
        "message": {
            "role": "assistant",
            "content": json.dumps({"titulo_preparado": titulo, "texto_preparado": texto}),
        },
        "done": True,
    }
    return json.dumps(cuerpo).encode("utf-8")


def _respuesta_falsa(contenido_bytes):
    respuesta = MagicMock()
    respuesta.read.return_value = contenido_bytes
    respuesta.__enter__.return_value = respuesta
    respuesta.__exit__.return_value = False
    return respuesta


class TestPeticionOllama(unittest.TestCase):
    def setUp(self):
        self.noticia = _noticia_de_prueba()

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_request_usa_endpoint_y_modelo_configurados(self, urlopen_mock):
        urlopen_mock.return_value = _respuesta_falsa(_respuesta_ollama())
        redactor = RedactorOllama()

        redactor.redactar(self.noticia)

        urlopen_mock.assert_called_once()
        peticion = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion, urllib.request.Request)
        self.assertEqual(peticion.full_url, ENDPOINT_DEFAULT)

        cuerpo = json.loads(peticion.data)
        self.assertEqual(cuerpo["model"], MODELO_DEFAULT)

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_request_usa_stream_think_y_temperatura_correctos(self, urlopen_mock):
        urlopen_mock.return_value = _respuesta_falsa(_respuesta_ollama())
        redactor = RedactorOllama()

        redactor.redactar(self.noticia)

        cuerpo = json.loads(urlopen_mock.call_args.args[0].data)
        self.assertIs(cuerpo["stream"], False)
        self.assertIs(cuerpo["think"], False)
        self.assertEqual(cuerpo["options"]["temperature"], 0)

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_request_incluye_json_schema_de_respuesta(self, urlopen_mock):
        urlopen_mock.return_value = _respuesta_falsa(_respuesta_ollama())
        redactor = RedactorOllama()

        redactor.redactar(self.noticia)

        cuerpo = json.loads(urlopen_mock.call_args.args[0].data)
        self.assertEqual(cuerpo["format"], ESQUEMA_RESPUESTA)
        self.assertIn("titulo_preparado", cuerpo["format"]["properties"])
        self.assertIn("texto_preparado", cuerpo["format"]["properties"])

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_prompt_contiene_las_reglas_editoriales(self, urlopen_mock):
        urlopen_mock.return_value = _respuesta_falsa(_respuesta_ollama())
        redactor = RedactorOllama()

        redactor.redactar(self.noticia)

        cuerpo = json.loads(urlopen_mock.call_args.args[0].data)
        prompt_sistema = cuerpo["messages"][0]["content"]
        for regla in (
            "español",
            "No inventes nombres",
            "No inventes cifras",
            "No inventes fechas",
            "No inventes declaraciones",
            "No agregues fechas",
            "No agregues lugares",
            "No agregues personas",
            "No agregues asistentes",
            "No agregues características físicas",
            "No agregues objetivos, beneficios ni consecuencias",
            "No agregues contexto institucional",
            "fuente oficial informó",
            "conocimiento general o inferencia",
            "reescribir, nunca enriquecer",
            "No emitas opiniones",
            "No uses lenguaje partidario",
            "neutralidad editorial",
        ):
            self.assertIn(regla, prompt_sistema)

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_solo_envia_los_campos_permitidos_de_la_noticia(self, urlopen_mock):
        urlopen_mock.return_value = _respuesta_falsa(_respuesta_ollama())
        redactor = RedactorOllama()

        redactor.redactar(self.noticia)

        cuerpo = json.loads(urlopen_mock.call_args.args[0].data)
        mensaje_usuario = cuerpo["messages"][1]["content"]
        self.assertIn(self.noticia.titulo_original, mensaje_usuario)
        self.assertIn(self.noticia.texto_original, mensaje_usuario)
        self.assertIn(self.noticia.nombre_fuente, mensaje_usuario)
        self.assertIn(self.noticia.localidad, mensaje_usuario)
        self.assertNotIn(self.noticia.url_fuente, mensaje_usuario)

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_parsea_titulo_y_texto_preparado(self, urlopen_mock):
        urlopen_mock.return_value = _respuesta_falsa(
            _respuesta_ollama("Jayat asumió en el BRIPAEM", "El intendente fue elegido presidente del organismo.")
        )
        redactor = RedactorOllama()

        titulo, texto = redactor.redactar(self.noticia)

        self.assertEqual(titulo, "Jayat asumió en el BRIPAEM")
        self.assertEqual(texto, "El intendente fue elegido presidente del organismo.")


class TestErroresOllama(unittest.TestCase):
    def setUp(self):
        self.noticia = _noticia_de_prueba()
        self.redactor = RedactorOllama()

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_servidor_no_disponible_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.URLError("Connection refused")

        with self.assertRaises(ErrorRedaccionOllama) as contexto:
            self.redactor.redactar(self.noticia)
        self.assertIn(ENDPOINT_DEFAULT, str(contexto.exception))

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_modelo_no_descargado_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.HTTPError(
            url=ENDPOINT_DEFAULT, code=404, msg="Not Found", hdrs=None, fp=None
        )

        with self.assertRaises(ErrorRedaccionOllama) as contexto:
            self.redactor.redactar(self.noticia)
        self.assertIn("404", str(contexto.exception))

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_timeout_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = TimeoutError("timed out")

        with self.assertRaises(ErrorRedaccionOllama):
            self.redactor.redactar(self.noticia)

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_cuerpo_de_respuesta_no_es_json_valido(self, urlopen_mock):
        urlopen_mock.return_value = _respuesta_falsa(b"esto no es json")

        with self.assertRaises(ErrorRedaccionOllama):
            self.redactor.redactar(self.noticia)

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_content_del_mensaje_no_es_json_valido(self, urlopen_mock):
        cuerpo = {"message": {"role": "assistant", "content": "no es json"}, "done": True}
        urlopen_mock.return_value = _respuesta_falsa(json.dumps(cuerpo).encode("utf-8"))

        with self.assertRaises(ErrorRedaccionOllama):
            self.redactor.redactar(self.noticia)

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_respuesta_incompleta_sin_campos_requeridos(self, urlopen_mock):
        cuerpo = {
            "message": {"role": "assistant", "content": json.dumps({"titulo_preparado": "Solo título"})},
            "done": True,
        }
        urlopen_mock.return_value = _respuesta_falsa(json.dumps(cuerpo).encode("utf-8"))

        with self.assertRaises(ErrorRedaccionOllama):
            self.redactor.redactar(self.noticia)

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_respuesta_sin_message_error_controlado(self, urlopen_mock):
        urlopen_mock.return_value = _respuesta_falsa(json.dumps({"done": True}).encode("utf-8"))

        with self.assertRaises(ErrorRedaccionOllama):
            self.redactor.redactar(self.noticia)


class TestProteccionAntiAlucinacion(unittest.TestCase):
    """Reproduce los tres casos reales detectados con qwen3:1.7b."""

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_caso_a_bripaem_con_texto_suficiente_puede_reescribirse(self, urlopen_mock):
        noticia = _noticia_de_prueba(
            titulo_original="Ing. Oscar Jayat nuevo Presidente del BRIPAEM",
            texto_original=(
                "En una asamblea extraordinaria realizada en la ciudad de Buenos Aires, "
                "asumió como Presidente del BRIPAEM por el periodo 2026-2028."
            ),
        )
        urlopen_mock.return_value = _respuesta_falsa(
            _respuesta_ollama(
                "Jayat asumió como Presidente del BRIPAEM",
                "Oscar Jayat asumió como Presidente del BRIPAEM para el periodo 2026-2028, "
                "en una asamblea extraordinaria en Buenos Aires.",
            )
        )
        redactor = RedactorOllama()

        titulo, texto = redactor.redactar(noticia)

        urlopen_mock.assert_called_once()
        self.assertEqual(titulo, "Jayat asumió como Presidente del BRIPAEM")
        self.assertIn("BRIPAEM", texto)

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_caso_a_respuesta_con_agregado_no_sustentado_usa_fallback(self, urlopen_mock):
        # reproduce el agregado real detectado: una frase de tipo "fuente
        # oficial" que no está en el contenido original.
        noticia = _noticia_de_prueba(
            titulo_original="Ing. Oscar Jayat nuevo Presidente del BRIPAEM",
            texto_original=(
                "En una asamblea extraordinaria realizada en la ciudad de Buenos Aires, "
                "asumió como Presidente del BRIPAEM por el periodo 2026-2028."
            ),
        )
        urlopen_mock.return_value = _respuesta_falsa(
            _respuesta_ollama(
                "Jayat asumió como Presidente del BRIPAEM",
                "Oscar Jayat asumió como Presidente del BRIPAEM para el periodo 2026-2028. "
                "La información se encuentra registrada en la fuente oficial correspondiente.",
            )
        )
        redactor = RedactorOllama()

        titulo, texto = redactor.redactar(noticia)

        self.assertEqual(titulo, noticia.titulo_original)
        self.assertEqual(texto, noticia.texto_original)

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_caso_b_polideportivo_sin_informacion_usa_fallback_seguro(self, urlopen_mock):
        noticia = _noticia_de_prueba(
            titulo_original="Reinauguración Polideportivo del Barrio 18 de Noviembre",
            texto_original="",
        )
        redactor = RedactorOllama()

        titulo, texto = redactor.redactar(noticia)

        urlopen_mock.assert_not_called()
        self.assertEqual(titulo, "Reinauguración Polideportivo del Barrio 18 de Noviembre")
        self.assertEqual(texto, "Reinauguración Polideportivo del Barrio 18 de Noviembre")

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_caso_c_convenio_sin_informacion_usa_fallback_seguro(self, urlopen_mock):
        noticia = _noticia_de_prueba(
            titulo_original="Firma de Convenio Etapa 2 Techado del Predio Ferial Municipal",
            texto_original="",
        )
        redactor = RedactorOllama()

        titulo, texto = redactor.redactar(noticia)

        urlopen_mock.assert_not_called()
        self.assertEqual(titulo, "Firma de Convenio Etapa 2 Techado del Predio Ferial Municipal")
        self.assertEqual(texto, "Firma de Convenio Etapa 2 Techado del Predio Ferial Municipal")

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_titulo_identico_al_texto_usa_fallback_seguro_sin_llamar_al_modelo(self, urlopen_mock):
        noticia = _noticia_de_prueba(
            titulo_original="Reinauguración Polideportivo del Barrio 18 de Noviembre",
            texto_original="Reinauguración Polideportivo del Barrio 18 de Noviembre",
        )
        redactor = RedactorOllama()

        titulo, texto = redactor.redactar(noticia)

        urlopen_mock.assert_not_called()
        self.assertEqual(titulo, noticia.titulo_original)
        self.assertEqual(texto, noticia.titulo_original)

    @patch("motor_noticias.redaccion.ollama.urllib.request.urlopen")
    def test_respuesta_muy_expandida_respecto_de_la_fuente_usa_fallback(self, urlopen_mock):
        # reproduce el caso donde el modelo inventó objetivos, fecha,
        # autoridades, instalaciones y actividades futuras a partir de un
        # texto fuente corto.
        noticia = _noticia_de_prueba(
            titulo_original="Reinauguración Polideportivo del Barrio 18 de Noviembre",
            texto_original="El intendente encabezó la reinauguración del polideportivo.",
        )
        texto_inventado = (
            "El acto tuvo como objetivo promover el deporte y el desarrollo social en la "
            "comunidad. Se realizó el 15 de noviembre con la presencia de autoridades "
            "municipales y numerosos vecinos del barrio. Las instalaciones renovadas "
            "cuentan con equipamiento moderno y se prevén nuevas actividades deportivas "
            "y recreativas para los próximos meses, fortaleciendo el vínculo comunitario "
            "y el acceso al deporte en la zona."
        )
        urlopen_mock.return_value = _respuesta_falsa(
            _respuesta_ollama("Reinauguraron el polideportivo del Barrio 18 de Noviembre", texto_inventado)
        )
        redactor = RedactorOllama()

        titulo, texto = redactor.redactar(noticia)

        self.assertEqual(titulo, noticia.titulo_original)
        self.assertEqual(texto, noticia.texto_original)


class TestRedactorMockSigueFuncionando(unittest.TestCase):
    def test_redactor_mock_devuelve_titulo_y_texto(self):
        noticia = _noticia_de_prueba()
        titulo, texto = RedactorMock().redactar(noticia)
        self.assertTrue(titulo)
        self.assertTrue(texto)


if __name__ == "__main__":
    unittest.main()
