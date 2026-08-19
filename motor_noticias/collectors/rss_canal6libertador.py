import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Union

from .base import Collector

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "fuentes.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LedesmaParticipa/1.0; RSS Reader)",
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
}

PATRON_IMG_SRC = re.compile(r'<img[^>]*\bsrc="([^"]+)"', re.IGNORECASE)
PATRON_BOILERPLATE_WORDPRESS = re.compile(
    r"<p>\s*La entrada.*?se public[oó] primero en.*?</p>\s*$",
    re.IGNORECASE | re.DOTALL,
)


class ErrorRecoleccionCanal6Libertador(RuntimeError):
    """Error controlado al recolectar el RSS de Canal 6 Libertador."""


def _cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)["canal6_libertador"]


def _texto(item: ET.Element, etiqueta: str) -> Optional[str]:
    elemento = item.find(etiqueta)
    return elemento.text.strip() if elemento is not None and elemento.text else None


def _limpiar_espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _quitar_etiquetas_html(texto: str) -> str:
    return _limpiar_espacios(re.sub(r"<[^>]+>", " ", texto))


def parsear_rss(contenido: Union[str, bytes], nombre_fuente: str) -> List[dict]:
    """Parsea el feed RSS real de Canal 6 Libertador (WordPress estándar,
    mismo formato que Jujuy al día: ver rss_jujuyaldia.py). La imagen no
    viene en un <enclosure> separado: está embebida como un <img src="...">
    al principio del HTML de <description>. La descripción también trae,
    al final, el párrafo estándar de WordPress "La entrada X se publicó
    primero en Y." que se descarta antes de limpiar el resto del HTML."""
    raiz = ET.fromstring(contenido)
    noticias = []
    for item in raiz.findall("./channel/item"):
        titulo = _texto(item, "title")
        enlace = _texto(item, "link")
        if not titulo or not enlace:
            continue
        descripcion_html = _texto(item, "description") or ""
        coincidencia_imagen = PATRON_IMG_SRC.search(descripcion_html)
        imagen_url = coincidencia_imagen.group(1) if coincidencia_imagen else None
        descripcion_sin_boilerplate = PATRON_BOILERPLATE_WORDPRESS.sub("", descripcion_html)
        noticias.append(
            {
                "titulo": titulo,
                "texto": _quitar_etiquetas_html(descripcion_sin_boilerplate),
                "url": enlace,
                "fuente": nombre_fuente,
                "fecha": _texto(item, "pubDate") or "",
                "imagen_url": imagen_url,
            }
        )
    return noticias


class Canal6LibertadorRSSCollector(Collector):
    """Collector RSS real de Canal 6 Libertador (https://canalseis.com.ar/feed/).

    Canal de TV local de Libertador General San Martín: no asigna una
    localidad fija, la relevancia geográfica de cada noticia se deriva de
    su contenido con el clasificador existente. Requiere acceso saliente a
    internet; no se ejecuta durante las pruebas automáticas, que usan un
    fixture XML local en su lugar.
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
            raise ErrorRecoleccionCanal6Libertador(
                f"Canal 6 Libertador respondió HTTP {error.code} ({error.reason}) al pedir {self.url}"
            ) from error
        except urllib.error.URLError as error:
            raise ErrorRecoleccionCanal6Libertador(
                f"No se pudo conectar a Canal 6 Libertador ({self.url}): {error.reason}"
            ) from error
        return parsear_rss(contenido, self.nombre_fuente)
