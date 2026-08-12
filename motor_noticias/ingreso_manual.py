import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from .ciclo_continuo import NOMBRE_SALUD_AGENDA
from .db import Database
from .dedupe import hash_contenido as calcular_hash_contenido
from .models import Estado, OrigenIngreso
from .motor_editorial import generar_agenda
from .pipeline import normalizar_noticia, procesar_noticia
from .redaccion.base import Redactor

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

    _, resultado_pipeline = procesar_noticia(db, noticia, redactor, categoria=None)
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
