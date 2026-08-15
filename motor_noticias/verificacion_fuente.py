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

from .relevancia import _sin_acentos, clasificar_relevancia

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LedesmaParticipa/1.0; VerificadorFuente)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TIMEOUT_DEFAULT_SEGUNDOS = 8
TAGS_SIN_TEXTO = {"script", "style", "noscript"}
# Ventana de texto, a partir de donde aparece el propio título, que se
# considera "cuerpo del artículo". Calibrada empíricamente: alcanza para
# cubrir el cuerpo real (una mención genuina de Libertador apareció a ~2200
# caracteres del título) sin llegar a widgets de "Te puede interesar" /
# notas relacionadas de otros artículos (que en la práctica aparecen bastante
# más lejos, ~5700 caracteres en el caso que motivó este ajuste) — esos
# widgets, si no se acotara la ventana, producen falsos positivos: matchean
# localidades mencionadas en OTRA nota, no en la que se está verificando.
LONGITUD_VENTANA_ARTICULO = 3000


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
    titulo_original: str, url_fuente: str, timeout: int = TIMEOUT_DEFAULT_SEGUNDOS
) -> ResultadoVerificacionLocal:
    """Descarga la fuente real y confirma si el CUERPO del artículo (no la
    página entera) menciona Libertador o el Departamento Ledesma. Ubica el
    propio título dentro del texto extraído y solo busca dentro de la
    ventana que sigue: una página de noticias real trae, además del
    artículo, navegación, notas relacionadas y "también te puede interesar"
    con títulos de OTRAS notas — sin acotar la búsqueda al cuerpo, esas
    secciones producen falsos positivos (mencionan una localidad, pero de
    una nota distinta a la que se está verificando).

    Falla siempre hacia "no verificado": cualquier error de red, HTTP, de
    parseo, o no poder ubicar el título en la página, se trata como sin
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
    texto_norm = _sin_acentos(texto)
    titulo_norm = _sin_acentos(titulo_original or "")
    inicio = texto_norm.find(titulo_norm) if titulo_norm else -1
    if inicio == -1:
        return ResultadoVerificacionLocal(
            False, "No se pudo ubicar el título original dentro del contenido de la fuente."
        )

    cuerpo_articulo = texto[inicio : inicio + LONGITUD_VENTANA_ARTICULO]
    resultado = clasificar_relevancia("", cuerpo_articulo)
    if resultado["relevante"]:
        return ResultadoVerificacionLocal(True, f"El cuerpo de la nota {resultado['motivo'].lower()}.")
    return ResultadoVerificacionLocal(
        False, "El cuerpo de la nota no menciona Libertador ni el Departamento Ledesma."
    )
