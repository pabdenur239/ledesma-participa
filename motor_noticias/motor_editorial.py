from datetime import datetime, timedelta, timezone
from typing import List, NamedTuple, Optional

from .db import Database
from .dedupe import normalizar_url
from .models import Estado, RevisionEstado
from .verificacion_fuente import ResultadoVerificacionLocal, verificar_impacto_local_concreto

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

# Franjas fijas de la Agenda Editorial / programación de publicación en Meta.
# 07:30 está reservada exclusivamente al informe diario (clima/dólar, ver
# `reservar_franja_informe_diario`); las 9 franjas restantes siguen la
# cascada territorial normal. Entre las 10, cubren el volumen diario de 6-10
# contenidos pedido para la publicación automática en Meta.
HORA_INFORME_DIARIO = "07:30"
HORARIOS_DEFAULT = (
    "09:30", "11:30", "13:30", "15:30", "17:30", "19:00", "20:30", "21:30", "22:30",
)
ANTIGUEDAD_MAXIMA_HORAS = 48
# Línea editorial: local y departamental son siempre elegibles (ya vienen
# verificados por su propio título/texto). "provincial" ya NO es un nivel de
# respaldo automático: solo se acepta si `verificar_impacto_local_concreto`
# confirma, contra el HTML real de la fuente, que el artículo completo sí
# tiene relación directa con Libertador o el Departamento Ledesma (un
# extracto recortado por el recolector puede perder esa mención). "nacional"
# nunca se elige de forma automática: una franja sin candidato local,
# departamental o provincial-verificado queda vacía en vez de rellenarse.
ORDEN_CASCADA_AUTOMATICA = ("local", "departamental")


class EntradaAgenda(NamedTuple):
    fecha: str
    hora: Optional[str]
    tipo: str  # "normal" | "urgente"
    territorio: Optional[str]
    noticia_id: Optional[int]
    estado: str  # "creado" | "actualizado" | "existente" | "sin_candidato"


def _fecha_limite_antiguedad(ahora_utc: datetime) -> str:
    return (ahora_utc - timedelta(hours=ANTIGUEDAD_MAXIMA_HORAS)).isoformat()


def _es_franja_pasada(fecha: str, hora: str, ahora: datetime) -> bool:
    """Una franja ya pasada (según `ahora`, en America/Argentina/Jujuy) no
    admite más candidatos automáticos: evita propuestas retrospectivas."""
    momento = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONA_JUJUY)
    return momento <= ahora


def _buscar_candidato_cascada(
    db: Database,
    usados: set,
    fecha_limite: str,
    verificar_impacto_provincial,
    provinciales_rechazados: set,
) -> Optional[dict]:
    """Recorre local → departamental (siempre elegibles) y, solo si ninguno
    tiene candidato, intenta UNA excepción provincial verificada contra la
    fuente real. Nunca elige nacional. Nunca elige un nivel inferior si
    existe uno superior apto."""
    for territorio in ORDEN_CASCADA_AUTOMATICA:
        candidato = db.candidato_editorial(territorio, usados, fecha_limite)
        if candidato:
            return candidato

    candidato_provincial = db.candidato_editorial(
        "provincial", usados | provinciales_rechazados, fecha_limite
    )
    if not candidato_provincial:
        return None

    resultado: ResultadoVerificacionLocal = verificar_impacto_provincial(candidato_provincial["url_fuente"])
    if resultado.impacto_local:
        return candidato_provincial

    provinciales_rechazados.add(candidato_provincial["id"])
    return None


