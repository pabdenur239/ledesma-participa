"""Publicación real por franja horaria en Facebook e Instagram, con estados
separados por red social, idempotencia (nunca vuelve a publicar una fila ya
'publicado') y reintentos acotados. Nunca publica una noticia que no sea
apta según `elegibilidad_automatica` (queda pendiente de revisión humana en
el panel, igual que hoy) ni una noticia sin imagen segura."""
import logging
import os
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

REDES_SOCIALES = ("facebook", "instagram")
MAX_INTENTOS_DEFAULT = 3


def _es_url_remota(valor: str) -> bool:
    return valor.startswith("http://") or valor.startswith("https://")


def _url_publica_imagen(ruta: str, image_base_url: Optional[str]) -> Optional[str]:
    """Instagram exige una `image_url` públicamente accesible (a diferencia
    de Facebook, que admite subir el archivo directamente). Si la imagen ya
    es una URL remota (foto original de la fuente), se usa tal cual; si es
    una placa local, se arma con META_IMAGE_BASE_URL (la ruta pública donde
    el panel expone `data/placas`, ver panel/server.py `/placas/<archivo>`)."""
    if _es_url_remota(ruta):
        return ruta
    if not image_base_url:
        return None
    nombre = Path(ruta).name
    return f"{image_base_url.rstrip('/')}/{nombre}"


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


def publicar_franja(
    db: Database,
    fecha: str,
    hora: str,
    cliente_fb: Optional[ClienteMetaGraphAPI] = None,
    cliente_ig: Optional[ClienteMetaGraphAPI] = None,
    image_base_url: Optional[str] = None,
    ahora: Optional[datetime] = None,
) -> ResultadoFranja:
    ahora_utc = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cliente_fb = cliente_fb or ClienteMetaGraphAPI()
    cliente_ig = cliente_ig or ClienteMetaGraphAPI()
    image_base_url = image_base_url if image_base_url is not None else os.environ.get("META_IMAGE_BASE_URL")

    item = db.obtener_agenda_item(fecha, hora)
    if not item or not item.get("noticia_id"):
        return ResultadoFranja(fecha, hora, None, "sin_contenido")

    noticia = db.obtener(item["noticia_id"])
    if noticia is None:
        return ResultadoFranja(fecha, hora, item["noticia_id"], "sin_contenido")

    noticia = aprobar_si_elegible(db, noticia, ahora=ahora_utc)
    if noticia["revision_estado"] != RevisionEstado.APROBADA.value:
        return ResultadoFranja(fecha, hora, noticia["id"], "pendiente_revision_humana")

    try:
        contenido = preparar_publicacion(noticia, dry_run=True, db=db)
    except ErrorPreparacionFacebook as error:
        logger.error("Franja %s %s bloqueada: %s", fecha, hora, error)
        return ResultadoFranja(fecha, hora, noticia["id"], "bloqueada_sin_imagen")

    if not contenido.imagen_url:
        logger.error("Franja %s %s bloqueada: sin imagen segura para publicar.", fecha, hora)
        return ResultadoFranja(fecha, hora, noticia["id"], "bloqueada_sin_imagen")

    resultados_red = []
    creada_en = datetime.now(timezone.utc).isoformat()

    for red_social in REDES_SOCIALES:
        prog_id = db.reservar_programacion_meta(fecha, hora, noticia["id"], red_social, creada_en)
        fila = db.obtener_programacion_meta(fecha, hora, red_social)

        if fila["estado"] == "publicado":
            resultados_red.append(ResultadoRed(red_social, "omitido", fila["meta_id"], "ya publicado (idempotente)"))
            continue

        ahora_iso = datetime.now(timezone.utc).isoformat()
        try:
            if red_social == "facebook":
                if _es_url_remota(contenido.imagen_url):
                    post_id = cliente_fb.publicar_foto_facebook_por_url(contenido, contenido.imagen_url, dry_run=False)
                else:
                    post_id = cliente_fb.publicar_foto_facebook(contenido, Path(contenido.imagen_url), dry_run=False)
                cliente_fb.publicar_comentario_facebook(post_id, contenido.primer_comentario, dry_run=False)
                meta_id = post_id
            else:
                imagen_url_publica = _url_publica_imagen(contenido.imagen_url, image_base_url)
                if not imagen_url_publica:
                    raise ErrorClienteMeta(
                        "Falta META_IMAGE_BASE_URL: no hay una URL pública para la placa, "
                        "Instagram no admite subir el archivo directamente."
                    )
                caption = generar_caption_instagram(noticia)
                meta_id = cliente_ig.publicar_instagram(caption, imagen_url_publica, dry_run=False)

            db.actualizar_programacion_meta(
                prog_id, "publicado", meta_id=meta_id, intentos=fila["intentos"] + 1,
                actualizada_en=ahora_iso, publicada_en=ahora_iso,
            )
            resultados_red.append(ResultadoRed(red_social, "publicado", meta_id))
        except ErrorClienteMeta as error:
            logger.error("Error publicando en %s (franja %s %s): %s", red_social, fecha, hora, error)
            db.actualizar_programacion_meta(
                prog_id, "error", ultimo_error=str(error), intentos=fila["intentos"] + 1, actualizada_en=ahora_iso,
            )
            resultados_red.append(ResultadoRed(red_social, "error", detalle=str(error)))

    if any(r.estado == "publicado" for r in resultados_red):
        db.actualizar_estado_noticia(noticia["id"], Estado.PUBLICADA.value)

    return ResultadoFranja(fecha, hora, noticia["id"], "procesada", tuple(resultados_red))


def reintentar_publicaciones(
    db: Database,
    cliente_fb: Optional[ClienteMetaGraphAPI] = None,
    cliente_ig: Optional[ClienteMetaGraphAPI] = None,
    image_base_url: Optional[str] = None,
    max_intentos: int = MAX_INTENTOS_DEFAULT,
    ahora: Optional[datetime] = None,
) -> list:
    """Reintenta, de forma acotada (`max_intentos`), las filas de
    programacion_meta que quedaron en estado 'error'. Cada red social se
    reintenta de forma independiente: si Facebook ya está 'publicado' y solo
    Instagram falló, únicamente se reintenta la fila de Instagram (nunca se
    vuelve a publicar en la red que ya tuvo éxito)."""
    pendientes = db.listar_programacion_meta_para_reintentar(max_intentos)
    franjas = sorted({(fila["fecha"], fila["hora"]) for fila in pendientes})

    resultados = []
    for fecha, hora in franjas:
        resultados.append(
            publicar_franja(
                db, fecha, hora, cliente_fb=cliente_fb, cliente_ig=cliente_ig,
                image_base_url=image_base_url, ahora=ahora,
            )
        )
    return resultados
