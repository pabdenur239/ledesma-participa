"""RADIOS EN VIVO (Etapa 2, 9/10/2026).

Lista de emisoras en `config/radios.json` (alta, baja lógica, cambio de URL,
zona, orden y activar/desactivar se hacen editando ese archivo). Solo se
aceptan fuentes autorizadas: stream oficial de la emisora, player oficial
embebible, URL oficial publicada por la radio o integración autorizada.
Nunca se captura audio de Facebook ni se extrae de YouTube, no se
retransmite ni se hace proxy de ningún stream: la web y la app reproducen
directamente la URL oficial. Sin stream ni player oficial, la ficha se
muestra con "Sin transmisión online disponible".

Los datos DEMO (`config/radios_demo.json`, `demo: true`) solo se cargan con
`LEDESMA_RADIOS_DEMO=1` (entorno local); un registro `demo: true` dentro
de `config/radios.json` se descarta siempre.

Verificación de stream: una consulta por radio con timeout corto, solo al
generar el sitio y como máximo cada `verificacion_minutos` (caché en
`data/radios_estado.json`). Nunca se informa EN VIVO sin una verificación
reciente exitosa.
"""
import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("motor_noticias.radios")

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_PATH_DEFAULT = RAIZ / "config" / "radios.json"
DEMO_PATH_DEFAULT = RAIZ / "config" / "radios_demo.json"
ESTADO_PATH_DEFAULT = RAIZ / "data" / "radios_estado.json"
VARIABLE_DEMO = "LEDESMA_RADIOS_DEMO"

# (etiqueta, slug) en el orden en que se muestran.
ZONAS = (
    ("Libertador", "libertador"),
    ("Departamento Ledesma", "ledesma"),
    ("Jujuy", "jujuy"),
    ("Argentina", "argentina"),
)
SLUG_ZONA = dict(ZONAS)
TIPOS_STREAM = ("mp3", "aac", "ogg", "hls")
VERIFICACION_MINUTOS_DEFAULT = 60
TIMEOUT_SEGUNDOS = 8

# Estados de transmisión (nunca se muestra un estado que no se verificó).
EN_VIVO = "en_vivo"
NO_DISPONIBLE = "no_disponible"          # verificación reciente fallida
SIN_VERIFICAR = "sin_verificar"          # stream sin verificación reciente, o solo player oficial
SIN_TRANSMISION = "sin_transmision"      # no hay stream ni player oficial

# Plataformas de las que está prohibido tomar audio (Etapa 2, regla legal).
_HOSTS_PROHIBIDOS = (
    "facebook.com", "fb.watch", "fb.com", "fbcdn.net", "instagram.com", "youtube.com", "youtu.be",
    "youtube-nocookie.com", "googlevideo.com", "tiktok.com",
)
_TIPOS_AUDIO = (
    "audio/", "application/ogg", "application/vnd.apple.mpegurl", "application/x-mpegurl",
)
_RE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")


def _host_prohibido(host: str) -> bool:
    host = host.lower().split(":")[0]
    return any(host == h or host.endswith("." + h) for h in _HOSTS_PROHIBIDOS)


def url_autorizable(url: Optional[str]) -> Optional[str]:
    """La URL si es https y no es de una plataforma de la que está prohibido
    tomar audio; si no, None. (http se descarta: el sitio es https y el
    navegador bloquearía el audio como contenido mixto.)"""
    url = (url or "").strip()
    if not url:
        return None
    try:
        partes = urlparse(url)
    except ValueError:
        return None
    if partes.scheme != "https" or not partes.netloc or _host_prohibido(partes.netloc):
        return None
    return url


def _enlace(url: Optional[str]) -> Optional[str]:
    """Enlaces informativos (sitio, redes): https/http, sin reproducir nada."""
    url = (url or "").strip()
    try:
        partes = urlparse(url)
    except ValueError:
        return None
    return url if partes.scheme in ("http", "https") and partes.netloc else None


