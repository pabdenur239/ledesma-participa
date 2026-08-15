import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .contenido import ContenidoFacebook

GRAPH_API_VERSION = "v19.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Page ID de "Ledesma Participa": dato público, no es secreto. El token de
# acceso, en cambio, nunca tiene valor por defecto: solo puede venir de la
# variable de entorno META_PAGE_ACCESS_TOKEN (ver .env.example). Lo mismo
# para META_IG_USER_ID (ID de la cuenta de Instagram profesional vinculada
# a la página, necesario para publicar en Instagram).
PAGE_ID_DEFAULT = "1174992842373499"
TIMEOUT_DEFAULT_SEGUNDOS = 30


class ErrorClienteMeta(RuntimeError):
    """Error controlado del cliente de la Graph API de Meta. El mensaje
    nunca incluye el token de acceso: no forma parte de las respuestas de
    Meta ni se interpola en ningún mensaje de error de este módulo."""


@dataclass
class ResultadoDryRun:
    dry_run: bool
    page_id: str
    endpoint_post: str
    endpoint_comentario: str
    texto_post_principal: str
    texto_primer_comentario: str


@dataclass
class ResultadoFotoFacebook:
    """`photo_id` es el ID del objeto foto (el que hace falta para
    consultar después su URL pública vía `obtener_url_publica_foto`);
    `post_id` es el ID de la publicación en el muro de la página (el que
    hace falta para comentarla). Meta los devuelve como dos campos
    distintos (`id` y `post_id`) en la misma respuesta de /photos."""

    photo_id: str
    post_id: str


def _resultado_foto_desde_respuesta(resultado: dict) -> "ResultadoFotoFacebook":
    photo_id = resultado.get("id")
    post_id = resultado.get("post_id") or photo_id
    if not photo_id or not post_id:
        raise ErrorClienteMeta("Meta no devolvió un ID de publicación de Facebook.")
    return ResultadoFotoFacebook(photo_id=photo_id, post_id=post_id)


def _multipart(campos: dict, archivo: Optional[Path] = None, nombre_campo_archivo: str = "source"):
    """Arma un cuerpo multipart/form-data a mano (stdlib puro, sin
    dependencias nuevas) para subir texto + opcionalmente un archivo binario
    a la Graph API de Meta."""
    boundary = uuid.uuid4().hex
    partes = []
    for clave, valor in campos.items():
        if valor is None:
            continue
        partes.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{clave}"\r\n\r\n{valor}\r\n'.encode("utf-8")
        )
    if archivo is not None:
        tipo = mimetypes.guess_type(str(archivo))[0] or "application/octet-stream"
        cabecera = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{nombre_campo_archivo}"; '
            f'filename="{archivo.name}"\r\nContent-Type: {tipo}\r\n\r\n'
        ).encode("utf-8")
        partes.append(cabecera + archivo.read_bytes() + b"\r\n")
    partes.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(partes), f"multipart/form-data; boundary={boundary}"


