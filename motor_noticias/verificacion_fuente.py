"""Verificación en vivo de "impacto local concreto": para una noticia que la
clasificación territorial determinística marcó como `provincial` (sin
relación directa detectada en el título/texto ya recolectados), confirma
contra el HTML real de la fuente si el artículo completo sí menciona
Libertador General San Martín o alguna localidad del Departamento Ledesma —
algo que un resumen/extracto recortado por el recolector puede perder.

Nunca se usa para relajar `local`/`departamental` (esos ya están verificados
por texto propio) ni para habilitar `nacional`: es exclusivamente la
excepción acotada para contenido provincial con impacto local real pero mal
clasificado por falta de texto completo."""
import html.parser
import urllib.error
import urllib.request
from dataclasses import dataclass

from .relevancia import clasificar_relevancia

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LedesmaParticipa/1.0; VerificadorFuente)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TIMEOUT_DEFAULT_SEGUNDOS = 8
TAGS_SIN_TEXTO = {"script", "style", "noscript"}


@dataclass
class ResultadoVerificacionLocal:
    impacto_local: bool
    motivo: str


class _ExtractorTexto(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self._omitir = 0
        self._partes = []

    def handle_starttag(self, tag, attrs):
        if tag in TAGS_SIN_TEXTO:
            self._omitir += 1

    def handle_endtag(self, tag):
        if tag in TAGS_SIN_TEXTO and self._omitir > 0:
            self._omitir -= 1

    def handle_data(self, data):
        if not self._omitir:
            self._partes.append(data)

    def texto(self) -> str:
        return " ".join(self._partes)


def _texto_plano(html_crudo: str) -> str:
    extractor = _ExtractorTexto()
    extractor.feed(html_crudo)
    return extractor.texto()


def verificar_impacto_local_concreto(
    url_fuente: str, timeout: int = TIMEOUT_DEFAULT_SEGUNDOS
) -> ResultadoVerificacionLocal:
    """Descarga la fuente real y confirma si el artículo completo menciona
    Libertador o el Departamento Ledesma. Falla siempre hacia "no
    verificado": cualquier error de red, HTTP o de parseo se trata como sin
    impacto local (nunca se asume relación local sin confirmarla), para no
    rellenar una franja con contenido provincial sin evidencia real."""
    if not url_fuente:
        return ResultadoVerificacionLocal(False, "Sin URL de fuente para verificar.")

    peticion = urllib.request.Request(url_fuente, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            crudo = respuesta.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        return ResultadoVerificacionLocal(False, f"No se pudo verificar la fuente: {error}")

    texto = _texto_plano(crudo)
    resultado = clasificar_relevancia("", texto)
    if resultado["relevante"]:
        return ResultadoVerificacionLocal(True, f"La nota completa {resultado['motivo'].lower()}.")
    return ResultadoVerificacionLocal(
        False, "La nota completa no menciona Libertador ni el Departamento Ledesma."
    )
