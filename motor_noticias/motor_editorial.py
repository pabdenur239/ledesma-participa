from datetime import datetime, timedelta, timezone
from typing import List, NamedTuple, Optional

from .db import Database
from .dedupe import normalizar_url
from .entretenimiento import es_entretenimiento_o_curiosidad
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

# Franjas fijas de la Agenda Editorial / programación de publicación en Meta.
# 07:30 está reservada exclusivamente al informe diario (clima/dólar, ver
# `reservar_franja_informe_diario`); las 14 franjas restantes siguen la
# cascada territorial normal, una por hora entre las 09:00 y las 22:00.
# Entre las 15, cubren el volumen diario de 12 a 15 contenidos pedido para
# la publicación automática en Meta.
HORA_INFORME_DIARIO = "07:30"
# HORA_NOTICIA_DEL_DIA y HORA_RESUMEN_DEL_DIA quedan definidas porque
# `noticia_del_dia.py`, `resumen_dia.py` y `meta/publicador.py` todavía las
# importan, pero ninguna franja fija las reserva: esas dos publicaciones
# extra (agregadas 20/8/2026 junto con la grilla de 66/día) están
# deshabilitadas — revertidas el 23/8/2026 por exceder la grilla de 12 a 15
# publicaciones diarias acordada.
HORA_NOTICIA_DEL_DIA = "13:00"
HORA_RESUMEN_DEL_DIA = "22:30"
# La institucional vive en motor_noticias.institucional (institucional.py
# importa este módulo, así que la hora no se importa acá para no crear un
# ciclo): debe coincidir exactamente con `institucional.HORA_INSTITUCIONAL`.
HORA_INSTITUCIONAL_RESERVADA = "20:30"
HORARIOS_DEFAULT = (
    "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00",
    "16:00", "17:00", "18:00", "19:00", "20:00", "21:00", "22:00",
)
ANTIGUEDAD_MAXIMA_HORAS = 48
# Línea editorial (prioridad acumulativa, no cuota rígida diaria): Libertador
# General San Martín primero, Departamento Ledesma segundo, la provincia de
# Jujuy tercero, noticias nacionales cuarto y, como último recurso para no
# dejar una franja vacía pudiendo completarla, contenido de entretenimiento/
# espectáculos/curiosidades/tendencias virales verificable (nunca elige un
# nivel inferior si existe uno superior apto).
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


def _es_franja_pasada(fecha: str, hora: str, ahora: datetime) -> bool:
    """Una franja ya pasada (según `ahora`, en America/Argentina/Jujuy) no
    admite más candidatos automáticos: evita propuestas retrospectivas."""
    momento = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONA_JUJUY)
    return momento <= ahora


# Categorías temáticas (no geográficas) que diversifican la cascada por
# debajo de nacional, agregadas el 20/8/2026 junto con sus fuentes propias
# (espectáculos, internacional, gastronomía, salud). Prioridad editorial
# vigente: LOCAL > DEPARTAMENTAL > PROVINCIAL > NACIONAL > INTERNACIONAL —
# esta lista es exactamente el nivel "internacional y variedad temática" de
# esa prioridad, nunca compite con local/departamental/provincial/nacional
# (solo se intenta después de agotar los cuatro).
CATEGORIAS_TEMATICAS_DIVERSIFICACION = ("internacional", "salud", "gastronomia", "espectaculos")


def _buscar_candidato_tematico(
    db: Database, usados: set, fecha_limite: str, conteo_categorias: dict
) -> Optional[dict]:
    """Entre las categorías temáticas disponibles, prueba primero la que
    menos se usó en lo que va de esta corrida (evita monotonía sin imponer
    una cuota rígida por franja: "no forzar porcentajes rígidos"). Devuelve
    el candidato encontrado y dejar que el llamador registre en
    `conteo_categorias` cuál categoría ganó."""
    orden = sorted(CATEGORIAS_TEMATICAS_DIVERSIFICACION, key=lambda c: conteo_categorias.get(c, 0))
    for categoria in orden:
        candidato = db.candidato_tematico(categoria, usados, fecha_limite)
        if candidato:
            return candidato
    return None


