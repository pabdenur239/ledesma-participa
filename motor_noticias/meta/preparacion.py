from typing import List, Optional

from ..models import RevisionEstado
from .contenido import ContenidoFacebook, generar_contenido_facebook


class ErrorPreparacionFacebook(RuntimeError):
    """Error controlado al preparar una publicación de Facebook."""


def preparar_publicacion(
    noticia: dict,
    dry_run: bool = True,
    incluir_menciones: Optional[bool] = None,
    menciones: Optional[List[str]] = None,
) -> ContenidoFacebook:
    """Punto de entrada único para preparar una publicación de Facebook.

    Reglas obligatorias, sin excepción:
    - Solo se puede preparar (ni siquiera en DRY RUN) una noticia con
      revision_estado == 'aprobada'.
    - Si la noticia requiere revisión política/institucional
      (requiere_revision_especial == true), solo se permite DRY RUN;
      cualquier intento de publicación real (dry_run=False) se rechaza.
    """
    if noticia.get("revision_estado") != RevisionEstado.APROBADA.value:
        raise ErrorPreparacionFacebook(
            "Solo se puede preparar una publicación de Facebook para noticias "
            "con revision_estado = 'aprobada'."
        )

    if noticia.get("requiere_revision_especial") and not dry_run:
        raise ErrorPreparacionFacebook(
            "Esta noticia requiere revisión política/institucional obligatoria: "
            "solo se permite previsualización en modo DRY RUN, nunca publicación "
            "automática."
        )

    return generar_contenido_facebook(
        noticia, incluir_menciones=incluir_menciones, menciones=menciones
    )
