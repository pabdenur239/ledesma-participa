import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, NamedTuple, Optional

from .db import Database
from .dedupe import es_mismo_contenido, normalizar_url, palabras_clave, refieren_a_hecho_distinto
from .entretenimiento import es_entretenimiento_o_curiosidad
from .models import Estado, OrigenIngreso, RevisionEstado
from .calidad_editorial import evaluar_calidad
from .eventos import relacion_editorial, ventana_desde
from .fechas import momento_vigencia
from .scoring_editorial import CLASIFICACION_URGENTE, cargar_config as _cargar_config_scoring, evaluar_noticia

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
# Prueba editorial 30/9/2026 al 6/10/2026: el feed normal baja a 6
# publicaciones diarias (informe 07:30 + estas 4 franjas de cascada +
# institucional 20:30). Urgentes locales, alertas y Stories no cuentan en
# ese límite (circuito propio, `publicar_urgentes_meta.py`).
HORARIOS_DEFAULT = ("09:00", "12:00", "16:00", "19:00")
ANTIGUEDAD_MAXIMA_HORAS = 48
# Línea editorial (prioridad acumulativa, no cuota rígida diaria): Libertador
# General San Martín primero, Departamento Ledesma segundo, la provincia de
# Jujuy tercero, noticias nacionales cuarto y, como último recurso para no
# dejar una franja vacía pudiendo completarla, contenido de entretenimiento/
# espectáculos/curiosidades/tendencias virales verificable (nunca elige un
# nivel inferior si existe uno superior apto).
ORDEN_CASCADA = ("local", "departamental", "provincial", "nacional")

# Regla de mezcla editorial (agregada 28/8/2026, subida a 70% el 17/9/2026
# para bajar el contenido externo directo a un máximo de 30%): en las
# franjas normales se apunta a que al menos esta proporción sea contenido
# propio de Ledesma Participa, sustituyendo publicaciones externas cuando
# hay una nota propia `preparada` válida disponible. Es un objetivo
# flexible, no una cuota rígida: si no hay material propio de calidad para
# una franja, se mantiene la externa (nunca se degrada calidad ni se
# inventa contenido para cumplir el porcentaje). Configurable en
# `config/agenda.json`.
CONFIG_AGENDA_PATH = Path(__file__).resolve().parent.parent / "config" / "agenda.json"
PROPORCION_MINIMA_CONTENIDO_PROPIO_DEFAULT = 0.7

# La regla de mezcla NUNCA desplaza una publicación externa de estos
# territorios: son las noticias que deben salir primero y sin demora. El
# contenido propio solo reemplaza a externas de prioridad provincial o
# inferior (provincial / nacional / temática / entretenimiento).
TERRITORIOS_PROTEGIDOS_MEZCLA = ("local", "departamental")


def _proporcion_minima_contenido_propio(path: Optional[Path] = None) -> float:
    """Lee `config/agenda.json` → "proporcion_minima_contenido_propio"
    (default 0.5). Se relee en cada llamada, se puede ajustar sin reiniciar
    nada. Un valor fuera de [0, 1] o ilegible cae al default."""
    try:
        with open(path or CONFIG_AGENDA_PATH, encoding="utf-8") as f:
            valor = float(json.load(f).get(
                "proporcion_minima_contenido_propio", PROPORCION_MINIMA_CONTENIDO_PROPIO_DEFAULT
            ))
        return valor if 0.0 <= valor <= 1.0 else PROPORCION_MINIMA_CONTENIDO_PROPIO_DEFAULT
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return PROPORCION_MINIMA_CONTENIDO_PROPIO_DEFAULT


def _solo_territorios_prioritarios(path: Optional[Path] = None) -> bool:
    """Lee `config/agenda.json` → "solo_territorios_prioritarios" (default
    False). Si es True, la cascada se corta en provincial: sin nacional,
    temáticas ni entretenimiento de relleno (una franja puede quedar vacía).
    Activado para la prueba editorial 30/9/2026 al 6/10/2026."""
    try:
        with open(path or CONFIG_AGENDA_PATH, encoding="utf-8") as f:
            return bool(json.load(f).get("solo_territorios_prioritarios", False))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _es_mismo_hecho(titulo_a: str, titulo_b: str) -> bool:
    """True si dos títulos son la misma nota real (mismo criterio que el
    gate de deduplicación de publicación). Se usa para no programar una
    nota propia sobre un hecho que ya ocupa otra franja del día."""
    if refieren_a_hecho_distinto(titulo_a, titulo_b):
        return False
    return es_mismo_contenido(palabras_clave(titulo_a or ""), palabras_clave(titulo_b or ""))


