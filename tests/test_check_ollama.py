import json
import unittest
import urllib.error

from scripts.windows.check_ollama import (
    CODIGO_OK,
    CODIGO_SIN_API,
    CODIGO_SIN_MODELO,
    _url_base,
    main,
    verificar_ollama,
)


class _RespuestaFalsa:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.data).encode("utf-8")


def _abrir_url_con_modelos(*nombres):
    def _abrir(url, timeout=5):
        return _RespuestaFalsa({"models": [{"name": n} for n in nombres]})

    return _abrir


def _abrir_url_caido(url, timeout=5):
    raise urllib.error.URLError("conexión rechazada")


class TestUrlBase(unittest.TestCase):
    def test_extrae_host_desde_endpoint_de_chat(self):
        self.assertEqual(_url_base("http://127.0.0.1:11434/api/chat"), "http://127.0.0.1:11434")


class TestVerificarOllama(unittest.TestCase):
    # 3. check Ollama OK simulado
    def test_ollama_disponible_con_modelo(self):
        dormidas = []
        resultado = verificar_ollama(
            "http://127.0.0.1:11434",
            "qwen3:1.7b",
            abrir_url=_abrir_url_con_modelos("qwen3:1.7b", "otro-modelo"),
            dormir=dormidas.append,
        )
        self.assertTrue(resultado["disponible"])
        self.assertTrue(resultado["modelo_presente"])
        self.assertEqual(resultado["intentos_realizados"], 1)
        self.assertEqual(dormidas, [])  # no reintentó: respondió al primer intento

    # 4. Ollama no disponible
    def test_ollama_no_disponible_reintenta_y_reporta(self):
        dormidas = []
        resultado = verificar_ollama(
            "http://127.0.0.1:11434",
            "qwen3:1.7b",
            espera_maxima_segundos=15,
            intervalo_segundos=5,
            abrir_url=_abrir_url_caido,
            dormir=dormidas.append,
        )
        self.assertFalse(resultado["disponible"])
        self.assertFalse(resultado["modelo_presente"])
        self.assertEqual(resultado["intentos_realizados"], 3)  # 15 / 5
        self.assertEqual(dormidas, [5, 5])  # duerme entre intentos, no después del último

    # 5. Ollama sin modelo
    def test_ollama_disponible_sin_el_modelo_configurado(self):
        resultado = verificar_ollama(
            "http://127.0.0.1:11434",
            "qwen3:1.7b",
            abrir_url=_abrir_url_con_modelos("otro-modelo"),
            dormir=lambda s: None,
        )
        self.assertTrue(resultado["disponible"])
        self.assertFalse(resultado["modelo_presente"])
        self.assertIn("qwen3:1.7b", resultado["motivo"])

    def test_nunca_reemplaza_silenciosamente_nada_solo_informa(self):
        # El resultado es puramente informativo: no hay ninguna rama que
        # instancie otro redactor ni decida nada por su cuenta.
        resultado = verificar_ollama(
            "http://127.0.0.1:11434", "qwen3:1.7b", abrir_url=_abrir_url_caido, dormir=lambda s: None
        )
        self.assertEqual(set(resultado.keys()), {
            "disponible", "modelo_presente", "modelos_instalados", "intentos_realizados", "motivo"
        })


class TestCodigosDeSalida(unittest.TestCase):
    def test_codigo_ok(self):
        import unittest.mock as mock

        with mock.patch(
            "scripts.windows.check_ollama.verificar_ollama",
            return_value={
                "disponible": True,
                "modelo_presente": True,
                "modelos_instalados": ["qwen3:1.7b"],
                "intentos_realizados": 1,
                "motivo": "ok",
            },
        ):
            self.assertEqual(main(["--espera-maxima", "1", "--intervalo", "1"]), CODIGO_OK)

    def test_codigo_sin_api(self):
        import unittest.mock as mock

        with mock.patch(
            "scripts.windows.check_ollama.verificar_ollama",
            return_value={
                "disponible": False,
                "modelo_presente": False,
                "modelos_instalados": [],
                "intentos_realizados": 1,
                "motivo": "no responde",
            },
        ):
            self.assertEqual(main(["--espera-maxima", "1", "--intervalo", "1"]), CODIGO_SIN_API)

    def test_codigo_sin_modelo(self):
        import unittest.mock as mock

        with mock.patch(
            "scripts.windows.check_ollama.verificar_ollama",
            return_value={
                "disponible": True,
                "modelo_presente": False,
                "modelos_instalados": ["otro"],
                "intentos_realizados": 1,
                "motivo": "sin modelo",
            },
        ):
            self.assertEqual(main(["--espera-maxima", "1", "--intervalo", "1"]), CODIGO_SIN_MODELO)


if __name__ == "__main__":
    unittest.main()
