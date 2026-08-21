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
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple, Optional

from ..db import Database
from ..dedupe import es_mismo_contenido, palabras_clave
from ..models import Estado, OrigenIngreso, RevisionEstado
from ..motor_editorial import HORA_NOTICIA_DEL_DIA
from .cliente import ClienteMetaGraphAPI, ErrorClienteMeta
from .contenido import generar_caption_instagram
from .preparacion import ErrorPreparacionFacebook, preparar_publicacion, preparar_publicacion_story
from .programacion import aprobar_si_elegible

logger = logging.getLogger("motor_noticias.meta.publicador")

MAX_INTENTOS_DEFAULT = 3

CONFIG_META_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "meta.json"


def _historias_instagram_habilitadas(path: Optional[Path] = None) -> bool:
    """Lee `config/meta.json` → "historias_instagram_habilitadas" (default
    `true` si el archivo falta o es inválido). Se relee en cada llamada,
    así se puede desactivar sin reiniciar ningún proceso — mismo criterio
    que `agenda_automatica_habilitada` en ciclo_continuo."""
    try:
        with open(path or CONFIG_META_PATH_DEFAULT, encoding="utf-8") as f:
            config = json.load(f)
        return bool(config.get("historias_instagram_habilitadas", True))
    except (OSError, json.JSONDecodeError):
        return True


# Ventana hacia atrás en la que se busca una publicación ya salida que sea
# la misma nota (mismo gate de deduplicación para franja fija, urgente y
# reintento, ver `_publicar_noticia_en_clave`). Coincide con
# `ANTIGUEDAD_MAXIMA_HORAS` de motor_editorial: más atrás de eso una noticia
# ya ni siquiera es candidata de la cascada, así que tampoco hace falta
# compararla.
VENTANA_DEDUPLICACION_HORAS = 48


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
    resultado: str  # "sin_contenido" | "pendiente_revision_humana" | "bloqueada_sin_imagen" | "duplicado_bloqueado" | "procesada"
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


def _publicar_story_instagram(db, prog_id, fila, cliente_fb, cliente_ig, noticia):
    """Publica la Instagram Story de esta noticia: es un `red_social` más de
    `programacion_meta` (`"instagram_story"`), con exactamente la misma
    idempotencia/reintentos/verificación por GET que Facebook e Instagram
    feed — nunca se marca 'publicado' solo por la respuesta del POST, y un
    media_id ya confirmado en un intento anterior nunca se vuelve a
    publicar. No depende de que el feed de Facebook/Instagram haya
    publicado: reutiliza la misma noticia ya seleccionada para la franja,
    pero no genera ningún post de feed nuevo (la placa 9:16 se aloja en
    Facebook como foto no publicada, invisible en la Página, solo para
    obtener la URL de CDN que exige la Graph API de Instagram)."""
    ahora_iso = datetime.now(timezone.utc).isoformat()

    if fila.get("meta_id"):
        media_id = fila["meta_id"]
    else:
        try:
            ruta_imagen = preparar_publicacion_story(noticia, db=db)
        except ErrorPreparacionFacebook as error:
            logger.error("Story de Instagram bloqueada para noticia %s: %s", noticia["id"], error)
            db.actualizar_programacion_meta(
                prog_id, "error", ultimo_error=str(error), intentos=fila["intentos"] + 1, actualizada_en=ahora_iso
            )
            return ResultadoRed("instagram_story", "error", detalle=str(error))

        try:
            photo_id = cliente_fb.alojar_imagen_para_story(Path(ruta_imagen), dry_run=False)
            imagen_url_publica = cliente_fb.obtener_url_publica_foto(photo_id)
            media_id = cliente_ig.publicar_instagram_story(imagen_url_publica, dry_run=False)
        except ErrorClienteMeta as error:
            logger.error("Error publicando la Story de Instagram (franja %s): %s", prog_id, error)
            db.actualizar_programacion_meta(
                prog_id, "error", ultimo_error=str(error), intentos=fila["intentos"] + 1, actualizada_en=ahora_iso
            )
            return ResultadoRed("instagram_story", "error", detalle=str(error))

        db.actualizar_programacion_meta(
            prog_id, "error", meta_id=media_id,
            ultimo_error="Publicado; pendiente de confirmar con GET.",
            intentos=fila["intentos"] + 1, actualizada_en=ahora_iso,
        )

    try:
        if not cliente_ig.verificar_publicacion(media_id):
            raise ErrorClienteMeta("Meta no confirmó la publicación de la Story de Instagram al verificarla con GET.")
    except ErrorClienteMeta as error:
        logger.error("Story de Instagram publicada pero la verificación por GET falló (franja %s): %s", prog_id, error)
        db.actualizar_programacion_meta(
            prog_id, "error", meta_id=media_id, ultimo_error=str(error),
            intentos=fila["intentos"] + 1, actualizada_en=ahora_iso,
        )
        return ResultadoRed("instagram_story", "error", detalle=str(error))

    db.actualizar_programacion_meta(
        prog_id, "publicado", meta_id=media_id, intentos=fila["intentos"] + 1,
        actualizada_en=ahora_iso, publicada_en=ahora_iso,
    )
    return ResultadoRed("instagram_story", "publicado", media_id)