def reservar_franja_informe_diario(
    db: Database, fecha: Optional[str] = None, ahora: Optional[datetime] = None
) -> EntradaAgenda:
    """Reserva la franja fija 07:30 para el informe diario (clima/dólar) del
    día, si ya fue generado (ver `informe_diario.generar_informe_diario`,
    misma identidad determinística por URL). Se llama antes de `generar_agenda`
    para que esa noticia quede excluida de la cascada de las demás franjas
    (vía `noticias_ids_usadas_en_agenda`). Sigue exactamente las mismas
    protecciones que cualquier otra franja: nunca pisa una decisión humana
    (aprobada/rechazada) ni una franja ya pasada previamente evaluada."""
    ahora = (ahora or datetime.now(ZONA_JUJUY)).astimezone(ZONA_JUJUY)
    fecha = fecha or ahora.strftime("%Y-%m-%d")
    hora = HORA_INFORME_DIARIO

    existente = db.obtener_agenda_item(fecha, hora)
    noticia_existente = db.obtener(existente["noticia_id"]) if existente and existente["noticia_id"] else None

    protegido = noticia_existente is not None and (
        noticia_existente["revision_estado"] in REVISIONES_PROTEGIDAS
        or noticia_existente["estado"] == Estado.PUBLICADA.value
    )
    if protegido:
        return EntradaAgenda(fecha, hora, "normal", existente["territorio"], existente["noticia_id"], "existente")

    if existente is not None and _es_franja_pasada(fecha, hora, ahora):
        if noticia_existente is not None:
            return EntradaAgenda(fecha, hora, "normal", existente["territorio"], existente["noticia_id"], "existente")
        return EntradaAgenda(fecha, hora, "normal", None, None, "sin_candidato")

    id_existente_item = existente["id"] if existente else None
    url_informe = normalizar_url(f"https://ledesma-participa.local/informe-diario/{fecha}")
    informe = db.obtener_por_url(url_informe)

    apto = (
        informe is not None
        and informe["estado"] == Estado.PREPARADA.value
        and informe["revision_estado"] != RevisionEstado.RECHAZADA.value
    )
    if apto:
        if informe["id"] == (noticia_existente["id"] if noticia_existente else None):
            return EntradaAgenda(fecha, hora, "normal", informe.get("territorio"), informe["id"], "existente")
        creada_en = datetime.now(timezone.utc).isoformat()
        db.guardar_agenda_item(
            fecha, hora, "normal", informe.get("territorio"), informe["id"], creada_en,
            id_existente=id_existente_item,
        )
        estado_entrada = "actualizado" if id_existente_item else "creado"
        return EntradaAgenda(fecha, hora, "normal", informe.get("territorio"), informe["id"], estado_entrada)

    if id_existente_item is None or existente.get("noticia_id") is not None:
        creada_en = datetime.now(timezone.utc).isoformat()
        db.guardar_agenda_item(fecha, hora, "normal", None, None, creada_en, id_existente=id_existente_item)
    return EntradaAgenda(fecha, hora, "normal", None, None, "sin_candidato")


def generar_agenda(
    db: Database,
    fecha: Optional[str] = None,
    horarios=HORARIOS_DEFAULT,
    ahora: Optional[datetime] = None,
    verificar_impacto_provincial=None,
) -> List[EntradaAgenda]:
    """Genera (o completa) la agenda editorial de un día: un candidato por
    franja horaria siguiendo la cascada territorial, más cualquier noticia
    local/departamental marcada urgente como propuesta aparte. Nunca publica
    nada. Pensada para poder llamarse repetidamente (p.ej. desde el Motor
    Continuo, una vez por ciclo tras consultar todas las fuentes) sin pisar
    nada que no deba pisar:

    - `aprobada`, `rechazada` y `publicada` nunca se tocan.
    - Una franja futura sin decisión humana (`pendiente` o `sin_candidato`)
      se reevalúa en cada llamada: puede mejorar si aparece un candidato de
      mayor prioridad territorial (o más reciente dentro del mismo nivel).
    - Una franja ya pasada (según `ahora`, en America/Argentina/Jujuy) que
      ya fue evaluada antes queda congelada tal cual quedó, tenga o no
      candidato: no se generan propuestas retrospectivas. Solo se completa
      por primera vez si el ciclo corrió más tarde de lo previsto y esa
      franja nunca llegó a evaluarse.

    `verificar_impacto_provincial`: inyectable para pruebas offline (recibe
    una URL y devuelve `ResultadoVerificacionLocal`); por defecto,
    `verificar_impacto_local_concreto` (hace una petición GET real)."""
    verificar_impacto_provincial = verificar_impacto_provincial or verificar_impacto_local_concreto
    # Provinciales ya descartados por no verificar impacto local en esta
    # misma corrida: evita repetir la misma petición de red fallida en cada
    # franja vacía subsiguiente del día.
    provinciales_rechazados: set = set()
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

        # Franja ya evaluada antes y cuya hora ya pasó: no se generan
        # propuestas retrospectivas, tenga o no candidato asignado (con o
        # sin decisión humana pendiente). Se conserva tal cual quedó. Si
        # nunca se evaluó (el ciclo corrió por primera vez más tarde de lo
        # previsto), sí se completa una única vez más abajo.
        if existente is not None and _es_franja_pasada(fecha, hora, ahora):
            if noticia_existente is not None:
                usados.add(noticia_existente["id"])
                entradas.append(
                    EntradaAgenda(
                        fecha, hora, "normal", existente["territorio"], existente["noticia_id"], "existente"
                    )
                )
            else:
                entradas.append(EntradaAgenda(fecha, hora, "normal", None, None, "sin_candidato"))
            continue

        # El espacio no está protegido (sin candidato todavía, o con una
        # propuesta que sigue "pendiente" de decisión humana): se busca de
        # nuevo el mejor candidato disponible. Se excluye temporalmente al
        # propio ocupante actual de la búsqueda de "usados" para poder
        # compararlo contra el resto sin descalificarlo a él mismo; si sigue
        # siendo el mejor, la búsqueda lo vuelve a encontrar y no cambia nada.
        id_existente_noticia = noticia_existente["id"] if noticia_existente else None
        usados_para_busqueda = usados - {id_existente_noticia} if id_existente_noticia else usados
        candidato = _buscar_candidato_cascada(
            db, usados_para_busqueda, fecha_limite, verificar_impacto_provincial, provinciales_rechazados
        )
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
