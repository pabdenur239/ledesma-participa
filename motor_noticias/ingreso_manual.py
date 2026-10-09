import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from .ciclo_continuo import NOMBRE_SALUD_AGENDA
from .db import Database
from .dedupe import es_mismo_contenido, normalizar_url, palabras_clave, refieren_a_hecho_distinto
from .dedupe import hash_contenido as calcular_hash_contenido
from .lectura_url import ErrorLecturaURL, es_enlace_video, leer_texto_url
from .models import Estado, OrigenIngreso
from .motor_editorial import generar_agenda
from .pipeline import normalizar_noticia, procesar_noticia
from .portal import PALABRAS_NOMBRE_CIUDAD
from .redaccion.base import Redactor
from .territorio import clasificar_territorio

logger = logging.getLogger("motor_noticias.ingreso_manual")

# Límites centralizados: seguridad básica de un formulario local (evitar
# campos absurdamente grandes), no reglas editoriales — la suficiencia
# periodística la sigue evaluando `elegibilidad_editorial`, sin duplicarla acá.
LONGITUD_MAXIMA_FUENTE = 150
LONGITUD_MAXIMA_TITULO = 500
LONGITUD_MAXIMA_TEXTO = 20000
LONGITUD_MAXIMA_OBSERVACION = 2000
LONGITUD_MAXIMA_URL = 2000
LONGITUD_MAXIMA_LOCALIDAD_INFORMADA = 150
LONGITUD_MAXIMA_FECHA_ORIGEN = 100

# Fallback de título cuando no se informa uno: un recorte literal del propio
# texto pegado (nunca un título inventado), en un límite de palabra.
LONGITUD_TITULO_FALLBACK = 120


class ErrorIngresoManual(ValueError):
    """Datos inválidos en la carga manual: no llega a tocar la base de datos."""


@dataclass
class ResultadoIngresoManual:
    noticia_id: Optional[int]
    resultado_pipeline: str  # "preparada" | "descartada" | "duplicado"
    duplicado: bool
    territorio: Optional[str]
    motivo_territorio: Optional[str]
    estado: str
    revision_estado: Optional[str]
    requiere_revision_especial: bool
    motivo_revision_especial: Optional[str]
    urgente: bool
    fuente: str
    titulo_original: str
    agenda_actualizada: Optional[bool]  # None = no correspondía actualizarla
    agenda_mensaje_error: Optional[str]


def _validar_obligatorio(valor: Optional[str], nombre_campo: str, longitud_maxima: int) -> str:
    valor = (valor or "").strip()
    if not valor:
        raise ErrorIngresoManual(f"{nombre_campo}: campo obligatorio, no puede quedar vacío.")
    if len(valor) > longitud_maxima:
        raise ErrorIngresoManual(f"{nombre_campo} supera el máximo de {longitud_maxima} caracteres.")
    return valor


def _validar_opcional(valor: Optional[str], nombre_campo: str, longitud_maxima: int) -> Optional[str]:
    if valor is None:
        return None
    valor = valor.strip()
    if not valor:
        return None
    if len(valor) > longitud_maxima:
        raise ErrorIngresoManual(f"{nombre_campo} supera el máximo de {longitud_maxima} caracteres.")
    return valor


def _validar_url_opcional(valor: Optional[str], nombre_campo: str) -> Optional[str]:
    valor = _validar_opcional(valor, nombre_campo, LONGITUD_MAXIMA_URL)
    if valor is None:
        return None
    # Solo se valida la forma de la URL (esquema http/https). Nunca se hace
    # ningún request de red sobre ella: se guarda como referencia únicamente.
    esquema = urlsplit(valor).scheme.lower()
    if esquema not in ("http", "https"):
        raise ErrorIngresoManual(f"{nombre_campo} debe empezar con http:// o https://.")
    return valor