def _tope_reintentos_alcanzado(fila: dict, max_intentos: int = MAX_INTENTOS_DEFAULT) -> bool:
    """True si esta fila ya agotó el tope de reintentos y sigue en 'error'.
    Bug real corregido 21/8: `publicar_urgentes` llama a
    `_publicar_noticia_en_clave` en cada corrida de MetaUrgentes (cada 15
    minutos, indefinidamente mientras la urgente exista en la agenda), sin
    ningún tope — a diferencia de `reintentar_publicaciones`, que sí lo
    respeta vía `listar_programacion_meta_para_reintentar`. Una fila que
    nunca llegó a confirmar `meta_id` (falla antes de que Meta responda,
    ej. rate limit) se reintentaba sin límite: se detectó una fila real con
    68 intentos en 15 horas. Cada reintento repite el POST completo a la
    Graph API desde cero (no hay nada que deduplicar todavía si el intento
    anterior nunca devolvió un id), así que cada uno es indistinguible de
    una publicación nueva para Meta — machacar sin límite además agrava el
    rate-limit que causa la propia falla. Puesto acá, en el único punto que
    comparten las tres vías (franja fija, urgente, reintento), protege a
    las tres por igual: pasado el tope la fila queda en 'error' tal cual
    (no se toca ni se borra), disponible para revisión manual."""
    return fila["estado"] == "error" and fila["intentos"] >= max_intentos


def _programacion_ya_publicada(db: Database, fecha: str, clave: str) -> bool:
    """True si ambas redes de esta franja/urgente ya están 'publicado'."""
    fila_fb = db.obtener_programacion_meta(fecha, clave, "facebook")
    fila_ig = db.obtener_programacion_meta(fecha, clave, "instagram")
    return bool(fila_fb) and bool(fila_ig) and fila_fb["estado"] == "publicado" and fila_ig["estado"] == "publicado"


def _buscar_duplicado_ya_publicado(db: Database, noticia: dict, ahora_utc: datetime) -> Optional[dict]:
    """Gate de deduplicación único y común a los tres circuitos de
    publicación (franja fija, urgente y reintento — los tres pasan por
    `_publicar_noticia_en_clave`). Busca, entre las noticias que ya
    salieron publicadas recientemente, alguna que sea la misma nota que
    `noticia`: primero por URL normalizada (o id de fuente, cuando
    coincide exactamente — la señal más fuerte), y si no alcanza, por
    fingerprint de contenido normalizado (palabras clave del título) para
    cubrir el caso de dos registros internos distintos (otra fuente, un
    título apenas distinto) que en realidad son la misma noticia."""
    fecha_limite = (ahora_utc - timedelta(hours=VENTANA_DEDUPLICACION_HORAS)).isoformat()
    candidatas = db.noticias_publicadas_recientes(fecha_limite, excluir_id=noticia["id"])
    if not candidatas:
        return None

    url_propia = noticia.get("url_normalizada")
    for candidata in candidatas:
        if url_propia and candidata.get("url_normalizada") == url_propia:
            return candidata

    palabras_propias_titulo = palabras_clave(noticia.get("titulo_original") or "")
    palabras_propias_completas = palabras_clave(
        f"{noticia.get('titulo_original') or ''} {noticia.get('texto_original') or ''}"
    )
    if not palabras_propias_titulo:
        return None
    for candidata in candidatas:
        if es_mismo_contenido(palabras_propias_titulo, palabras_clave(candidata.get("titulo_original") or "")):
            return candidata
        # Corroboración cruzada entre fuentes distintas: dos medios que cubren
        # el mismo hecho real suelen titularlo con palabras muy distintas
        # (nombres de jugadores vs. equipos, ángulo distinto de la misma
        # nota) que el fingerprint de título por sí solo no alcanza a
        # emparejar (caso real detectado 20/8: Infobae y La Nación sobre el
        # mismo partido Flamengo-Cruzeiro, títulos sin ninguna palabra en
        # común salvo "Flamengo"). Ampliar la comparación al cuerpo de la
        # nota solo cuando la fuente es distinta: dentro de la misma fuente
        # (ej. dos anuncios oficiales consecutivos del mismo organismo) el
        # texto comparte tanto lenguaje de trámite que compararlo completo
        # genera falsos positivos entre noticias reales y distintas
        # (verificado con datos de producción: dos anuncios de Jujuy al día
        # sobre programas sociales distintos comparten "Ministerio de
        # Desarrollo Humano... a través de la Secretaría... jueves 20 de
        # agosto" casi palabra por palabra).
        fuente_candidata = candidata.get("nombre_fuente")
        if fuente_candidata and fuente_candidata != noticia.get("nombre_fuente"):
            palabras_candidata_completas = palabras_clave(
                f"{candidata.get('titulo_original') or ''} {candidata.get('texto_original') or ''}"
            )
            if es_mismo_contenido(palabras_propias_completas, palabras_candidata_completas):
                return candidata
    return None


