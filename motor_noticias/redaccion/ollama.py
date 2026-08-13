import json
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from ..models import Noticia
from .base import Redactor

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "redaccion.json"

ENDPOINT_DEFAULT = "http://localhost:11434/api/chat"
MODELO_DEFAULT = "qwen3:1.7b"
# 120s (antes 60s): en producción el modelo queda "frío" entre ciclos del
# Motor Continuo (cada 30 min) y la primera carga/redacción tras eso puede
# superar los 60s.
TIMEOUT_DEFAULT = 120
# Motor Continuo corre cada 30 min: 35m mantiene el modelo cargado en
# memoria entre ciclos y evita una recarga fría en cada ronda.
KEEP_ALIVE_DEFAULT = "35m"
# qwen3 soporta un modo "thinking" que no aporta nada para reescritura
# periodística y puede ser más lento: se pide explícitamente apagado, sin
# depender del default de Ollama.
THINK_DEFAULT = False

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
    "- Cada afirmación debe estar sustentada directamente por los datos recibidos.\n"
    "- No inventes nombres.\n"
    "- No inventes cifras.\n"
    "- No inventes fechas.\n"
    "- No inventes declaraciones.\n"
    "- No agregues fechas que no estén en el contenido original.\n"
    "- No agregues lugares que no estén en el contenido original.\n"
    "- No agregues personas que no estén en el contenido original.\n"
    "- No agregues asistentes ni presencia de autoridades no mencionadas.\n"
    "- No agregues características físicas de lugares o instalaciones.\n"
    "- No agregues objetivos, beneficios ni consecuencias no mencionados.\n"
    "- No agregues declaraciones que no estén en el contenido original.\n"
    "- No agregues contexto institucional ni antecedentes no mencionados.\n"
    "- No agregues frases como 'la fuente oficial informó...' salvo que "
    "estén presentes en el contenido original.\n"
    "- El nombre de la fuente y la localidad que se te indican son "
    "metadatos internos para tu contexto, no contenido periodístico: no "
    "los menciones en el título ni en el texto preparado salvo que ya "
    "aparezcan explícitamente en el título original o el texto original.\n"
    "- No escribas frases como 'la fuente es...', 'según la fuente...', "
    "'la localidad es...' o 'informó la Municipalidad...' si esa "
    "formulación no existe en el contenido original.\n"
    "- No completes información faltante mediante conocimiento general o inferencia.\n"
    "- No agregues contexto que no esté presente en la fuente.\n"
    "- No emitas opiniones.\n"
    "- No exageres.\n"
    "- No uses lenguaje partidario.\n"
    "- No copies innecesariamente el texto original.\n"
    "- Producí un título breve.\n"
    "- Producí un texto apto para una publicación informativa local.\n"
    "- Mantené neutralidad editorial.\n"
    "El objetivo es reescribir, nunca enriquecer: si un dato no está en la "
    "fuente, no debe aparecer en el resultado.\n"
    "Si la información de origen es insuficiente, redactá solamente con lo "
    "disponible; no inventes ni completes datos faltantes.\n"
    "Respondé únicamente con el JSON solicitado, sin texto adicional."
)

# Por debajo de esta longitud, un texto_original no se considera un aporte
# real de hechos respecto del título: se usa el fallback seguro sin llamar
# al modelo.
LONGITUD_MINIMA_TEXTO_SUFICIENTE = 30

# El texto preparado no puede superar este múltiplo (más un margen fijo) del
# contenido disponible; una expansión mayor indica que el modelo agregó
# información no sustentada por la fuente.
FACTOR_MAXIMO_EXPANSION = 2.0
MARGEN_ABSOLUTO_EXPANSION = 60

FRASES_NO_SUSTENTADAS = (
    "fuente oficial",
    "según informó",
    "según informaron",
    "cabe destacar",
    "vale la pena destacar",
    "vale la pena mencionar",
    "es importante destacar",
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
        f"Fuente (metadato interno, no mencionar salvo que ya figure en el "
        f"título o el texto original): {noticia.nombre_fuente or ''}\n"
        f"Localidad (metadato interno, no mencionar salvo que ya figure en "
        f"el título o el texto original): {noticia.localidad or ''}"
    )


