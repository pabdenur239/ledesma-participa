"""Piloto de "contenido propio": notas originales de Ledesma Participa,
distintas de relayar una nota de otro medio, generadas a partir de HECHOS
extraídos (nunca inferidos) de noticias ya recolectadas de fuentes
PRIMARIAS oficiales (municipios, gobierno provincial, organismos
públicos) — nunca de medios de prensa.

Regla central, igual que en el resto del proyecto: si un patrón no
encuentra el dato con confianza, no se genera nada. Ningún extractor
"completa" ni "interpreta" — solo reconoce un patrón textual explícito
(fecha, hora, palabra clave de servicio, dos cifras comparables) ya
presente en el texto de la fuente. La redacción final es un template
propio (título/bajada/cuerpo escritos por este módulo, nunca una copia de
la nota original) que cita la fuente real de forma explícita en el cuerpo.

Reutiliza el mismo pipeline que cualquier otra noticia (`normalizar_noticia`
/ `procesar_noticia`: deduplicación, clasificación territorial, riesgo
editorial, elegibilidad) y el mismo redactor "identidad" que ya usa
`informe_diario` (sin IA: el texto ya es final por construcción, no debe
parafrasearse). Cada nota generada queda `origen_ingreso = "contenido_propio"`,
compite normalmente en la cascada territorial (no tiene franja reservada
propia, a diferencia de institucional/resumen del día) y sigue exactamente
el mismo circuito de revisión humana / elegibilidad automática / publicación
que cualquier otra noticia preparada — no altera horarios, urgentes, Stories
ni web."""
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .db import Database
from .models import Noticia, OrigenIngreso
from .motor_editorial import ZONA_JUJUY
from .pipeline import normalizar_noticia, procesar_noticia
from .redaccion.base import Redactor

logger = logging.getLogger("motor_noticias.contenido_propio")

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "contenido_propio.json"

# Solo fuentes PRIMARIAS (organismo oficial, no medio de prensa) — en orden
# de prioridad territorial (LOCAL > DEPARTAMENTAL > PROVINCIAL), igual
# criterio que la cascada del Motor Editorial. Los nombres deben coincidir
# exactamente con `nombre_fuente` tal como lo guarda cada collector (ver
# config/fuentes.json).
FUENTES_PRIMARIAS_DEFAULT = [
    "Municipalidad de Libertador General San Martín",
    "Prensa Jujuy (Gobierno de Jujuy)",
    "Ministerio de Salud de la Nación",
]
# Tope de seguridad de notas propias generadas por día calendario local. No
# es una cuota objetivo: el generador ya se autolimita (solo produce una
# nota cuando un extractor determinístico reconoce un patrón textual
# explícito en una fuente primaria oficial, con dedup por URL/hash/
# fingerprint). Subido de 3 a 12 el 28/8/2026 para que la regla de mezcla
# editorial (>=50% contenido propio en franjas normales, ver
# `motor_editorial.generar_agenda`) tenga material suficiente; 12 = piso de
# la grilla diaria, nunca puede empujar el total por encima de la grilla.
MAX_NOTAS_POR_DIA_DEFAULT = 12
VENTANA_HORAS_DEFAULT = 48
PALABRAS_CLAVE_SERVICIO_DEFAULT = [
    "corte de", "corte programado", "cronograma", "vencimiento", "vence el",
    "alerta", "tránsito", "transito", "trámite", "tramite", "turnos",
    "inscripción", "inscripcion", "operativo",
]
NOMBRE_FUENTE_PROPIA = "Ledesma Participa (contenido propio)"


def _cargar_config(path: Optional[Path] = None) -> dict:
    try:
        with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


class _RedactorIdentidad(Redactor):
    """Mismo criterio que `informe_diario._RedactorIdentidad`: el
    título/texto de una nota propia ya es final y determinístico por
    construcción (armado por los templates de este módulo a partir de
    datos extraídos) — nunca debe pasar por un modelo de lenguaje que
    podría parafrasear o alterar una cifra o una fecha."""

    def redactar(self, noticia: Noticia) -> Tuple[str, str]:
        return noticia.titulo_original, noticia.texto_original


# ---------------------------------------------------------------------------
# Extractores: cada uno busca un patrón textual explícito en el título/texto
# YA RECOLECTADO de una noticia de fuente primaria. Devuelven None si el
# patrón no aparece — nunca completan ni infieren el dato faltante.
# ---------------------------------------------------------------------------

