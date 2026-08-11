import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from ..models import Noticia
from .base import Redactor

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "redaccion.json"

ENDPOINT_DEFAULT = "http://localhost:11434/api/chat"
MODELO_DEFAULT = "qwen3:1.7b"
TIMEOUT_DEFAULT = 60

ESQUEMA_RESPUESTA = {
    "type": "object",
    "properties": {
        "titulo_preparado": {"type": "string"},
        "texto_preparado": {"type": "string"},
    },
    "required": ["titulo_preparado", "texto_preparado"],
}

PROMPT_SISTEMA = (
    "Sos un redactor periodístico de un medio digital hiperlocal. Reescribí "
    "la noticia recibida siguiendo estas reglas de forma estricta:\n"
    "- Escribí en español claro y periodístico.\n"
    "- Conservá estrictamente los hechos recibidos.\n"
    "- No inventes nombres.\n"
    "- No inventes cifras.\n"
    "- No inventes fechas.\n"
    "- No inventes declaraciones.\n"
    "- No agregues contexto que no esté presente en la fuente.\n"
    "- No emitas opiniones.\n"
    "- No exageres.\n"
    "- No uses lenguaje partidario.\n"
    "- No copies innecesariamente el texto original.\n"
    "- Producí un título breve.\n"
    "- Producí un texto apto para una publicación informativa local.\n"
    "- Mantené neutralidad editorial.\n"
    "Si la información de origen es insuficiente, redactá solamente con lo "
    "disponible; no inventes ni completes datos faltantes.\n"
    "Respondé únicamente con el JSON solicitado, sin texto adicional."
)


class ErrorRedaccionOllama(RuntimeError):
    """Error controlado al redactar una noticia mediante Ollama."""


def _cargar_config(path: Optional[Path] = None) -> dict:
    try:
        with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _construir_mensaje_usuario(noticia: Noticia) -> str:
    return (
        f"Título original: {noticia.titulo_original}\n"
        f"Texto original: {noticia.texto_original}\n"
        f"Fuente: {noticia.nombre_fuente or ''}\n"
        f"Localidad: {noticia.localidad or ''}"
    )


class RedactorOllama(Redactor):
    """Redactor real mediante un modelo local servido por Ollama.

    No tiene acceso a internet ni a otras fuentes: solo recibe título,
    texto, nombre de fuente y localidad de la propia noticia. Si Ollama
    no está disponible, el error se informa de forma controlada
    (ErrorRedaccionOllama); nunca cambia automáticamente a otro proveedor.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        modelo: Optional[str] = None,
        timeout: Optional[int] = None,
        config_path: Optional[Path] = None,
    ):
        config = _cargar_config(config_path)
        self.endpoint = endpoint or config.get("endpoint") or ENDPOINT_DEFAULT
        self.modelo = modelo or config.get("modelo") or MODELO_DEFAULT
        self.timeout = timeout or config.get("timeout") or TIMEOUT_DEFAULT

    def redactar(self, noticia: Noticia) -> Tuple[str, str]:
        cuerpo = {
            "model": self.modelo,
            "messages": [
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user", "content": _construir_mensaje_usuario(noticia)},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
            "format": ESQUEMA_RESPUESTA,
        }
        peticion = urllib.request.Request(
            self.endpoint,
            data=json.dumps(cuerpo).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(peticion, timeout=self.timeout) as respuesta:
                contenido = respuesta.read()
        except urllib.error.HTTPError as error:
            raise ErrorRedaccionOllama(
                f"Ollama respondió HTTP {error.code} ({error.reason}) en {self.endpoint}. "
                f"¿El modelo '{self.modelo}' está descargado?"
            ) from error
        except urllib.error.URLError as error:
            raise ErrorRedaccionOllama(
                f"No se pudo conectar a Ollama en {self.endpoint}: {error.reason}. "
                "¿Ollama está instalado y corriendo (`ollama serve`)?"
            ) from error
        except TimeoutError as error:
            raise ErrorRedaccionOllama(
                f"Tiempo de espera agotado al conectar con Ollama en {self.endpoint}"
            ) from error

        try:
            cuerpo_respuesta = json.loads(contenido)
        except json.JSONDecodeError as error:
            raise ErrorRedaccionOllama("Ollama devolvió una respuesta que no es JSON válido") from error

        mensaje = cuerpo_respuesta.get("message")
        if not isinstance(mensaje, dict) or not mensaje.get("content"):
            raise ErrorRedaccionOllama("La respuesta de Ollama no contiene 'message.content'")

        try:
            resultado = json.loads(mensaje["content"])
        except json.JSONDecodeError as error:
            raise ErrorRedaccionOllama(
                "El contenido devuelto por el modelo no es JSON válido"
            ) from error

        titulo_preparado = resultado.get("titulo_preparado")
        texto_preparado = resultado.get("texto_preparado")
        if not titulo_preparado or not texto_preparado:
            raise ErrorRedaccionOllama(
                "La respuesta del modelo no incluye 'titulo_preparado' y 'texto_preparado'"
            )

        return titulo_preparado, texto_preparado
