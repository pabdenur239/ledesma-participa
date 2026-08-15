"""Publicación real por franja horaria en Facebook e Instagram, con estados
separados por red social, idempotencia (nunca vuelve a publicar una fila ya
'publicado') y reintentos acotados. Nunca publica una noticia que no sea
apta según `elegibilidad_automatica` (queda pendiente de revisión humana en
el panel, igual que hoy) ni una noticia sin imagen segura.

Instagram nunca se intenta si Facebook no publicó primero: la imagen se
sube una única vez, a Facebook, y la URL pública (CDN) que Meta le asigna
ahí mismo es la que se reutiliza como `image_url` del contenedor de
Instagram — sin necesitar hosting, túnel ni URL pública propia. Esa URL se
reobtiene, no se recalcula: si Facebook ya publicó en un intento anterior,
el `photo_id` queda persistido (`referencia_extra`) para no volver a subir
la imagen en un reintento."""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

from ..db import Database
from ..models import Estado, RevisionEstado
from .cliente import ClienteMetaGraphAPI, ErrorClienteMeta
from .contenido import generar_caption_instagram
from .preparacion import ErrorPreparacionFacebook, preparar_publicacion
from .programacion import aprobar_si_elegible

logger = logging.getLogger("motor_noticias.meta.publicador")

MAX_INTENTOS_DEFAULT = 3


def _es_url_remota(valor: str) -> bool:
    return valor.startswith("http://") or valor.startswith("https://")


class ResultadoRed(NamedTuple):
    red_social: str
    estado: str  # "publicado" | "error" | "omitido"
    meta_id: Optional[str] = None
    detalle: Optional[str] = None


class ResultadoFranja(NamedTuple):
    fecha: str
    hora: str
    noticia_id: Optional[int]
    resultado: str  # "sin_contenido" | "pendiente_revision_humana" | "bloqueada_sin_imagen" | "procesada"
    redes: tuple = ()


def _publicar_en_facebook(db, prog_id, fila, cliente_fb, contenido):
    ahora_iso = datetime.now(timezone.utc).isoformat()

    if fila.get("meta_id"):
        # Ya se había publicado en un intento anterior, pero la
        # verificación por GET había fallado antes de llegar a "publicado":
        # nunca se vuelve a publicar solo porque la verificación falló,
        # eso duplicaría el post real. Se reintenta únicamente la
        # verificación sobre el mismo post_id ya confirmado por Meta.
        post_id = fila["meta_id"]
        photo_id = fila.get("referencia_extra")
    else:
        try:
            if _es_url_remota(contenido.imagen_url):
                resultado_fb = cliente_fb.publicar_foto_facebook_por_url(contenido, contenido.imagen_url, dry_run=False)
            else:
                resultado_fb = cliente_fb.publicar_foto_facebook(contenido, Path(contenido.imagen_url), dry_run=False)
        except ErrorClienteMeta as error:
            logger.error("Error publicando en facebook (franja %s): %s", prog_id, error)
            db.actualizar_programacion_meta(
                prog_id, "error", ultimo_error=str(error), intentos=fila["intentos"] + 1, actualizada_en=ahora_iso
            )
            return ResultadoRed("facebook", "error", detalle=str(error)), None

        post_id, photo_id = resultado_fb.post_id, resultado_fb.photo_id
        # Persistir de inmediato el ID que Meta ya confirmó, antes de
        # verificar: si la verificación falla, el próximo reintento debe
        # encontrar este meta_id y no volver a publicar.
        db.actualizar_programacion_meta(
            prog_id, "error", meta_id=post_id, referencia_extra=photo_id,
            ultimo_error="Publicado; pendiente de confirmar con GET.",
            intentos=fila["intentos"] + 1, actualizada_en=ahora_iso,
        )

    # Nunca se marca "publicado" solo por la respuesta del POST: se
    # confirma con un GET aparte contra la propia Graph API.
    try:
        if not cliente_fb.verificar_publicacion(post_id):
            raise ErrorClienteMeta("Meta no confirmó la publicación de Facebook al verificarla con GET.")
    except ErrorClienteMeta as error:
        logger.error("Facebook publicó pero la verificación por GET falló (franja %s): %s", prog_id, error)
        db.actualizar_programacion_meta(
            prog_id, "error", meta_id=post_id, referencia_extra=photo_id, ultimo_error=str(error),
            intentos=fila["intentos"] + 1, actualizada_en=ahora_iso,
        )
        return ResultadoRed("facebook", "error", detalle=str(error)), None

    # El post principal ya es autosuficiente (incluye fuente y enlace): no
    # se usa ni se promete un primer comentario en la publicación real (el
    # token tampoco tiene permiso pages_manage_engagement, ver historial).
    db.actualizar_programacion_meta(
        prog_id, "publicado", meta_id=post_id, referencia_extra=photo_id,
        intentos=fila["intentos"] + 1, actualizada_en=ahora_iso, publicada_en=ahora_iso,
    )
    return ResultadoRed("facebook", "publicado", post_id), photo_id


