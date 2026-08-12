import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

from .base import Collector
from .rss_arc_nacional import LIMITE_ITEMS_DEFAULT, parsear_rss_arc

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "fuentes.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LedesmaParticipa/1.0; RSS Reader)",
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
}


class ErrorRecoleccionLaNacion(RuntimeError):
    """Error controlado al recolectar el RSS de La Nación."""


def _cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)["la_nacion"]


class LaNacionRSSCollector(Collector):
    """Collector RSS real de La Nación (Arc XP: mismo dialecto que Infobae).

    Fuente nacional: no asigna una localidad ni un territorio fijo, la
    clasificación territorial de cada noticia la decide el clasificador
    existente (motor_noticias/territorio.py) sin modificarlo. Requiere
    acceso saliente a internet; no se ejecuta durante las pruebas
    automáticas, que usan un fixture XML local en su lugar.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        nombre_fuente: Optional[str] = None,
        timeout: int = 20,
        limite: int = LIMITE_ITEMS_DEFAULT,
        config_path: Optional[Path] = None,
    ):
        config = _cargar_config(config_path)
        self.url = url or config["url"]
        self.nombre_fuente = nombre_fuente or config["nombre_fuente"]
        self.timeout = timeout
        self.limite = limite

    def recolectar(self) -> List[dict]:
        peticion = urllib.request.Request(self.url, headers=HEADERS)
        try:
            with urllib.request.urlopen(peticion, timeout=self.timeout) as respuesta:
                contenido = respuesta.read()
        except urllib.error.HTTPError as error:
            raise ErrorRecoleccionLaNacion(
                f"La Nación respondió HTTP {error.code} ({error.reason}) al pedir {self.url}"
            ) from error
        except urllib.error.URLError as error:
            raise ErrorRecoleccionLaNacion(
                f"No se pudo conectar a La Nación ({self.url}): {error.reason}"
            ) from error
        return parsear_rss_arc(contenido, self.nombre_fuente, limite=self.limite)
