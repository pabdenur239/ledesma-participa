"""Panel remoto LIMITADO para cargar noticias locales desde el celular.

Proceso aparte del panel principal (que sigue sin login en 127.0.0.1:8000).
Escucha solo en 127.0.0.1:8020 y se publica por el túnel de Cloudflare
existente (panel.ledesmaparticipa.com.ar). Permite únicamente: ingresar,
cargar/procesar una noticia local, ver una noticia y reintentar su
redacción. Nunca aprobar, rechazar ni editar notas, ni rutas administrativas
(/estado, /agenda, /crecimiento, ...): todo lo demás devuelve 404.

Autenticación propia: contraseña (hash scrypt) + TOTP (RFC 6238), sesión en
memoria con cookie __Host- Secure/HttpOnly/SameSite=Strict, CSRF (token de
sesión + verificación de Origin), límite de intentos por IP y global.
Secretos solo en el archivo de entorno (fuera del repo, permisos 600):
  PANEL_REMOTO_PASSWORD_HASH  scrypt$n$r$p$sal_b64$hash_b64
  PANEL_REMOTO_TOTP_SECRET    base32
Sin esas variables el login queda deshabilitado (falla cerrado).
Los logs nunca registran contraseña, código, cookies ni tokens.

Uso:
  python -m motor_noticias.panel.remoto servir
  python -m motor_noticias.panel.remoto configurar --archivo /etc/ledesma-panel-remoto.env
"""
import argparse
import base64
import getpass
import hashlib
import hmac
import io
import logging
import os
import re
import secrets
import struct
import sys
import threading
import time
import urllib.parse
from collections import deque
from http.server import HTTPServer
from typing import Dict, Optional

from ..db import Database
from ..models import Estado
from ..pipeline import CATEGORIA_SIN_REDACCION_PROPIA, reintentar_redaccion
from ..redaccion import crear_redactor
from .server import (
    DB_PATH_DEFAULT,
    LONGITUD_MAXIMA_CUERPO_POST_CARGA,
    PanelHandler,
    _advertencia_riesgo,
    _e,
    _pagina,
)

HOST_REMOTO = "127.0.0.1"
PORT_REMOTO = 8020
ORIGEN_DEFAULT = "https://panel.ledesmaparticipa.com.ar"
RUTAS_REMOTAS = ("/login", "/logout", "/cargar-noticia-local", "/noticia")

COOKIE_SESION = "__Host-sesion"
COOKIE_PRELOGIN = "__Host-prelogin"
SESION_INACTIVIDAD_SEGUNDOS = 12 * 3600
SESION_MAXIMA_SEGUNDOS = 7 * 24 * 3600

INTENTOS_POR_IP = 5
VENTANA_IP_SEGUNDOS = 15 * 60
BLOQUEO_IP_SEGUNDOS = 15 * 60
INTENTOS_GLOBALES = 20
VENTANA_GLOBAL_SEGUNDOS = 3600
BLOQUEO_GLOBAL_SEGUNDOS = 3600

LONGITUD_MAXIMA_LOGIN = 2_000
LONGITUD_MINIMA_PASSWORD = 16
TOTP_PASO_SEGUNDOS = 30
TOTP_DIGITOS = 6
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1

ENCABEZADOS_SEGURIDAD = (
    ("Strict-Transport-Security", "max-age=31536000"),
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
    (
        "Content-Security-Policy",
        "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    ),
)

log = logging.getLogger("panel_remoto")


# --- Contraseña y TOTP ----------------------------------------------------

def generar_hash_password(password: str) -> str:
    sal = secrets.token_bytes(16)
    clave = hashlib.scrypt(
        password.encode("utf-8"), salt=sal, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=2 ** 26
    )
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N, SCRYPT_R, SCRYPT_P,
        base64.b64encode(sal).decode(), base64.b64encode(clave).decode(),
    )


