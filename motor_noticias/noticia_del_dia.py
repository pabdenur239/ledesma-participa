"""Noticia del Día: una franja fija diaria (13:00, fuera de HORARIOS_DEFAULT,
agregada 20/8/2026) que reserva la mejor noticia REAL disponible del día,
siguiendo la prioridad LOCAL → DEPARTAMENTAL → PROVINCIAL → NACIONAL →
INTERNACIONAL — nunca entretenimiento/curiosidades ("sin sensacionalismo
innecesario"): si no hay nada mejor que eso disponible, la franja queda
`sin_candidato` ese día en vez de forzar algo de menor jerarquía editorial.

No crea ninguna noticia sintética (a diferencia de institucional/informe
diario): reutiliza tal cual una noticia real ya recolectada y preparada, lo
que además la excluye automáticamente de cualquier otra franja normal vía
`noticias_ids_usadas_en_agenda` — nunca se publica dos veces. El "formato
destacado" (mejor imagen ya elegida por el pipeline normal, encabezado
distintivo) se aplica solo al momento de publicar esta franja puntual (ver
`motor_noticias.meta.publicador`), sin tocar el registro guardado de la
noticia."""
from datetime import datetime, timezone
from typing import Optional

from .db import Database
from .models import Estado, RevisionEstado
from .motor_editorial import (
    EntradaAgenda,
    HORA_NOTICIA_DEL_DIA,
    ORDEN_CASCADA,
    ZONA_JUJUY,
    _fecha_limite_antiguedad,
)

# Prioridad específica de Noticia del Día: igual que ORDEN_CASCADA
# (local→departamental→provincial→nacional) más "internacional" al final,
# vía categoria_tematica (fuentes agregadas 20/8/2026: BBC Mundo, France 24
# Español). A diferencia de la cascada normal, nunca cae a entretenimiento/
# curiosidades genéricas: esta franja es para la noticia más relevante del
# día, no para completar un hueco.
CATEGORIA_TEMATICA_INTERNACIONAL = "internacional"

REVISIONES_PROTEGIDAS = (RevisionEstado.APROBADA.value, RevisionEstado.RECHAZADA.value)


def _mejor_noticia_del_dia(db: Database, usados: set, fecha_limite: str) -> Optional[dict]:
    for territorio in ORDEN_CASCADA:
        candidato = db.candidato_editorial(territorio, usados, fecha_limite)
        if candidato:
            return candidato
    return db.candidato_tematico(CATEGORIA_TEMATICA_INTERNACIONAL, usados, fecha_limite)


def reservar_franja_noticia_del_dia(
    db: Database, fecha: Optional[str] = None, ahora: Optional[datetime] = None
) -> EntradaAgenda:
    """Reserva (si no existe todavía o si sigue sin decisión humana) la
    franja fija de Noticia del Día. Idempotente y segura de llamar
    repetidas veces por ciclo, con las mismas protecciones que cualquier
    otra franja fija: nunca pisa una decisión humana (aprobada/rechazada)
    ni una franja ya pasada previamente evaluada."""
    ahora_local = (ahora or datetime.now(ZONA_JUJUY)).astimezone(ZONA_JUJUY)
    fecha = fecha or ahora_local.strftime("%Y-%m-%d")
    hora = HORA_NOTICIA_DEL_DIA

    existente = db.obtener_agenda_item(fecha, hora)
    noticia_existente = db.obtener(existente["noticia_id"]) if existente and existente["noticia_id"] else None

    protegido = noticia_existente is not None and (
        noticia_existente["revision_estado"] in REVISIONES_PROTEGIDAS
        or noticia_existente["estado"] == Estado.PUBLICADA.value
    )
    if protegido:
        return EntradaAgenda(fecha, hora, "normal", existente["territorio"], existente["noticia_id"], "existente")

    momento_franja = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONA_JUJUY)
    if existente is not None and momento_franja <= ahora_local:
        if noticia_existente is not None:
            return EntradaAgenda(fecha, hora, "normal", existente["territorio"], existente["noticia_id"], "existente")
        return EntradaAgenda(fecha, hora, "normal", None, None, "sin_candidato")

    ahora_utc = ahora_local.astimezone(timezone.utc)
    fecha_limite = _fecha_limite_antiguedad(ahora_utc)
    usados = db.noticias_ids_usadas_en_agenda()
    id_existente_noticia = noticia_existente["id"] if noticia_existente else None
    usados_para_busqueda = usados - {id_existente_noticia} if id_existente_noticia else usados

    candidato = _mejor_noticia_del_dia(db, usados_para_busqueda, fecha_limite)
    id_existente_item = existente["id"] if existente else None

    if candidato:
        if candidato["id"] == id_existente_noticia:
            return EntradaAgenda(fecha, hora, "normal", candidato["territorio"], candidato["id"], "existente")
        creada_en = datetime.now(timezone.utc).isoformat()
        db.guardar_agenda_item(
            fecha, hora, "normal", candidato["territorio"], candidato["id"], creada_en,
            id_existente=id_existente_item,
        )
        estado_entrada = "actualizado" if id_existente_item else "creado"
        return EntradaAgenda(fecha, hora, "normal", candidato["territorio"], candidato["id"], estado_entrada)

    if id_existente_item is None or existente.get("noticia_id") is not None:
        creada_en = datetime.now(timezone.utc).isoformat()
        db.guardar_agenda_item(fecha, hora, "normal", None, None, creada_en, id_existente=id_existente_item)
    return EntradaAgenda(fecha, hora, "normal", None, None, "sin_candidato")