def _publicar_noticia_en_clave(
    db: Database,
    fecha: str,
    clave: str,
    noticia_id: int,
    cliente_fb: ClienteMetaGraphAPI,
    cliente_ig: ClienteMetaGraphAPI,
    ahora_utc: datetime,
) -> ResultadoFranja:
    """Lógica de publicación real compartida por franja fija y por urgente:
    `clave` es la franja horaria (`"HH:MM"`) para una franja fija, o una
    clave sintética (`"urgente-<agenda_item_id>"`) para una propuesta
    urgente — en ambos casos identifica de forma única la fila de
    `programacion_meta` para esa noticia, así la idempotencia y los
    reintentos por red social funcionan igual en los dos casos."""
    noticia = db.obtener(noticia_id)
    if noticia is None:
        return ResultadoFranja(fecha, clave, noticia_id, "sin_contenido")

    noticia = aprobar_si_elegible(db, noticia, ahora=ahora_utc)
    if noticia["revision_estado"] != RevisionEstado.APROBADA.value:
        return ResultadoFranja(fecha, clave, noticia["id"], "pendiente_revision_humana")

    # La publicación institucional diaria (motor_noticias.institucional) es
    # intencionalmente idéntica día a día — mismo texto, misma imagen — y
    # por eso queda marcada aparte (origen_ingreso="institucional"): el
    # gate de duplicados por fingerprint de contenido, más abajo, existe
    # justamente para bloquear texto repetido entre noticias reales
    # distintas, así que aplicado tal cual bloquearía la institucional de
    # hoy contra la de ayer. No afecta al primer gate (mismo noticia_id
    # publicado por otra clave): ese sigue protegiendo también a la
    # institucional, que tiene una fila de noticia nueva y propia cada día.
    #
    # El Resumen del Día (motor_noticias.resumen_dia, agregado 20/8/2026)
    # tiene el mismo problema por una razón distinta: su texto necesariamente
    # menciona títulos de noticias reales ya publicadas hoy, así que
    # comparado por fingerprint contra esas mismas noticias quedaría
    # bloqueado como "duplicado" de algo que en realidad solo está
    # resumiendo, no republicando.
    es_institucional = noticia.get("origen_ingreso") in (
        OrigenIngreso.INSTITUCIONAL.value,
        OrigenIngreso.RESUMEN_DIARIO.value,
    )

    creada_en = datetime.now(timezone.utc).isoformat()
    prog_id_fb = db.reservar_programacion_meta(fecha, clave, noticia["id"], "facebook", creada_en)
    prog_id_ig = db.reservar_programacion_meta(fecha, clave, noticia["id"], "instagram", creada_en)
    fila_fb = db.obtener_programacion_meta(fecha, clave, "facebook")
    fila_ig = db.obtener_programacion_meta(fecha, clave, "instagram")

    # Nota: no hay un atajo separado para "facebook e instagram ya
    # publicados" — cada red (incluida la Story) resuelve su propio estado
    # "omitido (ya publicado)" más abajo, así ninguna red queda fuera del
    # reporte cuando se reingresa a una franja ya completa (idempotente en
    # las tres, no solo en feed).
    #
    # Gate de deduplicación en dos capas. Primera capa — identificador más
    # estable posible: el propio noticia_id. Si esta noticia ya está
    # `publicada` mientras que ESTA fila (esta clave: esta franja/urgente/
    # reintento en particular) nunca llegó a publicar nada ella misma, es
    # que otra franja/circuito distinto ya la publicó primero — sin importar
    # cómo haya terminado esa misma noticia asignada a dos claves (una
    # regeneración de agenda concurrente, un selector alternativo, una
    # carga manual). Bug real corregido: antes esta condición se leía al
    # revés («si NO está publicada, revisar duplicados») y por eso una
    # segunda clave sobre la misma noticia ya publicada se colaba derecho
    # hacia el POST real, sin pasar por ningún chequeo — el propio
    # `noticia["estado"]` ya alcanzaba para bloquearla y no se usaba.
    ya_publicada_por_esta_fila = fila_fb["estado"] == "publicado" or fila_ig["estado"] == "publicado"
    if noticia["estado"] == Estado.PUBLICADA.value and not ya_publicada_por_esta_fila:
        detalle = f"la noticia #{noticia['id']} ya fue publicada por otra franja/circuito"
        logger.info(
            "Franja %s %s bloqueada: noticia #%s ya publicada por otra franja/circuito (mismo noticia_id).",
            fecha, clave, noticia["id"],
        )
        ahora_iso = datetime.now(timezone.utc).isoformat()
        db.actualizar_programacion_meta(
            prog_id_fb, "duplicado", ultimo_error=detalle,
            intentos=fila_fb["intentos"] + 1, actualizada_en=ahora_iso,
        )
        db.actualizar_programacion_meta(
            prog_id_ig, "duplicado", ultimo_error=detalle,
            intentos=fila_ig["intentos"] + 1, actualizada_en=ahora_iso,
        )
        return ResultadoFranja(
            fecha, clave, noticia["id"], "duplicado_bloqueado",
            (
                ResultadoRed("facebook", "omitido", detalle=detalle),
                ResultadoRed("instagram", "omitido", detalle=detalle),
            ),
        )

    # Segunda capa — solo si esta noticia todavía no se publicó por ningún
    # lado: compara por fingerprint de contenido (URL normalizada o
    # palabras clave del título) contra OTRAS noticias (id distinto) que
    # puedan ser la misma nota real bajo un registro interno separado.
    # Nunca se aplica a la institucional (ver `es_institucional` arriba).
    if noticia["estado"] != Estado.PUBLICADA.value and not es_institucional:
        duplicado = _buscar_duplicado_ya_publicado(db, noticia, ahora_utc)
        if duplicado is not None:
            detalle = f"misma noticia ya publicada como noticia #{duplicado['id']}"
            logger.info(
                "Franja %s %s bloqueada por duplicado: noticia #%s ~ noticia #%s ya publicada.",
                fecha, clave, noticia["id"], duplicado["id"],
            )
            ahora_iso = datetime.now(timezone.utc).isoformat()
            db.actualizar_programacion_meta(
                prog_id_fb, "duplicado", ultimo_error=detalle,
                intentos=fila_fb["intentos"] + 1, actualizada_en=ahora_iso,
            )
            db.actualizar_programacion_meta(
                prog_id_ig, "duplicado", ultimo_error=detalle,
                intentos=fila_ig["intentos"] + 1, actualizada_en=ahora_iso,
            )
            return ResultadoFranja(
                fecha, clave, noticia["id"], "duplicado_bloqueado",
                (
                    ResultadoRed("facebook", "omitido", detalle=detalle),
                    ResultadoRed("instagram", "omitido", detalle=detalle),
                ),
            )

    try:
        contenido = preparar_publicacion(noticia, dry_run=True, db=db)
    except ErrorPreparacionFacebook as error:
        logger.error("Franja %s %s bloqueada: %s", fecha, clave, error)
        return ResultadoFranja(fecha, clave, noticia["id"], "bloqueada_sin_imagen")

    # Noticia del Día: misma noticia real, mismo pipeline de preparación
    # (no se regenera nada, "mejor selección de imagen" = la que ya eligió
    # `preparar_publicacion` para esa noticia), solo se le agrega un
    # encabezado distintivo al texto de esta publicación puntual — nunca se
    # modifica el registro guardado de la noticia (titulo_preparado/
    # texto_preparado quedan intactos para cualquier otro uso).
    if clave == HORA_NOTICIA_DEL_DIA:
        contenido.post_principal = f"🌟 NOTICIA DEL DÍA\n\n{contenido.post_principal}"

    if not contenido.imagen_url:
        logger.error("Franja %s %s bloqueada: sin imagen segura para publicar.", fecha, clave)
        return ResultadoFranja(fecha, clave, noticia["id"], "bloqueada_sin_imagen")

    resultados_red = []

    # -- Facebook: siempre primero. Instagram depende de su resultado. -----
    if fila_fb["estado"] == "publicado":
        resultados_red.append(ResultadoRed("facebook", "omitido", fila_fb["meta_id"], "ya publicado (idempotente)"))
        photo_id = fila_fb["referencia_extra"]
        facebook_ok = bool(photo_id)
    elif _tope_reintentos_alcanzado(fila_fb):
        resultados_red.append(
            ResultadoRed("facebook", "omitido", detalle=f"tope de {MAX_INTENTOS_DEFAULT} reintentos alcanzado")
        )
        photo_id = fila_fb["referencia_extra"]
        facebook_ok = bool(photo_id)
    else:
        resultado_fb, photo_id = _publicar_en_facebook(db, prog_id_fb, fila_fb, cliente_fb, contenido)
        resultados_red.append(resultado_fb)
        facebook_ok = resultado_fb.estado == "publicado"

    # -- Instagram: nunca se intenta si Facebook no publicó (ahora o antes) -
    if fila_ig["estado"] == "publicado":
        resultados_red.append(ResultadoRed("instagram", "omitido", fila_ig["meta_id"], "ya publicado (idempotente)"))
    elif _tope_reintentos_alcanzado(fila_ig):
        resultados_red.append(
            ResultadoRed("instagram", "omitido", detalle=f"tope de {MAX_INTENTOS_DEFAULT} reintentos alcanzado")
        )
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

    # -- Instagram Story: independiente del feed (no depende de que Facebook
    # o Instagram feed hayan publicado), pero reutiliza la misma noticia ya
    # seleccionada para esta franja/urgente/reintento — nunca genera otro
    # feed. No hay equivalente de Facebook Story: la Graph API pública de
    # Meta no ofrece ningún endpoint para publicar Stories en una Página de
    # Facebook desde una app de terceros (bloqueo real de la plataforma, no
    # de este código). La institucional nunca genera Story (regla propia
    # de esa publicación, no un cambio de comportamiento de Stories).
    if _historias_instagram_habilitadas() and not es_institucional:
        prog_id_story = db.reservar_programacion_meta(fecha, clave, noticia["id"], "instagram_story", creada_en)
        fila_story = db.obtener_programacion_meta(fecha, clave, "instagram_story")
        if fila_story["estado"] == "publicado":
            resultados_red.append(
                ResultadoRed("instagram_story", "omitido", fila_story["meta_id"], "ya publicado (idempotente)")
            )
        elif _tope_reintentos_alcanzado(fila_story):
            resultados_red.append(
                ResultadoRed(
                    "instagram_story", "omitido", detalle=f"tope de {MAX_INTENTOS_DEFAULT} reintentos alcanzado"
                )
            )
        else:
            resultados_red.append(
                _publicar_story_instagram(db, prog_id_story, fila_story, cliente_fb, cliente_ig, noticia)
            )

    return ResultadoFranja(fecha, clave, noticia["id"], "procesada", tuple(resultados_red))


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

    return _publicar_noticia_en_clave(db, fecha, hora, item["noticia_id"], cliente_fb, cliente_ig, ahora_utc)


