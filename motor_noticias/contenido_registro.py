"""Registro de contenido (Etapa 3 — medición): un identificador interno
único por noticia publicada (`content_id`, p. ej. `lp_20261009_0730_001`)
que relaciona NOTICIA → RED SOCIAL → WEB → MÉTRICAS.

Tabla `contenido_registro` (aditiva, en la misma base): una fila por
noticia que llegó a publicarse en alguna red. Los IDs de Meta no se copian:
se leen siempre de `programacion_meta` (fuente única de verdad de lo
publicado), así el registro nunca queda desincronizado.

Formato visual (`visual_format`): se registra en el momento real de la
publicación (`registrar_publicacion`, llamado por el publicador después de
preparar la imagen). Para lo publicado antes de la Etapa 3 se infiere de
los datos guardados de la noticia y la fila queda marcada
`formato_inferido = 1` (honesto: no se registró en el momento).

Sin datos personales de usuarios: solo datos editoriales del contenido.
Nunca bloquea ni altera la publicación (el publicador lo llama dentro de un
try/except)."""
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from .informe_diario_datos import datos_informe_de_noticia
from .models import OrigenIngreso

logger = logging.getLogger("motor_noticias.contenido_registro")

FORMATOS_VISUALES = (
    "PHOTO_HEADLINE",
    "EDITORIAL_CARD",
    "URGENT_CARD",
    "SERVICE_CARD",
    "INSTITUTIONAL",
    "STORY",
    "CAROUSEL",
    "REEL",
    "EXTERNAL_IMAGE",
)

