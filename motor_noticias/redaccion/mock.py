from typing import Tuple

from ..models import Noticia
from .base import Redactor


class RedactorMock(Redactor):
    """Redacción de prueba sin conexión a ningún proveedor de IA externo."""

    def redactar(self, noticia: Noticia) -> Tuple[str, str]:
        titulo_preparado = noticia.titulo_original.strip()
        texto_preparado = (
            f"{noticia.texto_original.strip()}\n\n"
            "(Nota preparada en modo de prueba, pendiente de redacción editorial.)"
        )
        return titulo_preparado, texto_preparado
