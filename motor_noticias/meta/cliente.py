import os
from dataclasses import dataclass
from typing import Optional

from .contenido import ContenidoFacebook

GRAPH_API_VERSION = "v19.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Page ID de "Ledesma Participa": dato público, no es secreto. El token de
# acceso, en cambio, nunca tiene valor por defecto: solo puede venir de la
# variable de entorno META_PAGE_ACCESS_TOKEN (ver .env.example).
PAGE_ID_DEFAULT = "1174992842373499"


class ErrorClienteMeta(RuntimeError):
    """Error controlado del cliente de la Graph API de Meta."""


@dataclass
class ResultadoDryRun:
    dry_run: bool
    page_id: str
    endpoint_post: str
    endpoint_comentario: str
    texto_post_principal: str
    texto_primer_comentario: str


class ClienteMetaGraphAPI:
    """Cliente mínimo, preparado pero no habilitado, para la Graph API de
    Meta: publicar el post principal de la página, obtener el ID del post
    creado y publicar sobre él el primer comentario.

    En esta fase no existe ningún camino de código que envíe una petición
    real a Meta: dry_run=True (el valor por defecto) es el único modo
    implementado. Pasar dry_run=False informa un error controlado en lugar
    de intentar publicar.
    """

    def __init__(self, page_id: Optional[str] = None, access_token: Optional[str] = None):
        self.page_id = page_id or os.environ.get("META_PAGE_ID") or PAGE_ID_DEFAULT
        self._access_token = access_token or os.environ.get("META_PAGE_ACCESS_TOKEN")

    def tiene_token_configurado(self) -> bool:
        return bool(self._access_token)

    def publicar_post_principal(
        self, contenido: ContenidoFacebook, dry_run: bool = True
    ) -> ResultadoDryRun:
        endpoint = f"{GRAPH_API_BASE}/{self.page_id}/feed"
        if not dry_run:
            raise ErrorClienteMeta(
                "La publicación real a Meta no está habilitada en esta fase del proyecto."
            )
        return ResultadoDryRun(
            dry_run=True,
            page_id=self.page_id,
            endpoint_post=endpoint,
            endpoint_comentario="",
            texto_post_principal=contenido.post_principal,
            texto_primer_comentario=contenido.primer_comentario,
        )

    def publicar_primer_comentario(
        self, post_id: str, contenido: ContenidoFacebook, dry_run: bool = True
    ) -> ResultadoDryRun:
        endpoint = f"{GRAPH_API_BASE}/{post_id}/comments"
        if not dry_run:
            raise ErrorClienteMeta(
                "La publicación real a Meta no está habilitada en esta fase del proyecto."
            )
        return ResultadoDryRun(
            dry_run=True,
            page_id=self.page_id,
            endpoint_post="",
            endpoint_comentario=endpoint,
            texto_post_principal=contenido.post_principal,
            texto_primer_comentario=contenido.primer_comentario,
        )