def _leer(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def demo_habilitado() -> bool:
    return os.environ.get(VARIABLE_DEMO, "").strip() == "1"


def normalizar_radio(crudo: dict, *, permitir_demo: bool = False) -> Optional[dict]:
    """Registro limpio o None si no corresponde mostrarlo (inactivo, baja
    lógica, demo fuera de pruebas, datos mínimos faltantes o zona inválida).
    Una URL de stream/player no autorizable se descarta (queda la ficha sin
    botón Escuchar), no se corrige."""
    if not isinstance(crudo, dict):
        return None
    es_demo = bool(crudo.get("demo"))
    if es_demo and not permitir_demo:
        return None
    if crudo.get("activa") is not True or (crudo.get("estado") or "activa") != "activa":
        return None
    radio_id = (crudo.get("id") or "").strip()
    nombre = (crudo.get("nombre") or "").strip()
    zona = (crudo.get("zona") or "").strip()
    if not _RE_ID.match(radio_id) or not nombre or zona not in SLUG_ZONA:
        return None

    stream_url = url_autorizable(crudo.get("stream_url"))
    player_url = url_autorizable(crudo.get("player_url"))
    autorizacion = (crudo.get("fuente_autorizacion") or "").strip()
    if (stream_url or player_url) and not autorizacion:
        logger.warning("Radio %s sin fuente_autorizacion: se muestra sin botón Escuchar", radio_id)
        stream_url = player_url = None
    if crudo.get("stream_url") and not stream_url:
        logger.warning("Radio %s: stream_url no autorizable (https, sin Facebook/YouTube): descartada", radio_id)
    tipo = (crudo.get("tipo_stream") or "").strip().lower() or None
    if stream_url and tipo not in TIPOS_STREAM:
        tipo = "hls" if stream_url.lower().split("?")[0].endswith(".m3u8") else "mp3"

    try:
        orden = int(crudo.get("orden") or 0)
    except (TypeError, ValueError):
        orden = 0
    return {
        "id": radio_id,
        "nombre": nombre,
        "dial": (crudo.get("dial") or "").strip() or None,
        "localidad": (crudo.get("localidad") or "").strip() or None,
        "zona": zona,
        "zona_slug": SLUG_ZONA[zona],
        "logo_url": url_autorizable(crudo.get("logo_url")),
        "stream_url": stream_url,
        "player_url": player_url,
        "tipo_stream": tipo if stream_url else None,
        "sitio_web": _enlace(crudo.get("sitio_web")),
        "facebook": _enlace(crudo.get("facebook")),
        "instagram": _enlace(crudo.get("instagram")),
        "estado": "activa",
        "activa": True,
        "orden": orden,
        "demo": es_demo,
    }


def cargar_radios(
    path: Optional[Path] = None, *, demo_path: Optional[Path] = None, incluir_demo: Optional[bool] = None,
) -> List[dict]:
    """Radios activas y válidas, ordenadas por zona, `orden` y nombre."""
    incluir_demo = demo_habilitado() if incluir_demo is None else incluir_demo
    crudos = list(_leer(Path(path or CONFIG_PATH_DEFAULT)).get("radios") or [])
    radios = [r for r in (normalizar_radio(c) for c in crudos) if r]
    if incluir_demo:
        demos = _leer(Path(demo_path or DEMO_PATH_DEFAULT)).get("radios") or []
        radios += [r for r in (normalizar_radio(c, permitir_demo=True) for c in demos if c.get("demo")) if r]
    vistos, unicas = set(), []
    for r in radios:
        if r["id"] not in vistos:
            vistos.add(r["id"])
            unicas.append(r)
    indice_zona = {etiqueta: i for i, (etiqueta, _) in enumerate(ZONAS)}
    unicas.sort(key=lambda r: (indice_zona[r["zona"]], r["orden"], r["nombre"].lower()))
    return unicas


def minutos_verificacion(path: Optional[Path] = None) -> int:
    try:
        return max(15, int(_leer(Path(path or CONFIG_PATH_DEFAULT)).get("verificacion_minutos") or VERIFICACION_MINUTOS_DEFAULT))
    except (TypeError, ValueError):
        return VERIFICACION_MINUTOS_DEFAULT


def tipo_compatible(content_type: Optional[str]) -> bool:
    tipo = (content_type or "").split(";")[0].strip().lower()
    return any(tipo.startswith(t) for t in _TIPOS_AUDIO)


def verificar_stream(url: str, *, timeout: float = TIMEOUT_SEGUNDOS, abrir: Optional[Callable] = None) -> dict:
    """Una sola consulta GET (sin descargar audio: se cierra apenas llegan
    los encabezados). {"ok", "content_type", "error"}; nunca lanza."""
    abrir = abrir or urllib.request.urlopen
    pedido = urllib.request.Request(url, headers={"User-Agent": "LedesmaParticipa-Radios/1.0", "Icy-MetaData": "0"})
    try:
        respuesta = abrir(pedido, timeout=timeout)
        try:
            codigo = getattr(respuesta, "status", None) or respuesta.getcode()
            content_type = respuesta.headers.get("Content-Type")
        finally:
            respuesta.close()
    except urllib.error.HTTPError as e:
        return {"ok": False, "content_type": None, "error": f"HTTP {e.code}"}
    except Exception as e:  # timeout, DNS, TLS, conexión rechazada…
        return {"ok": False, "content_type": None, "error": type(e).__name__}
    if not 200 <= int(codigo) < 300:
        return {"ok": False, "content_type": content_type, "error": f"HTTP {codigo}"}
    if not tipo_compatible(content_type):
        return {"ok": False, "content_type": content_type, "error": "tipo de contenido no compatible"}
    return {"ok": True, "content_type": content_type, "error": None}


def _parsear(fecha: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(fecha) if fecha else None
    except ValueError:
        return None


def actualizar_estados(
    radios: List[dict], *, ahora: Optional[datetime] = None, estado_path: Optional[Path] = None,
    minutos: Optional[int] = None, verificar: Optional[Callable[[str], dict]] = None,
) -> List[dict]:
    """Agrega `estado_transmision` y `ultima_verificacion` a cada radio.
    Re-verifica un stream solo si su última verificación tiene más de
    `minutos` o si cambió la URL; el resto sale de la caché. Las radios
    demo nunca se verifican (no hay tráfico hacia URLs ficticias)."""
    ahora = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    estado_path = Path(estado_path or ESTADO_PATH_DEFAULT)
    minutos = minutos or minutos_verificacion()
    verificar = verificar or verificar_stream
    cache: Dict[str, dict] = _leer(estado_path)
    nueva_cache: Dict[str, dict] = {}

    for r in radios:
        if not r["stream_url"]:
            r["estado_transmision"] = SIN_VERIFICAR if r["player_url"] else SIN_TRANSMISION
            r["ultima_verificacion"] = None
            continue
        if r.get("demo"):
            r["estado_transmision"] = SIN_VERIFICAR
            r["ultima_verificacion"] = None
            continue
        previo = cache.get(r["id"]) or {}
        verificado_en = _parsear(previo.get("verificado_en"))
        vigente = (
            previo.get("url") == r["stream_url"] and verificado_en is not None
            and ahora - verificado_en < timedelta(minutes=minutos)
        )
        if not vigente:
            resultado = verificar(r["stream_url"])
            previo = {"url": r["stream_url"], "ok": bool(resultado.get("ok")), "error": resultado.get("error"),
                      "verificado_en": ahora.isoformat()}
            if not previo["ok"]:
                logger.info("Radio %s: stream no disponible (%s)", r["id"], previo["error"])
        nueva_cache[r["id"]] = previo
        r["estado_transmision"] = EN_VIVO if previo["ok"] else NO_DISPONIBLE
        r["ultima_verificacion"] = previo["verificado_en"]

    if nueva_cache or cache:
        try:
            estado_path.parent.mkdir(parents=True, exist_ok=True)
            estado_path.write_text(json.dumps(nueva_cache, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as e:
            logger.warning("No se pudo guardar %s: %s", estado_path, e)
    return radios


def datos_api(r: dict) -> dict:
    """Formato público de la API (sin el campo interno `demo` si es False)."""
    claves = (
        "id", "nombre", "dial", "localidad", "zona", "zona_slug", "logo_url", "stream_url", "player_url",
        "tipo_stream", "sitio_web", "facebook", "instagram", "estado", "activa", "orden",
        "estado_transmision", "ultima_verificacion",
    )
    datos = {k: r.get(k) for k in claves}
    if r.get("demo"):
        datos["demo"] = True
    return datos
