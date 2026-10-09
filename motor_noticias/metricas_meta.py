"""Métricas reales de Meta (Etapa 3 — medición), solo lectura.

Usa exclusivamente el token y los IDs ya configurados (`META_*`); no pide
permisos nuevos ni cambia credenciales. Verificado contra la API real el
9/10/2026 con los permisos actuales:

- Facebook: `followers_count` / `fan_count` de la página → DISPONIBLE.
  Insights de página y de publicación (alcance, visualizaciones,
  interacciones, nuevos seguidores, visitas) responden `data: []` → la app
  no tiene `read_insights`: NO DISPONIBLE. Listar publicaciones o leer
  reacciones exige `pages_read_user_content`: NO DISPONIBLE.
- Instagram: `followers_count`, `media_count` → DISPONIBLE; por publicación
  `like_count` y `comments_count` → DISPONIBLE. Toda métrica de insights
  (alcance, visualizaciones, interacciones totales, visitas al perfil,
  Stories) → "Application does not have permission": NO DISPONIBLE.

Regla: una métrica que Meta no entrega queda `NO DISPONIBLE` con su motivo;
nunca se estima, nunca se toma `data: []` como cero. Si en el futuro se
habilitan permisos, las mismas consultas empiezan a devolver valores sin
cambiar código (la lista está en `INSIGHTS_*`).

Sanitización: las respuestas de Meta incluyen URLs de paginación con el
token; nunca se guardan (`_sanitizar`) y los errores se reducen al mensaje.
"""
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("motor_noticias.metricas_meta")

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"
PAGE_ID_DEFAULT = "1174992842373499"
DIRECTORIO_METRICAS = Path(__file__).resolve().parent.parent / "data" / "metricas"
NO_DISPONIBLE = "NO DISPONIBLE"
TIMEOUT = 20
DIAS_PUBLICACIONES_IG = 7

# (clave interna, métrica de Graph API). Se intentan todas en cada corrida.
INSIGHTS_FACEBOOK = (
    ("nuevos_seguidores", "page_daily_follows_unique"),
    ("visualizaciones", "page_media_view"),
    ("alcance", "page_total_media_view_unique"),
    ("interacciones", "page_post_engagements"),
    ("visitas", "page_views_total"),
)
INSIGHTS_INSTAGRAM = (
    ("alcance", "reach"),
    ("visualizaciones", "views"),
    ("interacciones", "total_interactions"),
    ("visitas_perfil", "profile_views"),
    ("nuevos_seguidores", "follows_and_unfollows"),
)

_RE_TOKEN = re.compile(r"access_token=[^&\s\"']+")

Getter = Callable[[str, dict], dict]


class ErrorMeta(Exception):
    pass


def _limpiar_texto(texto: str) -> str:
    return _RE_TOKEN.sub("access_token=***", texto or "")


def _sanitizar(valor):
    """Quita paginación (trae el token en la URL) y enmascara cualquier
    `access_token=` que pudiera venir en un texto."""
    if isinstance(valor, dict):
        return {k: _sanitizar(v) for k, v in valor.items() if k not in ("paging", "access_token")}
    if isinstance(valor, list):
        return [_sanitizar(v) for v in valor]
    if isinstance(valor, str):
        return _limpiar_texto(valor)
    return valor


def _getter_real(token: str) -> Getter:
    def get(path: str, params: dict) -> dict:
        consulta = dict(params, access_token=token)
        url = f"{GRAPH_API_BASE}/{path}?{urllib.parse.urlencode(consulta)}"
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as respuesta:
                return _sanitizar(json.loads(respuesta.read()))
        except urllib.error.HTTPError as error:
            try:
                mensaje = json.loads(error.read()).get("error", {}).get("message", "")
            except (ValueError, OSError):
                mensaje = f"HTTP {error.code}"
            raise ErrorMeta(_limpiar_texto(mensaje)[:200]) from None
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise ErrorMeta(_limpiar_texto(str(error))[:200]) from None

    return get


