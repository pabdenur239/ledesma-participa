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


class ErrorRecoleccionTodoJujuy(RuntimeError):
    """Error controlado al recolectar el RSS de TodoJujuy."""


def _cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)["todojujuy"]


def _texto(item: ET.Element, etiqueta: str) -> Optional[str]:
    elemento = item.find(etiqueta)
    return elemento.text.strip() if elemento is not None and elemento.text else None


def _quitar_etiquetas_html(texto: str) -> str:
    return re.sub(r"<[^>]+>", " ", texto).strip()


def parsear_rss(contenido: Union[str, bytes], nombre_fuente: str) -> List[dict]:
    """Parsea el feed RSS real de TodoJujuy. La descripción ya viene como
    texto plano (sin HTML embebido) y cada item trae la imagen en
    <enclosure url="...">, no en la descripción."""
    raiz = ET.fromstring(contenido)
    noticias = []
    for item in raiz.findall("./channel/item"):
        titulo = _texto(item, "title")
        enlace = _texto(item, "link")
        if not titulo or not enlace:
            continue
        descripcion = _texto(item, "description") or ""
        enclosure = item.find("enclosure")
        imagen_url = enclosure.get("url") if enclosure is not None else None
        noticias.append(
            {
                "titulo": titulo,
                "texto": _quitar_etiquetas_html(descripcion),
                "url": enlace,
                "fuente": nombre_fuente,
                "fecha": _texto(item, "pubDate") or "",
                "imagen_url": imagen_url or None,
            }
        )
    return noticias


class TodoJujuyRSSCollector(Collector):
    """Collector RSS real de TodoJujuy (canal "Jujuy").

    Fuente provincial: no asigna una localidad fija, la relevancia
    geográfica de cada noticia se deriva de su contenido con el
    clasificador existente. Requiere acceso saliente a internet; no se
    ejecuta durante las pruebas automáticas, que usan un fixture XML
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
            raise ErrorRecoleccionTodoJujuy(
                f"TodoJujuy respondió HTTP {error.code} ({error.reason}) al pedir {self.url}"
            ) from error
        except urllib.error.URLError as error:
            raise ErrorRecoleccionTodoJujuy(
                f"No se pudo conectar a TodoJujuy ({self.url}): {error.reason}"
            ) from error
        return parsear_rss(contenido, self.nombre_fuente)