_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
RE_DIA_SEMANA = re.compile(
    r"\b(?:este |el )?(lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo)\b", re.IGNORECASE
)
RE_FECHA_EXPLICITA = re.compile(
    r"\b(\d{1,2}) de (" + "|".join(_MESES) + r")\b", re.IGNORECASE
)
RE_HORA = re.compile(
    r"\b(de \d{1,2}(?::\d{2})? a \d{1,2}(?::\d{2})? horas?|a las \d{1,2}(?::\d{2})? ?h?s?\b)", re.IGNORECASE
)


def _extraer_agenda(titulo: str, texto: str) -> Optional[dict]:
    """Actividad con fecha/día reconocible (fecha explícita "25 de agosto" o
    día de la semana "este viernes"), con u opcionalmente sin horario. Sin
    fecha ni día reconocible, no es un candidato de agenda."""
    base = f"{titulo} {texto}"
    fecha_m = RE_FECHA_EXPLICITA.search(base)
    dia_m = RE_DIA_SEMANA.search(base)
    if not fecha_m and not dia_m:
        return None
    cuando = fecha_m.group(0) if fecha_m else dia_m.group(0)
    hora_m = RE_HORA.search(base)
    return {"cuando": cuando.strip(), "hora": hora_m.group(0).strip() if hora_m else None}


ETIQUETAS_SERVICIO = {
    "corte de": "Corte de servicio", "corte programado": "Corte de servicio",
    "cronograma": "Cronograma", "vencimiento": "Vencimiento", "vence el": "Vencimiento",
    "alerta": "Alerta", "tránsito": "Tránsito", "transito": "Tránsito",
    "trámite": "Trámite", "tramite": "Trámite", "turnos": "Turnos",
    "inscripción": "Inscripción", "inscripcion": "Inscripción", "operativo": "Operativo",
}


def _oracion_alrededor_de(texto: str, indice: int) -> str:
    inicio = texto.rfind(".", 0, indice)
    inicio = 0 if inicio == -1 else inicio + 1
    fin = texto.find(".", indice)
    fin = len(texto) if fin == -1 else fin + 1
    return texto[inicio:fin].strip()


def _extraer_servicio(titulo: str, texto: str, palabras_clave: List[str]) -> Optional[dict]:
    """Palabra clave de servicio/utilidad presente en el texto: se extrae
    la oración completa que la contiene (no se resume ni se reinterpreta,
    se cita esa oración tal cual, atribuida a la fuente)."""
    texto_lower = texto.lower()
    for palabra in palabras_clave:
        indice = texto_lower.find(palabra.lower())
        if indice != -1:
            etiqueta = ETIQUETAS_SERVICIO.get(palabra.lower(), "Servicio")
            return {"palabra_clave": palabra, "etiqueta": etiqueta, "oracion": _oracion_alrededor_de(texto, indice)}
    titulo_lower = titulo.lower()
    for palabra in palabras_clave:
        if palabra.lower() in titulo_lower:
            etiqueta = ETIQUETAS_SERVICIO.get(palabra.lower(), "Servicio")
            return {"palabra_clave": palabra, "etiqueta": etiqueta, "oracion": titulo}
    return None


def _a_numero(cadena: str) -> Optional[float]:
    cadena = cadena.strip()
    if "," in cadena:
        cadena = cadena.replace(".", "").replace(",", ".")
    else:
        cadena = cadena.replace(".", "")
    try:
        return float(cadena)
    except ValueError:
        return None


RE_DATOS_CONTEXTO = re.compile(
    r"(?:aument[oó]|subi[oó]|pas[oó]|se ubic[oó]|baj[oó])\s+de\s*\$\s*([\d\.,]+)\s+a\s*\$\s*([\d\.,]+)"
    r"|de\s*\$\s*([\d\.,]+)\s+a\s*\$\s*([\d\.,]+)",
    re.IGNORECASE,
)


def _extraer_datos_contexto(texto: str) -> Optional[dict]:
    """Dos cifras monetarias comparables explícitas en el texto ("de $X a
    $Y", "aumentó de $X a $Y"): el porcentaje de variación se CALCULA
    (aritmética simple, no una cifra tomada de la fuente ni inventada).
    Sin dos cifras inequívocas, no se genera nota de este tipo."""
    coincidencia = RE_DATOS_CONTEXTO.search(texto)
    if not coincidencia:
        return None
    grupos = [g for g in coincidencia.groups() if g is not None]
    if len(grupos) != 2:
        return None
    anterior = _a_numero(grupos[0])
    nuevo = _a_numero(grupos[1])
    if anterior is None or nuevo is None or anterior == 0:
        return None
    variacion_pct = (nuevo - anterior) / anterior * 100
    return {"valor_anterior": anterior, "valor_nuevo": nuevo, "variacion_pct": variacion_pct}