def _publicar_en_instagram(db, prog_id, fila, cliente_fb, cliente_ig, noticia, photo_id):
    ahora_iso = datetime.now(timezone.utc).isoformat()

    if fila.get("meta_id"):
        # Mismo criterio que Facebook: si ya se publicó en un intento
        # anterior y solo falló la verificación, nunca se vuelve a publicar.
        media_id = fila["meta_id"]
    else:
        try:
            imagen_url_publica = cliente_fb.obtener_url_publica_foto(photo_id)
            caption = generar_caption_instagram(noticia)
            media_id = cliente_ig.publicar_instagram(caption, imagen_url_publica, dry_run=False)
        except ErrorClienteMeta as error:
            # Cubre tanto un fallo de publicar_instagram como el caso pedido
            # explícitamente: si Meta no entrega una URL de Facebook apta
            # para Instagram (obtener_url_publica_foto), se detiene acá y
            # queda reportado el bloqueo — nunca se intenta un hosting
            # alternativo.
            logger.error("Error publicando en instagram (franja %s): %s", prog_id, error)
            db.actualizar_programacion_meta(
                prog_id, "error", ultimo_error=str(error), intentos=fila["intentos"] + 1, actualizada_en=ahora_iso
            )
            return ResultadoRed("instagram", "error", detalle=str(error))

        db.actualizar_programacion_meta(
            prog_id, "error", meta_id=media_id,
            ultimo_error="Publicado; pendiente de confirmar con GET.",
            intentos=fila["intentos"] + 1, actualizada_en=ahora_iso,
        )

    # Nunca se marca "publicado" solo por la respuesta del paso de
    # publicación: se confirma con un GET aparte contra la Graph API.
    try:
        if not cliente_ig.verificar_publicacion(media_id):
            raise ErrorClienteMeta("Meta no confirmó la publicación de Instagram al verificarla con GET.")
    except ErrorClienteMeta as error:
        logger.error("Instagram publicó pero la verificación por GET falló (franja %s): %s", prog_id, error)
        db.actualizar_programacion_meta(
            prog_id, "error", meta_id=media_id, ultimo_error=str(error),
            intentos=fila["intentos"] + 1, actualizada_en=ahora_iso,
        )
        return ResultadoRed("instagram", "error", detalle=str(error))

    db.actualizar_programacion_meta(
        prog_id, "publicado", meta_id=media_id, intentos=fila["intentos"] + 1,
        actualizada_en=ahora_iso, publicada_en=ahora_iso,
    )
    return ResultadoRed("instagram", "publicado", media_id)