def _titulo_o_recorte_literal(titulo: Optional[str], texto: str) -> str:
    if titulo:
        return titulo
    # Sin título informado: se usa un recorte literal del propio texto (no se
    # inventa contenido), cortado en un límite de palabra.
    if len(texto) <= LONGITUD_TITULO_FALLBACK:
        return texto
    recorte = texto[:LONGITUD_TITULO_FALLBACK]
    ultimo_espacio = recorte.rfind(" ")
    if ultimo_espacio > 0:
        recorte = recorte[:ultimo_espacio]
    return recorte.rstrip(" .,;:") + "…"


def cargar_noticia_manual(
    db: Database,
    redactor: Redactor,
    *,
    fuente: str,
    texto: str,
    url: Optional[str] = None,
    titulo: Optional[str] = None,
    fecha_origen: Optional[str] = None,
    localidad_informada: Optional[str] = None,
    imagen_url: Optional[str] = None,
    urgente: bool = False,
    observacion_interna: Optional[str] = None,
    localidad_respaldo: Optional[str] = None,
) -> ResultadoIngresoManual:
    """Carga manual de una noticia local desde el panel (fuentes que hoy no
    se pueden automatizar: Ledesma Soy, FM Imagen, Canal 6, radios, Facebook,
    WhatsApp, comunicados, vecinos, etc.). Reutiliza exactamente el mismo
    circuito editorial que las fuentes automáticas — normalización,
    deduplicación, clasificación territorial, elegibilidad, redacción, riesgo
    editorial — sin crear ningún camino paralelo ni publicar nada. Es una
    función de dominio pura: el panel (`panel/server.py`) es solo la interfaz
    que la invoca; también puede llamarse directo desde un test o un CLI."""
    fuente = _validar_obligatorio(fuente, "La fuente", LONGITUD_MAXIMA_FUENTE)
    texto = _validar_obligatorio(texto, "El texto original", LONGITUD_MAXIMA_TEXTO)
    titulo = _validar_opcional(titulo, "El título", LONGITUD_MAXIMA_TITULO)
    url = _validar_url_opcional(url, "La URL de origen")
    imagen_url = _validar_url_opcional(imagen_url, "La URL de imagen")
    fecha_origen = _validar_opcional(fecha_origen, "La fecha de origen", LONGITUD_MAXIMA_FECHA_ORIGEN)
    localidad_informada = _validar_opcional(
        localidad_informada, "La localidad informada", LONGITUD_MAXIMA_LOCALIDAD_INFORMADA
    )
    observacion_interna = _validar_opcional(
        observacion_interna, "La observación interna", LONGITUD_MAXIMA_OBSERVACION
    )

    titulo_final = _titulo_o_recorte_literal(titulo, texto)

    # Sin URL informada: se genera una referencia sintética estable (según el
    # contenido) solo para satisfacer la columna NOT NULL — nunca se navega
    # ni se le da otro uso. La deduplicación real de estos casos ocurre por
    # hash de contenido, no por esta referencia.
    if url:
        url_para_noticia = url
    else:
        hash_previsto = calcular_hash_contenido(titulo_final, texto)
        url_para_noticia = f"manual://sin-url/{hash_previsto}"

    cruda = {
        "titulo": titulo_final,
        "texto": texto,
        "url": url_para_noticia,
        "fuente": fuente,
        "fecha": fecha_origen or "",
        "imagen_url": imagen_url,
        # Solo lo pasa el canal rápido cuando el contenido por sí solo no
        # ubica el hecho en Libertador/Ledesma (ver `cargar_noticia_local`).
        "localidad": localidad_respaldo,
    }

    noticia = normalizar_noticia(cruda)
    noticia.origen_ingreso = OrigenIngreso.MANUAL.value
    # Pista editorial auditable únicamente: NO se pasa como `localidad_fuente`
    # a la clasificación territorial (eso forzaría silenciosamente un
    # resultado sin mirar el contenido real, como hacen los collectors de
    # fuentes 100% institucionales). El territorio siempre lo decide
    # `clasificar_territorio()` a partir del título/texto, igual que para
    # cualquier otra fuente.
    noticia.localidad_informada = localidad_informada
    noticia.observacion_interna = observacion_interna
    noticia.urgente = urgente

    _, resultado_pipeline = procesar_noticia(
        db, noticia, redactor, categoria=None, tolerar_fallo_redaccion=True
    )
    duplicado = resultado_pipeline == "duplicado"

    agenda_actualizada: Optional[bool] = None
    agenda_mensaje_error: Optional[str] = None
    if resultado_pipeline == "preparada":
        try:
            generar_agenda(db)
            agenda_actualizada = True
            db.registrar_salud_fuente(NOMBRE_SALUD_AGENDA, "ok")
            logger.info("Agenda editorial actualizada")
        except Exception as error:  # nunca se pierde la carga manual por esto
            agenda_actualizada = False
            agenda_mensaje_error = f"Error actualizando agenda: {error}"
            logger.error(agenda_mensaje_error)
            db.registrar_salud_fuente(NOMBRE_SALUD_AGENDA, "error", mensaje_error=agenda_mensaje_error)

    return ResultadoIngresoManual(
        noticia_id=noticia.id,
        resultado_pipeline=resultado_pipeline,
        duplicado=duplicado,
        territorio=noticia.territorio,
        motivo_territorio=noticia.motivo_territorio,
        estado=noticia.estado,
        revision_estado=noticia.revision_estado if resultado_pipeline == "preparada" else None,
        requiere_revision_especial=bool(noticia.requiere_revision_especial),
        motivo_revision_especial=noticia.motivo_revision_especial,
        urgente=bool(noticia.urgente),
        fuente=fuente,
        titulo_original=titulo_final,
        agenda_actualizada=agenda_actualizada,
        agenda_mensaje_error=agenda_mensaje_error,
    )