RE_EXPLICADOR_VIGENCIA = re.compile(
    r"(rige|entra en vigencia|comenzar[áa] a regir|ser[áa] de aplicaci[oó]n|se aplicar[áa])\s+"
    r"(desde|a partir de)\s+el\s+([^\.,;]+)",
    re.IGNORECASE,
)


def _extraer_explicador(texto: str) -> Optional[dict]:
    """Frase explícita de vigencia ("rige desde el...", "a partir del...").
    Sin esa frase textual, no se genera explicador — no se infiere una
    fecha de vigencia a partir del contexto."""
    coincidencia = RE_EXPLICADOR_VIGENCIA.search(texto)
    if not coincidencia:
        return None
    return {"frase": coincidencia.group(0).strip(), "fecha": coincidencia.group(3).strip()}


# ---------------------------------------------------------------------------
# Composición de la nota propia (título/bajada/cuerpo propios, nunca una
# copia de la nota original) a partir de lo que cada extractor encontró.
# ---------------------------------------------------------------------------


@dataclass
class NotaPropiaCandidata:
    tipo: str  # "servicio" | "agenda" | "datos_contexto" | "explicador"
    titulo: str
    texto: str
    url_identidad: str
    fuente_real_nombre: str
    fuente_real_url: str
    localidad: Optional[str]
    ids_fuente: List[int]


def _fecha_legible(fecha_recoleccion_iso: str) -> str:
    try:
        momento = datetime.fromisoformat(fecha_recoleccion_iso.replace("Z", "+00:00"))
    except ValueError:
        return fecha_recoleccion_iso
    return momento.astimezone(ZONA_JUJUY).strftime("%d/%m/%Y")


def _componer_servicio(noticia_fuente: dict, datos: dict) -> NotaPropiaCandidata:
    fecha = _fecha_legible(noticia_fuente["fecha_recoleccion"])
    titulo = f"{datos['etiqueta']}: novedad de {noticia_fuente['nombre_fuente']} ({fecha})"
    texto = (
        f"{noticia_fuente['nombre_fuente']} informó lo siguiente: “{datos['oracion']}”\n\n"
        f"Fuente: {noticia_fuente['nombre_fuente']} — {noticia_fuente['url_fuente']}\n"
        "Nota propia de Ledesma Participa a partir de información oficial pública."
    )
    return NotaPropiaCandidata(
        tipo="servicio", titulo=titulo, texto=texto,
        url_identidad=f"https://ledesma-participa.local/contenido-propio/servicio/{noticia_fuente['id']}",
        fuente_real_nombre=noticia_fuente["nombre_fuente"], fuente_real_url=noticia_fuente["url_fuente"],
        localidad=noticia_fuente.get("localidad"), ids_fuente=[noticia_fuente["id"]],
    )


def _componer_datos_contexto(noticia_fuente: dict, datos: dict) -> NotaPropiaCandidata:
    fecha = _fecha_legible(noticia_fuente["fecha_recoleccion"])
    direccion = "aumentó" if datos["variacion_pct"] > 0 else "bajó" if datos["variacion_pct"] < 0 else "se mantuvo"
    titulo = f"Cuánto {direccion}: de ${datos['valor_anterior']:.0f} a ${datos['valor_nuevo']:.0f} ({datos['variacion_pct']:+.1f}%)"
    texto = (
        f"Según {noticia_fuente['nombre_fuente']} ({fecha}), el valor pasó de "
        f"${datos['valor_anterior']:.0f} a ${datos['valor_nuevo']:.0f}, una variación del "
        f"{datos['variacion_pct']:+.1f}% (cálculo propio a partir de las dos cifras informadas).\n\n"
        f"Fuente: {noticia_fuente['nombre_fuente']} — {noticia_fuente['url_fuente']}\n"
        "Nota propia de Ledesma Participa a partir de datos oficiales públicos."
    )
    return NotaPropiaCandidata(
        tipo="datos_contexto", titulo=titulo, texto=texto,
        url_identidad=f"https://ledesma-participa.local/contenido-propio/datos/{noticia_fuente['id']}",
        fuente_real_nombre=noticia_fuente["nombre_fuente"], fuente_real_url=noticia_fuente["url_fuente"],
        localidad=noticia_fuente.get("localidad"), ids_fuente=[noticia_fuente["id"]],
    )


