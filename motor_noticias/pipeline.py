import html
import logging
import re
from dataclasses import asdict, fields
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from .calidad_editorial import evaluar_calidad
from .collectors.base import Collector
from .db import Database
from .dedupe import hash_contenido, normalizar_url
from .elegibilidad_editorial import evaluar_elegibilidad_editorial
from .entretenimiento import es_entretenimiento_o_curiosidad
from .models import Estado, Noticia, RevisionEstado
from .redaccion.base import Redactor
from .riesgo_editorial import evaluar_riesgo_editorial
from .scoring_editorial import es_urgente, evaluar_noticia
from .territorio import clasificar_territorio

logger = logging.getLogger("motor_noticias.pipeline")

# Marca en `observacion_interna` (privada) cuando la redacción automática
# falló y se conservó el texto original de la fuente.
MARCA_SIN_REDACCION = "sin_redaccion_automatica"

# Sin redacción propia (cierre del canal rápido, 9/10/2026): si la redacción
# automática falla, o el texto preparado termina siendo una copia literal
# extensa del texto de la fuente (fallback seguro del redactor o control de
# calidad que vuelve al original), la noticia NO sigue a ningún circuito
# automático: queda en revisión con esta categoría de riesgo (que no es
# revisable para el portal), el original se conserva solo como referencia
# interna y la redacción se puede reintentar desde el panel. Hasta este largo
# una coincidencia literal se considera cita breve (siempre atribuida).
CATEGORIA_SIN_REDACCION_PROPIA = "sin_redaccion_propia"
LONGITUD_MAXIMA_CITA_LITERAL = 300

# Internacional para web/app (cobertura 9/10/2026): una internacional que
# no es entretenimiento ya no se descarta si pasa el gate mínimo de calidad
# y tiene al menos este puntaje base del scoring editorial único (filtro
# mínimo de relevancia: una cumbre o una suba de tasas sí, una muestra de
# museo no). Queda en estado `solo_portal`: nunca entra a franjas, urgentes,
# Stories ni push (todas esas consultas piden `preparada`); el portal toma
# como máximo `portal.TOPES_POR_TERRITORIO["internacional"]` por día.
BASE_MINIMA_INTERNACIONAL_PORTAL = 30

# Territorios que hoy ya se preparan siempre (igual que el comportamiento
# histórico de `relevancia_local`): local y departamental.
TERRITORIOS_SIEMPRE_ELEGIBLES = ("local", "departamental")
# Territorios que solo se preparan si además pasan el gate mínimo de calidad
# editorial (`evaluar_elegibilidad_editorial`): provincial y nacional.
TERRITORIOS_CON_GATE_EDITORIAL = ("provincial", "nacional")


def _aplicar_riesgo_editorial(noticia: Noticia) -> None:
    resultado = evaluar_riesgo_editorial(
        noticia.titulo_original,
        noticia.texto_original,
        noticia.titulo_preparado,
        noticia.texto_preparado,
        noticia.nombre_fuente,
    )
    noticia.requiere_revision_especial = resultado["requiere_revision_especial"]
    noticia.categoria_riesgo = resultado["categoria_riesgo"]
    noticia.motivo_revision_especial = resultado["motivo"]


def _normalizar_espacios(texto: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (texto or "").strip().lower())


def es_copia_literal_extensa(texto_original: Optional[str], texto_preparado: Optional[str]) -> bool:
    """True si el texto preparado es (o está contenido literalmente en) el
    texto de la fuente y supera el largo de una cita breve."""
    original = _normalizar_espacios(texto_original)
    preparado = _normalizar_espacios(texto_preparado)
    if len(preparado) <= LONGITUD_MAXIMA_CITA_LITERAL:
        return False
    return preparado == original or preparado in original