def _normalizar_comparacion(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.strip().lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def _hay_informacion_suficiente(noticia: Noticia) -> bool:
    texto = (noticia.texto_original or "").strip()
    if not texto:
        return False

    titulo_norm = _normalizar_comparacion(noticia.titulo_original)
    texto_norm = _normalizar_comparacion(texto)
    if texto_norm == titulo_norm or texto_norm in titulo_norm or titulo_norm in texto_norm:
        return False

    return len(texto) >= LONGITUD_MINIMA_TEXTO_SUFICIENTE


def _fallback_seguro(noticia: Noticia) -> Tuple[str, str]:
    titulo = noticia.titulo_original.strip()
    texto = (noticia.texto_original or "").strip()
    return titulo, texto if texto else titulo


def _metadato_filtrado(metadato: Optional[str], original_combinado: str, preparado_combinado: str) -> bool:
    if not metadato:
        return False
    metadato_norm = _normalizar_comparacion(metadato)
    if not metadato_norm:
        return False
    if metadato_norm in _normalizar_comparacion(original_combinado):
        # el propio contenido original ya lo menciona legítimamente
        return False
    return metadato_norm in _normalizar_comparacion(preparado_combinado)


def _respuesta_es_sospechosa(noticia: Noticia, titulo_preparado: str, texto_preparado: str) -> bool:
    base = (noticia.texto_original or "").strip() or noticia.titulo_original.strip()
    limite = len(base) * FACTOR_MAXIMO_EXPANSION + MARGEN_ABSOLUTO_EXPANSION
    if len(texto_preparado) > limite:
        return True

    if len(titulo_preparado) > len(noticia.titulo_original) * 3 + 40:
        return True

    texto_preparado_norm = texto_preparado.lower()
    base_norm = base.lower()
    for frase in FRASES_NO_SUSTENTADAS:
        if frase in texto_preparado_norm and frase not in base_norm:
            return True

    original_combinado = f"{noticia.titulo_original} {noticia.texto_original or ''}"
    preparado_combinado = f"{titulo_preparado} {texto_preparado}"
    if _metadato_filtrado(noticia.nombre_fuente, original_combinado, preparado_combinado):
        return True
    if _metadato_filtrado(noticia.localidad, original_combinado, preparado_combinado):
        return True

    return False


class RedactorOllama(Redactor):
    """Redactor real mediante un modelo local servido por Ollama.

    No tiene acceso a internet ni a otras fuentes: solo recibe título,
    texto, nombre de fuente y localidad de la propia noticia. Si Ollama
    no está disponible, el error se informa de forma controlada
    (ErrorRedaccionOllama); nunca cambia automáticamente a otro proveedor.

    Cuando la fuente no aporta hechos suficientes, o la respuesta del
    modelo parece haber agregado información no sustentada, se usa un
    fallback seguro basado en el contenido original en lugar de guardar
    una redacción potencialmente inventada. Ese fallback no se trata como
    error: es preferible una publicación poco elaborada pero factual.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        modelo: Optional[str] = None,
        timeout: Optional[int] = None,
        keep_alive: Optional[str] = None,
        think: Optional[bool] = None,
        config_path: Optional[Path] = None,
    ):
        config = _cargar_config(config_path)
        self.endpoint = endpoint or config.get("endpoint") or ENDPOINT_DEFAULT
        self.modelo = modelo or config.get("modelo") or MODELO_DEFAULT
        self.timeout = timeout or config.get("timeout") or TIMEOUT_DEFAULT
        self.keep_alive = keep_alive or config.get("keep_alive") or KEEP_ALIVE_DEFAULT
        # bool: "or" trataría a False como "no configurado" e ignoraría un
        # think=False explícito, por eso se compara contra None.
        self.think = think if think is not None else config.get("think", THINK_DEFAULT)

    def redactar(self, noticia: Noticia) -> Tuple[str, str]:
        if not _hay_informacion_suficiente(noticia):
            return _fallback_seguro(noticia)

        titulo_preparado, texto_preparado = self._pedir_redaccion_al_modelo(noticia)

        if _respuesta_es_sospechosa(noticia, titulo_preparado, texto_preparado):
            return _fallback_seguro(noticia)

        return titulo_preparado, texto_preparado

    def _pedir_redaccion_al_modelo(self, noticia: Noticia) -> Tuple[str, str]:
        cuerpo = {
            "model": self.modelo,
            "messages": [
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user", "content": _construir_mensaje_usuario(noticia)},
            ],
            "stream": False,
            "think": self.think,
            "keep_alive": self.keep_alive,
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