def publicar_franja(
    db: Database,
    fecha: str,
    hora: str,
    cliente_fb: Optional[ClienteMetaGraphAPI] = None,
    cliente_ig: Optional[ClienteMetaGraphAPI] = None,
    ahora: Optional[datetime] = None,
) -> ResultadoFranja:
    ahora_utc = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cliente_fb = cliente_fb or ClienteMetaGraphAPI()
    cliente_ig = cliente_ig or ClienteMetaGraphAPI()

    item = db.obtener_agenda_item(fecha, hora)
    if not item or not item.get("noticia_id"):
        return ResultadoFranja(fecha, hora, None, "sin_contenido")

    noticia = db.obtener(item["noticia_id"])
    if noticia is None:
        return ResultadoFranja(fecha, hora, item["noticia_id"], "sin_contenido")

    noticia = aprobar_si_elegible(db, noticia, ahora=ahora_utc)
    if noticia["revision_estado"] != RevisionEstado.APROBADA.value:
        return ResultadoFranja(fecha, hora, noticia["id"], "pendiente_revision_humana")

    creada_en = datetime.now(timezone.utc).isoformat()
    prog_id_fb = db.reservar_programacion_meta(fecha, hora, noticia["id"], "facebook", creada_en)
    prog_id_ig = db.reservar_programacion_meta(fecha, hora, noticia["id"], "instagram", creada_en)
    fila_fb = db.obtener_programacion_meta(fecha, hora, "facebook")
    fila_ig = db.obtener_programacion_meta(fecha, hora, "instagram")

    if fila_fb["estado"] == "publicado" and fila_ig["estado"] == "publicado":
        return ResultadoFranja(
            fecha, hora, noticia["id"], "procesada",
            (
                ResultadoRed("facebook", "omitido", fila_fb["meta_id"], "ya publicado (idempotente)"),
                ResultadoRed("instagram", "omitido", fila_ig["meta_id"], "ya publicado (idempotente)"),
            ),
        )

    try:
        contenido = preparar_publicacion(noticia, dry_run=True, db=db)
    except ErrorPreparacionFacebook as error:
        logger.error("Franja %s %s bloqueada: %s", fecha, hora, error)
        return ResultadoFranja(fecha, hora, noticia["id"], "bloqueada_sin_imagen")

    if not contenido.imagen_url:
        logger.error("Franja %s %s bloqueada: sin imagen segura para publicar.", fecha, hora)
        return ResultadoFranja(fecha, hora, noticia["id"], "bloqueada_sin_imagen")

    resultados_red = []

    # -- Facebook: siempre primero. Instagram depende de su resultado. -----
    if fila_fb["estado"] == "publicado":
        resultados_red.append(ResultadoRed("facebook", "omitido", fila_fb["meta_id"], "ya publicado (idempotente)"))
        photo_id = fila_fb["referencia_extra"]
        facebook_ok = bool(photo_id)
    else:
        resultado_fb, photo_id = _publicar_en_facebook(db, prog_id_fb, fila_fb, cliente_fb, contenido)
        resultados_red.append(resultado_fb)
        facebook_ok = resultado_fb.estado == "publicado"

    # -- Instagram: nunca se intenta si Facebook no publicó (ahora o antes) -
    if fila_ig["estado"] == "publicado":
        resultados_red.append(ResultadoRed("instagram", "omitido", fila_ig["meta_id"], "ya publicado (idempotente)"))
    elif not facebook_ok:
        resultados_red.append(
            ResultadoRed("instagram", "omitido", detalle="no intentado: depende de que Facebook publique primero")
        )
    else:
        resultados_red.append(
            _publicar_en_instagram(db, prog_id_ig, fila_ig, cliente_fb, cliente_ig, noticia, photo_id)
        )

    if any(r.estado == "publicado" for r in resultados_red):
        db.actualizar_estado_noticia(noticia["id"], Estado.PUBLICADA.value)

    return ResultadoFranja(fecha, hora, noticia["id"], "procesada", tuple(resultados_red))


def reintentar_publicaciones(
    db: Database,
    cliente_fb: Optional[ClienteMetaGraphAPI] = None,
    cliente_ig: Optional[ClienteMetaGraphAPI] = None,
    max_intentos: int = MAX_INTENTOS_DEFAULT,
    ahora: Optional[datetime] = None,
) -> list:
    """Reintenta, de forma acotada (`max_intentos`), las filas de
    programacion_meta que quedaron en estado 'error'. Cada red social se
    reintenta de forma independiente: si Facebook ya está 'publicado' y solo
    Instagram falló, únicamente se reintenta Instagram (reutilizando el
    photo_id ya persistido, sin volver a subir la imagen); si Facebook
    todavía no publicó, Instagram sigue sin intentarse."""
    pendientes = db.listar_programacion_meta_para_reintentar(max_intentos)
    franjas = sorted({(fila["fecha"], fila["hora"]) for fila in pendientes})

    resultados = []
    for fecha, hora in franjas:
        resultados.append(publicar_franja(db, fecha, hora, cliente_fb=cliente_fb, cliente_ig=cliente_ig, ahora=ahora))
    return resultados