def _marcar_sin_redaccion_propia(noticia: Noticia, motivo: str) -> None:
    detalle = (
        f"Sin redacción propia ({motivo}): queda en revisión; el texto de la fuente se "
        "conserva solo como referencia interna. Reintentar la redacción desde el panel."
    )
    if noticia.requiere_revision_especial and noticia.categoria_riesgo != CATEGORIA_SIN_REDACCION_PROPIA:
        # Ya retenida por otro riesgo: esta categoría manda igual (no es
        # revisable, así una aprobación humana del otro riesgo nunca lleva la
        # copia al portal) y se conserva el motivo anterior. Al reintentar la
        # redacción, el riesgo editorial se reevalúa desde cero.
        detalle = f"{detalle} | Riesgo previo: {noticia.categoria_riesgo} — {noticia.motivo_revision_especial or ''}"
    noticia.requiere_revision_especial = True
    noticia.categoria_riesgo = CATEGORIA_SIN_REDACCION_PROPIA
    noticia.motivo_revision_especial = detalle


def normalizar_noticia(cruda: dict) -> Noticia:
    """`titulo`/`texto` pasan por `html.unescape` acá, en el único punto por
    el que pasa la salida de cualquier collector (RSS, scraper HTML o carga
    manual) antes de guardarse como `titulo_original`/`texto_original`: de
    ahí se derivan titulo_preparado/texto_preparado (`redactor.redactar`,
    ver pipeline) y, con eso, tanto el post de Facebook/Instagram
    (`meta/contenido.py`) como el sitio web (`sitio/generador.py`) — un
    único lugar decodifica para los tres. No todos los collectors decodían
    entidades HTML ellos mismos (bug real detectado: el feed de Jujuy al
    día dejaba pasar `&#8211;`/`&#8217;` tal cual, sin decodificar). `url`
    nunca se toca acá: una entidad real en un query string (poco común,
    pero válida) no debe alterarse."""
    imagen_url = cruda.get("imagen_url") or None
    return Noticia(
        id=None,
        titulo_original=html.unescape(cruda["titulo"]).strip(),
        texto_original=html.unescape(cruda["texto"]).strip(),
        url_fuente=cruda["url"].strip(),
        nombre_fuente=cruda.get("fuente", "").strip(),
        fecha_fuente=cruda.get("fecha", ""),
        fecha_recoleccion=datetime.now(timezone.utc).isoformat(),
        estado=Estado.ENCONTRADA.value,
        hash_contenido="",
        localidad=cruda.get("localidad") or None,
        tiene_imagen_original=bool(imagen_url),
        imagen_publicacion_ruta=imagen_url,
        categoria_tematica=cruda.get("categoria_tematica") or None,
    )