def _buscar_candidato_cascada(
    db: Database, usados: set, fecha_limite: str, conteo_categorias: Optional[dict] = None
) -> Optional[dict]:
    """Recorre la cascada territorial obligatoria (local → departamental →
    provincial → nacional) y devuelve el primer candidato apto que
    encuentre. Nunca elige un nivel inferior si existe uno superior apto.

    Si ningún nivel territorial tiene candidato, antes de recurrir al
    fallback genérico se prueba con las categorías temáticas dedicadas
    (internacional/salud/gastronomía/espectáculos: fuentes propias, no
    substrings de "sin_clasificar" cualquiera) para diversificar sin bajar
    el criterio editorial. Recién si tampoco hay nada ahí, se prueba con la
    mejor noticia `sin_clasificar` genérica, pero solo si es contenido de
    entretenimiento/curiosidades/tendencia viral verificable (nunca una
    noticia sin_clasificar cualquiera)."""
    for territorio in ORDEN_CASCADA:
        candidato = db.candidato_editorial(territorio, usados, fecha_limite)
        if candidato:
            return candidato

    conteo_categorias = conteo_categorias if conteo_categorias is not None else {}
    candidato_tematico = _buscar_candidato_tematico(db, usados, fecha_limite, conteo_categorias)
    if candidato_tematico:
        categoria = candidato_tematico.get("categoria_tematica")
        if categoria:
            conteo_categorias[categoria] = conteo_categorias.get(categoria, 0) + 1
        return candidato_tematico

    candidato_sin_clasificar = db.candidato_editorial("sin_clasificar", usados, fecha_limite)
    if candidato_sin_clasificar and es_entretenimiento_o_curiosidad(
        candidato_sin_clasificar["titulo_original"], candidato_sin_clasificar["texto_original"]
    ):
        return candidato_sin_clasificar
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


def resolver_urgentes(db: Database, fecha: str, usados: set, fecha_limite: str) -> List[EntradaAgenda]:
    """Resuelve las propuestas urgentes (local/departamental) y las reserva
    de inmediato — modifica `usados` en el lugar (agrega los ids recién
    reservados) para que cualquier selección posterior en el mismo ciclo
    (cascada normal, Noticia del Día, Resumen del Día) ya las vea como
    ocupadas y nunca las vuelva a tomar para otra cosa. Extraído de
    `generar_agenda` (que la sigue llamando primero, igual que siempre) para
    poder llamarla también desde `noticia_del_dia`/`resumen_dia` ANTES de su
    propia selección — evitan así "robarle" a una urgente recién detectada
    la noticia que le corresponde salir de inmediato, sin esperar franja
    (bug real corregido 20/8/2026: Noticia del Día podía tomar una noticia
    local recién marcada urgente antes de que `generar_agenda` llegara a
    proponerla, dejándola sin su propuesta urgente aparte). Idempotente:
    una urgente ya reservada en una llamada anterior queda en `usados` y
    `candidatos_urgentes` no la vuelve a proponer."""
    entradas = []
    for urgente in db.candidatos_urgentes(usados, fecha_limite):
        creada_en = datetime.now(timezone.utc).isoformat()
        db.guardar_agenda_item(fecha, None, "urgente", urgente["territorio"], urgente["id"], creada_en)
        usados.add(urgente["id"])
        entradas.append(EntradaAgenda(fecha, None, "urgente", urgente["territorio"], urgente["id"], "creado"))
    return entradas


def generar_agenda(
    db: Database,
    fecha: Optional[str] = None,
    horarios=HORARIOS_DEFAULT,
    ahora: Optional[datetime] = None,
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
      franja nunca llegó a evaluarse."""
    # Se normaliza siempre a Jujuy, sin importar en qué huso venga `ahora`
    # (propio o inyectado en un test), para que la fecha del día se calcule
    # de forma consistente con America/Argentina/Jujuy y no con UTC u otro
    # huso horario del entorno de ejecución.
    ahora = (ahora or datetime.now(ZONA_JUJUY)).astimezone(ZONA_JUJUY)
    fecha = fecha or ahora.strftime("%Y-%m-%d")
    ahora_utc = ahora.astimezone(timezone.utc)
    fecha_limite = _fecha_limite_antiguedad(ahora_utc)

    usados = db.noticias_ids_usadas_en_agenda()
    entradas: List[EntradaAgenda] = list(resolver_urgentes(db, fecha, usados, fecha_limite))
    # Cuenta, dentro de esta corrida, cuántas veces se usó cada categoría
    # temática de diversificación: alimenta `_buscar_candidato_tematico`
    # para preferir la menos usada (evitar monotonía sin cuota rígida).
    conteo_categorias_tematicas: dict = {}

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
            db, usados_para_busqueda, fecha_limite, conteo_categorias_tematicas
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