def _sigue_siendo_elegible(noticia: dict, fecha_limite: str) -> bool:
    """Mismas condiciones que aplica `candidato_editorial` para que una
    noticia pueda ocupar una franja automática: `preparada`, no rechazada,
    sin riesgo editorial obligatorio y dentro de la antigüedad máxima."""
    return (
        noticia.get("estado") == Estado.PREPARADA.value
        and noticia.get("revision_estado") != RevisionEstado.RECHAZADA.value
        and not noticia.get("requiere_revision_especial")
        and (noticia.get("fecha_recoleccion") or "") >= fecha_limite
    )


def _mezcla_propio_para_franja(
    db: Database,
    candidato_externo: Optional[dict],
    excluidos_ids: set,
    fecha_limite: str,
    titulos_en_agenda: List[str],
    propio_en_normales: int,
    objetivo_propio: int,
) -> Optional[dict]:
    """Regla de mezcla editorial: devuelve la mejor nota propia `preparada`
    para cubrir una franja normal en lugar de `candidato_externo`, o `None`
    si no corresponde sustituir — ya se alcanzó el objetivo de contenido
    propio del día, el candidato externo es local/departamental (tiene
    prioridad y no se desplaza) o es contenido propio, no hay nota propia
    apta, o la nota propia repetiría un hecho ya comprometido en el día."""
    if propio_en_normales >= objetivo_propio or candidato_externo is None:
        return None
    if candidato_externo.get("origen_ingreso") == OrigenIngreso.CONTENIDO_PROPIO.value:
        return None
    if candidato_externo.get("territorio") in TERRITORIOS_PROTEGIDOS_MEZCLA:
        return None
    # Scoring editorial único: una externa "importante" (o más) ganó su
    # franja por relevancia real; la mezcla no la reemplaza por una nota
    # propia de menor relevancia.
    if evaluar_noticia(candidato_externo)["base"] >= _cargar_config_scoring()["umbrales"]["importante"]:
        return None
    propio = db.candidato_contenido_propio(excluidos_ids, fecha_limite)
    if propio is None:
        return None
    titulos_a_evitar = titulos_en_agenda + [candidato_externo.get("titulo_original") or ""]
    if any(_es_mismo_hecho(propio["titulo_original"], titulo) for titulo in titulos_a_evitar):
        return None
    return propio


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


# Rango de desempate entre candidatas con el mismo puntaje total: mantiene
# la prioridad editorial histórica (local > departamental > provincial >
# nacional > temática > entretenimiento sin clasificar) solo como
# desempate, nunca como prioridad absoluta.
_RANGO_DESEMPATE = {"local": 0, "departamental": 1, "provincial": 2, "nacional": 3}
_RANGO_TEMATICA = 4
_RANGO_SIN_CLASIFICAR = 5


def _rango_candidata(noticia: dict, solo_prioritarios: bool, base: int) -> Optional[int]:
    """Rango de desempate si la noticia puede competir por una franja, o
    `None` si no puede. Mismo universo de candidatas que la cascada
    anterior (territorios de ORDEN_CASCADA, categorías temáticas dedicadas
    y entretenimiento verificable sin clasificar), con dos reglas nuevas:

    - "internacional" solo compite si es excepcionalmente relevante
      (puntaje base >= umbral "importante").
    - Con `solo_territorios_prioritarios` (prueba editorial 30/9–6/10/2026:
      sin relleno nacional/temático/entretenimiento), nacional/temáticas
      solo compiten si son importantes de verdad (base >= umbral
      "importante"): una nacional trascendente igual puede ganarle a una
      local menor, pero nunca entra una nacional común de relleno."""
    importante = base >= _cargar_config_scoring()["umbrales"]["importante"]
    territorio = noticia.get("territorio")
    if territorio in ("local", "departamental", "provincial"):
        return _RANGO_DESEMPATE[territorio]
    if territorio == "nacional":
        return _RANGO_DESEMPATE[territorio] if (importante or not solo_prioritarios) else None
    if territorio == "internacional" and not es_entretenimiento_o_curiosidad(
        noticia.get("titulo_original") or "", noticia.get("texto_original") or ""
    ):
        # Internacional (nivel territorial desde 2/10/2026): solo compite si
        # es excepcionalmente relevante, igual que la categoría temática.
        return _RANGO_TEMATICA if importante else None
    if noticia.get("categoria_tematica") in CATEGORIAS_TEMATICAS_DIVERSIFICACION:
        if noticia.get("categoria_tematica") == "internacional" and not importante:
            return None
        return _RANGO_TEMATICA if (importante or not solo_prioritarios) else None
    if territorio in ("sin_clasificar", "internacional") and not solo_prioritarios and es_entretenimiento_o_curiosidad(
        noticia.get("titulo_original") or "", noticia.get("texto_original") or ""
    ):
        return _RANGO_SIN_CLASIFICAR
    return None


