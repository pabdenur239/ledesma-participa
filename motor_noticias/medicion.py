"""Medición propia, anónima y agregada de web y app (Etapa 3).

Solo contadores: (fecha, origen, evento, clave) → cantidad. No se guarda
nada que identifique a una persona: ni IP (ni completa ni parcial), ni
cookies, ni identificadores de dispositivo, ni user-agent, ni ubicación.
La IP solo se usa en memoria, como clave efímera de un límite de
frecuencia anti-abuso, y nunca se escribe en disco ni en logs.

`clave` es un identificador de CONTENIDO (id de noticia, slug de comercio,
id de radio, slug de categoría, red social), validado contra un patrón
estricto: texto libre, correos o teléfonos se descartan.

Sin terceros (sin Google Analytics, sin Pixel): base propia
`data/medicion.db`, separada de la base editorial para no competir por el
lock de escritura con el motor y el publicador.

Receptor HTTP: `servir()` (stdlib, `run_medicion.py`) escucha en
127.0.0.1; para que la web pública pueda enviar eventos necesita un
hostname HTTPS público (túnel) — ver `config/sitio.json`
`medicion_endpoint`. Si no hay endpoint configurado, la web y la app no
envían nada (no-op) y todo sigue funcionando igual."""
import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

logger = logging.getLogger("motor_noticias.medicion")

DB_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "medicion.db"

ORIGENES = ("web", "app")

# Evento -> descripción. Lista cerrada: cualquier otro se descarta.
EVENTOS = {
    "home_view": "Visita a portada",
    "article_open": "Apertura de nota",
    "home_article_click": "Clic desde portada a una nota",
    "category_open": "Apertura de categoría",
    "social_click": "Clic a red social (clave: facebook | instagram)",
    "follow_cta_click": "Clic en CTA 'Seguí Ledesma Participa' (clave: red)",
    "share_click": "Clic en compartir (clave: whatsapp | facebook | sistema)",
    "guia_open": "Apertura de la Guía Comercial",
    "commercial_view": "Vista de ficha comercial en la web (clave: comercio)",
    "commercial_open": "Apertura de ficha comercial en la app (clave: comercio)",
    "commercial_whatsapp_click": "Clic WhatsApp comercial (clave: comercio)",
    "commercial_instagram_click": "Clic Instagram comercial (clave: comercio)",
    "commercial_promo_open": "Promoción abierta (clave: comercio)",
    "radio_select": "Radio seleccionada (clave: radio)",
    "radio_play": "Play de radio (clave: radio)",
    "radio_pause": "Pausa de radio (clave: radio)",
    "radio_listen_minutes": "Minutos aproximados escuchados (clave: radio; valor agregado)",
    "video_open": "Apertura de video (clave: video)",
    "video_play": "Reproducción de video (clave: video)",
    "app_open": "Apertura de la app",
}

_RE_CLAVE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,79}$")
_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAXIMO_VALOR_POR_EVENTO = 30  # minutos de radio por envío (heartbeat), tope anti-abuso
MAXIMO_EVENTOS_POR_LOTE = 20
MAXIMO_BYTES_CUERPO = 4096

SCHEMA = """
CREATE TABLE IF NOT EXISTS evento_diario (
    fecha TEXT NOT NULL,
    origen TEXT NOT NULL,
    evento TEXT NOT NULL,
    clave TEXT NOT NULL DEFAULT '',
    cantidad INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (fecha, origen, evento, clave)
);
"""


def normalizar_evento(datos: dict) -> Optional[tuple]:
    """(evento, clave, valor) válido o None. Descarta todo lo que no esté
    en la lista cerrada o no tenga forma de identificador de contenido."""
    if not isinstance(datos, dict):
        return None
    evento = datos.get("e")
    if evento not in EVENTOS:
        return None
    clave = str(datos.get("k") or "").strip().lower()
    if clave and not _RE_CLAVE.match(clave):
        return None
    if re.fullmatch(r"\d{7,}", clave):  # parece un teléfono, no un id de contenido
        return None
    valor = 1
    if evento == "radio_listen_minutes":
        try:
            valor = int(datos.get("v") or 0)
        except (TypeError, ValueError):
            return None
        if not 1 <= valor <= MAXIMO_VALOR_POR_EVENTO:
            return None
    return evento, clave, valor