def publicar_urgentes(
    db: Database,
    fecha: str,
    cliente_fb: Optional[ClienteMetaGraphAPI] = None,
    cliente_ig: Optional[ClienteMetaGraphAPI] = None,
    ahora: Optional[datetime] = None,
    max_pendientes: Optional[int] = None,
) -> list:
    """Publica de inmediato las propuestas urgentes (último momento local o
    departamental, ver `Database.candidatos_urgentes`) del día que ya tengan
    noticia asignada, sin esperar a la franja fija más cercana. Reutiliza
    exactamente el mismo gate de aptitud automática y el mismo flujo de
    publicación por red social que una franja fija — la única diferencia es
    la clave de `programacion_meta` (`"urgente-<agenda_item_id>"` en vez de
    una hora fija), para poder tener varias urgentes el mismo día sin que
    colisionen entre sí.

    `max_pendientes` (None = sin límite) acota cuántas propuestas *nuevas*
    se publican en esta llamada, en el orden en que aparecen en la agenda
    (la más vieja primero): evita que una cola acumulada (por ejemplo, tras
    un corte de la tarea programada) se vacíe entera de una sola vez — el
    resto queda igual de pendiente para la próxima corrida, no se pierde.
    Una urgente que ya estaba publicada por completo (ambas redes) no
    consume cupo: solo se limita el trabajo nuevo, nunca el reporte
    idempotente de lo ya hecho."""
    ahora_utc = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cliente_fb = cliente_fb or ClienteMetaGraphAPI()
    cliente_ig = cliente_ig or ClienteMetaGraphAPI()

    resultados = []
    publicadas_nuevas = 0
    for item in db.listar_agenda(fecha):
        if item["tipo"] != "urgente" or not item.get("noticia_id"):
            continue
        clave = f"urgente-{item['id']}"
        ya_completa = _programacion_ya_publicada(db, fecha, clave)
        if not ya_completa and max_pendientes is not None and publicadas_nuevas >= max_pendientes:
            continue  # deja esta pendiente para la próxima corrida
        resultados.append(
            _publicar_noticia_en_clave(db, fecha, clave, item["noticia_id"], cliente_fb, cliente_ig, ahora_utc)
        )
        if not ya_completa:
            publicadas_nuevas += 1
    return resultados


