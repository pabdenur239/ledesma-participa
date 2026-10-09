"""Lectura del texto de una URL para el canal rápido de noticias locales
(panel → "Cargar noticia local", 9/10/2026).

Solo se leen sitios web abiertos (portales, municipios, organismos): se
toma el título y el texto de la nota (metadatos `og:` y párrafos del
artículo). Nunca se descarga nada de redes sociales — Facebook, Instagram,
WhatsApp, TikTok, X — ni se evade ningún login: para esas URLs el operador
pega el texto a mano y la URL queda solo como referencia de la fuente.

Tampoco se toma la imagen de la nota (`og:image`): reutilizar una foto
ajena exige permiso, así que la imagen solo entra si el operador carga una
propia/autorizada (si no, placa editorial).
"""
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import urlsplit

TIMEOUT_SEGUNDOS = 10
TAMANIO_MAXIMO_BYTES = 2_000_000
LONGITUD_MAXIMA_TEXTO_EXTRAIDO = 6000
LONGITUD_MINIMA_PARRAFO = 40
USER_AGENT = "Mozilla/5.0 (compatible; LedesmaParticipaBot/1.0; +https://ledesmaparticipa.com.ar)"

# Redes y plataformas que NO se leen automáticamente (sin acceso oficial y
# sin scraping): la URL se guarda como referencia y el texto lo pega el
# operador.
DOMINIOS_NO_LEGIBLES = (
    "facebook.com", "fb.com", "fb.watch", "fb.me", "instagram.com", "instagr.am",
    "whatsapp.com", "wa.me", "tiktok.com", "twitter.com", "x.com", "threads.net",
)

# Enlaces de video: nunca se descarga ni se resube el video, solo se
# conserva el enlace original como referencia.
_RE_VIDEO = re.compile(
    r"(fb\.watch/|/videos?/|/watch/?\?|/reel/|/reels/|/share/v/|/share/r/|youtube\.com/|youtu\.be/|tiktok\.com/)",
    re.IGNORECASE,
)


class ErrorLecturaURL(Exception):
    """La URL no se pudo leer: el operador tiene que pegar el texto."""


@dataclass
class TextoURL:
    titulo: Optional[str]
    texto: str


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _es_dominio(host: str, dominio: str) -> bool:
    return host == dominio or host.endswith("." + dominio)


def es_red_social(url: str) -> bool:
    host = _host(url)
    return any(_es_dominio(host, d) for d in DOMINIOS_NO_LEGIBLES)


def es_enlace_video(url: str) -> bool:
    return bool(_RE_VIDEO.search(url or ""))


def _host_publico(host: str) -> bool:
    """Evita que el panel (que corre en el servidor) pida direcciones
    internas: solo hosts que resuelven a IPs públicas."""
    try:
        direcciones = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except (socket.gaierror, UnicodeError):
        return False
    for direccion in direcciones:
        ip = ipaddress.ip_address(direccion.split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return bool(direcciones)


class _ExtractorNota(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.titulo_html = ""
        self.parrafos_articulo: List[str] = []
        self.parrafos: List[str] = []
        self._en_title = False
        self._en_p = 0
        self._en_article = 0
        self._ignorar = 0
        self._buffer: List[str] = []

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if tag == "meta":
            clave = (atributos.get("property") or atributos.get("name") or "").lower()
            if clave in ("og:title", "og:description", "description", "twitter:title", "twitter:description"):
                self.meta.setdefault(clave, atributos.get("content") or "")
        elif tag == "title":
            self._en_title = True
        elif tag in ("script", "style", "noscript", "nav", "footer", "aside", "form"):
            self._ignorar += 1
        elif tag == "article":
            self._en_article += 1
        elif tag == "p" and not self._ignorar:
            self._en_p += 1
            self._buffer = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._en_title = False
        elif tag in ("script", "style", "noscript", "nav", "footer", "aside", "form"):
            self._ignorar = max(0, self._ignorar - 1)
        elif tag == "article":
            self._en_article = max(0, self._en_article - 1)
        elif tag == "p" and self._en_p:
            self._en_p -= 1
            parrafo = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
            if len(parrafo) >= LONGITUD_MINIMA_PARRAFO:
                (self.parrafos_articulo if self._en_article else self.parrafos).append(parrafo)

    def handle_data(self, data):
        if self._en_title:
            self.titulo_html += data
        elif self._en_p and not self._ignorar:
            self._buffer.append(data)


def extraer_texto_html(contenido_html: str) -> TextoURL:
    extractor = _ExtractorNota()
    extractor.feed(contenido_html)
    meta = extractor.meta
    titulo = (meta.get("og:title") or meta.get("twitter:title") or extractor.titulo_html or "").strip()
    parrafos = extractor.parrafos_articulo or extractor.parrafos
    texto = "\n\n".join(parrafos)
    if not texto:
        texto = (meta.get("og:description") or meta.get("description") or meta.get("twitter:description") or "").strip()
    texto = unescape(texto)[:LONGITUD_MAXIMA_TEXTO_EXTRAIDO].strip()
    return TextoURL(titulo=unescape(titulo) or None, texto=texto)


def _descargar(url: str) -> str:
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_SEGUNDOS) as respuesta:
            if not _host_publico(_host(respuesta.geturl())):
                raise ErrorLecturaURL("la URL redirige a una dirección no permitida.")
            tipo = respuesta.headers.get("Content-Type", "")
            if "html" not in tipo.lower():
                raise ErrorLecturaURL("la URL no es una página web (no es HTML).")
            datos = respuesta.read(TAMANIO_MAXIMO_BYTES + 1)
            charset = respuesta.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as error:
        raise ErrorLecturaURL(f"el sitio respondió HTTP {error.code}.") from error
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as error:
        raise ErrorLecturaURL("no se pudo conectar con el sitio.") from error
    if len(datos) > TAMANIO_MAXIMO_BYTES:
        raise ErrorLecturaURL("la página es demasiado grande.")
    return datos.decode(charset, errors="replace")


def leer_texto_url(url: str, descargar=_descargar) -> TextoURL:
    """Título y texto de una nota web. Lanza `ErrorLecturaURL` (con un
    motivo legible para el operador) si es una red social, un host interno,
    o si no se obtuvo texto suficiente."""
    if es_red_social(url):
        raise ErrorLecturaURL("las publicaciones de redes sociales no se leen automáticamente.")
    host = _host(url)
    if not host or not _host_publico(host):
        raise ErrorLecturaURL("la dirección no es un sitio web público.")
    resultado = extraer_texto_html(descargar(url))
    if len(resultado.texto) < LONGITUD_MINIMA_PARRAFO:
        raise ErrorLecturaURL("no se encontró texto de nota en la página.")
    return resultado
