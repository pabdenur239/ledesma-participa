import json
from pathlib import Path
from typing import List, Optional

from ._rss_generico import ErrorRecoleccionRSSGenerico, obtener_rss, parsear_rss_generico
from .base import Collector

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "fuentes.json"
CATEGORIA_TEMATICA = "salud"


def _cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)["medlineplus_es"]


class MedlinePlusEsRSSCollector(Collector):
    """Collector RSS real de MedlinePlus en español, feed general "Qué hay
    de nuevo" (https://medlineplus.gov/spanish/feeds/whatsnew.xml).

    Fuente institucional oficial de salud pública (Biblioteca Nacional de
    Medicina de EE.UU., NIH). No asigna localidad. Requiere acceso saliente
    a internet; no se ejecuta durante las pruebas automáticas, que usan un
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
        try:
            contenido = obtener_rss(self.url, timeout=self.timeout)
        except ErrorRecoleccionRSSGenerico as error:
            raise ErrorRecoleccionRSSGenerico(f"MedlinePlus en español: {error}") from error
        return parsear_rss_generico(
            contenido, self.nombre_fuente, CATEGORIA_TEMATICA, quitar_boilerplate_wordpress=False
        )
