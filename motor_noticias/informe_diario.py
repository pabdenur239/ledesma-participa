"""Informe diario de servicio: clima de Libertador General San Martín
(Open-Meteo) + cotización del dólar oficial y blue (DolarApi Argentina), a
las 07:30 hora local. Queda como noticia `preparada`/`pendiente` para
revisión humana igual que cualquier otra — nunca se publica automáticamente.

Reutiliza el mismo pipeline que el resto del proyecto (normalizar_noticia /
procesar_noticia: deduplicación, clasificación territorial, elegibilidad,
riesgo editorial). El texto se arma de forma enteramente determinística
(sin IA): un redactor "identidad" interno devuelve el título/texto tal como
se construyeron, para no depender de Ollama ni arriesgar que un modelo
altere valores numéricos.

Costo cero: ambas APIs son públicas y no requieren clave. Solo biblioteca
estándar (urllib/json), sin dependencias nuevas."""
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlencode

from .db import Database
from .models import Noticia
from .motor_editorial import ZONA_JUJUY
from .pipeline import normalizar_noticia, procesar_noticia
from .redaccion.base import Redactor

logger = logging.getLogger("motor_noticias.informe_diario")

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "informe_diario.json"

ENDPOINT_CLIMA = "https://api.open-meteo.com/v1/forecast"
ENDPOINT_DOLAR = "https://dolarapi.com/v1/dolares/{casa}"

LATITUD_DEFAULT = -23.8058
LONGITUD_DEFAULT = -64.7892
TIMEZONE_DEFAULT = "America/Argentina/Jujuy"
TIMEOUT_DEFAULT = 10

NOMBRE_SALUD = "informe-diario"
NOMBRE_FUENTE = "Informe Diario (Clima y Dólar) — Ledesma Participa"

# Códigos meteorológicos WMO (weather_code de Open-Meteo) -> texto en
# español. Un código no listado usa un texto genérico honesto, nunca se
# inventa una condición climática.
CODIGOS_CLIMA = {
    0: "despejado",
    1: "mayormente despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "con niebla",
    48: "con niebla escarchada",
    51: "con llovizna débil",
    53: "con llovizna moderada",
    55: "con llovizna intensa",
    56: "con llovizna helada débil",
    57: "con llovizna helada intensa",
    61: "con lluvia débil",
    63: "con lluvia moderada",
    65: "con lluvia intensa",
    66: "con lluvia helada débil",
    67: "con lluvia helada intensa",
    71: "con nevada débil",
    73: "con nevada moderada",
    75: "con nevada intensa",
    77: "con granizo fino",
    80: "con chubascos débiles",
    81: "con chubascos moderados",
    82: "con chubascos intensos",
    85: "con chubascos de nieve débiles",
    86: "con chubascos de nieve intensos",
    95: "con tormenta",
    96: "con tormenta y granizo débil",
    99: "con tormenta y granizo intenso",
}
DESCRIPCION_CLIMA_DESCONOCIDA = "sin condición climática especificada por la fuente"


class ErrorInformeDiario(RuntimeError):
    """Error controlado al generar el informe diario: nunca se completa
    con datos inventados, se registra y se puede reintentar en el próximo
    disparo de la tarea programada."""


class _RedactorIdentidad(Redactor):
    """Devuelve el título/texto exactamente como se armaron, sin pasar por
    ningún modelo de lenguaje: el contenido del informe ya es final y
    determinístico por construcción (no debe parafrasearse ni arriesgarse
    a que un LLM altere una cifra)."""

    def redactar(self, noticia: Noticia) -> Tuple[str, str]:
        return noticia.titulo_original, noticia.texto_original


def _cargar_config(path: Optional[Path] = None) -> dict:
    try:
        with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _codigo_clima_a_texto(codigo: Optional[int]) -> str:
    if codigo is None:
        return DESCRIPCION_CLIMA_DESCONOCIDA
    return CODIGOS_CLIMA.get(codigo, DESCRIPCION_CLIMA_DESCONOCIDA)


