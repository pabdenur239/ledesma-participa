import html
import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import List, Optional, Union
from urllib.parse import urlparse

# La Nación e Infobae comparten exactamente el mismo dialecto real de RSS
# (ambos corren sobre Arc XP): RSS 2.0 con content:encoded, media:content y
# category (opcional: el feed real de Infobae inspeccionado no trae
# category en ningún item, el de La Nación sí en casi todos). Por eso el
# parser se comparte en un único módulo en vez de duplicarlo.
NS = {
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}

LIMITE_ITEMS_DEFAULT = 25
TOPE_PROPORCION_DEPORTES_ESPECTACULOS = 0.4
LONGITUD_MINIMA_DESCRIPCION = 30
LONGITUD_MAXIMA_RESUMEN_FALLBACK = 500

# Exclusión determinística por categoría/URL (sin IA): contenido sin valor
# periodístico general para alimentar el nivel nacional de la cascada.
CATEGORIAS_EXCLUIDAS = {
    "horoscopo",
    "loteria",
    "quiniela",
    "sorteos",
    "promociones",
    "publicidad",
    "branded content",
    "contenido patrocinado",
    "publirreportaje",
}
SEGMENTOS_URL_EXCLUIDOS = {
    "horoscopo",
    "loteria",
    "quiniela",
    "sorteos",
    "promociones",
    "publicidad",
    "branded",
    "patrocinado",
    "publirreportaje",
}

# Deportes/espectáculos no se bloquean, pero no pueden dominar el lote.
CATEGORIAS_DEPORTES_ESPECTACULOS = {
    "deportes",
    "futbol",
    "hockey",
    "basquetbol",
    "espectaculos",
    "teleshow",
    "entretenimiento",
}
SEGMENTOS_URL_DEPORTES_ESPECTACULOS = CATEGORIAS_DEPORTES_ESPECTACULOS

PATRON_IMG_SRC = re.compile(r'<img[^>]*\bsrc="([^"]+)"', re.IGNORECASE)
PATRONES_IMAGEN_INVALIDA = ("pixel", "1x1", "spacer", "favicon", "tracking", "logo", "icon")


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def _texto(item: ET.Element, etiqueta: str, ns: dict = NS) -> Optional[str]:
    elemento = item.find(etiqueta, ns)
    return elemento.text.strip() if elemento is not None and elemento.text else None


def _limpiar_html(texto_html: str) -> str:
    if not texto_html:
        return ""
    sin_scripts = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", texto_html, flags=re.IGNORECASE | re.DOTALL)
    sin_etiquetas = re.sub(r"<[^>]+>", " ", sin_scripts)
    texto = html.unescape(sin_etiquetas)
    return re.sub(r"\s+", " ", texto).strip()


def _resumen(descripcion: Optional[str], contenido_encoded: Optional[str]) -> str:
    """Prioriza `description` si alcanza para un resumen periodístico
    usable; si está vacía o es insuficiente, recorta el inicio de
    `content:encoded` ya limpio de HTML — nunca la nota completa."""
    resumen_desc = _limpiar_html(descripcion or "")
    if len(resumen_desc) >= LONGITUD_MINIMA_DESCRIPCION:
        return resumen_desc

    resumen_contenido = _limpiar_html(contenido_encoded or "")
    if not resumen_contenido:
        return resumen_desc
    if len(resumen_contenido) <= LONGITUD_MAXIMA_RESUMEN_FALLBACK:
        return resumen_contenido

    recorte = resumen_contenido[:LONGITUD_MAXIMA_RESUMEN_FALLBACK]
    ultimo_espacio = recorte.rfind(" ")
    if ultimo_espacio > 0:
        recorte = recorte[:ultimo_espacio]
    return recorte.rstrip(" .,;:") + "…"


def _es_imagen_valida(url: Optional[str]) -> bool:
    if not url:
        return False
    url_norm = url.lower()
    return not any(patron in url_norm for patron in PATRONES_IMAGEN_INVALIDA)