def _componer_explicador(noticia_fuente: dict, datos: dict) -> NotaPropiaCandidata:
    fecha = _fecha_legible(noticia_fuente["fecha_recoleccion"])
    titulo = f"¿Desde cuándo rige? Novedad de {noticia_fuente['nombre_fuente']} ({fecha})"
    texto = (
        f"{noticia_fuente['nombre_fuente']} informó: “{noticia_fuente['titulo_original']}”. "
        f"Según la fuente, la medida {datos['frase']}.\n\n"
        f"Fuente: {noticia_fuente['nombre_fuente']} — {noticia_fuente['url_fuente']}\n"
        "Nota propia de Ledesma Participa a partir de información oficial pública."
    )
    return NotaPropiaCandidata(
        tipo="explicador", titulo=titulo, texto=texto,
        url_identidad=f"https://ledesma-participa.local/contenido-propio/explicador/{noticia_fuente['id']}",
        fuente_real_nombre=noticia_fuente["nombre_fuente"], fuente_real_url=noticia_fuente["url_fuente"],
        localidad=noticia_fuente.get("localidad"), ids_fuente=[noticia_fuente["id"]],
    )


def _componer_agenda(items: List[Tuple[dict, dict]], fecha_iso: str) -> NotaPropiaCandidata:
    lineas = []
    fuentes_citadas = set()
    for noticia_fuente, datos in items:
        hora_txt = f", {datos['hora']}" if datos["hora"] else ""
        lineas.append(f"• {noticia_fuente['titulo_original']} — {datos['cuando']}{hora_txt}.")
        fuentes_citadas.add(noticia_fuente["nombre_fuente"])
    titulo = "Agenda: actividades oficiales de los próximos días"
    texto = (
        "Actividades informadas por fuentes oficiales para los próximos días:\n\n"
        + "\n".join(lineas)
        + "\n\nVerificá horarios y condiciones antes de asistir; pueden cambiar. "
        f"Fuentes: {', '.join(sorted(fuentes_citadas))}."
    )
    return NotaPropiaCandidata(
        tipo="agenda", titulo=titulo, texto=texto,
        url_identidad=f"https://ledesma-participa.local/contenido-propio/agenda/{fecha_iso}",
        fuente_real_nombre=NOMBRE_FUENTE_PROPIA, fuente_real_url="",
        localidad=None, ids_fuente=[nf["id"] for nf, _ in items],
    )


# ---------------------------------------------------------------------------
# Detección de oportunidades y generación real (vía el pipeline existente).
# ---------------------------------------------------------------------------


def detectar_oportunidades(
    db: Database, ahora: Optional[datetime] = None, config: Optional[dict] = None
) -> List[NotaPropiaCandidata]:
    """Recorre las noticias ya recolectadas de las fuentes primarias
    configuradas (más recientes primero, en orden de prioridad territorial)
    y devuelve las candidatas de nota propia detectadas — nunca publica ni
    guarda nada. Cada noticia fuente genera como máximo una nota individual
    (servicio / datos_contexto / explicador, el primer extractor que
    encuentre algo); las que además matchean el patrón de agenda pero no
    generaron una nota individual se compilan aparte en una única nota de
    agenda. No repite una noticia fuente ya usada en una nota propia
    anterior (`obtener_por_url` sobre la URL de identidad determinística)."""
    config = config or _cargar_config()
    fuentes_primarias = config.get("fuentes_primarias") or FUENTES_PRIMARIAS_DEFAULT
    palabras_clave_servicio = config.get("palabras_clave_servicio") or PALABRAS_CLAVE_SERVICIO_DEFAULT
    ventana_horas = config.get("ventana_horas", VENTANA_HORAS_DEFAULT)

    ahora_local = (ahora or datetime.now(ZONA_JUJUY)).astimezone(ZONA_JUJUY)
    fecha_limite = (ahora_local.astimezone(timezone.utc) - timedelta(hours=ventana_horas)).isoformat()

    candidatas_fuente = db.noticias_de_fuentes_recientes(fuentes_primarias, fecha_limite)
    # Reordena por prioridad territorial de la fuente (orden de
    # `fuentes_primarias` en config: LOCAL antes que PROVINCIAL), luego más
    # reciente primero (ya viene así de la consulta) — sort estable.
    orden_fuente = {nombre: i for i, nombre in enumerate(fuentes_primarias)}
    candidatas_fuente.sort(key=lambda n: orden_fuente.get(n["nombre_fuente"], len(fuentes_primarias)))

    notas: List[NotaPropiaCandidata] = []
    pendientes_agenda: List[Tuple[dict, dict]] = []

    for noticia_fuente in candidatas_fuente:
        titulo = noticia_fuente["titulo_original"] or ""
        texto = noticia_fuente["texto_original"] or ""
        if not texto:
            continue

        ya_usada = any(
            db.obtener_por_url(f"https://ledesma-participa.local/contenido-propio/{t}/{noticia_fuente['id']}")
            for t in ("servicio", "datos", "explicador")
        )
        if ya_usada:
            continue

        datos_servicio = _extraer_servicio(titulo, texto, palabras_clave_servicio)
        if datos_servicio:
            notas.append(_componer_servicio(noticia_fuente, datos_servicio))
            continue

        datos_contexto = _extraer_datos_contexto(texto)
        if datos_contexto:
            notas.append(_componer_datos_contexto(noticia_fuente, datos_contexto))
            continue

        datos_explicador = _extraer_explicador(texto)
        if datos_explicador:
            notas.append(_componer_explicador(noticia_fuente, datos_explicador))
            continue

        datos_agenda = _extraer_agenda(titulo, texto)
        if datos_agenda:
            pendientes_agenda.append((noticia_fuente, datos_agenda))

    if pendientes_agenda:
        fecha_iso = ahora_local.strftime("%Y-%m-%d")
        ya_hay_agenda_hoy = db.obtener_por_url(f"https://ledesma-participa.local/contenido-propio/agenda/{fecha_iso}")
        if not ya_hay_agenda_hoy:
            notas.append(_componer_agenda(pendientes_agenda[:5], fecha_iso))

    return notas


