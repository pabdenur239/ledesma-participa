from datetime import datetime, timedelta, timezone
from typing import List, NamedTuple, Optional

from .db import Database
from .models import Estado, RevisionEstado

# Estados de la propia noticia que congelan su espacio en la agenda: una vez
# que un humano decidió (aprobó/rechazó) o la noticia ya se publicó, el
# Motor Editorial nunca la reemplaza automáticamente. "pendiente" (sin
# decisión humana todavía) y "sin_candidato" sí se pueden actualizar en cada
# regeneración si aparece un candidato mejor.
REVISIONES_PROTEGIDAS = (RevisionEstado.APROBADA.value, RevisionEstado.RECHAZADA.value)

# Argentina (y Jujuy en particular) usa un único huso horario fijo, UTC-3,
# sin horario de verano desde 2009. Se usa un offset fijo en vez de
# zoneinfo.ZoneInfo("America/Argentina/Jujuy") para no depender de que el
# sistema operativo tenga la base de datos IANA de zonas horarias instalada
# (Windows no la trae por defecto salvo instalar el paquete `tzdata`, y el
# proyecto es exclusivamente stdlib + Pillow).
ZONA_JUJUY = timezone(timedelta(hours=-3), name="America/Argentina/Jujuy")

HORARIOS_DEFAULT = ("08:00", "10:30", "13:00", "16:00", "19:00", "21:30")
ANTIGUEDAD_MAXIMA_HORAS = 48
ORDEN_CASCADA = ("local", "departamental", "provincial", "nacional")


class EntradaAgenda(NamedTuple):
    fecha: str
    hora: Optional[str]
    tipo: str  # "normal" | "urgente"
    territorio: Optional[str]
    noticia_id: Optional[int]
    estado: str  # "creado" | "actualizado" | "existente" | "sin_candidato"


def _fecha_limite_antiguedad(ahora_utc: datetime) -> str:
    return (ahora_utc - timedelta(hours=ANTIGUEDAD_MAXIMA_HORAS)).isoformat()


def _buscar_candidato_cascada(db: Database, usados: set, fecha_limite: str) -> Optional[dict]:
    """Recorre la cascada territorial obligatoria (local → departamental →
    provincial → nacional) y devuelve el primer candidato apto que
    encuentre. Nunca elige un nivel inferior si existe uno superior apto."""
    for territorio in ORDEN_CASCADA:
        candidato = db.candidato_editorial(territorio, usados, fecha_limite)
        if candidato:
            return candidato
    return None


def generar_agenda(
    db: Database,
    fecha: Optional[str] = None,
    horarios=HORARIOS_DEFAULT,
    ahora: Optional[datetime] = None,
) -> List[EntradaAgenda]:
    """Genera (o completa) la agenda editorial de un día: un candidato por
    franja horaria siguiendo la cascada territorial, más cualquier noticia
    local/departamental marcada urgente como propuesta aparte. Nunca publica
    nada ni reemplaza un espacio que ya tiene una noticia asignada (eso es lo
    que preserva las decisiones humanas ante una regeneración). Si un espacio
    sigue en `sin_candidato`, se reintenta en cada llamada por si ya hay
    contenido nuevo disponible."""
    # Se normaliza siempre a Jujuy, sin importar en qué huso venga `ahora`
    # (propio o inyectado en un test), para que la fecha del día se calcule
    # de forma consistente con America/Argentina/Jujuy y no con UTC u otro
    # huso horario del entorno de ejecución.
    ahora = (ahora or datetime.now(ZONA_JUJUY)).astimezone(ZONA_JUJUY)
    fecha = fecha or ahora.strftime("%Y-%m-%d")
    ahora_utc = ahora.astimezone(timezone.utc)
    fecha_limite = _fecha_limite_antiguedad(ahora_utc)

    usados = db.noticias_ids_usadas_en_agenda()
    entradas: List[EntradaAgenda] = []

    # Las urgentes se resuelven primero: si una noticia local/departamental
    # urgente fuera además el mejor candidato "normal" disponible, tiene que
    # salir como propuesta urgente aparte, no consumirse en una franja fija.
    for urgente in db.candidatos_urgentes(usados, fecha_limite):
        creada_en = datetime.now(timezone.utc).isoformat()
        db.guardar_agenda_item(fecha, None, "urgente", urgente["territorio"], urgente["id"], creada_en)
        usados.add(urgente["id"])
        entradas.append(EntradaAgenda(fecha, None, "urgente", urgente["territorio"], urgente["id"], "creado"))

    for hora in horarios:
        existente = db.obtener_agenda_item(fecha, hora)
        noticia_existente = db.obtener(existente["noticia_id"]) if existente and existente["noticia_id"] else None

        protegido = noticia_existente is not None and (
            noticia_existente["revision_estado"] in REVISIONES_PROTEGIDAS
            or noticia_existente["estado"] == Estado.PUBLICADA.value
        )
        if protegido:
            usados.add(noticia_existente["id"])
            entradas.append(
                EntradaAgenda(fecha, hora, "normal", existente["territorio"], existente["noticia_id"], "existente")
            )
            continue

        # El espacio no está protegido (sin candidato todavía, o con una
        # propuesta que sigue "pendiente" de decisión humana): se busca de
        # nuevo el mejor candidato disponible. Se excluye temporalmente al
        # propio ocupante actual de la búsqueda de "usados" para poder
        # compararlo contra el resto sin descalificarlo a él mismo; si sigue
        # siendo el mejor, la búsqueda lo vuelve a encontrar y no cambia nada.
        id_existente_noticia = noticia_existente["id"] if noticia_existente else None
        usados_para_busqueda = usados - {id_existente_noticia} if id_existente_noticia else usados
        candidato = _buscar_candidato_cascada(db, usados_para_busqueda, fecha_limite)
        id_existente_item = existente["id"] if existente else None

        if candidato:
            usados.add(candidato["id"])
            if candidato["id"] == id_existente_noticia:
                # mismo candidato de antes: nada que actualizar en la base.
                entradas.append(
                    EntradaAgenda(fecha, hora, "normal", candidato["territorio"], candidato["id"], "existente")
                )
            else:
                creada_en = datetime.now(timezone.utc).isoformat()
                db.guardar_agenda_item(
                    fecha, hora, "normal", candidato["territorio"], candidato["id"], creada_en,
                    id_existente=id_existente_item,
                )
                estado_entrada = "actualizado" if id_existente_item else "creado"
                entradas.append(
                    EntradaAgenda(fecha, hora, "normal", candidato["territorio"], candidato["id"], estado_entrada)
                )
        else:
            if id_existente_item is None or existente.get("noticia_id") is not None:
                # o es la primera vez, o antes tenía candidato y ahora ya no
                # (por ejemplo, envejeció): hay que dejar constancia.
                creada_en = datetime.now(timezone.utc).isoformat()
                db.guardar_agenda_item(
                    fecha, hora, "normal", None, None, creada_en, id_existente=id_existente_item
                )
            entradas.append(EntradaAgenda(fecha, hora, "normal", None, None, "sin_candidato"))

    return entradas