def _pedir_json(url: str, timeout: int, urlopen) -> dict:
    # Bug real detectado en producción: DolarApi (detrás de Cloudflare)
    # devolvía HTTP 403 a una petición sin User-Agent (la que hace
    # urllib.request por defecto no alcanza). Un identificador claro y un
    # Accept explícito resuelven el rechazo, sin cambiar endpoints ni
    # lógica. Mismo cliente para clima y dólar: aplica a ambas fuentes.
    peticion = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 LedesmaParticipa/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(peticion, timeout=timeout) as respuesta:
            estado = getattr(respuesta, "status", 200)
            if estado and estado >= 400:
                raise ErrorInformeDiario(f"{url} respondió HTTP {estado}")
            contenido = respuesta.read()
    except urllib.error.HTTPError as error:
        raise ErrorInformeDiario(f"{url} respondió HTTP {error.code} ({error.reason})") from error
    except urllib.error.URLError as error:
        raise ErrorInformeDiario(f"No se pudo conectar a {url}: {error.reason}") from error
    except TimeoutError as error:
        raise ErrorInformeDiario(f"Tiempo de espera agotado al conectar con {url}") from error

    try:
        return json.loads(contenido)
    except json.JSONDecodeError as error:
        raise ErrorInformeDiario(f"{url} devolvió una respuesta que no es JSON válido") from error