def procesar_noticia(
    db: Database,
    noticia: Noticia,
    redactor: Redactor,
    categoria: Optional[str] = None,
    clave_dedup: Optional[str] = None,
    territorio_forzado: Optional[str] = None,
    tolerar_fallo_redaccion: bool = False,
) -> Tuple[Noticia, str]:
    """`clave_dedup` (opcional): cuando se pasa, la deduplicación de ingreso
    se hace contra esa clave sintética (URL de identidad propia) en vez de
    contra `url_fuente` + hash del texto original. Lo usa la reelaboración
    de contenido propio (`motor_noticias.contenido_propio`): una nota propia
    reescrita a partir de una noticia de un medio conserva `url_fuente` = URL
    real del medio (para la atribución "Fuente y nota completa:"), pero no
    debe contar como duplicado de esa misma noticia del medio ya recolectada.
    La clave sintética es única y estable por noticia de origen, así que
    reintentar la reelaboración de la misma nota sigue siendo idempotente.

    `territorio_forzado` (opcional): la reelaboración parte de una noticia de
    medio YA clasificada y vetada por el sistema (provincial o nacional);
    hereda ese territorio en vez de reclasificar el texto reescrito, que
    puede quedar `sin_clasificar` al perder alguna mención geográfica en la
    reescritura. El riesgo editorial sí se reevalúa siempre sobre el texto
    final.

    `tolerar_fallo_redaccion`: lo usa la recolección (`ejecutar_pipeline`):
    si el redactor (Ollama) falla o no responde, se conserva el texto
    original y la noticia sigue su circuito en vez de tumbar la fuente
    entera. La reelaboración de contenido propio NO lo usa: sin redacción
    no hay nota propia."""
    if clave_dedup:
        noticia.url_normalizada = normalizar_url(clave_dedup)
        noticia.hash_contenido = hash_contenido(clave_dedup, "")
    else:
        noticia.url_normalizada = normalizar_url(noticia.url_fuente)
        noticia.hash_contenido = hash_contenido(noticia.titulo_original, noticia.texto_original)

    clasificacion = clasificar_territorio(
        noticia.titulo_original,
        noticia.texto_original,
        localidad_fuente=noticia.localidad,
        nombre_fuente=noticia.nombre_fuente,
        url=noticia.url_fuente,
        categoria=categoria,
    )
    # `relevancia_local` conserva exactamente el mismo significado que tenía
    # antes de la cascada editorial: relación directa con Libertador o el
    # Departamento Ledesma (nunca se infiere ni se relaja para provincial/
    # nacional). La clasificación territorial es información nueva, aparte.
    noticia.relevancia_local = clasificacion["relevante"]
    noticia.motivo_relevancia = clasificacion["motivo_relevancia"]
    noticia.localidad = clasificacion["localidad"]
    if territorio_forzado:
        noticia.territorio = territorio_forzado
        noticia.motivo_territorio = (
            f"Territorio heredado de la noticia de origen ({territorio_forzado})."
        )
    else:
        noticia.territorio = clasificacion["territorio"]
        noticia.motivo_territorio = clasificacion["motivo_territorio"]

    if db.existe_duplicado(noticia.url_normalizada, noticia.hash_contenido):
        db.registrar_descarte(
            titulo=noticia.titulo_original,
            motivo="duplicado",
            fuente=noticia.nombre_fuente,
            localidad=noticia.localidad,
            territorio=noticia.territorio,
        )
        return noticia, "duplicado"

    motivo_descarte = None
    if noticia.territorio in TERRITORIOS_SIEMPRE_ELEGIBLES:
        apta_para_preparar = True
    elif noticia.territorio in TERRITORIOS_CON_GATE_EDITORIAL:
        # Provincial/nacional no tienen relevancia_local, pero igual pueden
        # prepararse si superan un gate mínimo de calidad editorial (sin IA):
        # solo quedan disponibles para la cascada cuando falte contenido
        # local/departamental, nunca reemplazan a `relevancia_local`.
        gate = evaluar_elegibilidad_editorial(
            noticia.titulo_original, noticia.texto_original, noticia.nombre_fuente
        )
        apta_para_preparar = gate["elegible"]
        if not apta_para_preparar:
            motivo_descarte = ("fuente_insuficiente", gate["motivo"])
    else:  # sin_clasificar: solo se prepara como último recurso editorial
        # (cascada nivel 5) si además de pasar el mismo gate mínimo de
        # calidad que provincial/nacional, es contenido de entretenimiento/
        # espectáculos/curiosidades/tendencia viral verificable. Cualquier
        # otro contenido sin_clasificar sigue sin prepararse, igual que hoy.
        gate = evaluar_elegibilidad_editorial(
            noticia.titulo_original, noticia.texto_original, noticia.nombre_fuente
        )
        apta_para_preparar = gate["elegible"] and es_entretenimiento_o_curiosidad(
            noticia.titulo_original, noticia.texto_original
        )
        if not apta_para_preparar:
            motivo_descarte = (
                ("fuente_insuficiente", gate["motivo"]) if not gate["elegible"]
                else ("fuera_de_alcance", noticia.motivo_territorio)
            )
        if not apta_para_preparar and gate["elegible"] and _es_internacional(noticia):
            if evaluar_noticia(asdict(noticia))["base"] >= BASE_MINIMA_INTERNACIONAL_PORTAL:
                return _guardar_solo_portal(db, noticia)

    if not apta_para_preparar:
        noticia.estado = Estado.DESCARTADA.value
        _aplicar_riesgo_editorial(noticia)
        db.guardar(noticia)
        motivo, detalle = motivo_descarte or ("otro", None)
        db.registrar_descarte(
            titulo=noticia.titulo_original,
            motivo=motivo,
            fuente=noticia.nombre_fuente,
            localidad=noticia.localidad,
            territorio=noticia.territorio,
            detalle=detalle,
            noticia_id=noticia.id,
        )
        return noticia, "descartada"

    fallo_redaccion = None
    try:
        titulo_preparado, texto_preparado = redactor.redactar(noticia)
    except Exception as error:  # Ollama caído o lento: no debe tumbar la fuente entera
        if not tolerar_fallo_redaccion:
            raise
        fallo_redaccion = str(error)[:200]
        # Se conserva el texto original (mismo criterio que el fallback
        # seguro del redactor) y se deja constancia interna de que no hubo
        # redacción automática; la noticia sigue el circuito normal.
        logger.warning("Redacción automática falló para '%s' (%s): %s", noticia.titulo_original[:80], noticia.nombre_fuente, error)
        titulo_preparado = noticia.titulo_original
        texto_preparado = noticia.texto_original or noticia.titulo_original
        if not noticia.observacion_interna:
            noticia.observacion_interna = f"{MARCA_SIN_REDACCION}: {str(error)[:200]}"
        else:
            noticia.observacion_interna = f"{MARCA_SIN_REDACCION}: {str(error)[:200]} | {noticia.observacion_interna}"
    noticia.titulo_preparado = titulo_preparado
    noticia.texto_preparado = texto_preparado
    # Control de calidad (calidad_editorial): si la redacción automática
    # introdujo algo que la fuente no dice (número nuevo, nombre deformado,
    # fecha imposible) y el texto de la fuente está bien, se usa el de la
    # fuente. Nunca se inventa nada para "reparar" un texto.
    calidad = evaluar_calidad(asdict(noticia))
    if calidad.accion == "usar_original":
        noticia.titulo_preparado = noticia.titulo_original
        noticia.texto_preparado = noticia.texto_original
        calidad = evaluar_calidad(asdict(noticia))
    noticia.estado = Estado.PREPARADA.value
    noticia.revision_estado = RevisionEstado.PENDIENTE.value
    # Circuito inmediato (scoring editorial único, 2/10/2026): ya NO se
    # marca urgente cualquier local/departamental por el solo hecho de ser
    # local. Se marca solo si `scoring_editorial` la clasifica URGENTE
    # (local con relevancia suficiente, o provincial/nacional
    # extraordinaria). Nunca se desmarca una que ya venía tildada a mano
    # desde el panel. El resto compite en las franjas programadas.
    # `candidatos_urgentes` / `resolver_urgentes` / `publicar_urgentes`
    # siguen excluyendo por su cuenta riesgo editorial obligatorio y
    # rechazadas.
    if not noticia.urgente:
        noticia.urgente = es_urgente(asdict(noticia))
    _aplicar_riesgo_editorial(noticia)
    if calidad.accion == "retener" and not noticia.requiere_revision_especial:
        # No se puede corregir con seguridad (cuerpo vacío o que repite el
        # título, titular-metadata, errata de la propia fuente): queda
        # retenida para revisión humana, igual que el riesgo editorial, y no
        # entra en ningún circuito automático.
        noticia.requiere_revision_especial = True
        noticia.categoria_riesgo = "calidad_editorial"
        noticia.motivo_revision_especial = "Control de calidad: " + "; ".join(calidad.problemas)
    if fallo_redaccion is not None:
        _marcar_sin_redaccion_propia(noticia, f"falló la redacción automática: {fallo_redaccion}")
    elif not getattr(redactor, "texto_propio", False) and es_copia_literal_extensa(
        noticia.texto_original, noticia.texto_preparado
    ):
        # `texto_propio`: redactores identidad del informe diario y del
        # contenido propio. Su "texto original" lo arma Ledesma Participa
        # (no es de un tercero), así que repetirlo no es copia de la fuente.
        _marcar_sin_redaccion_propia(noticia, "el texto preparado repite literalmente el de la fuente")
    db.guardar(noticia)
    return noticia, "preparada"


