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

# El sitio real es una página AMP sin autodiscovery de RSS/Atom en el <head>
# (su página "RSS" en realidad lista redes sociales — RRSS —, no feeds; se
# descartó ese camino con evidencia real). Cada noticia es un
# <article class="nota ...">, con el título en
# <h2 class="nota__titulo-item"><a>, un resumen opcional en
# <div class="nota__introduccion"><a> (no todas las variantes de tarjeta lo
# muestran), y una imagen opcional (tampoco todas las variantes la incluyen)
# en el primer <amp-img src="..."> del artículo. El sitio no expone un campo
# de fecha aparte, pero el propio permalink de cada nota incluye la fecha y
# hora de publicación de forma explícita y estable
# (p. ej. /seccion/2026-8-12-13-21-0-titulo-slug); se extrae de ahí, nunca
# inferida de texto relativo.
TAGS_EXCLUIDOS = {"nav", "header", "footer", "aside", "script", "style", "noscript", "form", "iframe"}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img",
    "input", "link", "meta", "param", "source", "track", "wbr",
}
LONGITUD_MINIMA_RESUMEN = 15
PATRON_FECHA_EN_URL = re.compile(r"/(\d{4})-(\d{1,2})-(\d{1,2})-(\d{1,2})-(\d{1,2})-(\d{1,2})-")


class ErrorRecoleccionTribunoJujuy(RuntimeError):
    """Error controlado al recolectar el listado de El Tribuno de Jujuy."""


def _cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)["tribuno_jujuy"]


def _limpiar_espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _atributo(attrs, nombre):
    for clave, valor in attrs:
        if clave == nombre:
            return valor
    return None


def _fecha_desde_url(url: Optional[str]) -> str:
    if not url:
        return ""
    coincidencia = PATRON_FECHA_EN_URL.search(url)
    if not coincidencia:
        return ""
    anio, mes, dia, hora, minuto, segundo = (int(g) for g in coincidencia.groups())
    return f"{anio:04d}-{mes:02d}-{dia:02d}T{hora:02d}:{minuto:02d}:{segundo:02d}"


class _ParserListadoTribunoJujuy(html.parser.HTMLParser):
    """Recorre el listado real de El Tribuno de Jujuy: cada noticia es un
    <article class="nota ...">, con título y resumen opcional anidados. La
    imagen (cuando la variante de tarjeta la incluye) es el primer
    <amp-img src="..."> del artículo."""

    def __init__(self, url_base: str):
        super().__init__(convert_charrefs=True)
        self.url_base = url_base
        self.items: List[dict] = []

        self._pila: List[str] = []
        self._omitir_desde: Optional[int] = None

        self._en_nota = False
        self._profundidad_nota = 0
        self._nota_actual: Optional[dict] = None
        self._imagen_capturada = False

        self._en_titulo = False
        self._profundidad_titulo = 0
        self._buffer_titulo: List[str] = []

        self._en_resumen = False
        self._profundidad_resumen = 0
        self._buffer_resumen: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            return
        self._pila.append(tag)

        if self._omitir_desde is not None:
            return
        if tag in TAGS_EXCLUIDOS:
            self._omitir_desde = len(self._pila)
            return

        clase = _atributo(attrs, "class") or ""
        clases = clase.split()

        if not self._en_nota:
            if tag == "article" and "nota" in clases:
                self._en_nota = True
                self._profundidad_nota = len(self._pila)
                self._nota_actual = {
                    "titulo": "",
                    "url": None,
                    "resumen": "",
                    "imagen_url": None,
                }
                self._imagen_capturada = False
                self._en_titulo = False
                self._en_resumen = False
            return

        if tag == "h2" and "nota__titulo-item" in clases and not self._en_titulo and not self._nota_actual["titulo"]:
            self._en_titulo = True
            self._profundidad_titulo = len(self._pila)
            self._buffer_titulo = []
        elif (
            tag == "div"
            and "nota__introduccion" in clases
            and not self._en_resumen
            and not self._nota_actual["resumen"]
        ):
            self._en_resumen = True
            self._profundidad_resumen = len(self._pila)
            self._buffer_resumen = []
        elif tag == "a" and self._en_titulo and not self._nota_actual["url"]:
            href = _atributo(attrs, "href")
            if href:
                self._nota_actual["url"] = urljoin(self.url_base, href)
        elif tag == "amp-img" and not self._imagen_capturada:
            src = _atributo(attrs, "src")
            if src:
                self._nota_actual["imagen_url"] = urljoin(self.url_base, src)
                self._imagen_capturada = True

    def handle_endtag(self, tag):
        if not self._pila or self._pila[-1] != tag:
            return
        self._pila.pop()

        if self._omitir_desde is not None:
            if len(self._pila) < self._omitir_desde:
                self._omitir_desde = None
            return

        if not self._en_nota:
            return

        if self._en_titulo and len(self._pila) < self._profundidad_titulo:
            self._nota_actual["titulo"] = _limpiar_espacios(" ".join(self._buffer_titulo))
            self._en_titulo = False
        elif self._en_resumen and len(self._pila) < self._profundidad_resumen:
            resumen = _limpiar_espacios(" ".join(self._buffer_resumen))
            if len(resumen) >= LONGITUD_MINIMA_RESUMEN:
                self._nota_actual["resumen"] = resumen
            self._en_resumen = False
        elif tag == "article" and len(self._pila) < self._profundidad_nota:
            self._en_nota = False
            if self._nota_actual["titulo"] and self._nota_actual["url"]:
                self.items.append(self._nota_actual)
            self._nota_actual = None

    def handle_data(self, data):
        if self._omitir_desde is not None or not self._en_nota:
            return
        texto = data.strip()
        if not texto:
            return
        if self._en_titulo:
            self._buffer_titulo.append(texto)
        elif self._en_resumen:
            self._buffer_resumen.append(texto)


def parsear_listado(html_crudo: str, url_base: str, nombre_fuente: str) -> List[dict]:
    parser = _ParserListadoTribunoJujuy(url_base)
    parser.feed(html_crudo)
    parser.close()

    return [
        {
            "titulo": item["titulo"],
            "texto": item["resumen"],
            "url": item["url"],
            "fuente": nombre_fuente,
            "fecha": _fecha_desde_url(item["url"]),
            "imagen_url": item["imagen_url"],
        }
        for item in parser.items
    ]


class TribunoJujuyHTMLCollector(Collector):
    """Collector HTML real de El Tribuno de Jujuy (https://eltribunodejujuy.com/).

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
            raise ErrorRecoleccionTribunoJujuy(
                f"El Tribuno de Jujuy respondió HTTP {error.code} ({error.reason}) al pedir {self.url}"
            ) from error
        except urllib.error.URLError as error:
            raise ErrorRecoleccionTribunoJujuy(
                f"No se pudo conectar a El Tribuno de Jujuy ({self.url}): {error.reason}"
            ) from error
        html_crudo = contenido.decode("utf-8", errors="replace")
        return parsear_listado(html_crudo, self.url, self.nombre_fuente)