def _numero(valor, campo: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErrorInformeDiario(f"Campo '{campo}' inválido o ausente en la respuesta de la fuente")
    return float(valor)


@dataclass
class DatosClima:
    descripcion: str
    temperatura_actual: float
    temperatura_minima: float
    temperatura_maxima: float
    probabilidad_lluvia_maxima: float
    actualizado_en: str


@dataclass
class DatosDolar:
    casa: str
    nombre: str
    compra: float
    venta: float
    actualizado_en: str


def obtener_clima(config: Optional[dict] = None, urlopen=urllib.request.urlopen) -> DatosClima:
    config = config or {}
    clima_config = config.get("clima", {})
    latitud = clima_config.get("latitud", LATITUD_DEFAULT)
    longitud = clima_config.get("longitud", LONGITUD_DEFAULT)
    tz = clima_config.get("timezone", TIMEZONE_DEFAULT)
    timeout = config.get("timeout_segundos", TIMEOUT_DEFAULT)

    parametros = urlencode(
        {
            "latitude": latitud,
            "longitude": longitud,
            "current": "temperature_2m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": tz,
        }
    )
    datos = _pedir_json(f"{ENDPOINT_CLIMA}?{parametros}", timeout, urlopen)

    if not isinstance(datos, dict):
        raise ErrorInformeDiario("La respuesta de Open-Meteo no tiene el formato esperado")

    actual = datos.get("current")
    diario = datos.get("daily")
    if not isinstance(actual, dict) or not isinstance(diario, dict):
        raise ErrorInformeDiario("La respuesta de Open-Meteo no incluye 'current'/'daily' válidos")

    try:
        temperatura_actual = _numero(actual.get("temperature_2m"), "current.temperature_2m")
        codigo_clima = actual.get("weather_code")
        if isinstance(codigo_clima, bool) or not isinstance(codigo_clima, int):
            raise ErrorInformeDiario("Campo 'current.weather_code' inválido o ausente")
        actualizado_en = actual.get("time")
        if not actualizado_en or not isinstance(actualizado_en, str):
            raise ErrorInformeDiario("Campo 'current.time' inválido o ausente")

        maximas = diario.get("temperature_2m_max")
        minimas = diario.get("temperature_2m_min")
        lluvias = diario.get("precipitation_probability_max")
        if not isinstance(maximas, list) or not maximas:
            raise ErrorInformeDiario("Campo 'daily.temperature_2m_max' inválido o vacío")
        if not isinstance(minimas, list) or not minimas:
            raise ErrorInformeDiario("Campo 'daily.temperature_2m_min' inválido o vacío")
        if not isinstance(lluvias, list) or not lluvias:
            raise ErrorInformeDiario("Campo 'daily.precipitation_probability_max' inválido o vacío")

        temperatura_maxima = _numero(maximas[0], "daily.temperature_2m_max[0]")
        temperatura_minima = _numero(minimas[0], "daily.temperature_2m_min[0]")
        probabilidad_lluvia = _numero(lluvias[0], "daily.precipitation_probability_max[0]")
    except (IndexError, TypeError) as error:
        raise ErrorInformeDiario("La respuesta de Open-Meteo tiene un formato inesperado") from error

    return DatosClima(
        descripcion=_codigo_clima_a_texto(codigo_clima),
        temperatura_actual=temperatura_actual,
        temperatura_minima=temperatura_minima,
        temperatura_maxima=temperatura_maxima,
        probabilidad_lluvia_maxima=probabilidad_lluvia,
        actualizado_en=actualizado_en,
    )


def obtener_dolar(casa: str, config: Optional[dict] = None, urlopen=urllib.request.urlopen) -> DatosDolar:
    config = config or {}
    timeout = config.get("timeout_segundos", TIMEOUT_DEFAULT)
    datos = _pedir_json(ENDPOINT_DOLAR.format(casa=casa), timeout, urlopen)

    if not isinstance(datos, dict):
        raise ErrorInformeDiario(f"La respuesta de DolarApi ({casa}) no tiene el formato esperado")

    compra = _numero(datos.get("compra"), f"{casa}.compra")
    venta = _numero(datos.get("venta"), f"{casa}.venta")
    actualizado_en = datos.get("fechaActualizacion")
    if not actualizado_en or not isinstance(actualizado_en, str):
        raise ErrorInformeDiario(f"Campo 'fechaActualizacion' inválido o ausente para dólar {casa}")

    nombre = datos.get("nombre")
    nombre = nombre if isinstance(nombre, str) and nombre else casa.capitalize()

    return DatosDolar(casa=casa, nombre=nombre, compra=compra, venta=venta, actualizado_en=actualizado_en)


def _hora_legible(iso_o_fecha: str) -> str:
    """Extrae HH:MM de un timestamp ISO 8601 (con o sin offset/zona) para
    mostrarlo en el texto. Si no se puede interpretar, devuelve el valor
    crudo tal cual — nunca se inventa una hora."""
    try:
        momento = datetime.fromisoformat(iso_o_fecha.replace("Z", "+00:00"))
    except ValueError:
        return iso_o_fecha
    return momento.strftime("%H:%M")


def _construir_texto(clima: DatosClima, dolar_oficial: DatosDolar, dolar_blue: DatosDolar, fecha_local) -> Tuple[str, str]:
    fecha_legible = fecha_local.strftime("%d/%m/%Y")
    titulo = f"Clima y dólar en Libertador: informe del {fecha_legible}"

    texto = (
        f"Buen día. En Libertador General San Martín, la temperatura actual es de "
        f"{clima.temperatura_actual:.1f}°C ({clima.descripcion}). Para hoy se espera una mínima de "
        f"{clima.temperatura_minima:.1f}°C, una máxima de {clima.temperatura_maxima:.1f}°C y una "
        f"probabilidad de lluvia de {clima.probabilidad_lluvia_maxima:.0f}% "
        f"(Open-Meteo, actualizado {_hora_legible(clima.actualizado_en)}).\n\n"
        f"Dólar oficial: compra ${dolar_oficial.compra:.0f} / venta ${dolar_oficial.venta:.0f} "
        f"(DolarApi, actualizado {_hora_legible(dolar_oficial.actualizado_en)}).\n"
        f"Dólar blue: compra ${dolar_blue.compra:.0f} / venta ${dolar_blue.venta:.0f} "
        f"(DolarApi, actualizado {_hora_legible(dolar_blue.actualizado_en)}).\n\n"
        "Informe de servicio generado automáticamente con datos de fuentes externas; "
        "no reemplaza asesoramiento financiero ni meteorológico oficial."
    )
    return titulo, texto


@dataclass
class ResultadoInformeDiario:
    resultado: str  # "preparada" | "duplicado" | "error"
    noticia_id: Optional[int]
    fecha_local: str
    mensaje_error: Optional[str] = None


def generar_informe_diario(
    db: Database,
    ahora: Optional[datetime] = None,
    config_path: Optional[Path] = None,
    urlopen=urllib.request.urlopen,
) -> ResultadoInformeDiario:
    """Genera (a lo sumo una vez por fecha local en America/Argentina/Jujuy)
    el informe diario de clima + dólar, y lo deja como noticia `preparada`/
    `pendiente`. Si el informe de hoy ya existe, termina limpiamente sin
    duplicar. Si falta cualquiera de las dos fuentes o los datos esenciales
    no son válidos, no guarda nada: termina con error para poder
    reintentarse en la próxima ejecución de la tarea programada."""
    config = _cargar_config(config_path)
    ahora_local = (ahora or datetime.now(ZONA_JUJUY)).astimezone(ZONA_JUJUY)
    fecha_local = ahora_local.date()
    fecha_iso = fecha_local.isoformat()

    # Identidad determinística por día: reutiliza el mecanismo de dedupe ya
    # existente (URL normalizada) para garantizar como máximo un informe
    # por fecha, sin necesidad de ningún campo ni tabla nueva.
    url_informe = f"https://ledesma-participa.local/informe-diario/{fecha_iso}"

    try:
        clima = obtener_clima(config, urlopen=urlopen)
        dolar_oficial = obtener_dolar("oficial", config, urlopen=urlopen)
        dolar_blue = obtener_dolar("blue", config, urlopen=urlopen)
    except ErrorInformeDiario as error:
        mensaje = str(error)
        logger.error("Informe diario: %s", mensaje)
        db.registrar_salud_fuente(NOMBRE_SALUD, "error", mensaje_error=mensaje)
        return ResultadoInformeDiario(resultado="error", noticia_id=None, fecha_local=fecha_iso, mensaje_error=mensaje)

    titulo, texto = _construir_texto(clima, dolar_oficial, dolar_blue, fecha_local)

    cruda = {
        "titulo": titulo,
        "texto": texto,
        "url": url_informe,
        "fuente": NOMBRE_FUENTE,
        "fecha": ahora_local.isoformat(),
    }
    noticia = normalizar_noticia(cruda)
    noticia_procesada, resultado_pipeline = procesar_noticia(db, noticia, _RedactorIdentidad(), categoria=None)

    if resultado_pipeline == "duplicado":
        logger.info("Informe diario: ya existe el informe de %s, no se duplica.", fecha_iso)
        db.registrar_salud_fuente(NOMBRE_SALUD, "ok", elementos_obtenidos=1, noticias_nuevas=0)
        return ResultadoInformeDiario(resultado="duplicado", noticia_id=None, fecha_local=fecha_iso)

    if resultado_pipeline == "preparada":
        logger.info("Informe diario: generado y preparado para revisión (fecha %s).", fecha_iso)
        db.registrar_salud_fuente(NOMBRE_SALUD, "ok", elementos_obtenidos=1, noticias_nuevas=1)
        return ResultadoInformeDiario(resultado="preparada", noticia_id=noticia_procesada.id, fecha_local=fecha_iso)

    # No debería ocurrir (el texto siempre menciona "Libertador General San
    # Martín" -> territorio local -> siempre elegible), pero si alguna vez
    # pasara, nunca se deja pasar como si estuviera todo bien: se informa
    # como error real en vez de un informe "descartada" silencioso.
    mensaje = f"El informe no quedó preparado (resultado del pipeline: {resultado_pipeline})"
    logger.error("Informe diario: %s", mensaje)
    db.registrar_salud_fuente(NOMBRE_SALUD, "error", mensaje_error=mensaje)
    return ResultadoInformeDiario(resultado="error", noticia_id=None, fecha_local=fecha_iso, mensaje_error=mensaje)