class AlmacenMedicion:
    def __init__(self, path=None):
        self.path = Path(path or DB_PATH_DEFAULT)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def registrar(self, fecha: str, origen: str, evento: str, clave: str = "", valor: int = 1) -> None:
        if origen not in ORIGENES or evento not in EVENTOS or not _RE_FECHA.match(fecha):
            raise ValueError("evento de medición inválido")
        with self._lock:
            self.conn.execute(
                "INSERT INTO evento_diario (fecha, origen, evento, clave, cantidad) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(fecha, origen, evento, clave) DO UPDATE SET cantidad = cantidad + excluded.cantidad",
                (fecha, origen, evento, clave or "", int(valor)),
            )
            self.conn.commit()

    def totales(self, desde: str, hasta: str, origen: Optional[str] = None) -> dict:
        """{evento: {"total": n, "por_clave": {clave: n}}} del período."""
        query = "SELECT evento, clave, SUM(cantidad) AS n FROM evento_diario WHERE fecha >= ? AND fecha <= ?"
        params: list = [desde, hasta]
        if origen:
            query += " AND origen = ?"
            params.append(origen)
        resultado: dict = {}
        for fila in self.conn.execute(query + " GROUP BY evento, clave", params).fetchall():
            item = resultado.setdefault(fila["evento"], {"total": 0, "por_clave": {}})
            item["total"] += fila["n"]
            if fila["clave"]:
                item["por_clave"][fila["clave"]] = fila["n"]
        return resultado

    def close(self) -> None:
        self.conn.close()


class LimiteFrecuencia:
    """Ventana deslizante en memoria (nunca persistida) por remitente."""

    def __init__(self, maximo: int = 120, ventana_segundos: int = 60):
        self.maximo = maximo
        self.ventana = ventana_segundos
        self._marcas: dict = {}
        self._lock = threading.Lock()

    def permitir(self, remitente: str) -> bool:
        ahora = time.monotonic()
        with self._lock:
            if len(self._marcas) > 10000:
                self._marcas.clear()
            marcas = [m for m in self._marcas.get(remitente, []) if ahora - m < self.ventana]
            if len(marcas) >= self.maximo:
                self._marcas[remitente] = marcas
                return False
            marcas.append(ahora)
            self._marcas[remitente] = marcas
            return True


def procesar_cuerpo(almacen: AlmacenMedicion, cuerpo: bytes, fecha: str) -> int:
    """Acepta un evento `{"o","e","k","v"}` o un lote `{"o", "eventos": [...]}`.
    Devuelve cuántos eventos se contaron."""
    try:
        datos = json.loads(cuerpo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return 0
    if not isinstance(datos, dict):
        return 0
    origen = datos.get("o") if datos.get("o") in ORIGENES else None
    if origen is None:
        return 0
    eventos = datos.get("eventos") if isinstance(datos.get("eventos"), list) else [datos]
    contados = 0
    for item in eventos[:MAXIMO_EVENTOS_POR_LOTE]:
        normalizado = normalizar_evento(item)
        if normalizado is None:
            continue
        evento, clave, valor = normalizado
        almacen.registrar(fecha, origen, evento, clave, valor)
        contados += 1
    return contados


def _fecha_local() -> str:
    from .motor_editorial import ZONA_JUJUY

    return datetime.now(ZONA_JUJUY).date().isoformat()


def crear_manejador(almacen: AlmacenMedicion, origenes_permitidos: tuple, limite: Optional[LimiteFrecuencia] = None):
    limite = limite or LimiteFrecuencia()

    class Manejador(BaseHTTPRequestHandler):
        server_version = "medicion"
        sys_version = ""

        def _cors(self) -> None:
            origen = self.headers.get("Origin")
            if origen and origen in origenes_permitidos:
                self.send_header("Access-Control-Allow-Origin", origen)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "86400")

        def do_OPTIONS(self):  # noqa: N802
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):  # noqa: N802
            self.send_response(200 if self.path == "/salud" else 404)
            self.end_headers()

        def do_POST(self):  # noqa: N802
            if self.path != "/e":
                self.send_response(404)
                self.end_headers()
                return
            # Detrás del túnel, la IP real llega en CF-Connecting-IP. Solo
            # para el límite de frecuencia en memoria: nunca se guarda.
            remitente = self.headers.get("CF-Connecting-IP") or self.client_address[0]
            try:
                largo = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                largo = 0
            if largo <= 0 or largo > MAXIMO_BYTES_CUERPO or not limite.permitir(remitente):
                self.send_response(429 if largo and largo <= MAXIMO_BYTES_CUERPO else 400)
                self._cors()
                self.end_headers()
                return
            try:
                procesar_cuerpo(almacen, self.rfile.read(largo), _fecha_local())
            except Exception:
                logger.exception("Medición: error registrando un evento.")
            self.send_response(204)
            self._cors()
            self.end_headers()

        def log_message(self, format, *args):  # sin access log: no se registran IPs
            return

    return Manejador


def servir(puerto: int, origenes_permitidos: tuple, db_path=None) -> None:
    almacen = AlmacenMedicion(db_path)
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), crear_manejador(almacen, origenes_permitidos))
    logger.info("Medición escuchando en 127.0.0.1:%s", puerto)
    try:
        servidor.serve_forever()
    finally:
        almacen.close()