def disponible(valor, fuente: str) -> dict:
    return {"valor": valor, "estado": "DISPONIBLE", "fuente": fuente}


def no_disponible(motivo: str) -> dict:
    return {"valor": None, "estado": NO_DISPONIBLE, "motivo": motivo}


def _campo(get: Getter, objeto: str, campo: str, etiqueta: str) -> tuple:
    try:
        datos = get(objeto, {"fields": campo})
    except ErrorMeta as error:
        return no_disponible(str(error)), {"error": str(error)}
    if datos.get(campo) is None:
        return no_disponible(f"Meta no devolvió {campo}"), datos
    return disponible(datos[campo], etiqueta), datos


def _insight(get: Getter, objeto: str, metrica: str, params: dict, etiqueta: str) -> tuple:
    try:
        datos = get(f"{objeto}/insights", dict(params, metric=metrica))
    except ErrorMeta as error:
        return no_disponible(f"Meta rechazó la métrica {metrica}: {error}"), {"error": str(error)}
    filas = datos.get("data") or []
    if not filas:
        return no_disponible(f"Meta devolvió datos vacíos para {metrica} (sin permiso de insights)"), datos
    total = 0
    hubo_valor = False
    for fila in filas:
        if isinstance(fila.get("total_value"), dict) and isinstance(fila["total_value"].get("value"), (int, float)):
            total += fila["total_value"]["value"]
            hubo_valor = True
        for punto in fila.get("values") or []:
            if isinstance(punto.get("value"), (int, float)):
                total += punto["value"]
                hubo_valor = True
    if not hubo_valor:
        return no_disponible(f"Meta no devolvió un valor numérico para {metrica}"), datos
    return disponible(total, etiqueta), datos


def _publicaciones_locales(db, fecha: str) -> dict:
    """Publicaciones confirmadas por red en el día (datos propios del
    publicador, verificados con GET antes de marcarse publicadas)."""
    filas = db.conn.execute(
        "SELECT red_social, COUNT(*) AS n FROM programacion_meta WHERE estado = 'publicado' AND fecha = ? GROUP BY red_social",
        (fecha,),
    ).fetchall()
    return {f["red_social"]: f["n"] for f in filas}


def asegurar_tabla(db) -> None:
    db.conn.execute(
        "CREATE TABLE IF NOT EXISTS metrica_publicacion ("
        "meta_id TEXT NOT NULL, red_social TEXT NOT NULL, fecha_medicion TEXT NOT NULL, "
        "likes INTEGER, comentarios INTEGER, alcance INTEGER, visualizaciones INTEGER, "
        "medido_en TEXT NOT NULL, PRIMARY KEY (meta_id, fecha_medicion))"
    )
    db.conn.commit()


def medir_publicaciones_instagram(db, get: Getter, fecha: str, dias: int = DIAS_PUBLICACIONES_IG) -> dict:
    """like_count / comments_count de cada publicación de feed de Instagram
    de los últimos `dias`. Alcance y visualizaciones por publicación: NO
    DISPONIBLE con los permisos actuales (quedan NULL, nunca 0)."""
    asegurar_tabla(db)
    desde = (datetime.fromisoformat(fecha) - timedelta(days=dias)).date().isoformat()
    filas = db.conn.execute(
        "SELECT DISTINCT meta_id FROM programacion_meta WHERE red_social = 'instagram' AND estado = 'publicado' "
        "AND meta_id IS NOT NULL AND fecha >= ?",
        (desde,),
    ).fetchall()
    medidas, errores = 0, 0
    ahora = datetime.now(timezone.utc).isoformat()
    for fila in filas:
        try:
            datos = get(fila["meta_id"], {"fields": "like_count,comments_count"})
        except ErrorMeta:
            errores += 1
            continue
        db.conn.execute(
            "INSERT OR REPLACE INTO metrica_publicacion (meta_id, red_social, fecha_medicion, likes, comentarios, "
            "alcance, visualizaciones, medido_en) VALUES (?, 'instagram', ?, ?, ?, NULL, NULL, ?)",
            (fila["meta_id"], fecha, datos.get("like_count"), datos.get("comments_count"), ahora),
        )
        medidas += 1
    db.conn.commit()
    return {"medidas": medidas, "errores": errores, "consultadas": len(filas)}