def reintentar_redaccion(db: Database, id_noticia: int, redactor: Redactor) -> Tuple[bool, str]:
    """Reintento manual (panel) de una noticia retenida sin redacción
    propia. Solo libera la noticia si ahora hay redacción propia que pase el
    control de calidad; el riesgo editorial se reevalúa sobre el texto nuevo.
    Devuelve (liberada, mensaje para el operador)."""
    fila = db.obtener(id_noticia)
    if not fila or fila.get("categoria_riesgo") != CATEGORIA_SIN_REDACCION_PROPIA:
        return False, "La noticia no está retenida por falta de redacción propia."
    campos = {f.name for f in fields(Noticia)}
    noticia = Noticia(**{k: v for k, v in fila.items() if k in campos})
    try:
        titulo_preparado, texto_preparado = redactor.redactar(noticia)
    except Exception as error:
        return False, f"La redacción automática sigue sin responder ({str(error)[:120]}). Reintentá más tarde."
    noticia.titulo_preparado, noticia.texto_preparado = titulo_preparado, texto_preparado
    calidad = evaluar_calidad(asdict(noticia))
    if calidad.accion != "publicar" or es_copia_literal_extensa(noticia.texto_original, texto_preparado):
        return False, "La nueva redacción no es propia o no pasó el control de calidad: sigue en revisión."
    noticia.requiere_revision_especial = False
    noticia.categoria_riesgo = None
    noticia.motivo_revision_especial = None
    _aplicar_riesgo_editorial(noticia)
    db.actualizar_redaccion(
        id_noticia, titulo_preparado, texto_preparado,
        bool(noticia.requiere_revision_especial), noticia.categoria_riesgo, noticia.motivo_revision_especial,
    )
    if noticia.requiere_revision_especial:
        return True, "Redacción propia generada; sigue en revisión por riesgo editorial."
    return True, "Redacción propia generada: la noticia vuelve al circuito normal."


