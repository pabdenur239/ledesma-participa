import html.parser
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin

from .base import Collector

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "fuentes.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LedesmaParticipa/1.0; RSS Reader)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# El sitio real (CMS Thinkindot) lista cada noticia dentro de un <article>;
# el título vive en <h2 class="title"><a href="...">, el resumen (cuando
# existe) en <div class="preview"><p>...</p></div>, y la imagen dentro de
# <figure class="figure"><img>. Algunas imágenes usan carga diferida: el
# <img src="...lazy.svg"> es un placeholder y la URL real está en el
# atributo longdesc, que se prioriza cuando está presente. Los widgets de
# encuesta (class contiene "survey") se excluyen explícitamente: no son
# noticias. El sitio no expone ninguna fecha estable en el listado (sin
# atributos datetime, sin <time>, y el único JSON-LD es un WebSite
# genérico sin datePublished), así que nunca se completa ese campo aquí.
CLASE_EXCLUIDA_ENCUESTA = "survey"
MARCADOR_PLACEHOLDER_LAZY = "lazy.svg"

TAGS_EXCLUIDOS = {"nav", "header", "footer", "aside", "script", "style", "noscript", "form", "iframe"}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img",
    "input", "link", "meta", "param", "source", "track", "wbr",
}
LONGITUD_MINIMA_RESUMEN = 15


class ErrorRecoleccionJujuyAlMomento(RuntimeError):
    """Error controlado al recolectar el listado de Jujuy al Momento."""


def _cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)["jujuyalmomento"]


def _limpiar_espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _atributo(attrs, nombre):
    for clave, valor in attrs:
        if clave == nombre:
            return valor
    return None


class _ParserListadoJujuyAlMomento(html.parser.HTMLParser):
    """Recorre el listado real de Jujuy al Momento: cada noticia es un
    <article>, con título en <h2 class="title"> y resumen opcional en
    <div class="preview">, ambos anidados. La imagen es el primer <img>
    dentro del artículo (con soporte de carga diferida vía longdesc). Los
    artículos con "survey" en su clase (encuestas) se descartan por completo."""

    def __init__(self, url_base: str):
        super().__init__(convert_charrefs=True)
        self.url_base = url_base
        self.items: List[dict] = []

        self._pila: List[str] = []
        self._omitir_desde: Optional[int] = None

        self._en_articulo = False
        self._profundidad_articulo = 0
        self._articulo_excluido = False
        self._articulo_actual: Optional[dict] = None
        self._imagen_capturada = False

        self._en_titulo = False
        self._profundidad_titulo = 0
        self._buffer_titulo: List[str] = []

        self._en_resumen = False
        self._profundidad_resumen = 0
        self._buffer_resumen: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            self._procesar_elemento_void(tag, attrs)
            return
        self._pila.append(tag)

        if self._omitir_desde is not None:
            return
        if tag in TAGS_EXCLUIDOS:
            self._omitir_desde = len(self._pila)
            return

        clase = _atributo(attrs, "class") or ""

        if not self._en_articulo:
            if tag == "article":
                self._en_articulo = True
                self._profundidad_articulo = len(self._pila)
                self._articulo_excluido = CLASE_EXCLUIDA_ENCUESTA in clase
                self._articulo_actual = {
                    "titulo": "",
                    "url": None,
                    "resumen": "",
                    "imagen_url": None,
                }
                self._imagen_capturada = False
                self._en_titulo = False
                self._en_resumen = False
            return

        if self._articulo_excluido:
            return

        clases = clase.split()
        if tag == "h2" and "title" in clases and not self._en_titulo and not self._articulo_actual["titulo"]:
            self._en_titulo = True
            self._profundidad_titulo = len(self._pila)
            self._buffer_titulo = []
        elif tag == "div" and "preview" in clases and not self._en_resumen and not self._articulo_actual["resumen"]:
            self._en_resumen = True
            self._profundidad_resumen = len(self._pila)
            self._buffer_resumen = []
        elif tag == "a" and self._en_titulo and not self._articulo_actual["url"]:
            href = _atributo(attrs, "href")
            if href:
                self._articulo_actual["url"] = urljoin(self.url_base, href)

    def _procesar_elemento_void(self, tag, attrs):
        if self._omitir_desde is not None or tag != "img":
            return
        if not self._en_articulo or self._articulo_excluido or self._imagen_capturada:
            return
        longdesc = _atributo(attrs, "longdesc")
        src = _atributo(attrs, "src")
        candidato = longdesc or src
        if not candidato or MARCADOR_PLACEHOLDER_LAZY in candidato:
            return
        self._articulo_actual["imagen_url"] = urljoin(self.url_base, candidato)
        self._imagen_capturada = True

    def handle_endtag(self, tag):
        if not self._pila or self._pila[-1] != tag:
            return
        self._pila.pop()

        if self._omitir_desde is not None:
            if len(self._pila) < self._omitir_desde:
                self._omitir_desde = None
            return

        if not self._en_articulo:
            return

        if self._en_titulo and len(self._pila) < self._profundidad_titulo:
            self._articulo_actual["titulo"] = _limpiar_espacios(" ".join(self._buffer_titulo))
            self._en_titulo = False
        elif self._en_resumen and len(self._pila) < self._profundidad_resumen:
            resumen = _limpiar_espacios(" ".join(self._buffer_resumen))
            if len(resumen) >= LONGITUD_MINIMA_RESUMEN:
                self._articulo_actual["resumen"] = resumen
            self._en_resumen = False
        elif tag == "article" and len(self._pila) < self._profundidad_articulo:
            self._en_articulo = False
            if not self._articulo_excluido and self._articulo_actual["titulo"] and self._articulo_actual["url"]:
                self.items.append(self._articulo_actual)
            self._articulo_actual = None
            self._articulo_excluido = False

    def handle_data(self, data):
        if self._omitir_desde is not None or not self._en_articulo or self._articulo_excluido:
            return
        texto = data.strip()
        if not texto:
            return
        if self._en_titulo:
            self._buffer_titulo.append(texto)
        elif self._en_resumen:
            self._buffer_resumen.append(texto)