# El informe diario de clima/dólar tiene su propia franja fija (07:30, ver
# `reservar_franja_informe_diario`): nunca compite en la cascada ni en el
# circuito urgente (antes salía por el circuito urgente solo porque toda
# noticia local se marcaba urgente).
PREFIJO_URL_INFORME_DIARIO = "https://ledesma-participa.local/informe-diario/"


def es_informe_diario(noticia: dict) -> bool:
    return (noticia.get("url_normalizada") or "").startswith(PREFIJO_URL_INFORME_DIARIO)


def _apta_para_circuito_automatico(
    db: Database, noticia: dict, comprometidas: Optional[list], cache_eventos: Optional[dict], ahora_utc: datetime
) -> bool:
    """Filtros comunes a franjas y urgentes, además del scoring:
    - vigencia medida desde la publicación en la FUENTE (no solo el ingreso):
      una nota vieja recolectada o reelaborada hoy no ocupa espacio;
    - control de calidad (`calidad_editorial`): lo que debe retenerse no sale;
    - deduplicación por acontecimiento (`eventos`): si ya se publicó o agendó
      el mismo hecho, no vuelve a salir; si es una ACTUALIZACIÓN real, sale
      marcada como tal (`actualizacion_de`)."""
    if es_informe_diario(noticia):
        return False
    vigencia = momento_vigencia(noticia)
    if vigencia is not None and vigencia < ahora_utc - timedelta(hours=ANTIGUEDAD_MAXIMA_HORAS):
        return False
    if evaluar_calidad(noticia).accion == "retener":
        return False
    if comprometidas is not None:
        relacion = relacion_editorial(noticia, comprometidas, cache=cache_eventos)
        if relacion is not None:
            if not relacion.es_actualizacion:
                return False
            if noticia.get("actualizacion_de") != relacion.relacionada["id"]:
                db.marcar_actualizacion(noticia["id"], relacion.relacionada["id"])
                noticia["actualizacion_de"] = relacion.relacionada["id"]
    return True


def _buscar_candidato_cascada(
    db: Database,
    usados: set,
    fecha_limite: str,
    conteo_categorias: Optional[dict] = None,
    ahora: Optional[datetime] = None,
    comprometidas: Optional[list] = None,
    cache_eventos: Optional[dict] = None,
) -> Optional[dict]:
    """Selección por scoring editorial único (2/10/2026, reemplaza a la
    cascada territorial rígida): reúne TODAS las candidatas aptas (ya sin
    duplicadas/usadas/rechazadas/riesgo/vencidas, ver
    `Database.candidatos_editoriales`), calcula el puntaje de cada una
    (`scoring_editorial.evaluar_noticia`: base 0–100 + bonus territorial) y
    devuelve la de mayor puntaje total. Ser local suma (relevancia + bonus)
    pero no garantiza ganar: una nacional o provincial trascendente supera a
    una local menor. Desempates: rango territorial histórico, categoría
    temática menos usada en esta corrida (diversificación), más reciente."""
    conteo_categorias = conteo_categorias if conteo_categorias is not None else {}
    solo_prioritarios = _solo_territorios_prioritarios()
    ahora_utc = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    minimo = _cargar_config_scoring()["umbrales"].get("minimo_franja", 0)
    ordenadas = []
    for noticia in db.candidatos_editoriales(usados, fecha_limite):
        evaluacion = evaluar_noticia(noticia, ahora)
        rango = _rango_candidata(noticia, solo_prioritarios, evaluacion["base"])
        if rango is None or evaluacion["base"] < minimo:
            # Mejor una franja vacía que contenido sin valor informativo.
            continue
        clave = (
            -evaluacion["total"],
            rango,
            conteo_categorias.get(noticia.get("categoria_tematica"), 0) if rango == _RANGO_TEMATICA else 0,
            "".join(chr(0x10FFFF - ord(c)) for c in (noticia.get("fecha_recoleccion") or "")),
        )
        ordenadas.append((clave, noticia))
    ordenadas.sort(key=lambda par: par[0])
    mejor = None
    for clave, noticia in ordenadas:
        if _apta_para_circuito_automatico(db, noticia, comprometidas, cache_eventos, ahora_utc):
            mejor = noticia
            if clave[1] == _RANGO_TEMATICA:
                categoria = noticia.get("categoria_tematica")
                conteo_categorias[categoria] = conteo_categorias.get(categoria, 0) + 1
            break
    return mejor


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