class ClienteMetaGraphAPI:
    """Cliente para la Graph API de Meta: publicar el post principal de la
    página, obtener el ID del post creado y publicar sobre él el primer
    comentario; y (nuevo) publicar realmente en Facebook (foto + caption) e
    Instagram (contenedor de media + publicación).

    `publicar_post_principal` / `publicar_primer_comentario` (post de solo
    texto) se conservan tal como estaban: dry_run=True es su único modo
    implementado, dry_run=False siempre informa un error controlado. Nunca
    se usan para publicar de verdad — el contenido real de este proyecto
    siempre lleva una imagen adjunta (placa o foto original), por eso la
    publicación real vive en los métodos nuevos `publicar_foto_facebook` /
    `publicar_comentario_facebook` / `publicar_instagram`, explícitos y
    separados para no reabrir ni cambiar el comportamiento ya probado de los
    métodos existentes."""

    def __init__(
        self,
        page_id: Optional[str] = None,
        access_token: Optional[str] = None,
        ig_user_id: Optional[str] = None,
        timeout: int = TIMEOUT_DEFAULT_SEGUNDOS,
        urlopen=urllib.request.urlopen,
    ):
        self.page_id = page_id or os.environ.get("META_PAGE_ID") or PAGE_ID_DEFAULT
        self._access_token = access_token or os.environ.get("META_PAGE_ACCESS_TOKEN")
        self.ig_user_id = ig_user_id or os.environ.get("META_IG_USER_ID")
        self.timeout = timeout
        self._urlopen = urlopen

    def tiene_token_configurado(self) -> bool:
        return bool(self._access_token)

    def tiene_instagram_configurado(self) -> bool:
        return bool(self.ig_user_id)

    def publicar_post_principal(
        self, contenido: ContenidoFacebook, dry_run: bool = True
    ) -> ResultadoDryRun:
        endpoint = f"{GRAPH_API_BASE}/{self.page_id}/feed"
        if not dry_run:
            raise ErrorClienteMeta(
                "La publicación de solo texto no está habilitada: el contenido real siempre "
                "se publica con imagen (ver publicar_foto_facebook)."
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
                "Este método de comentario de vista previa no está habilitado para publicación "
                "real (ver publicar_comentario_facebook)."
            )
        return ResultadoDryRun(
            dry_run=True,
            page_id=self.page_id,
            endpoint_post="",
            endpoint_comentario=endpoint,
            texto_post_principal=contenido.post_principal,
            texto_primer_comentario=contenido.primer_comentario,
        )

    # -- Publicación real ---------------------------------------------------

    def _ejecutar_peticion(self, peticion: urllib.request.Request) -> dict:
        try:
            with self._urlopen(peticion, timeout=self.timeout) as respuesta:
                crudo = respuesta.read()
        except urllib.error.HTTPError as error:
            detalle = error.read().decode("utf-8", errors="replace")[:500]
            raise ErrorClienteMeta(f"Meta respondió HTTP {error.code}: {detalle}") from error
        except urllib.error.URLError as error:
            raise ErrorClienteMeta(f"No se pudo conectar con la Graph API de Meta: {error.reason}") from error
        except TimeoutError as error:
            raise ErrorClienteMeta("Tiempo de espera agotado al conectar con la Graph API de Meta") from error

        try:
            resultado = json.loads(crudo)
        except json.JSONDecodeError as error:
            raise ErrorClienteMeta("La Graph API de Meta devolvió una respuesta que no es JSON válido") from error

        if isinstance(resultado, dict) and "error" in resultado:
            mensaje = (resultado.get("error") or {}).get("message", "error desconocido")
            raise ErrorClienteMeta(f"Meta rechazó la solicitud: {mensaje}")
        return resultado

    def _peticion_json(self, url: str, cuerpo: bytes, content_type: str) -> dict:
        peticion = urllib.request.Request(
            url, data=cuerpo, headers={"Content-Type": content_type}, method="POST"
        )
        return self._ejecutar_peticion(peticion)

    def _peticion_get_json(self, url: str, parametros: dict) -> dict:
        query = urllib.parse.urlencode(parametros)
        peticion = urllib.request.Request(f"{url}?{query}", method="GET")
        return self._ejecutar_peticion(peticion)

    def publicar_foto_facebook(
        self, contenido: ContenidoFacebook, ruta_imagen: Path, dry_run: bool = True
    ):
        """Publica el post principal de Facebook como foto con caption
        (adjuntando el archivo directamente vía multipart: no necesita una
        URL pública, a diferencia de Instagram). Devuelve el post_id real
        que Meta confirmó, o un ResultadoDryRun si dry_run=True."""
        endpoint = f"{GRAPH_API_BASE}/{self.page_id}/photos"
        if dry_run:
            return ResultadoDryRun(
                dry_run=True,
                page_id=self.page_id,
                endpoint_post=endpoint,
                endpoint_comentario="",
                texto_post_principal=contenido.post_principal,
                texto_primer_comentario=contenido.primer_comentario,
            )
        if not self.tiene_token_configurado():
            raise ErrorClienteMeta("Falta META_PAGE_ACCESS_TOKEN: no se puede publicar en Facebook.")

        cuerpo, content_type = _multipart(
            {
                "caption": contenido.post_principal,
                "published": "true",
                "access_token": self._access_token,
            },
            Path(ruta_imagen),
        )
        resultado = self._peticion_json(endpoint, cuerpo, content_type)
        return _resultado_foto_desde_respuesta(resultado)

    def publicar_foto_facebook_por_url(
        self, contenido: ContenidoFacebook, imagen_url: str, dry_run: bool = True
    ):
        """Igual que publicar_foto_facebook, pero para una imagen ya alojada
        en una URL remota (por ejemplo, la foto original de la fuente): se
        le pide a Meta que la busque él mismo (parámetro `url`), sin subir
        ningún archivo."""
        endpoint = f"{GRAPH_API_BASE}/{self.page_id}/photos"
        if dry_run:
            return ResultadoDryRun(
                dry_run=True,
                page_id=self.page_id,
                endpoint_post=endpoint,
                endpoint_comentario="",
                texto_post_principal=contenido.post_principal,
                texto_primer_comentario=contenido.primer_comentario,
            )
        if not self.tiene_token_configurado():
            raise ErrorClienteMeta("Falta META_PAGE_ACCESS_TOKEN: no se puede publicar en Facebook.")

        cuerpo, content_type = _multipart(
            {
                "url": imagen_url,
                "caption": contenido.post_principal,
                "published": "true",
                "access_token": self._access_token,
            }
        )
        resultado = self._peticion_json(endpoint, cuerpo, content_type)
        return _resultado_foto_desde_respuesta(resultado)

    def obtener_url_publica_foto(self, photo_id: str) -> str:
        """Consulta la Graph API para obtener la URL pública (CDN) de una
        foto ya subida a Facebook: `images` devuelve las distintas
        resoluciones disponibles, ordenadas de mayor a menor. Se usa esa
        misma URL para publicar en Instagram, sin necesitar hosting propio:
        Meta ya aloja la imagen apenas se publica en Facebook."""
        if not self.tiene_token_configurado():
            raise ErrorClienteMeta("Falta META_PAGE_ACCESS_TOKEN: no se puede consultar la foto en Meta.")

        resultado = self._peticion_get_json(
            f"{GRAPH_API_BASE}/{photo_id}", {"fields": "images", "access_token": self._access_token}
        )
        imagenes = resultado.get("images") or []
        url = imagenes[0].get("source") if imagenes else None
        if not url:
            raise ErrorClienteMeta(
                "Meta no devolvió una URL pública utilizable para la foto publicada en Facebook."
            )
        return url

    def publicar_comentario_facebook(self, post_id: str, texto: str, dry_run: bool = True):
        endpoint = f"{GRAPH_API_BASE}/{post_id}/comments"
        if dry_run:
            return ResultadoDryRun(
                dry_run=True,
                page_id=self.page_id,
                endpoint_post="",
                endpoint_comentario=endpoint,
                texto_post_principal="",
                texto_primer_comentario=texto,
            )
        if not self.tiene_token_configurado():
            raise ErrorClienteMeta("Falta META_PAGE_ACCESS_TOKEN: no se puede comentar en Facebook.")

        cuerpo, content_type = _multipart({"message": texto, "access_token": self._access_token})
        resultado = self._peticion_json(endpoint, cuerpo, content_type)
        comment_id = resultado.get("id")
        if not comment_id:
            raise ErrorClienteMeta("Meta no devolvió un ID de comentario de Facebook.")
        return comment_id

    def publicar_instagram(self, caption: str, imagen_url: Optional[str], dry_run: bool = True):
        """Publica en Instagram con el flujo oficial de dos pasos de la
        Graph API: crea un contenedor de media (requiere una `image_url`
        públicamente accesible: Instagram, a diferencia de Facebook, no
        admite adjuntar el archivo directamente) y lo publica. Devuelve el
        media_id real que Meta confirmó, o un ResultadoDryRun si dry_run=True."""
        endpoint_media = f"{GRAPH_API_BASE}/{self.ig_user_id}/media"
        endpoint_publish = f"{GRAPH_API_BASE}/{self.ig_user_id}/media_publish"
        if dry_run:
            return ResultadoDryRun(
                dry_run=True,
                page_id=self.ig_user_id or "",
                endpoint_post=endpoint_media,
                endpoint_comentario=endpoint_publish,
                texto_post_principal=caption,
                texto_primer_comentario="",
            )
        if not self.tiene_token_configurado():
            raise ErrorClienteMeta("Falta META_PAGE_ACCESS_TOKEN: no se puede publicar en Instagram.")
        if not self.tiene_instagram_configurado():
            raise ErrorClienteMeta("Falta META_IG_USER_ID: no se puede publicar en Instagram.")
        if not imagen_url:
            raise ErrorClienteMeta(
                "Falta una URL pública de imagen para Instagram (no admite adjuntar el archivo "
                "directamente como Facebook)."
            )

        cuerpo_media, tipo_media = _multipart(
            {"image_url": imagen_url, "caption": caption, "access_token": self._access_token}
        )
        contenedor = self._peticion_json(endpoint_media, cuerpo_media, tipo_media)
        creation_id = contenedor.get("id")
        if not creation_id:
            raise ErrorClienteMeta("Meta no devolvió un ID de contenedor de Instagram.")

        cuerpo_publish, tipo_publish = _multipart(
            {"creation_id": creation_id, "access_token": self._access_token}
        )
        publicado = self._peticion_json(endpoint_publish, cuerpo_publish, tipo_publish)
        media_id = publicado.get("id")
        if not media_id:
            raise ErrorClienteMeta("Meta no devolvió un ID de publicación de Instagram.")
        return media_id
