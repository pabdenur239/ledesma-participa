from datetime import datetime, timedelta, timezone
from typing import List, NamedTuple, Optional

from .db import Database

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
    estado: str  # "creado" | "existente" | "sin_candidato"


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
        if existente and existente["noticia_id"]:
            usados.add(existente["noticia_id"])
            entradas.append(
                EntradaAgenda(fecha, hora, "normal", existente["territorio"], existente["noticia_id"], "existente")
            )
            continue

        candidato = _buscar_candidato_cascada(db, usados, fecha_limite)
        creada_en = datetime.now(timezone.utc).isoformat()
        id_existente = existente["id"] if existente else None

        if candidato:
            db.guardar_agenda_item(
                fecha, hora, "normal", candidato["territorio"], candidato["id"], creada_en,
                id_existente=id_existente,
            )
            usados.add(candidato["id"])
            entradas.append(EntradaAgenda(fecha, hora, "normal", candidato["territorio"], candidato["id"], "creado"))
        else:
            db.guardar_agenda_item(
                fecha, hora, "normal", None, None, creada_en, id_existente=id_existente
            )
            entradas.append(EntradaAgenda(fecha, hora, "normal", None, None, "sin_candidato"))

    return entradas