def reintentar_publicaciones(
    db: Database,
    cliente_fb: Optional[ClienteMetaGraphAPI] = None,
    cliente_ig: Optional[ClienteMetaGraphAPI] = None,
    max_intentos: int = MAX_INTENTOS_DEFAULT,
    ahora: Optional[datetime] = None,
    max_pendientes: Optional[int] = None,
) -> list:
    """Reintenta, de forma acotada (`max_intentos`), las filas de
    programacion_meta que quedaron en estado 'error'. Cada red social se
    reintenta de forma independiente: si Facebook ya está 'publicado' y solo
    Instagram falló, únicamente se reintenta Instagram (reutilizando el
    photo_id ya persistido, sin volver a subir la imagen); si Facebook
    todavía no publicó, Instagram sigue sin intentarse.

    Una clave de franja urgente (`"urgente-<agenda_item_id>"`, ver
    `publicar_urgentes`) se reintenta contra ese mismo agenda_item en vez de
    `obtener_agenda_item` (que solo indexa franjas fijas, `tipo='normal'`).

    `max_pendientes` (None = sin límite) acota cuántas franjas distintas se
    reintentan en esta llamada, empezando por la más vieja (`claves` ya
    viene ordenada por fecha/hora): el resto sigue en 'error' tal cual,
    disponible para la próxima corrida — no se pierde ni se descarta."""
    pendientes = db.listar_programacion_meta_para_reintentar(max_intentos)
    claves = sorted({(fila["fecha"], fila["hora"]) for fila in pendientes})
    if max_pendientes is not None:
        claves = claves[:max_pendientes]

    ahora_utc = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cliente_fb = cliente_fb or ClienteMetaGraphAPI()
    cliente_ig = cliente_ig or ClienteMetaGraphAPI()

    resultados = []
    for fecha, clave in claves:
        if clave.startswith("urgente-"):
            item = db.obtener_agenda_item_por_id(int(clave[len("urgente-"):]))
            if not item or not item.get("noticia_id"):
                resultados.append(ResultadoFranja(fecha, clave, None, "sin_contenido"))
                continue
            resultados.append(
                _publicar_noticia_en_clave(db, fecha, clave, item["noticia_id"], cliente_fb, cliente_ig, ahora_utc)
            )
        else:
            resultados.append(
                publicar_franja(db, fecha, clave, cliente_fb=cliente_fb, cliente_ig=cliente_ig, ahora=ahora)
            )
    return resultados