def _es_internacional(noticia: Noticia) -> bool:
    return noticia.territorio == "internacional" or (
        noticia.territorio in (None, "sin_clasificar") and noticia.categoria_tematica == "internacional"
    )


def _guardar_solo_portal(db: Database, noticia: Noticia) -> Tuple[Noticia, str]:
    """Internacional relevante solo para web/app: texto original de la
    fuente (sin redacción automática), riesgo editorial evaluado igual que
    siempre (con riesgo no entra al portal), nunca urgente."""
    noticia.titulo_preparado = noticia.titulo_original
    noticia.texto_preparado = noticia.texto_original or noticia.titulo_original
    noticia.estado = Estado.SOLO_PORTAL.value
    noticia.revision_estado = RevisionEstado.PENDIENTE.value
    noticia.urgente = False
    _aplicar_riesgo_editorial(noticia)
    db.guardar(noticia)
    return noticia, "solo_portal"


def ejecutar_pipeline(
    db: Database, collector: Collector, redactor: Redactor
) -> List[Tuple[Noticia, str]]:
    resultados = []
    for cruda in collector.recolectar():
        noticia = normalizar_noticia(cruda)
        resultados.append(procesar_noticia(
            db, noticia, redactor, categoria=cruda.get("categoria"), tolerar_fallo_redaccion=True
        ))
    return resultados