def _contenido_propio_generadas_hoy(db: Database, ahora_local: datetime) -> int:
    inicio_dia_utc = ahora_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    return db.contar_por_origen_desde(OrigenIngreso.CONTENIDO_PROPIO.value, inicio_dia_utc)


@dataclass
class ResultadoContenidoPropio:
    tipo: str
    resultado: str  # "preparada" | "duplicado" | "descartada"
    noticia_id: Optional[int]
    titulo: str


def generar_contenido_propio(
    db: Database, ahora: Optional[datetime] = None, config: Optional[dict] = None
) -> List[ResultadoContenidoPropio]:
    """Genera (a lo sumo `max_notas_por_dia`, acumulado por día calendario
    local, no por corrida) las notas propias detectadas, reutilizando el
    pipeline existente completo: dedup por URL/hash/fingerprint, clasificación
    territorial, riesgo editorial y elegibilidad automática — una nota
    propia queda `preparada`/`pendiente` exactamente como cualquier otra, sin
    ningún atajo de aprobación. Nunca publica nada directamente."""
    config = config or _cargar_config()
    max_notas = config.get("max_notas_por_dia", MAX_NOTAS_POR_DIA_DEFAULT)
    ahora_local = (ahora or datetime.now(ZONA_JUJUY)).astimezone(ZONA_JUJUY)

    ya_generadas_hoy = _contenido_propio_generadas_hoy(db, ahora_local)
    cupo_restante = max(0, max_notas - ya_generadas_hoy)
    if cupo_restante == 0:
        logger.info("Contenido propio: ya se alcanzó el máximo de %s notas de hoy.", max_notas)
        return []

    candidatas = detectar_oportunidades(db, ahora_local, config)
    resultados = []
    for candidata in candidatas[:cupo_restante]:
        cruda = {
            "titulo": candidata.titulo,
            "texto": candidata.texto,
            "url": candidata.url_identidad,
            "fuente": NOMBRE_FUENTE_PROPIA,
            "fecha": ahora_local.isoformat(),
            "localidad": candidata.localidad,
        }
        noticia = normalizar_noticia(cruda)
        noticia.origen_ingreso = OrigenIngreso.CONTENIDO_PROPIO.value
        noticia_procesada, resultado_pipeline = procesar_noticia(db, noticia, _RedactorIdentidad())
        logger.info(
            "Contenido propio (%s): %s — %s", candidata.tipo, resultado_pipeline, candidata.titulo
        )
        resultados.append(
            ResultadoContenidoPropio(
                tipo=candidata.tipo, resultado=resultado_pipeline,
                noticia_id=noticia_procesada.id if resultado_pipeline != "duplicado" else None,
                titulo=candidata.titulo,
            )
        )
    return resultados
