"""Publicidad comercial gratuita: 1 publicación ADICIONAL por día (18:00),
rotando equitativamente los comercios de `config/publicidad.json`.

Circuito totalmente separado del editorial: no usa `programacion_meta`, no
ocupa ninguna de las franjas editoriales, no interviene en urgentes y no
cuenta para el cálculo 70/30 propio/externo. Sus registros y métricas
viven en su propia base (`data/publicidad_comercial.db`).

Mismas garantías que la publicación editorial: estado separado por red
social, idempotencia (una fila 'publicado' nunca se vuelve a publicar),
reintentos acotados y verificación por GET antes de marcar 'publicado'.
Instagram feed reutiliza la foto ya subida a Facebook (CDN de Meta); la
Story se aloja como foto no publicada, igual que la Story editorial."""
import io
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, NamedTuple, Optional

from PIL import Image, ImageDraw, ImageOps

from .meta.cliente import ErrorClienteMeta
from .meta.imagen import COLOR_FONDO, COLOR_MARCA, COLOR_MARCA_TEXTO, COLOR_TITULO, _cargar_fuente

logger = logging.getLogger("motor_noticias.publicidad")

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_PATH_DEFAULT = RAIZ / "config" / "publicidad.json"
DB_PATH_DEFAULT = RAIZ / "data" / "publicidad_comercial.db"
DIRECTORIO_SALIDA_DEFAULT = RAIZ / "data" / "publicidad"

REDES = ("facebook", "instagram", "instagram_story")

ANCHO_FEED, ALTO_FEED = 1080, 1350  # 4:5, apto para feed de Instagram
ANCHO_STORY, ALTO_STORY = 1080, 1920
ALTO_BANDA = 150
COLOR_ETIQUETA_FONDO = "#e8631c"


class ResultadoRedComercial(NamedTuple):
    red_social: str
    estado: str  # "publicado" | "error" | "omitido"
    meta_id: Optional[str] = None
    detalle: Optional[str] = None


class ResultadoPublicidad(NamedTuple):
    fecha: str
    comercio_id: Optional[str]
    resultado: str  # "deshabilitada" | "procesada"
    redes: tuple = ()


def cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)


