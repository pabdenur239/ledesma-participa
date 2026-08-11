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

ENCABEZADO_TAGS = ("h1", "h2", "h3", "h4")
TAGS_EXCLUIDOS = {"nav", "header", "footer", "aside", "script", "style", "noscript", "form", "iframe"}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img",
    "input", "link", "meta", "param", "source", "track", "wbr",
}
LONGITUD_MINIMA_RESUMEN = 15


class ErrorRecoleccionInfoYungas(RuntimeError):
    """Error controlado al recolectar el listado de InfoYungas."""


def _cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)["infoyungas"]


def _limpiar_espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _atributo(attrs, nombre):
    for clave, valor in attrs:
        if clave == nombre:
            return valor
    return None


class _ParserListadoInfoYungas(html.parser.HTMLParser):
    """Recorre el listado de noticias buscando bloques <article>: dentro de
    cada uno toma el primer encabezado con enlace como título, la primera
    imagen como imagen_url, el primer <time datetime="..."> como fecha (solo
    si está explícito) y el primer párrafo posterior al título como resumen.

    Ignora navegación, encabezado de sitio, pie de página, widgets/publicidad
    (aside), scripts y estilos."""

    def __init__(self, url_base: str):
        super().__init__(convert_charrefs=True)
        self.url_base = url_base
        self.items: List[dict] = []

        self._pila: List[str] = []
        self._omitir_desde: Optional[int] = None

        self._en_articulo = False
        self._profundidad_articulo = 0
        self._articulo_actual: Optional[dict] = None

        self._en_titulo = False
        self._capturando_enlace_titulo = False
        self._en_resumen = False
        self._buffer_titulo: List[str] = []
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

        if not self._en_articulo:
            if tag == "article":
                self._en_articulo = True
                self._profundidad_articulo = len(self._pila)
                self._articulo_actual = {
                    "titulo": "",
                    "url": None,
                    "resumen": "",
                    "imagen_url": None,
                    "fecha": "",
                }
                self._en_titulo = False
                self._capturando_enlace_titulo = False
                self._en_resumen = False
                self._buffer_titulo = []
                self._buffer_resumen = []
            return

        if tag in ENCABEZADO_TAGS and not self._articulo_actual["titulo"] and not self._en_titulo:
            self._en_titulo = True
            self._buffer_titulo = []
        elif tag == "a" and self._en_titulo and not self._articulo_actual["url"]:
            href = _atributo(attrs, "href")
            if href:
                self._articulo_actual["url"] = urljoin(self.url_base, href)
            self._capturando_enlace_titulo = True
        elif tag == "time" and not self._articulo_actual["fecha"]:
            fecha = _atributo(attrs, "datetime")
            if fecha:
                self._articulo_actual["fecha"] = fecha
        elif (
            tag == "p"
            and self._articulo_actual["titulo"]
            and not self._articulo_actual["resumen"]
            and not self._en_resumen
        ):
            self._en_resumen = True
            self._buffer_resumen = []

    def _procesar_elemento_void(self, tag, attrs):
        if self._omitir_desde is not None or not self._en_articulo:
            return
        if tag == "img" and not self._articulo_actual["imagen_url"]:
            src = _atributo(attrs, "src") or _atributo(attrs, "data-src")
            if src:
                self._articulo_actual["imagen_url"] = urljoin(self.url_base, src)

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

        if self._en_titulo and tag in ENCABEZADO_TAGS:
            self._articulo_actual["titulo"] = _limpiar_espacios(" ".join(self._buffer_titulo))
            self._en_titulo = False
            self._capturando_enlace_titulo = False
        elif tag == "a":
            self._capturando_enlace_titulo = False
        elif self._en_resumen and tag == "p":
            resumen = _limpiar_espacios(" ".join(self._buffer_resumen))
            if len(resumen) >= LONGITUD_MINIMA_RESUMEN:
                self._articulo_actual["resumen"] = resumen
            self._en_resumen = False
        elif tag == "article" and len(self._pila) < self._profundidad_articulo:
            self._en_articulo = False
            if self._articulo_actual["titulo"] and self._articulo_actual["url"]:
                self.items.append(self._articulo_actual)
            self._articulo_actual = None

    def handle_data(self, data):
        if self._omitir_desde is not None or not self._en_articulo:
            return
        texto = data.strip()
        if not texto:
            return
        if self._en_titulo:
            self._buffer_titulo.append(texto)
        elif self._en_resumen:
            self._buffer_resumen.append(texto)


def parsear_listado(html_crudo: str, url_base: str, nombre_fuente: str) -> List[dict]:
    parser = _ParserListadoInfoYungas(url_base)
    parser.feed(html_crudo)
    parser.close()

    return [
        {
            "titulo": item["titulo"],
            "texto": item["resumen"],
            "url": item["url"],
            "fuente": nombre_fuente,
            "fecha": item["fecha"],
            "imagen_url": item["imagen_url"],
        }
        for item in parser.items
    ]


class InfoYungasHTMLCollector(Collector):
    """Collector HTML real de InfoYungas (https://www.infoyungas.com/).

    Requiere acceso saliente a internet; no se ejecuta durante las pruebas
    automáticas, que usan un fixture HTML local en su lugar. No asigna una
    localidad fija: la relevancia geográfica se deriva del contenido de cada
    noticia mediante el clasificador existente.
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
            raise ErrorRecoleccionInfoYungas(
                f"InfoYungas respondió HTTP {error.code} ({error.reason}) al pedir {self.url}"
            ) from error
        except urllib.error.URLError as error:
            raise ErrorRecoleccionInfoYungas(
                f"No se pudo conectar a InfoYungas ({self.url}): {error.reason}"
            ) from error
        html_crudo = contenido.decode("utf-8", errors="replace")
        return parsear_listado(html_crudo, self.url, self.nombre_fuente)
