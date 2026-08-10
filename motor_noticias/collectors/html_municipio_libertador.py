import html.parser
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Union
from urllib.parse import urljoin

from .base import Collector

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "fuentes.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LedesmaParticipa/1.0; RSS Reader)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CONTENEDOR_TAG = "main"
CONTENEDOR_ID = "contenido-principal"
ARTICULO_TAG = "article"


class ErrorRecoleccionHTML(RuntimeError):
    """Error controlado al recolectar la página municipal."""


def _cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)["municipio_libertador"]


def _atributo(attrs, nombre):
    for clave, valor in attrs:
        if clave == nombre:
            return valor
    return None


class _ParserActividades(html.parser.HTMLParser):
    """Extrae publicaciones dentro del contenedor principal de la página,
    ignorando cualquier enlace de navegación, encabezado o pie de página."""

    def __init__(self, url_base: str):
        super().__init__(convert_charrefs=True)
        self.url_base = url_base
        self.items: List[dict] = []

        self._pila = []
        self._dentro_contenedor = False
        self._profundidad_contenedor = 0

        self._en_articulo = False
        self._profundidad_articulo = 0
        self._articulo_actual = None
        self._en_titulo = False
        self._capturando_enlace_titulo = False
        self._en_parrafo = False

    def handle_starttag(self, tag, attrs):
        self._pila.append(tag)

        if not self._dentro_contenedor:
            if tag == CONTENEDOR_TAG and _atributo(attrs, "id") == CONTENEDOR_ID:
                self._dentro_contenedor = True
                self._profundidad_contenedor = len(self._pila)
            return

        if not self._en_articulo:
            if tag == ARTICULO_TAG:
                self._en_articulo = True
                self._profundidad_articulo = len(self._pila)
                self._articulo_actual = {"titulo": "", "url": None, "fecha": "", "texto": ""}
            return

        if tag in ("h1", "h2", "h3") and not self._articulo_actual["titulo"]:
            self._en_titulo = True
        elif tag == "a" and self._en_titulo and not self._articulo_actual["url"]:
            href = _atributo(attrs, "href")
            if href:
                self._articulo_actual["url"] = urljoin(self.url_base, href)
            self._capturando_enlace_titulo = True
        elif tag == "time":
            fecha = _atributo(attrs, "datetime")
            if fecha:
                self._articulo_actual["fecha"] = fecha
        elif tag == "p" and not self._articulo_actual["texto"]:
            self._en_parrafo = True

    def handle_endtag(self, tag):
        if self._pila and self._pila[-1] == tag:
            self._pila.pop()

        if self._dentro_contenedor and len(self._pila) < self._profundidad_contenedor:
            self._dentro_contenedor = False

        if self._en_articulo:
            if tag in ("h1", "h2", "h3"):
                self._en_titulo = False
            elif tag == "a":
                self._capturando_enlace_titulo = False
            elif tag == "p":
                self._en_parrafo = False
            elif tag == ARTICULO_TAG and len(self._pila) < self._profundidad_articulo:
                self._en_articulo = False
                if self._articulo_actual["titulo"] and self._articulo_actual["url"]:
                    self.items.append(self._articulo_actual)
                self._articulo_actual = None

    def handle_data(self, data):
        if not self._en_articulo or self._articulo_actual is None:
            return
        texto = data.strip()
        if not texto:
            return
        if self._capturando_enlace_titulo:
            actual = self._articulo_actual["titulo"]
            self._articulo_actual["titulo"] = f"{actual} {texto}".strip() if actual else texto
        elif self._en_parrafo:
            actual = self._articulo_actual["texto"]
            self._articulo_actual["texto"] = f"{actual} {texto}".strip() if actual else texto


def parsear_html(contenido: Union[str, bytes], url_base: str, nombre_fuente: str) -> List[dict]:
    if isinstance(contenido, bytes):
        contenido = contenido.decode("utf-8", errors="replace")
    parser = _ParserActividades(url_base)
    parser.feed(contenido)
    return [
        {
            "titulo": item["titulo"],
            "texto": item["texto"],
            "url": item["url"],
            "fuente": nombre_fuente,
            "fecha": item["fecha"],
        }
        for item in parser.items
    ]


class MunicipioLibertadorHTMLCollector(Collector):
    """Collector HTML real de la Municipalidad de Libertador General San Martín.

    Requiere acceso saliente a internet; no se ejecuta durante las pruebas
    automáticas, que usan un fixture HTML local en su lugar.
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
            raise ErrorRecoleccionHTML(
                f"Municipio Libertador respondió HTTP {error.code} ({error.reason}) al pedir {self.url}"
            ) from error
        except urllib.error.URLError as error:
            raise ErrorRecoleccionHTML(
                f"No se pudo conectar al Municipio Libertador ({self.url}): {error.reason}"
            ) from error
        return parsear_html(contenido, self.url, self.nombre_fuente)
