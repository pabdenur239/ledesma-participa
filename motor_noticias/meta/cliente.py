import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional, Union

from .contenido import ContenidoFacebook

GRAPH_API_VERSION = "v26.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

TIMEOUT_PUBLICACION_SEGUNDOS = 30

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


@dataclass
class ResultadoPublicacionReal:
    dry_run: bool
    page_id: str
    post_id: str
    endpoint_post: str
    texto_post_principal: str
    url_fuente: Optional[str]


class ClienteMetaGraphAPI:
    """Cliente para la Graph API de Meta: publicar el post principal de la
    página, obtener el ID del post creado y publicar sobre él el primer
    comentario.

    dry_run=True (el valor por defecto) nunca hace red: solo arma el
    endpoint y los textos para previsualización, exactamente igual que
    antes de habilitar la publicación real. dry_run=False en
    `publicar_post_principal` hace un POST real, autenticado con
    `Authorization: Bearer`, a `/{page_id}/feed`. La publicación real del
    primer comentario todavía no está implementada: dry_run=False sigue
    informando un error controlado en ese método.
    """

    def __init__(self, page_id: Optional[str] = None, access_token: Optional[str] = None):
        self.page_id = page_id or os.environ.get("META_PAGE_ID") or PAGE_ID_DEFAULT
        self._access_token = access_token or os.environ.get("META_PAGE_ACCESS_TOKEN")

    def tiene_token_configurado(self) -> bool:
        return bool(self._access_token)

    def publicar_post_principal(
        self,
        contenido: ContenidoFacebook,
        dry_run: bool = True,
        url_fuente: Optional[str] = None,
    ) -> Union[ResultadoDryRun, ResultadoPublicacionReal]:
        endpoint = f"{GRAPH_API_BASE}/{self.page_id}/feed"
        if dry_run:
            return ResultadoDryRun(
                dry_run=True,
                page_id=self.page_id,
                endpoint_post=endpoint,
                endpoint_comentario="",
                texto_post_principal=contenido.post_principal,
                texto_primer_comentario=contenido.primer_comentario,
            )
        return self._publicar_real(endpoint, contenido, url_fuente)

    def _publicar_real(
        self, endpoint: str, contenido: ContenidoFacebook, url_fuente: Optional[str]
    ) -> ResultadoPublicacionReal:
        if not self._access_token:
            raise ErrorClienteMeta(
                "No hay token configurado (META_PAGE_ACCESS_TOKEN): no se puede publicar."
            )

        datos = {"message": contenido.post_principal}
        if url_fuente:
            datos["link"] = url_fuente

        peticion = urllib.request.Request(
            endpoint,
            data=urllib.parse.urlencode(datos).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(peticion, timeout=TIMEOUT_PUBLICACION_SEGUNDOS) as respuesta:
                cuerpo = json.loads(respuesta.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise ErrorClienteMeta(
                f"Meta respondió HTTP {error.code} al publicar en {endpoint}."
            ) from None
        except urllib.error.URLError as error:
            raise ErrorClienteMeta(
                f"No se pudo conectar a la Graph API en {endpoint}: {error.reason}."
            ) from None
        except (TimeoutError, json.JSONDecodeError) as error:
            raise ErrorClienteMeta(
                f"Respuesta inválida o tiempo de espera agotado al publicar en {endpoint}."
            ) from None

        post_id = cuerpo.get("id")
        if not post_id:
            raise ErrorClienteMeta("Meta no devolvió un ID de publicación válido.")

        return ResultadoPublicacionReal(
            dry_run=False,
            page_id=self.page_id,
            post_id=post_id,
            endpoint_post=endpoint,
            texto_post_principal=contenido.post_principal,
            url_fuente=url_fuente,
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