ORIGENES_PROPIOS = (
    OrigenIngreso.INSTITUCIONAL.value,
    OrigenIngreso.RESUMEN_DIARIO.value,
    OrigenIngreso.CONTENIDO_PROPIO.value,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS contenido_registro (
    content_id TEXT PRIMARY KEY,
    noticia_id INTEGER NOT NULL UNIQUE,
    fecha TEXT NOT NULL,
    hora TEXT NOT NULL,
    territorio TEXT,
    categoria TEXT,
    urgente INTEGER NOT NULL DEFAULT 0,
    visual_format TEXT NOT NULL,
    formato_inferido INTEGER NOT NULL DEFAULT 0,
    has_real_photo INTEGER NOT NULL DEFAULT 0,
    has_video INTEGER NOT NULL DEFAULT 0,
    has_link INTEGER NOT NULL DEFAULT 0,
    fuente TEXT,
    propia INTEGER NOT NULL DEFAULT 0,
    url_web TEXT,
    reel_candidate INTEGER NOT NULL DEFAULT 0,
    titular_palabras INTEGER,
    titular_alertas TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contenido_registro_fecha ON contenido_registro(fecha);
"""

_RE_URL = re.compile(r"https?://\S+")
_RE_HORA = re.compile(r"^\d{2}:\d{2}$")

# Reel candidato (no se publica automáticamente: solo se marca). Señales
# explícitas y verificables; nunca "todas las noticias".
CATEGORIAS_SERVICIO_EXPLICATIVO = ("servicios",)
UMBRAL_PUNTAJE_IMPORTANTE = 70


def asegurar_tabla(db) -> None:
    db.conn.executescript(SCHEMA)
    db.conn.commit()


def formato_visual(noticia: dict, *, urgente: bool, imagen_generada: bool, categoria: Optional[str] = None) -> str:
    """Formato visual de la pieza de feed, con la misma lógica de decisión
    que `meta.preparacion` (urgente rojo > informe/servicio verde >
    institucional > foto real + titular > placa editorial)."""
    if urgente:
        return "URGENT_CARD"
    if datos_informe_de_noticia(noticia) is not None:
        return "SERVICE_CARD"
    if noticia.get("territorio") == "institucional" or noticia.get("origen_ingreso") == OrigenIngreso.INSTITUCIONAL.value:
        return "INSTITUTIONAL"
    if categoria == "servicios":
        return "SERVICE_CARD"
    return "EDITORIAL_CARD" if imagen_generada else "PHOTO_HEADLINE"


def es_reel_candidato(noticia: dict, *, urgente: bool, categoria: Optional[str], puntaje: Optional[int]) -> bool:
    """reel_candidate=true cuando hay una señal concreta: urgente
    confirmado (alto impacto), noticia importante por scoring editorial, o
    servicio explicativo. Solo marca: no publica Reels."""
    if urgente:
        return True
    if puntaje is not None and puntaje >= UMBRAL_PUNTAJE_IMPORTANTE:
        return True
    return categoria in CATEGORIAS_SERVICIO_EXPLICATIVO and datos_informe_de_noticia(noticia) is None


def _clasificar(noticia: dict) -> tuple:
    from .clasificacion import clasificar_noticia

    clasificacion = clasificar_noticia(noticia, urgente=bool(noticia.get("urgente")))
    return clasificacion["territorio"]["interno"], clasificacion["categoria"]["valor"]


def _puntaje(noticia: dict) -> Optional[int]:
    try:
        from .scoring_editorial import evaluar_noticia

        return evaluar_noticia(noticia)["base"]
    except Exception:  # el scoring nunca debe impedir el registro
        return None


def _siguiente_content_id(db, fecha: str, hora: str) -> str:
    prefijo = f"lp_{fecha.replace('-', '')}_{hora.replace(':', '')}_"
    fila = db.conn.execute(
        "SELECT COUNT(*) FROM contenido_registro WHERE content_id LIKE ?", (prefijo + "%",)
    ).fetchone()
    return f"{prefijo}{fila[0] + 1:03d}"


def _hora_de_clave(clave: str, publicada_en: Optional[str]) -> str:
    """`clave` es "HH:MM" en franjas fijas; urgentes/reintentos usan una
    clave sintética: ahí vale la hora local real de publicación."""
    if _RE_HORA.match(clave or ""):
        return clave
    if publicada_en:
        try:
            from .motor_editorial import ZONA_JUJUY

            return datetime.fromisoformat(publicada_en).astimezone(ZONA_JUJUY).strftime("%H:%M")
        except ValueError:
            pass
    return "00:00"


def _tiene_foto_real(noticia: dict, formato: str) -> bool:
    if formato == "PHOTO_HEADLINE":
        return True
    # La pieza urgente siempre se reporta como "generada" (banda roja), con
    # o sin foto debajo: se mira la imagen guardada de la noticia.
    return formato == "URGENT_CARD" and bool(noticia.get("imagen_publicacion_ruta")) and not noticia.get(
        "imagen_generada_automaticamente"
    )


def obtener_por_noticia(db, noticia_id: int) -> Optional[dict]:
    asegurar_tabla(db)
    fila = db.conn.execute("SELECT * FROM contenido_registro WHERE noticia_id = ?", (noticia_id,)).fetchone()
    return dict(fila) if fila else None


def registrar_publicacion(
    db,
    noticia: dict,
    *,
    fecha: str,
    clave: str,
    imagen_generada: bool,
    texto_publicado: str = "",
    url_web: Optional[str] = None,
    publicada_en: Optional[str] = None,
    formato_inferido: bool = False,
) -> str:
    """Crea (una sola vez por noticia) la fila del registro y devuelve su
    content_id. Idempotente: un reintento o una segunda red de la misma
    noticia reutiliza el content_id existente."""
    from .atribucion import atribucion
    from .titulares import evaluar_titular

    asegurar_tabla(db)
    existente = obtener_por_noticia(db, noticia["id"])
    if existente:
        return existente["content_id"]

    urgente = (clave or "").startswith("urgente-")
    territorio, categoria = _clasificar(noticia)
    titulo = noticia.get("titulo_revisado") or noticia.get("titulo_preparado") or noticia.get("titulo_original") or ""
    evaluacion = evaluar_titular(titulo)
    formato = formato_visual(noticia, urgente=urgente, imagen_generada=imagen_generada, categoria=categoria)
    hora = _hora_de_clave(clave, publicada_en)
    autoria = atribucion(noticia)
    propia = noticia.get("origen_ingreso") in ORIGENES_PROPIOS or datos_informe_de_noticia(noticia) is not None
    for _ in range(3):  # carrera improbable entre dos procesos: reintenta con el siguiente número
        content_id = _siguiente_content_id(db, fecha, hora)
        try:
            db.conn.execute(
                "INSERT INTO contenido_registro (content_id, noticia_id, fecha, hora, territorio, categoria, urgente, "
                "visual_format, formato_inferido, has_real_photo, has_video, has_link, fuente, propia, url_web, "
                "reel_candidate, titular_palabras, titular_alertas, creado_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    content_id, noticia["id"], fecha, hora, territorio, categoria, int(urgente), formato,
                    int(formato_inferido), int(_tiene_foto_real(noticia, formato)), 0,
                    int(bool(_RE_URL.search(texto_publicado or ""))), autoria.etiqueta, int(propia), url_web,
                    int(es_reel_candidato(noticia, urgente=urgente, categoria=categoria, puntaje=_puntaje(noticia))),
                    evaluacion["palabras"], ",".join(evaluacion["alertas"]) or None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            db.conn.commit()
            return content_id
        except Exception as error:  # sqlite3.IntegrityError
            if "UNIQUE" not in str(error):
                raise
            existente = obtener_por_noticia(db, noticia["id"])
            if existente:
                return existente["content_id"]
    raise RuntimeError("No se pudo asignar un content_id único.")


def sincronizar_historico(db, desde_fecha: Optional[str] = None) -> int:
    """Registra lo ya publicado que todavía no tiene content_id (lo
    anterior a la Etapa 3), con formato inferido. Devuelve cuántas filas
    nuevas creó."""
    from .sitio.urls import base_url, url_relativa_noticia

    asegurar_tabla(db)
    query = (
        "SELECT p.noticia_id, p.fecha, p.hora, MIN(p.publicada_en) AS publicada_en FROM programacion_meta p "
        "LEFT JOIN contenido_registro c ON c.noticia_id = p.noticia_id "
        "WHERE p.estado = 'publicado' AND p.red_social IN ('facebook', 'instagram') AND c.noticia_id IS NULL"
    )
    params: list = []
    if desde_fecha:
        query += " AND p.fecha >= ?"
        params.append(desde_fecha)
    query += " GROUP BY p.noticia_id ORDER BY MIN(p.publicada_en)"
    nuevas = 0
    for fila in db.conn.execute(query, params).fetchall():
        noticia = db.obtener(fila["noticia_id"])
        if noticia is None:
            continue
        try:
            registrar_publicacion(
                db, noticia, fecha=fila["fecha"], clave=fila["hora"],
                imagen_generada=bool(noticia.get("imagen_generada_automaticamente")),
                url_web=base_url() + url_relativa_noticia(noticia),
                publicada_en=fila["publicada_en"], formato_inferido=True,
            )
            nuevas += 1
        except Exception:
            logger.exception("No se pudo registrar el contenido histórico de la noticia #%s.", fila["noticia_id"])
    return nuevas


def listar_con_plataformas(db, desde_fecha: str, hasta_fecha: Optional[str] = None) -> list:
    """Contenidos registrados con sus IDs por plataforma (desde
    `programacion_meta`): facebook_post_id, instagram_media_id,
    instagram_story_id."""
    asegurar_tabla(db)
    query = "SELECT * FROM contenido_registro WHERE fecha >= ?"
    params: list = [desde_fecha]
    if hasta_fecha:
        query += " AND fecha <= ?"
        params.append(hasta_fecha)
    contenidos = [dict(f) for f in db.conn.execute(query + " ORDER BY fecha, hora, content_id", params).fetchall()]
    for c in contenidos:
        ids = db.conn.execute(
            "SELECT red_social, meta_id FROM programacion_meta WHERE noticia_id = ? AND estado = 'publicado'",
            (c["noticia_id"],),
        ).fetchall()
        por_red = {f["red_social"]: f["meta_id"] for f in ids}
        c["facebook_post_id"] = por_red.get("facebook")
        c["instagram_media_id"] = por_red.get("instagram")
        c["instagram_story_id"] = por_red.get("instagram_story")
        c["plataformas"] = sorted(por_red)
    return contenidos