# ---------------------------------------------------------------------------
# Canal rápido de noticias locales (9/10/2026): "Cargar noticia local" en el
# panel. El operador ve una publicación (casi siempre en Facebook) y manda
# solo URL + fuente (+ texto, territorio y urgente opcionales). Reutiliza
# `cargar_noticia_manual` — mismo circuito editorial, sin camino paralelo —
# y agrega: lectura del texto de sitios web abiertos (nunca redes sociales),
# detección del mismo hecho ya ingresado, territorio informado como respaldo
# y trazabilidad interna (`ingreso_rapido_log`).
# ---------------------------------------------------------------------------

CANAL_PANEL = "panel"
PADRON_FUENTES_PATH = Path(__file__).resolve().parent.parent / "config" / "fuentes_locales.json"
# Ventana de comparación del "mismo hecho": igual que la recuperación local
# del portal (`portal.HORAS_RECUPERACION_LOCAL`).
HORAS_VENTANA_MISMO_HECHO = 48
# Menciones ambiguas (prócer, departamentos homónimos de otras provincias):
# sin contexto que confirme Jujuy, piden el territorio al operador.
_RE_MENCION_AMBIGUA = re.compile(r"\b(libertador|ledesma)\b")


@dataclass
class FuentePadron:
    nombre: str
    clasificacion: Optional[str]  # A / B / C, None = pendiente de confirmar
    monitoreo_inmediato: bool


@dataclass
class ResultadoIngresoLocal:
    resultado: str  # "preparada" | "descartada" | "solo_portal" | "duplicado" | "mismo_hecho"
    origen_texto: str  # "url" | "manual"
    es_video: bool
    fuente_padron: Optional[FuentePadron]
    duplicado_de: Optional[dict]  # {"id", "titulo", "fuente"} de la noticia que ya existía
    territorio_respaldo_usado: bool
    manual: Optional[ResultadoIngresoManual]  # None si se cortó antes del circuito


def _sin_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).strip()


def fuentes_canal_rapido(path: Optional[Path] = None) -> List[FuentePadron]:
    """Fuentes ofrecidas en el formulario: el padrón aprobado más las
    pendientes de confirmar (sin URL verificada). Si el archivo no se puede
    leer, lista vacía: el campo sigue aceptando texto libre."""
    try:
        with open(path or PADRON_FUENTES_PATH, encoding="utf-8") as archivo:
            padron = json.load(archivo)
    except (OSError, json.JSONDecodeError):
        return []
    fuentes = [
        FuentePadron(f["nombre"], f.get("clasificacion"), bool(f.get("monitoreo_inmediato")))
        for f in padron.get("fuentes", []) if f.get("nombre")
    ]
    fuentes += [
        FuentePadron(f["nombre"], None, False)
        for f in padron.get("pendientes_de_confirmar", []) if f.get("nombre")
    ]
    return fuentes