def obtener_snapshot(db, fecha: str, get: Optional[Getter] = None) -> dict:
    """Foto del día de todas las métricas Meta intentadas. Sin token: todo
    NO DISPONIBLE (nunca se inventa)."""
    page_id = os.environ.get("META_PAGE_ID") or PAGE_ID_DEFAULT
    ig_id = os.environ.get("META_IG_USER_ID")
    if get is None:
        token = os.environ.get("META_PAGE_ACCESS_TOKEN")
        if not token:
            motivo = "Falta META_PAGE_ACCESS_TOKEN en este entorno"
            return {
                "fecha": fecha, "obtenido_en": datetime.now(timezone.utc).isoformat(),
                "facebook": {"seguidores": no_disponible(motivo)}, "instagram": {"seguidores": no_disponible(motivo)},
                "publicaciones_confirmadas": _publicaciones_locales(db, fecha), "respuestas_api": {},
            }
        get = _getter_real(token)

    respuestas: dict = {}
    hasta = datetime.fromisoformat(fecha).replace(tzinfo=timezone.utc) + timedelta(days=1)
    rango = {"period": "day", "since": int((hasta - timedelta(days=1)).timestamp()), "until": int(hasta.timestamp())}

    facebook: dict = {}
    facebook["seguidores"], respuestas["facebook_page_fields"] = _campo(get, page_id, "followers_count", "page.followers_count")
    for clave, metrica in INSIGHTS_FACEBOOK:
        facebook[clave], respuestas[f"facebook_insight_{metrica}"] = _insight(get, page_id, metrica, rango, f"page insights {metrica}")
    facebook["rendimiento_por_publicacion"] = no_disponible(
        "Insights de publicación vacíos y lectura de reacciones requiere pages_read_user_content"
    )

    instagram: dict = {}
    if ig_id:
        instagram["seguidores"], respuestas["instagram_user_fields"] = _campo(get, ig_id, "followers_count", "ig_user.followers_count")
        instagram["publicaciones_totales"], _ = _campo(get, ig_id, "media_count", "ig_user.media_count")
        for clave, metrica in INSIGHTS_INSTAGRAM:
            instagram[clave], respuestas[f"instagram_insight_{metrica}"] = _insight(
                get, ig_id, metrica, dict(rango, metric_type="total_value"), f"ig insights {metrica}"
            )
        instagram["stories"] = no_disponible("Insights de Stories requieren instagram_manage_insights")
        resumen = medir_publicaciones_instagram(db, get, fecha)
        instagram["rendimiento_por_publicacion"] = disponible(
            resumen, "ig_media like_count + comments_count (alcance/visualizaciones por publicación: NO DISPONIBLE)"
        )
    else:
        instagram["seguidores"] = no_disponible("Falta META_IG_USER_ID en este entorno")

    return {
        "fecha": fecha,
        "obtenido_en": datetime.now(timezone.utc).isoformat(),
        "facebook": facebook,
        "instagram": instagram,
        "publicaciones_confirmadas": _publicaciones_locales(db, fecha),
        "respuestas_api": respuestas,
    }


def guardar_snapshot(snapshot: dict, directorio: Optional[Path] = None) -> Path:
    directorio = Path(directorio or DIRECTORIO_METRICAS)
    directorio.mkdir(parents=True, exist_ok=True)
    ruta = directorio / f"meta_{snapshot['fecha']}.json"
    ruta.write_text(json.dumps(_sanitizar(snapshot), ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def leer_snapshot(fecha: str, directorio: Optional[Path] = None) -> Optional[dict]:
    try:
        return json.loads((Path(directorio or DIRECTORIO_METRICAS) / f"meta_{fecha}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def leer_baseline(directorio: Optional[Path] = None) -> Optional[dict]:
    try:
        return json.loads((Path(directorio or DIRECTORIO_METRICAS) / "baseline_2026-09-30.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
