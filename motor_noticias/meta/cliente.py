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


def _photo_id_desde_respuesta_no_publicada(resultado: dict) -> str:
    photo_id = resultado.get("id")
    if not photo_id:
        raise ErrorClienteMeta("Meta no devolvió un ID de foto al subirla sin publicar.")
    return photo_id


def _post_id_desde_respuesta_feed(resultado: dict) -> str:
    post_id = resultado.get("id")
    if not post_id:
        raise ErrorClienteMeta("Meta no devolvió un ID de publicación de Facebook.")
    return post_id


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
    métodos existentes.

    `publicar_foto_facebook` / `publicar_foto_facebook_por_url` publican en
    dos pasos: suben la imagen sin publicar (`published=false` a
    `/{page_id}/photos`, así no queda como post propio) y recién después
    crean el post real en `/{page_id}/feed` con `message` y esa foto
    referenciada por `attached_media`. Un post creado directo en
    `/{page_id}/photos` (con `published=true`) queda como objeto Photo y no
    como un post de muro genuino: Meta le da una distribución distinta y no
    se ve igual para visitantes no administradores de la Página, aunque el
    objeto exista y `is_hidden` sea `false`."""

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

    def _crear_post_feed_con_foto(
        self, endpoint_post: str, mensaje: str, photo_id: str
    ) -> "ResultadoFotoFacebook":
        """Segundo paso de la publicación real: crea el post de muro
        genuino en `/{page_id}/feed`, con el texto completo en `message` y
        la foto ya subida (sin publicar) referenciada por `attached_media`.
        Este es el post que Meta distribuye igual que uno cargado a mano
        desde la interfaz de Facebook."""
        cuerpo, content_type = _multipart(
            {
                "message": mensaje,
                "attached_media[0]": json.dumps({"media_fbid": photo_id}),
                "access_token": self._access_token,
            }
        )
        resultado = self._peticion_json(endpoint_post, cuerpo, content_type)
        post_id = _post_id_desde_respuesta_feed(resultado)
        return ResultadoFotoFacebook(photo_id=photo_id, post_id=post_id)

    def _subir_foto_sin_publicar(self, endpoint_foto: str, ruta_imagen: Path) -> str:
        """Paso compartido de subida en dos pasos (foto `published=false`,
        sin adjuntar archivo remoto): lo usan tanto `publicar_foto_facebook`
        (que después la referencia en un post de `/feed`) como
        `alojar_imagen_para_story` (que nunca crea ningún post — solo
        necesita la URL de CDN que Meta le asigna a la foto para poder
        publicar la Story real en Instagram)."""
        if not self.tiene_token_configurado():
            raise ErrorClienteMeta("Falta META_PAGE_ACCESS_TOKEN: no se puede subir la imagen a Meta.")

        cuerpo_foto, content_type_foto = _multipart(
            {
                "published": "false",
                "access_token": self._access_token,
            },
            Path(ruta_imagen),
        )
        resultado_foto = self._peticion_json(endpoint_foto, cuerpo_foto, content_type_foto)
        return _photo_id_desde_respuesta_no_publicada(resultado_foto)

    def publicar_foto_facebook(
        self, contenido: ContenidoFacebook, ruta_imagen: Path, dry_run: bool = True
    ):
        """Publica el post principal de Facebook como un post de muro real
        con foto adjunta: primero sube la imagen sin publicar (adjuntando el
        archivo directamente vía multipart: no necesita una URL pública, a
        diferencia de Instagram) y recién después crea el post en
        `/{page_id}/feed` referenciando esa foto. Devuelve el post_id real
        que Meta confirmó, o un ResultadoDryRun si dry_run=True."""
        endpoint_foto = f"{GRAPH_API_BASE}/{self.page_id}/photos"
        endpoint_post = f"{GRAPH_API_BASE}/{self.page_id}/feed"
        if dry_run:
            return ResultadoDryRun(
                dry_run=True,
                page_id=self.page_id,
                endpoint_post=endpoint_post,
                endpoint_comentario="",
                texto_post_principal=contenido.post_principal,
                texto_primer_comentario=contenido.primer_comentario,
            )
        photo_id = self._subir_foto_sin_publicar(endpoint_foto, Path(ruta_imagen))
        return self._crear_post_feed_con_foto(endpoint_post, contenido.post_principal, photo_id)

    def alojar_imagen_para_story(self, ruta_imagen: Path, dry_run: bool = True) -> str:
        """Sube una imagen a Facebook como foto NO publicada (`published=false`)
        únicamente para obtener de Meta una URL pública (CDN) donde alojarla:
        a diferencia de `publicar_foto_facebook`, nunca crea un post de
        `/feed` a partir de ella — no queda ningún rastro visible en la
        Página de Facebook. Se usa solo como hosting para poder publicar la
        Story real de Instagram (que exige una `image_url` pública), mismo
        truco que ya se usa para el post de feed de Instagram: reutilizar el
        CDN de Meta en vez de necesitar hosting propio. Devuelve el photo_id
        de la foto subida, o un ResultadoDryRun si dry_run=True."""
        endpoint_foto = f"{GRAPH_API_BASE}/{self.page_id}/photos"
        if dry_run:
            return ResultadoDryRun(
                dry_run=True,
                page_id=self.page_id,
                endpoint_post=endpoint_foto,
                endpoint_comentario="",
                texto_post_principal="",
                texto_primer_comentario="",
            )
        return self._subir_foto_sin_publicar(endpoint_foto, Path(ruta_imagen))

    def publicar_foto_facebook_por_url(
        self, contenido: ContenidoFacebook, imagen_url: str, dry_run: bool = True
    ):
        """Igual que publicar_foto_facebook, pero para una imagen ya alojada
        en una URL remota (por ejemplo, la foto original de la fuente): se
        le pide a Meta que la busque él mismo (parámetro `url`), sin subir
        ningún archivo. Mismo flujo en dos pasos: foto sin publicar y
        después el post real en `/{page_id}/feed`."""
        endpoint_foto = f"{GRAPH_API_BASE}/{self.page_id}/photos"
        endpoint_post = f"{GRAPH_API_BASE}/{self.page_id}/feed"
        if dry_run:
            return ResultadoDryRun(
                dry_run=True,
                page_id=self.page_id,
                endpoint_post=endpoint_post,
                endpoint_comentario="",
                texto_post_principal=contenido.post_principal,
                texto_primer_comentario=contenido.primer_comentario,
            )
        if not self.tiene_token_configurado():
            raise ErrorClienteMeta("Falta META_PAGE_ACCESS_TOKEN: no se puede publicar en Facebook.")

        cuerpo_foto, content_type_foto = _multipart(
            {
                "url": imagen_url,
                "published": "false",
                "access_token": self._access_token,
            }
        )
        resultado_foto = self._peticion_json(endpoint_foto, cuerpo_foto, content_type_foto)
        photo_id = _photo_id_desde_respuesta_no_publicada(resultado_foto)
        return self._crear_post_feed_con_foto(endpoint_post, contenido.post_principal, photo_id)

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

    def verificar_publicacion(self, id_publicacion: str) -> bool:
        """Confirma con un GET, contra la propia Graph API, que un post de
        Facebook o un media de Instagram realmente existe en Meta. Se usa
        siempre antes de marcar cualquier publicación real como
        'publicado': nunca se confía únicamente en la respuesta del POST."""
        if not self.tiene_token_configurado():
            raise ErrorClienteMeta("Falta META_PAGE_ACCESS_TOKEN: no se puede verificar la publicación.")

        resultado = self._peticion_get_json(
            f"{GRAPH_API_BASE}/{id_publicacion}", {"fields": "id", "access_token": self._access_token}
        )
        return bool(resultado.get("id"))

    def editar_caption_foto_facebook(self, photo_id: str, caption: str, dry_run: bool = True):
        """Corrige el caption de una foto de Facebook ya publicada (no crea
        una publicación nueva). Pensado para arreglar un texto principal que
        haya quedado incorrecto — p.ej. una promesa de información en el
        primer comentario cuando ese comentario falló."""
        endpoint = f"{GRAPH_API_BASE}/{photo_id}"
        if dry_run:
            return ResultadoDryRun(
                dry_run=True,
                page_id=self.page_id,
                endpoint_post=endpoint,
                endpoint_comentario="",
                texto_post_principal=caption,
                texto_primer_comentario="",
            )
        if not self.tiene_token_configurado():
            raise ErrorClienteMeta("Falta META_PAGE_ACCESS_TOKEN: no se puede editar la publicación de Facebook.")

        cuerpo, content_type = _multipart({"caption": caption, "access_token": self._access_token})
        resultado = self._peticion_json(endpoint, cuerpo, content_type)
        if not resultado.get("success"):
            raise ErrorClienteMeta("Meta no confirmó la edición de la publicación de Facebook.")
        return True

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

    def publicar_instagram_story(self, imagen_url: Optional[str], dry_run: bool = True):
        """Publica una Instagram Story real: mismo flujo oficial de dos
        pasos que `publicar_instagram` (contenedor de media + publish), con
        `media_type=STORIES`. A diferencia del feed, las Stories publicadas
        por la Graph API no admiten un caption visible aparte — por eso no
        recibe `caption`: todo el texto ya viene impreso en la propia
        imagen (ver `motor_noticias.meta.imagen.generar_story`).

        No existe un equivalente de esto para Facebook: Meta no ofrece
        ningún endpoint público de Graph API para publicar Stories en una
        Página de Facebook desde una app de terceros (a diferencia de
        Instagram, donde sí es una función soportada) — limitación de la
        plataforma, no de este cliente."""
        endpoint_media = f"{GRAPH_API_BASE}/{self.ig_user_id}/media"
        endpoint_publish = f"{GRAPH_API_BASE}/{self.ig_user_id}/media_publish"
        if dry_run:
            return ResultadoDryRun(
                dry_run=True,
                page_id=self.ig_user_id or "",
                endpoint_post=endpoint_media,
                endpoint_comentario=endpoint_publish,
                texto_post_principal="",
                texto_primer_comentario="",
            )
        if not self.tiene_token_configurado():
            raise ErrorClienteMeta("Falta META_PAGE_ACCESS_TOKEN: no se puede publicar la Story de Instagram.")
        if not self.tiene_instagram_configurado():
            raise ErrorClienteMeta("Falta META_IG_USER_ID: no se puede publicar la Story de Instagram.")
        if not imagen_url:
            raise ErrorClienteMeta("Falta una URL pública de imagen para la Story de Instagram.")

        cuerpo_media, tipo_media = _multipart(
            {"image_url": imagen_url, "media_type": "STORIES", "access_token": self._access_token}
        )
        contenedor = self._peticion_json(endpoint_media, cuerpo_media, tipo_media)
        creation_id = contenedor.get("id")
        if not creation_id:
            raise ErrorClienteMeta("Meta no devolvió un ID de contenedor de Instagram Story.")

        cuerpo_publish, tipo_publish = _multipart(
            {"creation_id": creation_id, "access_token": self._access_token}
        )
        publicado = self._peticion_json(endpoint_publish, cuerpo_publish, tipo_publish)
        media_id = publicado.get("id")
        if not media_id:
            raise ErrorClienteMeta("Meta no devolvió un ID de publicación de Instagram Story.")
        return media_id

    # -- Reels (piloto) -------------------------------------------------

    def _peticion_binaria_json(self, url: str, cuerpo: bytes, cabeceras: dict) -> dict:
        """Igual que `_peticion_json`, pero para el protocolo de subida
        resumable de Facebook (`rupload.facebook.com`): cabeceras propias
        (`Authorization`, `offset`, `file_size`) en vez de multipart/
        form-data, cuerpo = bytes crudos del video."""
        peticion = urllib.request.Request(url, data=cuerpo, headers=cabeceras, method="POST")
        return self._ejecutar_peticion(peticion)

    def publicar_reel_facebook(self, ruta_video: Path, descripcion: str, dry_run: bool = True) -> str:
        """Publica un Reel real en la Página de Facebook vía subida
        resumable (`/{page_id}/video_reels`, tres fases: start, transfer,
        finish) — a diferencia de Instagram, no necesita ninguna URL
        pública: el archivo se transfiere directo a los servidores de Meta,
        igual principio que `publicar_foto_facebook` (adjunta el archivo,
        nunca depende de hosting propio). Devuelve el video_id real."""
        endpoint = f"{GRAPH_API_BASE}/{self.page_id}/video_reels"
        if dry_run:
            return ""
        if not self.tiene_token_configurado():
            raise ErrorClienteMeta("Falta META_PAGE_ACCESS_TOKEN: no se puede publicar el Reel de Facebook.")

        ruta_video = Path(ruta_video)
        tamano = ruta_video.stat().st_size

        # Nota: la fase "start" es un POST (no un GET) — un GET a este mismo
        # endpoint responde 200 con `{"data": []}` (lista los Reels
        # existentes de la página) en vez de abrir la sesión de subida.
        cuerpo_inicio, tipo_inicio = _multipart(
            {"upload_phase": "start", "access_token": self._access_token}
        )
        inicio = self._peticion_json(endpoint, cuerpo_inicio, tipo_inicio)
        video_id = inicio.get("video_id")
        upload_url = inicio.get("upload_url")
        if not video_id or not upload_url:
            raise ErrorClienteMeta(f"Meta no devolvió video_id/upload_url al iniciar la subida del Reel: {inicio}")

        transferencia = self._peticion_binaria_json(
            upload_url,
            ruta_video.read_bytes(),
            {
                "Authorization": f"OAuth {self._access_token}",
                "offset": "0",
                "file_size": str(tamano),
                "Content-Type": "application/octet-stream",
            },
        )
        # Verificado contra la API real: para un archivo chico (subido en
        # una sola parte, sin trozos) Meta responde {"success": true,
        # "message": "..."} — el par start_offset/end_offset solo aparece
        # en la respuesta cuando la subida quedó partida en varios trozos.
        subida_confirmada = transferencia.get("success") or int(transferencia.get("end_offset", -1)) == tamano
        if not subida_confirmada:
            raise ErrorClienteMeta(f"Meta no confirmó la subida completa del Reel de Facebook: {transferencia}")

        cuerpo_fin, tipo_fin = _multipart(
            {
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": descripcion,
                "access_token": self._access_token,
            }
        )
        fin = self._peticion_json(endpoint, cuerpo_fin, tipo_fin)
        if not fin.get("success"):
            raise ErrorClienteMeta(f"Meta no confirmó la publicación del Reel de Facebook: {fin}")
        return video_id

    def publicar_reel_instagram(
        self, video_url: str, caption: str, dry_run: bool = True,
        espera_maxima_segundos: int = 180, intervalo_segundos: int = 5,
    ) -> str:
        """Publica un Reel real en Instagram: mismo flujo oficial de dos
        pasos que `publicar_instagram` (contenedor de media + publish), con
        `media_type=REELS`, pero un video tarda en procesarse del lado de
        Meta antes de poder publicarse — a diferencia de una foto, hace
        falta sondear `status_code` del contenedor hasta que llegue a
        `FINISHED` (o falle) antes de intentar `media_publish`. Exige una
        `video_url` públicamente accesible (Instagram no admite adjuntar el
        archivo directamente, igual que con imágenes)."""
        import time

        endpoint_media = f"{GRAPH_API_BASE}/{self.ig_user_id}/media"
        endpoint_publish = f"{GRAPH_API_BASE}/{self.ig_user_id}/media_publish"
        if dry_run:
            return ""
        if not self.tiene_token_configurado():
            raise ErrorClienteMeta("Falta META_PAGE_ACCESS_TOKEN: no se puede publicar el Reel de Instagram.")
        if not self.tiene_instagram_configurado():
            raise ErrorClienteMeta("Falta META_IG_USER_ID: no se puede publicar el Reel de Instagram.")
        if not video_url:
            raise ErrorClienteMeta("Falta una URL pública de video para el Reel de Instagram.")

        cuerpo_media, tipo_media = _multipart(
            {
                "media_type": "REELS", "video_url": video_url, "caption": caption,
                "access_token": self._access_token,
            }
        )
        contenedor = self._peticion_json(endpoint_media, cuerpo_media, tipo_media)
        creation_id = contenedor.get("id")
        if not creation_id:
            raise ErrorClienteMeta("Meta no devolvió un ID de contenedor de Reel de Instagram.")

        transcurrido = 0
        while transcurrido < espera_maxima_segundos:
            estado = self._peticion_get_json(
                f"{GRAPH_API_BASE}/{creation_id}",
                {"fields": "status_code", "access_token": self._access_token},
            )
            status_code = estado.get("status_code")
            if status_code == "FINISHED":
                break
            if status_code == "ERROR":
                raise ErrorClienteMeta(f"Meta no pudo procesar el video del Reel de Instagram: {estado}")
            time.sleep(intervalo_segundos)
            transcurrido += intervalo_segundos
        else:
            raise ErrorClienteMeta(
                f"El video del Reel de Instagram no terminó de procesarse en {espera_maxima_segundos}s."
            )

        cuerpo_publish, tipo_publish = _multipart(
            {"creation_id": creation_id, "access_token": self._access_token}
        )
        publicado = self._peticion_json(endpoint_publish, cuerpo_publish, tipo_publish)
        media_id = publicado.get("id")
        if not media_id:
            raise ErrorClienteMeta("Meta no devolvió un ID de publicación de Reel de Instagram.")
        return media_id
