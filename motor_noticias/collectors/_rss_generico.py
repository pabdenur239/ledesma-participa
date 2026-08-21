"""Motor de parseo RSS 2.0 genérico, reutilizado por las fuentes temáticas
(espectáculos/internacional/gastronomía/salud) agregadas el 20/8/2026: a
diferencia de las fuentes geográficas ya existentes (que se mantienen cada
una en su propio módulo, aun siendo casi idénticas entre sí, por prioridad
de auditabilidad), acá el volumen de fuentes nuevas (12) hace que compartir
el motor de parseo sea la opción más segura — un solo lugar para corregir un
bug de parseo en vez de doce. Cada collector público sigue siendo un módulo
propio con su config, su URL y su `categoria_tematica` fija, igual que
cualquier otro collector del proyecto.

No reemplaza nada existente: los collectors geográficos (jujuyaldia,
canal6_libertador, jujuygrafico, etc.) siguen tal cual, sin tocarlos.
"""
import html
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional, Union

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LedesmaParticipa/1.0; RSS Reader)",
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
}

NS = {
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}

PATRON_IMG_SRC = re.compile(r'<img[^>]*\bsrc="([^"]+)"', re.IGNORECASE)
PATRON_BOILERPLATE_WORDPRESS = re.compile(
    r"<p>\s*(La entrada|The post).*?(se public[oó] primero en|appeared first on).*?</p>\s*$",
    re.IGNORECASE | re.DOTALL,
)
PATRONES_IMAGEN_INVALIDA = ("pixel", "1x1", "spacer", "favicon", "tracking", "logo", "icon", "avatar")

# Rango de caracteres válidos según XML 1.0 (https://www.w3.org/TR/xml/#charsets):
# #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF].
# El patrón matchea lo que queda AFUERA de ese rango (caracteres de control
# ilegales, ej. un \x03 real visto en producción en el feed de Fundación
# Favaloro) para poder eliminarlos antes de parsear.
PATRON_CARACTERES_XML_ILEGALES = re.compile(
    "[^\t\n\r -퟿-�\U00010000-\U0010FFFF]"
)


class ErrorRecoleccionRSSGenerico(RuntimeError):
    """Error controlado al recolectar un feed RSS con el motor genérico."""


def _texto(item: ET.Element, etiqueta: str, ns: dict = NS) -> Optional[str]:
    elemento = item.find(etiqueta, ns)
    return elemento.text.strip() if elemento is not None and elemento.text else None


def _limpiar_espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _quitar_etiquetas_html(texto_html: str) -> str:
    sin_scripts = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", texto_html, flags=re.IGNORECASE | re.DOTALL)
    sin_etiquetas = re.sub(r"<[^>]+>", " ", sin_scripts)
    return _limpiar_espacios(html.unescape(sin_etiquetas))


def _es_imagen_valida(url: Optional[str]) -> bool:
    if not url:
        return False
    url_norm = url.lower()
    return not any(patron in url_norm for patron in PATRONES_IMAGEN_INVALIDA)


def _imagen(item: ET.Element, descripcion_html: str, contenido_encoded_html: str) -> Optional[str]:
    media_content = item.find("media:content", NS)
    if media_content is not None and _es_imagen_valida(media_content.get("url")):
        return media_content.get("url")

    media_thumbnail = item.find("media:thumbnail", NS)
    if media_thumbnail is not None and _es_imagen_valida(media_thumbnail.get("url")):
        return media_thumbnail.get("url")

    enclosure = item.find("enclosure")
    if enclosure is not None:
        tipo = enclosure.get("type", "")
        if tipo.startswith("image") and _es_imagen_valida(enclosure.get("url")):
            return enclosure.get("url")

    for texto_html in (contenido_encoded_html, descripcion_html):
        if texto_html:
            coincidencia = PATRON_IMG_SRC.search(texto_html)
            if coincidencia and _es_imagen_valida(coincidencia.group(1)):
                return coincidencia.group(1)
    return None


def _normalizar_para_parseo(contenido: Union[str, bytes]) -> Union[str, bytes]:
    """Algunos feeds reales (ej. argentina.gob.ar) envían espacio/salto de
    línea antes de `<?xml ...?>`, y otros un BOM UTF-8: ambos son válidos
    para cualquier lector tolerante pero rompen `ET.fromstring`, que exige
    la declaración XML exactamente al principio del documento. Se recorta
    ese prefijo espurio antes de parsear.

    Además, algunos feeds (ej. Fundación Favaloro, visto en producción)
    traen caracteres de control ilegales según XML 1.0 (probablemente de un
    copy-paste desde otro editor) incrustados en el texto de algún ítem, lo
    que rompe el parseo estricto de todo el feed por un solo carácter. Se
    eliminan los caracteres fuera del rango válido de XML 1.0 antes de
    parsear — no reinterpreta ni reestructura nada, solo tolera bytes que
    nunca debieron estar ahí."""
    if isinstance(contenido, bytes):
        contenido = contenido.lstrip(b"\xef\xbb\xbf \t\r\n")
        texto = contenido.decode("utf-8", errors="replace")
        return PATRON_CARACTERES_XML_ILEGALES.sub("", texto).encode("utf-8")
    contenido = contenido.lstrip("﻿ \t\r\n")
    return PATRON_CARACTERES_XML_ILEGALES.sub("", contenido)


def parsear_rss_generico(
    contenido: Union[str, bytes],
    nombre_fuente: str,
    categoria_tematica: str,
    quitar_boilerplate_wordpress: bool = True,
) -> List[dict]:
    raiz = ET.fromstring(_normalizar_para_parseo(contenido))
    noticias = []
    for item in raiz.findall("./channel/item"):
        titulo = _texto(item, "title")
        enlace = _texto(item, "link")
        if not titulo or not enlace:
            continue

        descripcion_html = _texto(item, "description") or ""
        contenido_encoded_html = _texto(item, "content:encoded") or ""
        imagen_url = _imagen(item, descripcion_html, contenido_encoded_html)

        cuerpo_html = descripcion_html
        if quitar_boilerplate_wordpress:
            cuerpo_html = PATRON_BOILERPLATE_WORDPRESS.sub("", cuerpo_html)
        texto = _quitar_etiquetas_html(cuerpo_html)
        if len(texto) < 15 and contenido_encoded_html:
            texto = _quitar_etiquetas_html(contenido_encoded_html)[:500]

        noticias.append(
            {
                "titulo": titulo,
                "texto": texto,
                "url": enlace,
                "fuente": nombre_fuente,
                "fecha": _texto(item, "pubDate") or "",
                "imagen_url": imagen_url,
                "categoria_tematica": categoria_tematica,
            }
        )
    return noticias


def obtener_rss(url: str, timeout: int = 20) -> bytes:
    peticion = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            return respuesta.read()
    except urllib.error.HTTPError as error:
        raise ErrorRecoleccionRSSGenerico(
            f"Respondió HTTP {error.code} ({error.reason}) al pedir {url}"
        ) from error
    except urllib.error.URLError as error:
        raise ErrorRecoleccionRSSGenerico(f"No se pudo conectar a {url}: {error.reason}") from error
