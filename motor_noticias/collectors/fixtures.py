import json
from pathlib import Path
from typing import List, Optional, Union

from .base import Collector

FIXTURES_PATH_DEFAULT = (
    Path(__file__).resolve().parent.parent.parent / "data" / "fixtures" / "noticias_prueba.json"
)


class FixtureCollector(Collector):
    """Recolector de datos de prueba incluidos en el repositorio.

    Sustituye temporalmente a los futuros recolectores de fuentes reales
    (RSS, scraping, etc.), que no se implementan en esta fase.
    """

    def __init__(self, path: Optional[Union[str, Path]] = None):
        self.path = Path(path) if path else FIXTURES_PATH_DEFAULT

    def recolectar(self) -> List[dict]:
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)