def parsear_listado(html_crudo: str, url_base: str, nombre_fuente: str) -> List[dict]:
    parser = _ParserListadoJujuyAlMomento(url_base)
    parser.feed(html_crudo)
    parser.close()

    return [
        {
            "titulo": item["titulo"],
            "texto": item["resumen"],
            "url": item["url"],
            "fuente": nombre_fuente,
            "fecha": "",
            "imagen_url": item["imagen_url"],
        }
        for item in parser.items
    ]


class JujuyAlMomentoHTMLCollector(Collector):
    """Collector HTML real de Jujuy al Momento (https://www.jujuyalmomento.com/).

    Fuente provincial: no asigna una localidad fija, la relevancia
    geográfica de cada noticia se deriva de su contenido con el
    clasificador existente. Requiere acceso saliente a internet; no se
    ejecuta durante las pruebas automáticas, que usan un fixture HTML
    local en su lugar.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        nombre_fuente: Optional[str] = None,
        timeout: int = 20,
        config_path: Optional[Path] = None,
    ):
        config = _cargar_config(config_path)
        self.url = url or config["url"]
        self.nombre_fuente = nombre_fuente or config["nombre_fuente"]
        self.timeout = timeout

    def recolectar(self) -> List[dict]:
        peticion = urllib.request.Request(self.url, headers=HEADERS)
        try:
            with urllib.request.urlopen(peticion, timeout=self.timeout) as respuesta:
                contenido = respuesta.read()
        except urllib.error.HTTPError as error:
            raise ErrorRecoleccionJujuyAlMomento(
                f"Jujuy al Momento respondió HTTP {error.code} ({error.reason}) al pedir {self.url}"
            ) from error
        except urllib.error.URLError as error:
            raise ErrorRecoleccionJujuyAlMomento(
                f"No se pudo conectar a Jujuy al Momento ({self.url}): {error.reason}"
            ) from error
        html_crudo = contenido.decode("utf-8", errors="replace")
        return parsear_listado(html_crudo, self.url, self.nombre_fuente)