class DatabasePublicidad:
    def __init__(self, path=DB_PATH_DEFAULT):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS publicidad_comercial (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL UNIQUE,
                hora TEXT NOT NULL,
                comercio_id TEXT NOT NULL,
                imagen TEXT NOT NULL,
                texto TEXT NOT NULL,
                creada_en TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS publicidad_comercial_red (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publicidad_id INTEGER NOT NULL REFERENCES publicidad_comercial(id),
                red_social TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente',
                meta_id TEXT,
                referencia_extra TEXT,
                intentos INTEGER NOT NULL DEFAULT 0,
                ultimo_error TEXT,
                publicada_en TEXT,
                actualizada_en TEXT,
                UNIQUE (publicidad_id, red_social)
            );
            """
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

    def obtener_publicidad(self, fecha: str) -> Optional[dict]:
        fila = self.conn.execute("SELECT * FROM publicidad_comercial WHERE fecha = ?", (fecha,)).fetchone()
        return dict(fila) if fila else None

    def historial(self) -> List[dict]:
        filas = self.conn.execute("SELECT * FROM publicidad_comercial ORDER BY fecha").fetchall()
        return [dict(f) for f in filas]

    def crear_publicidad(self, fecha, hora, comercio_id, imagen, texto) -> dict:
        ahora = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO publicidad_comercial (fecha, hora, comercio_id, imagen, texto, creada_en) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (fecha, hora, comercio_id, imagen, texto, ahora),
        )
        for red in REDES:
            self.conn.execute(
                "INSERT INTO publicidad_comercial_red (publicidad_id, red_social, actualizada_en) VALUES (?, ?, ?)",
                (cur.lastrowid, red, ahora),
            )
        self.conn.commit()
        return self.obtener_publicidad(fecha)

    def obtener_red(self, publicidad_id: int, red: str) -> dict:
        fila = self.conn.execute(
            "SELECT * FROM publicidad_comercial_red WHERE publicidad_id = ? AND red_social = ?",
            (publicidad_id, red),
        ).fetchone()
        return dict(fila)

    def actualizar_red(self, red_id: int, estado: str, **campos):
        campos["estado"] = estado
        campos["actualizada_en"] = datetime.now(timezone.utc).isoformat()
        asignaciones = ", ".join(f"{k} = ?" for k in campos)
        self.conn.execute(
            f"UPDATE publicidad_comercial_red SET {asignaciones} WHERE id = ?", (*campos.values(), red_id)
        )
        self.conn.commit()

    def metricas(self) -> List[dict]:
        filas = self.conn.execute(
            """
            SELECT p.comercio_id,
                   COUNT(DISTINCT p.id) AS turnos,
                   SUM(CASE WHEN r.red_social = 'facebook' AND r.estado = 'publicado' THEN 1 ELSE 0 END) AS facebook,
                   SUM(CASE WHEN r.red_social = 'instagram' AND r.estado = 'publicado' THEN 1 ELSE 0 END) AS instagram,
                   SUM(CASE WHEN r.red_social = 'instagram_story' AND r.estado = 'publicado' THEN 1 ELSE 0 END) AS instagram_story,
                   SUM(CASE WHEN r.estado = 'error' THEN 1 ELSE 0 END) AS errores,
                   MAX(p.fecha) AS ultima_fecha
            FROM publicidad_comercial p
            LEFT JOIN publicidad_comercial_red r ON r.publicidad_id = p.id
            GROUP BY p.comercio_id
            ORDER BY p.comercio_id
            """
        ).fetchall()
        return [dict(f) for f in filas]


# -- Rotación -----------------------------------------------------------------


def elegir_comercio(config: dict, historial: List[dict]) -> dict:
    """Rotación equitativa: el comercio con menos turnos asignados; a
    igualdad, el que hace más tiempo que no sale; a igualdad, el orden del
    archivo de configuración."""
    comercios = config["comercios"]
    turnos = {c["id"]: 0 for c in comercios}
    ultima = {c["id"]: "" for c in comercios}
    for fila in historial:
        if fila["comercio_id"] in turnos:
            turnos[fila["comercio_id"]] += 1
            ultima[fila["comercio_id"]] = max(ultima[fila["comercio_id"]], fila["fecha"])
    orden = {c["id"]: i for i, c in enumerate(comercios)}
    return min(comercios, key=lambda c: (turnos[c["id"]], ultima[c["id"]], orden[c["id"]]))


def elegir_imagen(comercio: dict, historial: List[dict]) -> str:
    """Rota también las imágenes de un mismo comercio (DOSIS tiene tres)."""
    previas = sum(1 for f in historial if f["comercio_id"] == comercio["id"])
    imagenes = comercio["imagenes"]
    return imagenes[previas % len(imagenes)]


# -- Texto e imágenes ---------------------------------------------------------


def nombre_visible(comercio: dict) -> str:
    if comercio.get("alias"):
        return f"{comercio['nombre']} ({comercio['alias']})"
    return comercio["nombre"]


def generar_texto(comercio: dict, config: dict) -> str:
    etiqueta = config.get("etiqueta", "ESPACIO COMERCIAL")
    lineas = [f"📢 {etiqueta}", "", nombre_visible(comercio)]
    if comercio.get("rubro"):
        lineas.append(comercio["rubro"])
    lineas.append("")
    for clave in ("promocion", "texto"):
        if comercio.get(clave):
            lineas.append(comercio[clave])
    datos = []
    if comercio.get("direccion"):
        datos.append(f"📍 {comercio['direccion']}")
    if comercio.get("horario"):
        datos.append(f"🕒 {comercio['horario']}")
    if comercio.get("whatsapp"):
        datos.append(f"📲 WhatsApp: {comercio['whatsapp']}")
    if comercio.get("instagram"):
        datos.append(f"📷 Instagram: {comercio['instagram']}")
    if datos:
        lineas.append("")
        lineas.extend(datos)
    lineas += [
        "",
        f"{etiqueta}: espacio gratuito de Ledesma Participa para comercios y servicios de la zona. "
        "No es una nota periodística.",
        "",
        config.get("hashtags", "#EspacioComercial #LedesmaParticipa"),
    ]
    return "\n".join(lineas)


def _componer(ruta_origen: Path, ancho: int, alto: int, etiqueta: str, nombre: str) -> bytes:
    imagen = Image.new("RGB", (ancho, alto), COLOR_FONDO)
    dibujo = ImageDraw.Draw(imagen)

    dibujo.rectangle([(0, 0), (ancho, ALTO_BANDA)], fill=COLOR_ETIQUETA_FONDO)
    fuente_etiqueta = _cargar_fuente(64)
    ancho_txt = dibujo.textlength(etiqueta, font=fuente_etiqueta)
    dibujo.text(((ancho - ancho_txt) / 2, 38), etiqueta, font=fuente_etiqueta, fill=COLOR_TITULO)

    y_footer = alto - ALTO_BANDA
    dibujo.rectangle([(0, y_footer), (ancho, alto)], fill=COLOR_MARCA)
    fuente_nombre = _cargar_fuente(46)
    ancho_nombre = dibujo.textlength(nombre, font=fuente_nombre)
    dibujo.text(((ancho - ancho_nombre) / 2, y_footer + 22), nombre, font=fuente_nombre, fill=COLOR_TITULO)
    fuente_marca = _cargar_fuente(30)
    marca = "LEDESMA PARTICIPA"
    ancho_marca = dibujo.textlength(marca, font=fuente_marca)
    dibujo.text(((ancho - ancho_marca) / 2, y_footer + 90), marca, font=fuente_marca, fill=COLOR_MARCA_TEXTO)

    with Image.open(ruta_origen) as original:
        foto = ImageOps.exif_transpose(original).convert("RGB")
        caja = (ancho, alto - 2 * ALTO_BANDA)
        foto = ImageOps.contain(foto, caja, Image.LANCZOS)
        x = (ancho - foto.width) // 2
        y = ALTO_BANDA + (caja[1] - foto.height) // 2
        imagen.paste(foto, (x, y))

    buffer = io.BytesIO()
    imagen.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def generar_imagenes(
    comercio: dict, imagen: str, config: dict, raiz: Path = RAIZ, directorio_salida: Optional[Path] = None
):
    """Devuelve (ruta_feed, ruta_story): placas 4:5 y 9:16 con la etiqueta
    ESPACIO COMERCIAL impresa (la Story no admite caption aparte)."""
    origen = Path(raiz) / config.get("directorio_imagenes", "publicidad/entrada") / imagen
    if not origen.exists():
        raise FileNotFoundError(f"No existe la imagen comercial {origen}")
    salida = Path(directorio_salida or DIRECTORIO_SALIDA_DEFAULT)
    salida.mkdir(parents=True, exist_ok=True)
    etiqueta = config.get("etiqueta", "ESPACIO COMERCIAL")
    base = Path(imagen).stem
    rutas = []
    for sufijo, ancho, alto in (("feed", ANCHO_FEED, ALTO_FEED), ("story", ANCHO_STORY, ALTO_STORY)):
        ruta = salida / f"{comercio['id']}_{base}_{sufijo}.jpg"
        ruta.write_bytes(_componer(origen, ancho, alto, etiqueta, comercio["nombre"]))
        rutas.append(ruta)
    return tuple(rutas)


# -- Publicación --------------------------------------------------------------


class _Contenido(NamedTuple):
    """Interfaz mínima que espera `ClienteMetaGraphAPI.publicar_foto_facebook`."""

    post_principal: str
    primer_comentario: str = ""


def _verificar_y_cerrar(db, fila, red, meta_id, cliente, referencia_extra=None):
    try:
        if not cliente.verificar_publicacion(meta_id):
            raise ErrorClienteMeta(f"Meta no confirmó la publicación comercial de {red} al verificarla con GET.")
    except ErrorClienteMeta as error:
        db.actualizar_red(fila["id"], "error", meta_id=meta_id, referencia_extra=referencia_extra,
                          ultimo_error=str(error), intentos=fila["intentos"] + 1)
        return ResultadoRedComercial(red, "error", meta_id, str(error))
    db.actualizar_red(fila["id"], "publicado", meta_id=meta_id, referencia_extra=referencia_extra,
                      ultimo_error=None, intentos=fila["intentos"] + 1,
                      publicada_en=datetime.now(timezone.utc).isoformat())
    return ResultadoRedComercial(red, "publicado", meta_id)


def _registrar_error(db, fila, red, error, **campos):
    logger.error("Error publicando publicidad comercial en %s: %s", red, error)
    db.actualizar_red(fila["id"], "error", ultimo_error=str(error), intentos=fila["intentos"] + 1, **campos)
    return ResultadoRedComercial(red, "error", detalle=str(error))


def _publicar_facebook(db, fila, cliente_fb, texto, ruta_feed):
    if fila.get("meta_id"):
        # Ya publicado en un intento anterior: solo se reintenta verificar.
        return _verificar_y_cerrar(db, fila, "facebook", fila["meta_id"], cliente_fb, fila.get("referencia_extra"))
    try:
        resultado = cliente_fb.publicar_foto_facebook(_Contenido(texto), Path(ruta_feed), dry_run=False)
    except ErrorClienteMeta as error:
        return _registrar_error(db, fila, "facebook", error)
    db.actualizar_red(fila["id"], "error", meta_id=resultado.post_id, referencia_extra=resultado.photo_id,
                      ultimo_error="Publicado; pendiente de confirmar con GET.")
    return _verificar_y_cerrar(db, fila, "facebook", resultado.post_id, cliente_fb, resultado.photo_id)


def _publicar_instagram(db, fila, cliente_fb, cliente_ig, texto, photo_id):
    if fila.get("meta_id"):
        return _verificar_y_cerrar(db, fila, "instagram", fila["meta_id"], cliente_ig)
    try:
        url = cliente_fb.obtener_url_publica_foto(photo_id)
        media_id = cliente_ig.publicar_instagram(texto, url, dry_run=False)
    except ErrorClienteMeta as error:
        return _registrar_error(db, fila, "instagram", error)
    db.actualizar_red(fila["id"], "error", meta_id=media_id, ultimo_error="Publicado; pendiente de confirmar con GET.")
    return _verificar_y_cerrar(db, fila, "instagram", media_id, cliente_ig)


def _publicar_story(db, fila, cliente_fb, cliente_ig, ruta_story):
    if fila.get("meta_id"):
        return _verificar_y_cerrar(db, fila, "instagram_story", fila["meta_id"], cliente_ig)
    try:
        photo_id = cliente_fb.alojar_imagen_para_story(Path(ruta_story), dry_run=False)
        url = cliente_fb.obtener_url_publica_foto(photo_id)
        media_id = cliente_ig.publicar_instagram_story(url, dry_run=False)
    except ErrorClienteMeta as error:
        return _registrar_error(db, fila, "instagram_story", error)
    db.actualizar_red(fila["id"], "error", meta_id=media_id, ultimo_error="Publicado; pendiente de confirmar con GET.")
    return _verificar_y_cerrar(db, fila, "instagram_story", media_id, cliente_ig)


def _historias_habilitadas_globalmente() -> bool:
    from .meta.publicador import _historias_instagram_habilitadas

    return _historias_instagram_habilitadas()


def publicar_publicidad_del_dia(
    db: DatabasePublicidad,
    fecha: str,
    cliente_fb,
    cliente_ig,
    config: Optional[dict] = None,
    raiz: Path = RAIZ,
    directorio_salida: Optional[Path] = None,
    historias_habilitadas: Optional[bool] = None,
) -> ResultadoPublicidad:
    config = config or cargar_config()
    if not config.get("habilitada", True):
        return ResultadoPublicidad(fecha, None, "deshabilitada")

    max_intentos = int(config.get("max_intentos", 3))
    publicidad = db.obtener_publicidad(fecha)
    if publicidad is None:
        historial = db.historial()
        comercio = elegir_comercio(config, historial)
        imagen = elegir_imagen(comercio, historial)
        publicidad = db.crear_publicidad(
            fecha, config.get("hora", "18:00"), comercio["id"], imagen, generar_texto(comercio, config)
        )
    comercio = next(c for c in config["comercios"] if c["id"] == publicidad["comercio_id"])
    ruta_feed, ruta_story = generar_imagenes(comercio, publicidad["imagen"], config, raiz, directorio_salida)
    texto = publicidad["texto"]

    if historias_habilitadas is None:
        historias_habilitadas = config.get("story_habilitada", True) and _historias_habilitadas_globalmente()

    redes = []
    for red in REDES:
        fila = db.obtener_red(publicidad["id"], red)
        if fila["estado"] == "publicado":
            redes.append(ResultadoRedComercial(red, "publicado", fila["meta_id"], "ya publicado"))
            continue
        if fila["intentos"] >= max_intentos:
            redes.append(ResultadoRedComercial(red, "omitido", detalle="tope de reintentos alcanzado"))
            continue
        if red == "facebook":
            redes.append(_publicar_facebook(db, fila, cliente_fb, texto, ruta_feed))
        elif red == "instagram":
            fb = db.obtener_red(publicidad["id"], "facebook")
            if fb["estado"] != "publicado" or not fb.get("referencia_extra"):
                redes.append(ResultadoRedComercial(red, "omitido", detalle="Facebook aún no publicado"))
                continue
            redes.append(_publicar_instagram(db, fila, cliente_fb, cliente_ig, texto, fb["referencia_extra"]))
        else:
            if not historias_habilitadas:
                redes.append(ResultadoRedComercial(red, "omitido", detalle="Stories deshabilitadas"))
                continue
            redes.append(_publicar_story(db, fila, cliente_fb, cliente_ig, ruta_story))

    return ResultadoPublicidad(fecha, publicidad["comercio_id"], "procesada", tuple(redes))