def _imagen(item: ET.Element) -> Optional[str]:
    media_content = item.find("media:content", NS)
    if media_content is not None:
        url = media_content.get("url")
        if _es_imagen_valida(url):
            return url

    media_thumbnail = item.find("media:thumbnail", NS)
    if media_thumbnail is not None:
        url = media_thumbnail.get("url")
        if _es_imagen_valida(url):
            return url

    for etiqueta in ("content:encoded", "description"):
        texto_html = _texto(item, etiqueta) or ""
        if texto_html:
            coincidencia = PATRON_IMG_SRC.search(texto_html)
            if coincidencia and _es_imagen_valida(coincidencia.group(1)):
                return coincidencia.group(1)
    return None


def _primer_segmento_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return _sin_acentos(path.split("/")[0]) if path else ""


def _excluido_deterministicamente(categoria: Optional[str], url: str) -> bool:
    if _primer_segmento_url(url) in SEGMENTOS_URL_EXCLUIDOS:
        return True
    if categoria and _sin_acentos(categoria) in CATEGORIAS_EXCLUIDAS:
        return True
    return False


def _es_deportes_o_espectaculos(categoria: Optional[str], url: str) -> bool:
    if _primer_segmento_url(url) in SEGMENTOS_URL_DEPORTES_ESPECTACULOS:
        return True
    if categoria and _sin_acentos(categoria) in CATEGORIAS_DEPORTES_ESPECTACULOS:
        return True
    return False


def _limitar_con_tope_deportes(
    candidatas: List[tuple], limite: int, tope_proporcion: float
) -> List[dict]:
    """`candidatas`: lista de (noticia, es_deportes_o_espectaculos) en el
    orden real del feed (más reciente primero). No bloquea deportes/
    espectáculos, pero evita que dominen el lote si el feed trae demasiados:
    lo que exceda la proporción configurada queda para el final, solo se usa
    si sobran espacios tras priorizar el resto del contenido general."""
    tope_deportes = int(limite * tope_proporcion)
    seleccionadas: List[dict] = []
    pendientes_deportes: List[dict] = []
    deportes_incluidos = 0

    for noticia, es_deportes in candidatas:
        if len(seleccionadas) >= limite:
            break
        if es_deportes:
            if deportes_incluidos < tope_deportes:
                seleccionadas.append(noticia)
                deportes_incluidos += 1
            else:
                pendientes_deportes.append(noticia)
        else:
            seleccionadas.append(noticia)

    for noticia in pendientes_deportes:
        if len(seleccionadas) >= limite:
            break
        seleccionadas.append(noticia)

    return seleccionadas


def parsear_rss_arc(
    contenido: Union[str, bytes],
    nombre_fuente: str,
    limite: int = LIMITE_ITEMS_DEFAULT,
    tope_proporcion_deportes: float = TOPE_PROPORCION_DEPORTES_ESPECTACULOS,
) -> List[dict]:
    raiz = ET.fromstring(contenido)
    candidatas = []
    for item in raiz.findall("./channel/item"):
        titulo = _texto(item, "title")
        enlace = _texto(item, "link")
        if not titulo or not enlace:
            continue

        categoria = _texto(item, "category")
        if _excluido_deterministicamente(categoria, enlace):
            continue

        descripcion = _texto(item, "description")
        contenido_encoded = _texto(item, "content:encoded")
        noticia = {
            "titulo": titulo,
            "texto": _resumen(descripcion, contenido_encoded),
            "url": enlace,
            "fuente": nombre_fuente,
            "fecha": _texto(item, "pubDate") or "",
            "imagen_url": _imagen(item),
        }
        candidatas.append((noticia, _es_deportes_o_espectaculos(categoria, enlace)))

    return _limitar_con_tope_deportes(candidatas, limite, tope_proporcion_deportes)