def buscar_fuente_padron(nombre: str, fuentes: List[FuentePadron]) -> Optional[FuentePadron]:
    buscado = _sin_acentos(nombre)
    for fuente in fuentes:
        if _sin_acentos(fuente.nombre) == buscado:
            return fuente
    return None


def _huella_titulo(titulo: str) -> frozenset:
    return palabras_clave(titulo) - PALABRAS_NOMBRE_CIUDAD


def buscar_mismo_hecho(db: Database, titulo: str, ahora: Optional[datetime] = None) -> Optional[dict]:
    """Noticia ya ingresada (últimas 48 h, no descartada) que cuenta el mismo
    hecho con otro título — mismo criterio que la deduplicación del portal
    (huella de palabras clave; localidades o fechas distintas desempatan)."""
    huella = _huella_titulo(titulo)
    if not huella:
        return None
    limite = ((ahora or datetime.now(timezone.utc)) - timedelta(hours=HORAS_VENTANA_MISMO_HECHO)).isoformat()
    for otra in db.noticias_ingresadas_desde(limite):
        otro_titulo = otra.get("titulo_original") or ""
        if es_mismo_contenido(huella, _huella_titulo(otro_titulo)) and not refieren_a_hecho_distinto(titulo, otro_titulo):
            return {"id": otra["id"], "titulo": otro_titulo, "fuente": otra.get("nombre_fuente")}
    return None


def _territorio_de_localidad(localidad: str) -> Optional[str]:
    resultado = clasificar_territorio("", "", localidad_fuente=localidad)
    return resultado["territorio"] if resultado["territorio"] in ("local", "departamental") else None


def _contenido_ubica_en_ledesma(titulo: str, texto: str, fuente: str, url: Optional[str]) -> bool:
    clasificacion = clasificar_territorio(titulo, texto, nombre_fuente=fuente, url=url)
    return clasificacion["territorio"] in ("local", "departamental")


