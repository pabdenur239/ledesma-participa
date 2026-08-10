from abc import ABC, abstractmethod
from typing import Tuple

from ..models import Noticia


class Redactor(ABC):
    @abstractmethod
    def redactar(self, noticia: Noticia) -> Tuple[str, str]:
        """Debe devolver (titulo_preparado, texto_preparado). Implementaciones
        futuras podrán conectar un proveedor de IA; ninguna se conecta aquí."""
        raise NotImplementedError
