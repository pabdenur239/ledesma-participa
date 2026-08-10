from abc import ABC, abstractmethod
from typing import List


class Collector(ABC):
    @abstractmethod
    def recolectar(self) -> List[dict]:
        """Debe devolver una lista de diccionarios con los campos crudos de cada
        noticia: titulo, texto, url, fuente, fecha."""
        raise NotImplementedError