def resolver_urgentes(
    db: Database,
    fecha: str,
    usados: set,
    fecha_limite: str,
    ahora: Optional[datetime] = None,
    comprometidas: Optional[list] = None,
    cache_eventos: Optional[dict] = None,
) -> List[EntradaAgenda]:
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
    ahora_utc = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if comprometidas is None:
        comprometidas = db.noticias_comprometidas_desde(ventana_desde(ahora_utc))
    for urgente in db.candidatos_urgentes(usados, fecha_limite):
        # Una sola clasificación: el flag `urgente` solo vale si el scoring
        # editorial la sigue clasificando URGENTE ahora, o si un humano la
        # tildó a mano al cargarla desde el panel (`origen_ingreso` manual).
        # Así una local menor marcada urgente por la regla anterior (toda
        # local = urgente) no sale de inmediato: compite en franja.
        if (
            urgente.get("origen_ingreso") != OrigenIngreso.MANUAL.value
            and evaluar_noticia(urgente, ahora)["clasificacion"] != CLASIFICACION_URGENTE
        ):
            continue
        # Mismo acontecimiento ya publicado/agendado (otro medio, otra etapa
        # sin novedad sustancial) → no sale otra vez de inmediato.
        if not _apta_para_circuito_automatico(db, urgente, comprometidas, cache_eventos, ahora_utc):
            continue
        creada_en = datetime.now(timezone.utc).isoformat()
        db.guardar_agenda_item(fecha, None, "urgente", urgente["territorio"], urgente["id"], creada_en)
        usados.add(urgente["id"])
        comprometidas.append(urgente)
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
    # Una noticia de medio ya reelaborada como contenido propio no vuelve a
    # competir en la cascada: publicar la externa original y su reelaboración
    # sería el mismo hecho dos veces.
    usados |= db.ids_fuente_reelaborados()
    # Noticias ya publicadas o agendadas en la ventana de eventos: ninguna
    # franja ni urgente puede repetir su acontecimiento (deduplicación
    # global por hecho, `motor_noticias.eventos`).
    comprometidas = db.noticias_comprometidas_desde(ventana_desde(ahora_utc))
    cache_eventos: dict = {}
    entradas: List[EntradaAgenda] = list(
        resolver_urgentes(db, fecha, usados, fecha_limite, ahora_utc, comprometidas, cache_eventos)
    )
    # Cuenta, dentro de esta corrida, cuántas veces se usó cada categoría
    # temática de diversificación: alimenta `_buscar_candidato_tematico`
    # para preferir la menos usada (evitar monotonía sin cuota rígida).
    conteo_categorias_tematicas: dict = {}

    # Regla de mezcla editorial: objetivo de al menos `objetivo_propio`
    # franjas normales con contenido propio (>=50% de `len(horarios)` por
    # defecto). `titulos_en_agenda` acumula los títulos ya comprometidos en
    # el día (empezando por las urgentes) para no agendar una nota propia
    # sobre un hecho que ya ocupa otra franja. Las urgentes no cuentan para
    # la proporción (quedan fuera de la mezcla por diseño).
    objetivo_propio = math.ceil(_proporcion_minima_contenido_propio() * len(horarios))
    propio_en_normales = 0
    titulos_en_agenda: List[str] = []
    for entrada_previa in entradas:
        if entrada_previa.noticia_id:
            noticia_previa = db.obtener(entrada_previa.noticia_id)
            if noticia_previa:
                titulos_en_agenda.append(noticia_previa["titulo_original"])

    def _registrar_normal(noticia_asignada: Optional[dict]) -> None:
        nonlocal propio_en_normales
        if not noticia_asignada:
            return
        titulos_en_agenda.append(noticia_asignada.get("titulo_original") or "")
        if noticia_asignada.get("origen_ingreso") == OrigenIngreso.CONTENIDO_PROPIO.value:
            propio_en_normales += 1

    for hora in horarios:
        existente = db.obtener_agenda_item(fecha, hora)
        noticia_existente = db.obtener(existente["noticia_id"]) if existente and existente["noticia_id"] else None

        # Una noticia que ya quedó `descartada` (rechazada o filtrada) no
        # puede seguir ocupando su franja: se libera para que la cascada la
        # rellene. Sin esto, una franja con una nota descartada queda
        # bloqueada y no publica nada.
        if noticia_existente is not None and noticia_existente["estado"] == Estado.DESCARTADA.value:
            noticia_existente = None

        # Congelada de verdad: una DECISIÓN HUMANA (aprobó/rechazó) o la
        # noticia ya publicada. El Motor Editorial nunca la toca.
        decidida_por_humano = noticia_existente is not None and (
            (
                noticia_existente["revision_estado"] == RevisionEstado.APROBADA.value
                and not noticia_existente.get("revision_automatica")
            )
            or noticia_existente["revision_estado"] == RevisionEstado.RECHAZADA.value
        )
        ya_publicada = (
            noticia_existente is not None
            and noticia_existente["estado"] == Estado.PUBLICADA.value
        )
        if decidida_por_humano or ya_publicada:
            usados.add(noticia_existente["id"])
            _registrar_normal(noticia_existente)
            entradas.append(
                EntradaAgenda(fecha, hora, "normal", existente["territorio"], existente["noticia_id"], "existente")
            )
            continue

        # Franja aprobada SOLO por elegibilidad automática (sin decisión
        # humana) y todavía sin publicar: la cascada no la reevalúa —evita
        # rotar la grilla ya armada sin motivo—, pero la regla de mezcla
        # editorial sí puede cubrirla con contenido propio.
        aprobada_solo_automatica = (
            noticia_existente is not None
            and noticia_existente["revision_estado"] == RevisionEstado.APROBADA.value
            and noticia_existente.get("revision_automatica")
        )
        if aprobada_solo_automatica and not (existente is not None and _es_franja_pasada(fecha, hora, ahora)):
            propio = _mezcla_propio_para_franja(
                db, noticia_existente, usados - {noticia_existente["id"]}, fecha_limite,
                titulos_en_agenda, propio_en_normales, objetivo_propio,
            )
            elegida = propio or noticia_existente
            usados.add(elegida["id"])
            _registrar_normal(elegida)
            if elegida["id"] == noticia_existente["id"]:
                entradas.append(
                    EntradaAgenda(fecha, hora, "normal", existente["territorio"], existente["noticia_id"], "existente")
                )
            else:
                db.guardar_agenda_item(
                    fecha, hora, "normal", elegida["territorio"], elegida["id"],
                    datetime.now(timezone.utc).isoformat(), id_existente=existente["id"],
                )
                entradas.append(
                    EntradaAgenda(fecha, hora, "normal", elegida["territorio"], elegida["id"], "actualizado")
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
                _registrar_normal(noticia_existente)
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
        # El ocupante actual de esta franja no cuenta como "comprometido"
        # contra sí mismo ni contra sus competidores directos.
        comprometidas_franja = [n for n in comprometidas if n.get("id") != id_existente_noticia]
        candidato = _buscar_candidato_cascada(
            db, usados_para_busqueda, fecha_limite, conteo_categorias_tematicas, ahora_utc,
            comprometidas_franja, cache_eventos,
        )

        # Regla de mezcla editorial (>=50% contenido propio en franjas
        # normales). Nunca toca local/departamental (deben salir primero)
        # ni la institucional (franja reservada aparte).
        ocupante_es_propio = (
            noticia_existente is not None
            and noticia_existente.get("origen_ingreso") == OrigenIngreso.CONTENIDO_PROPIO.value
        )
        if (
            ocupante_es_propio
            and candidato is not None
            and candidato.get("territorio") not in TERRITORIOS_PROTEGIDOS_MEZCLA
            and candidato.get("origen_ingreso") != OrigenIngreso.CONTENIDO_PROPIO.value
            and _sigue_siendo_elegible(noticia_existente, fecha_limite)
        ):
            # Estabilidad entre ciclos: una nota propia ya asignada y todavía
            # válida no se degrada a externa solo porque la cascada, con esa
            # nota excluida de la búsqueda, encontró otra externa. Solo la
            # desplaza una externa local/departamental (rama de arriba).
            candidato = noticia_existente
        else:
            propio = _mezcla_propio_para_franja(
                db, candidato, usados_para_busqueda, fecha_limite,
                titulos_en_agenda, propio_en_normales, objetivo_propio,
            )
            if propio is not None:
                candidato = propio

        id_existente_item = existente["id"] if existente else None

        if candidato:
            usados.add(candidato["id"])
            _registrar_normal(candidato)
            if all(n.get("id") != candidato["id"] for n in comprometidas):
                comprometidas.append(candidato)
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