def verificar_password(password: str, hash_guardado: str) -> bool:
    try:
        esquema, n, r, p, sal_b64, clave_b64 = hash_guardado.split("$")
        if esquema != "scrypt":
            return False
        esperada = base64.b64decode(clave_b64)
        calculada = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(sal_b64),
            n=int(n), r=int(r), p=int(p), maxmem=2 ** 26, dklen=len(esperada),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculada, esperada)


def generar_secreto_totp() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def codigo_totp(secreto: str, contador: int) -> str:
    clave = base64.b32decode(secreto.upper() + "=" * (-len(secreto) % 8))
    digest = hmac.new(clave, struct.pack(">Q", contador), hashlib.sha1).digest()
    desplazamiento = digest[-1] & 0x0F
    numero = struct.unpack(">I", digest[desplazamiento:desplazamiento + 4])[0] & 0x7FFFFFFF
    return str(numero % 10 ** TOTP_DIGITOS).zfill(TOTP_DIGITOS)


def verificar_totp(secreto: str, codigo: str, ahora: float, ultimo_usado: int) -> Optional[int]:
    """Devuelve el contador aceptado (ventana ±1 paso) o None. Un contador
    ya usado (o anterior) se rechaza: el mismo código no sirve dos veces."""
    if not re.fullmatch(r"\d{%d}" % TOTP_DIGITOS, codigo or ""):
        return None
    actual = int(ahora // TOTP_PASO_SEGUNDOS)
    for contador in (actual - 1, actual, actual + 1):
        if contador > ultimo_usado and hmac.compare_digest(codigo_totp(secreto, contador), codigo):
            return contador
    return None


# --- Estado de autenticación (en memoria) ---------------------------------

class EstadoAuth:
    """Sesiones y contadores de intentos. En memoria: reiniciar el servicio
    invalida todas las sesiones (sirve también para cortar un acceso)."""

    def __init__(self, hash_password: Optional[str], secreto_totp: Optional[str], reloj=time.time):
        self.hash_password = hash_password or None
        self.secreto_totp = secreto_totp or None
        self.reloj = reloj
        self.lock = threading.Lock()
        self.sesiones: Dict[str, dict] = {}
        self.fallos_ip: Dict[str, deque] = {}
        self.bloqueo_ip: Dict[str, float] = {}
        self.fallos_globales: deque = deque()
        self.bloqueo_global_hasta = 0.0
        self.ultimo_totp = -1

    @property
    def configurado(self) -> bool:
        return bool(self.hash_password and self.secreto_totp)

    @staticmethod
    def _clave(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def bloqueado(self, ip: str) -> bool:
        ahora = self.reloj()
        with self.lock:
            return ahora < self.bloqueo_global_hasta or ahora < self.bloqueo_ip.get(ip, 0)

    def registrar_fallo(self, ip: str) -> None:
        ahora = self.reloj()
        with self.lock:
            fallos = self.fallos_ip.setdefault(ip, deque())
            fallos.append(ahora)
            while fallos and fallos[0] < ahora - VENTANA_IP_SEGUNDOS:
                fallos.popleft()
            if len(fallos) >= INTENTOS_POR_IP:
                self.bloqueo_ip[ip] = ahora + BLOQUEO_IP_SEGUNDOS
                fallos.clear()
                log.warning("bloqueo temporal por intentos ip=%s", ip)
            self.fallos_globales.append(ahora)
            while self.fallos_globales and self.fallos_globales[0] < ahora - VENTANA_GLOBAL_SEGUNDOS:
                self.fallos_globales.popleft()
            if len(self.fallos_globales) >= INTENTOS_GLOBALES:
                self.bloqueo_global_hasta = ahora + BLOQUEO_GLOBAL_SEGUNDOS
                self.fallos_globales.clear()
                log.warning("bloqueo global del login por intentos")

    def autenticar(self, password: str, codigo: str) -> bool:
        if not self.configurado:
            return False
        if not verificar_password(password, self.hash_password):
            return False
        with self.lock:
            contador = verificar_totp(self.secreto_totp, codigo, self.reloj(), self.ultimo_totp)
            if contador is None:
                return False
            self.ultimo_totp = contador
        return True

    def crear_sesion(self) -> str:
        token = secrets.token_urlsafe(32)
        ahora = self.reloj()
        with self.lock:
            self.sesiones[self._clave(token)] = {
                "creada": ahora, "ultima": ahora, "csrf": secrets.token_urlsafe(32),
            }
        return token

    def sesion(self, token: Optional[str]) -> Optional[dict]:
        if not token:
            return None
        ahora = self.reloj()
        clave = self._clave(token)
        with self.lock:
            datos = self.sesiones.get(clave)
            if datos is None:
                return None
            if ahora - datos["ultima"] > SESION_INACTIVIDAD_SEGUNDOS or ahora - datos["creada"] > SESION_MAXIMA_SEGUNDOS:
                del self.sesiones[clave]
                return None
            datos["ultima"] = ahora
            return datos

    def cerrar_sesion(self, token: Optional[str]) -> None:
        if token:
            with self.lock:
                self.sesiones.pop(self._clave(token), None)


# --- HTML ------------------------------------------------------------------

_RE_NAV = re.compile(r"<nav>.*?</nav>", re.S)
_RE_TITULO = re.compile(r'<h1><a href="/"[^>]*>.*?</a></h1>', re.S)
_RE_FORM_POST = re.compile(r'(<form method="post"[^>]*>)')
NAV_REMOTA = (
    '<nav><a href="/cargar-noticia-local">Cargar noticia local</a> | '
    '<form method="post" action="/logout" class="acciones-en-linea">'
    '<button type="submit">Salir</button></form></nav>'
)


def _adaptar_html(cuerpo: str, csrf: Optional[str]) -> str:
    """Quita la navegación administrativa del panel principal y agrega el
    token CSRF a cada formulario POST."""
    cuerpo = _RE_TITULO.sub("<h1>Ledesma Participa — Canal rápido local</h1>", cuerpo, count=1)
    cuerpo = _RE_NAV.sub(NAV_REMOTA if csrf else "", cuerpo, count=1)
    if csrf:
        oculto = f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
        cuerpo = _RE_FORM_POST.sub(lambda m: m.group(1) + oculto, cuerpo)
    return cuerpo


def _login_html(token_prelogin: str, mensaje: Optional[str] = None) -> str:
    aviso = f'<p class="error-formulario">{_e(mensaje)}</p>' if mensaje else ""
    cuerpo = f"""
<h2>Ingresar</h2>
{aviso}
<form method="post" action="/login">
<input type="hidden" name="prelogin" value="{_e(token_prelogin)}">
<label>Contraseña:<br>
<input type="password" name="password" autocomplete="current-password" required style="width:100%"></label>
<label>Código de la app autenticadora:<br>
<input type="text" name="codigo" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{{6}}" maxlength="6" required></label>
<br>
<button type="submit">Ingresar</button>
</form>
"""
    return _pagina("Ingresar — Ledesma Participa", cuerpo)


def _detalle_remoto_html(noticia: dict, mensaje: Optional[str] = None) -> str:
    """Vista de solo lectura: sin guardar, aprobar ni rechazar. El único
    botón es "Reintentar redacción" para notas sin redacción propia."""
    aviso = f"<p><em>{_e(mensaje)}</em></p>" if mensaje else ""
    boton = ""
    if noticia.get("categoria_riesgo") == CATEGORIA_SIN_REDACCION_PROPIA:
        boton = (
            f'<form method="post" action="/noticia?id={noticia["id"]}">'
            '<button type="submit" name="accion" value="reintentar_redaccion">Reintentar redacción</button>'
            "</form>"
        )
    cuerpo = f"""
{aviso}
{_advertencia_riesgo(noticia)}
<h2>{_e(noticia['titulo_original'])}</h2>
<p><strong>Fuente:</strong> {_e(noticia['nombre_fuente'])}
— <strong>Localidad:</strong> {_e(noticia['localidad'])}</p>
<p><strong>URL fuente:</strong> {_e(noticia['url_fuente'])}</p>
<p><strong>Título preparado:</strong> {_e(noticia['titulo_preparado'])}</p>
<p><strong>Texto preparado:</strong> {_e(noticia['texto_preparado'])}</p>
<p><strong>Estado de revisión:</strong> {_e(noticia['revision_estado'])}</p>
<p><em>La aprobación de notas se hace solo desde el panel principal.</em></p>
{boton}
"""
    return _pagina(f"Noticia #{noticia['id']}", cuerpo)


# --- Handler ---------------------------------------------------------------

def _cookies(encabezado: Optional[str]) -> Dict[str, str]:
    resultado = {}
    for parte in (encabezado or "").split(";"):
        nombre, _, valor = parte.strip().partition("=")
        if nombre:
            resultado[nombre] = valor
    return resultado


class PanelRemotoHandler(PanelHandler):
    server_version = "panel"
    sys_version = ""
    auth: EstadoAuth = EstadoAuth(None, None)
    origen = ORIGEN_DEFAULT

    # -- utilidades
    def end_headers(self):
        for nombre, valor in ENCABEZADOS_SEGURIDAD:
            self.send_header(nombre, valor)
        super().end_headers()

    def _ip(self) -> str:
        # Solo escucha en localhost y le llega únicamente tráfico del túnel:
        # CF-Connecting-IP es la IP real del visitante.
        return (self.headers.get("CF-Connecting-IP") or self.client_address[0])[:64]

    def _token(self) -> Optional[str]:
        return _cookies(self.headers.get("Cookie")).get(COOKIE_SESION)

    def _responder_html(self, cuerpo: str, status: int = 200, cookies=()) -> None:
        cuerpo_bytes = _adaptar_html(cuerpo, getattr(self, "_csrf", None)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo_bytes)))
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(cuerpo_bytes)

    def _redirigir(self, ubicacion: str, cookies=()) -> None:
        self.send_response(303)
        self.send_header("Location", ubicacion)
        self.send_header("Content-Length", "0")
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _no_encontrada(self) -> None:
        self._responder_html(_pagina("No encontrada", "<p>Página no encontrada.</p>"), status=404)

    def _prohibido(self) -> None:
        self._responder_html(_pagina("Prohibido", "<p>Solicitud rechazada.</p>"), status=403)

    def _origen_valido(self) -> bool:
        origen = self.headers.get("Origin")
        if origen:
            return origen == self.origen
        referer = self.headers.get("Referer") or ""
        return referer.startswith(self.origen + "/")

    def _leer_cuerpo(self, maximo: int) -> Optional[bytes]:
        try:
            longitud = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return None
        if longitud <= 0 or longitud > maximo:
            return None
        return self.rfile.read(longitud)

    def _sesion_actual(self) -> Optional[dict]:
        sesion = self.auth.sesion(self._token())
        self._csrf = sesion["csrf"] if sesion else None
        return sesion

    def _mostrar_login(self, mensaje: Optional[str] = None, status: int = 200) -> None:
        token = secrets.token_urlsafe(32)
        cookie = f"{COOKIE_PRELOGIN}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=900"
        self._csrf = None
        self._responder_html(_login_html(token, mensaje), status=status, cookies=(cookie,))

    # -- GET
    def do_GET(self):
        ruta = urllib.parse.urlsplit(self.path).path
        if ruta not in RUTAS_REMOTAS:
            self._no_encontrada()
            return
        if ruta == "/login":
            if self._sesion_actual():
                self._redirigir("/cargar-noticia-local")
            else:
                self._mostrar_login()
            return
        if ruta == "/logout":
            self._no_encontrada()
            return
        if not self._sesion_actual():
            self._redirigir("/login")
            return
        if ruta == "/cargar-noticia-local":
            super().do_GET()
            return
        self._get_noticia()

    def _get_noticia(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        id_texto = query.get("id", [None])[0]
        db = self._db()
        try:
            noticia = db.obtener(int(id_texto)) if id_texto and id_texto.isdigit() else None
            if not noticia or noticia["estado"] != Estado.PREPARADA.value:
                self._no_encontrada()
                return
            self._responder_html(_detalle_remoto_html(noticia))
        finally:
            db.close()

    # -- POST
    def _descartar_cuerpo(self) -> None:
        """Lee y descarta el cuerpo de un POST rechazado (sin procesarlo),
        para cerrar la respuesta limpiamente."""
        try:
            longitud = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            longitud = 0
        if 0 < longitud <= LONGITUD_MAXIMA_CUERPO_POST_CARGA:
            self.rfile.read(longitud)
        else:
            self.close_connection = True

    def do_POST(self):
        ruta = urllib.parse.urlsplit(self.path).path
        if ruta not in RUTAS_REMOTAS:
            self._descartar_cuerpo()
            self._no_encontrada()
            return
        if not self._origen_valido():
            log.warning("POST rechazado por origen ip=%s ruta=%s", self._ip(), ruta)
            self._descartar_cuerpo()
            self._prohibido()
            return
        if ruta == "/login":
            self._post_login()
            return

        sesion = self._sesion_actual()
        if not sesion:
            self._descartar_cuerpo()
            self._redirigir("/login")
            return
        cuerpo = self._leer_cuerpo(LONGITUD_MAXIMA_CUERPO_POST_CARGA)
        if cuerpo is None:
            self._responder_html(_pagina("Error", "<p>Formulario inválido o demasiado grande.</p>"), status=413)
            return
        datos = urllib.parse.parse_qs(cuerpo.decode("utf-8", errors="replace"))
        if not hmac.compare_digest(datos.get("csrf", [""])[0].encode(), sesion["csrf"].encode()):
            log.warning("POST rechazado por CSRF ip=%s ruta=%s", self._ip(), ruta)
            self._prohibido()
            return

        if ruta == "/logout":
            self.auth.cerrar_sesion(self._token())
            log.info("logout ip=%s", self._ip())
            self._redirigir("/login", cookies=(f"{COOKIE_SESION}=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0",))
            return
        if ruta == "/cargar-noticia-local":
            # Reutiliza el circuito del panel principal tal cual.
            self.rfile = io.BytesIO(cuerpo)
            self._post_cargar_noticia_local()
            return
        self._post_noticia(datos)

    def _post_noticia(self, datos: dict) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        id_texto = query.get("id", [None])[0]
        accion = datos.get("accion", [""])[0]
        if accion != "reintentar_redaccion":
            # Aprobar, rechazar o editar: solo desde el panel principal.
            log.warning("accion no permitida en remoto ip=%s accion=%s", self._ip(), accion[:30])
            self._prohibido()
            return
        if not id_texto or not id_texto.isdigit():
            self._no_encontrada()
            return
        db = self._db()
        try:
            noticia = db.obtener(int(id_texto))
            if not noticia or noticia["estado"] != Estado.PREPARADA.value:
                self._no_encontrada()
                return
            _, mensaje = reintentar_redaccion(db, noticia["id"], self.redactor)
            self._responder_html(_detalle_remoto_html(db.obtener(noticia["id"]), mensaje))
        finally:
            db.close()

    def _post_login(self) -> None:
        ip = self._ip()
        if self.auth.bloqueado(ip):
            log.warning("login bloqueado ip=%s", ip)
            self._descartar_cuerpo()
            self._mostrar_login("Demasiados intentos. Probá más tarde.", status=429)
            return
        cuerpo = self._leer_cuerpo(LONGITUD_MAXIMA_LOGIN)
        if cuerpo is None:
            self._mostrar_login("Formulario inválido.", status=400)
            return
        datos = urllib.parse.parse_qs(cuerpo.decode("utf-8", errors="replace"))
        prelogin = _cookies(self.headers.get("Cookie")).get(COOKIE_PRELOGIN, "")
        enviado = datos.get("prelogin", [""])[0]
        if not prelogin or not hmac.compare_digest(prelogin.encode(), enviado.encode()):
            log.warning("login rechazado por CSRF ip=%s", ip)
            self._mostrar_login("La página venció. Volvé a intentar.", status=403)
            return
        if not self.auth.configurado:
            log.error("login deshabilitado: faltan credenciales en el entorno")
            self._mostrar_login("Acceso no configurado.", status=503)
            return
        password = datos.get("password", [""])[0]
        codigo = datos.get("codigo", [""])[0].strip()
        if not self.auth.autenticar(password, codigo):
            self.auth.registrar_fallo(ip)
            log.warning("login fallido ip=%s", ip)
            self._mostrar_login("Credenciales inválidas.", status=401)
            return
        token = self.auth.crear_sesion()
        log.info("login ok ip=%s", ip)
        self._redirigir("/cargar-noticia-local", cookies=(
            f"{COOKIE_SESION}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={SESION_MAXIMA_SEGUNDOS}",
            f"{COOKIE_PRELOGIN}=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0",
        ))

    def log_message(self, format, *args):
        pass


# --- Arranque y configuración ---------------------------------------------

def iniciar_servidor_remoto(db_path=None, redactor=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    PanelRemotoHandler.db_path = db_path or DB_PATH_DEFAULT
    PanelRemotoHandler.redactor = redactor if redactor is not None else crear_redactor()
    PanelRemotoHandler.origen = os.environ.get("PANEL_REMOTO_ORIGEN", ORIGEN_DEFAULT)
    PanelRemotoHandler.auth = EstadoAuth(
        os.environ.get("PANEL_REMOTO_PASSWORD_HASH"), os.environ.get("PANEL_REMOTO_TOTP_SECRET")
    )
    if not PanelRemotoHandler.auth.configurado:
        log.error("credenciales no configuradas: el login queda deshabilitado")
    servidor = HTTPServer((HOST_REMOTO, PORT_REMOTO), PanelRemotoHandler)
    log.info("panel remoto limitado en http://%s:%s", HOST_REMOTO, PORT_REMOTO)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


def configurar(archivo: str) -> int:
    """Interactivo, para que lo ejecute el operador en su propia terminal:
    pide la contraseña (sin eco), genera la semilla TOTP, la muestra UNA vez
    para cargarla en la app autenticadora, verifica un código y guarda el
    archivo con permisos 600. Nada de esto queda en logs."""
    password = getpass.getpass(f"Contraseña nueva (mínimo {LONGITUD_MINIMA_PASSWORD} caracteres): ")
    if len(password) < LONGITUD_MINIMA_PASSWORD:
        print("Demasiado corta. No se guardó nada.")
        return 1
    if getpass.getpass("Repetila: ") != password:
        print("No coinciden. No se guardó nada.")
        return 1
    secreto = generar_secreto_totp()
    uri = "otpauth://totp/Ledesma%20Participa:panel?secret={}&issuer=Ledesma%20Participa".format(secreto)
    print("\nCargá esta clave en Google Authenticator (o similar) como clave manual, tipo 'basada en tiempo':")
    print(f"  {secreto}")
    print(f"  ({uri})\n")
    codigo = input("Código de 6 dígitos que muestra la app: ").strip()
    if verificar_totp(secreto, codigo, time.time(), -1) is None:
        print("Código incorrecto. No se guardó nada; volvé a ejecutar el comando.")
        return 1
    contenido = (
        f"PANEL_REMOTO_PASSWORD_HASH={generar_hash_password(password)}\n"
        f"PANEL_REMOTO_TOTP_SECRET={secreto}\n"
    )
    descriptor = os.open(archivo, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as salida:
        salida.write(contenido)
    os.chmod(archivo, 0o600)
    print(f"Guardado en {archivo} (permisos 600). Reiniciá el servicio: systemctl restart ledesma-panel-remoto")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Panel remoto limitado — Ledesma Participa")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("servir")
    conf = sub.add_parser("configurar")
    conf.add_argument("--archivo", default="/etc/ledesma-panel-remoto.env")
    args = parser.parse_args(argv)
    if args.comando == "configurar":
        return configurar(args.archivo)
    iniciar_servidor_remoto()
    return 0


if __name__ == "__main__":
    sys.exit(main())
