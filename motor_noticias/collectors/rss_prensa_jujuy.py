import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Union

from .base import Collector

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "fuentes.json"


def _cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)["prensa_jujuy"]


def _texto(item: ET.Element, etiqueta: str) -> Optional[str]:
    elemento = item.find(etiqueta)
    return elemento.text.strip() if elemento is not None and elemento.text else None


def _quitar_etiquetas_html(texto: str) -> str:
    return re.sub(r"<[^>]+>", " ", texto).strip()


def parsear_rss(contenido: Union[str, bytes], nombre_fuente: str) -> List[dict]:
    raiz = ET.fromstring(contenido)
    noticias = []
    for item in raiz.findall("./channel/item"):
        titulo = _texto(item, "title")
        enlace = _texto(item, "link")
        if not titulo or not enlace:
            continue
        descripcion = _texto(item, "description") or ""
        noticias.append(
            {
                "titulo": titulo,
                "texto": _quitar_etiquetas_html(descripcion),
                "url": enlace,
                "fuente": nombre_fuente,
                "fecha": _texto(item, "pubDate") or "",
            }
        )
    return noticias


class PrensaJujuyRSSCollector(Collector):
    """Collector RSS real de Prensa Jujuy (Gobierno de Jujuy).

    Requiere acceso saliente a internet; no se ejecuta durante las pruebas
    automáticas, que usan un fixture XML local en su lugar.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        nombre_fuente: Optional[str] = None,
        timeout: int = 20,
        config_path: Optional[Path] = None,
    ):
        config = _cargar_config(config_path)
        self.url = url or config["url_rss"]
        self.nombre_fuente = nombre_fuente or config["nombre_fuente"]
        self.timeout = timeout

    def recolectar(self) -> List[dict]:
        with urllib.request.urlopen(self.url, timeout=self.timeout) as respuesta:
            contenido = respuesta.read()
        return parsear_rss(contenido, self.nombre_fuente)