def cargar_noticia_local(
    db: Database,
    redactor: Redactor,
    *,
    fuente: str,
    url: Optional[str] = None,
    texto: Optional[str] = None,
    territorio_informado: Optional[str] = None,
    imagen_url: Optional[str] = None,
    urgente: bool = False,
    forzar_no_duplicado: bool = False,
    canal: str = CANAL_PANEL,
    leer_url=leer_texto_url,
) -> ResultadoIngresoLocal:
    """Entrada mínima: URL + fuente. El texto es obligatorio solo si la URL
    no se puede leer (redes sociales, sitio caído). Nunca se toma la imagen
    ni el video de la publicación original: la imagen solo entra si el
    operador carga una propia/autorizada (si no, placa editorial) y el video
    queda como enlace de referencia. No publica nada por sí mismo: la
    noticia queda en el mismo circuito que cualquier otra (web/app por el
    portal; redes solo si la eligen las franjas, el circuito urgente o una
    persona)."""
    fuente = _validar_obligatorio(fuente, "La fuente", LONGITUD_MAXIMA_FUENTE)
    url = _validar_url_opcional(url, "La URL de la publicación")
    texto = _validar_opcional(texto, "El texto", LONGITUD_MAXIMA_TEXTO)
    territorio_informado = _validar_opcional(
        territorio_informado, "El territorio", LONGITUD_MAXIMA_LOCALIDAD_INFORMADA
    )
    if not url and not texto:
        raise ErrorIngresoManual("Ingresá la URL de la publicación o pegá el texto.")

    titulo = None
    origen_texto = "manual"
    if not texto:
        try:
            leido = leer_url(url)
        except ErrorLecturaURL as error:
            raise ErrorIngresoManual(
                f"No se pudo leer la URL automáticamente ({error}) Pegá el texto de la publicación."
            ) from error
        titulo, texto, origen_texto = leido.titulo, leido.texto, "url"
        if titulo and len(titulo) > LONGITUD_MAXIMA_TITULO:
            titulo = None

    fuente_padron = buscar_fuente_padron(fuente, fuentes_canal_rapido())
    es_video = bool(url) and es_enlace_video(url)
    titulo_final = _titulo_o_recorte_literal(titulo, texto)
    traza = {
        "canal": canal, "fuente": fuente, "fuente_en_padron": int(fuente_padron is not None),
        "url_original": url, "origen_texto": origen_texto, "es_video": int(es_video),
        "territorio_informado": territorio_informado,
    }

    # 1) La misma publicación ya ingresada (URL normalizada, incluidas las
    #    variantes m./web. y los parámetros de compartir de Facebook).
    if url:
        existente = db.id_noticia_por_url(normalizar_url(url))
        if existente is not None:
            previa = db.obtener(existente) or {}
            duplicado_de = {"id": existente, "titulo": previa.get("titulo_original"), "fuente": previa.get("nombre_fuente")}
            db.registrar_ingreso_rapido(**traza, resultado="duplicado", duplicado_de=existente)
            return ResultadoIngresoLocal("duplicado", origen_texto, es_video, fuente_padron, duplicado_de, False, None)

    # 2) El mismo hecho desde otra página/medio con otro título: se consolida
    #    en la noticia existente, salvo que el operador confirme que es otro.
    if not forzar_no_duplicado:
        mismo = buscar_mismo_hecho(db, titulo_final)
        if mismo is not None:
            db.registrar_ingreso_rapido(**traza, resultado="mismo_hecho", duplicado_de=mismo["id"])
            return ResultadoIngresoLocal("mismo_hecho", origen_texto, es_video, fuente_padron, mismo, False, None)

    # 3) Territorio informado: solo respaldo cuando el contenido por sí solo
    #    no ubica el hecho en Libertador/Ledesma (lo que dice el texto manda).
    #    Si el texto nombra Libertador/Ledesma sin contexto que confirme que
    #    es la localidad jujeña (fuente fuera del padrón, sin Jujuy/Ramal…),
    #    no se adivina: se pide el territorio al operador.
    ubicada = _contenido_ubica_en_ledesma(titulo_final, texto, fuente, url)
    if not ubicada and not territorio_informado and _RE_MENCION_AMBIGUA.search(_sin_acentos(f"{titulo_final} {texto}")):
        db.registrar_ingreso_rapido(**traza, resultado="territorio_ambiguo")
        raise ErrorIngresoManual(
            "El texto menciona Libertador/Ledesma pero no alcanza para confirmar dónde ocurrió: "
            "completá el campo Territorio."
        )
    localidad_respaldo = None
    if territorio_informado and not ubicada and _territorio_de_localidad(territorio_informado):
        localidad_respaldo = territorio_informado

    notas = [f"Canal rápido ({canal}): texto {'leído de la URL' if origen_texto == 'url' else 'pegado por el operador'}."]
    if es_video:
        notas.append("Publicación con video: se conserva solo el enlace original (no se descarga).")
    if fuente_padron is None:
        notas.append("Fuente fuera del padrón: corroborar antes de aprobar.")
    elif fuente_padron.clasificacion == "C":
        notas.append("Fuente clase C: nunca única base, corroborar con A o B.")
    elif fuente_padron.clasificacion is None:
        notas.append("Fuente pendiente de confirmar en el padrón.")

    manual = cargar_noticia_manual(
        db, redactor,
        fuente=fuente, texto=texto, url=url, titulo=titulo,
        localidad_informada=territorio_informado, imagen_url=imagen_url,
        urgente=urgente, observacion_interna=" ".join(notas),
        localidad_respaldo=localidad_respaldo,
    )
    db.registrar_ingreso_rapido(
        **traza, resultado=manual.resultado_pipeline, noticia_id=manual.noticia_id, estado=manual.estado,
    )
    return ResultadoIngresoLocal(
        manual.resultado_pipeline, origen_texto, es_video, fuente_padron, None,
        localidad_respaldo is not None, manual,
    )
