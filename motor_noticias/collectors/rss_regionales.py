"""Lectura RSS de InfoYungas, Jujuy al Momento y El Tribuno de Jujuy
(cobertura web/app, 9/10/2026), con el collector HTML anterior como
respaldo.

Los tres medios publican un feed oficial (enlazado desde su propio sitio):
- InfoYungas: https://www.infoyungas.com/blog-feed.xml (Wix)
- Jujuy al Momento: https://www.jujuyalmomento.com/rss/pages/home.xml
- El Tribuno de Jujuy: https://eltribunodejujuy.com/feed

Validado en vivo el 9/10/2026 contra el scraping de portada: el feed trae
título, resumen, enlace, fecha e imagen en todos (o casi todos) los ítems,
mientras que el listado HTML traía la mayoría de los ítems sin texto (y, en
InfoYungas, solo 2 notas). Los enlaces coinciden con los del HTML (en
InfoYungas el feed los manda con %-encoding: se decodifican para que la
deduplicación por URL reconozca las notas ya recolectadas por el HTML).

Respaldo: si el feed falla (HTTP, conexión, certificado, XML roto) o viene
vacío, se usa el collector HTML de siempre, que no se modificó. Solo si
ambos fallan la fuente queda en error para ese ciclo.
"""
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional
from urllib.parse import unquote, urlsplit, urlunsplit

from ._rss_generico import ErrorRecoleccionRSSGenerico, obtener_rss, parsear_rss_generico
from .base import Collector
from .html_infoyungas import InfoYungasHTMLCollector
from .html_jujuyalmomento import JujuyAlMomentoHTMLCollector
from .html_tribuno_jujuy import TribunoJujuyHTMLCollector

logger = logging.getLogger("motor_noticias.collectors.rss_regionales")

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "fuentes.json"


def _url_decodificada(url: str) -> str:
    partes = urlsplit(url)
    return urlunsplit(partes._replace(path=unquote(partes.path)))


def parsear_rss_regional(contenido, nombre_fuente: str) -> List[dict]:
    noticias = parsear_rss_generico(contenido, nombre_fuente, None)
    for noticia in noticias:
        noticia["url"] = _url_decodificada(noticia["url"])
        noticia.pop("categoria_tematica", None)
    return noticias


class _RSSConRespaldoHTML(Collector):
    CLAVE_CONFIG = ""
    COLLECTOR_HTML = None

    def __init__(self, url_rss: Optional[str] = None, timeout: int = 20, config_path: Optional[Path] = None):
        with open(config_path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
            config = json.load(f)[self.CLAVE_CONFIG]
        self.url_rss = url_rss or config["url_rss"]
        self.nombre_fuente = config["nombre_fuente"]
        self.timeout = timeout
        self.config_path = config_path
        self.origen_ultima_lectura: Optional[str] = None  # "rss" | "html"
        self.motivo_respaldo: Optional[str] = None

    def _leer_rss(self) -> List[dict]:
        return parsear_rss_regional(obtener_rss(self.url_rss, timeout=self.timeout), self.nombre_fuente)

    def recolectar(self) -> List[dict]:
        try:
            noticias = self._leer_rss()
            if noticias:
                self.origen_ultima_lectura = "rss"
                return noticias
            self.motivo_respaldo = "feed RSS sin ítems"
        except (ErrorRecoleccionRSSGenerico, ET.ParseError, ValueError) as error:
            self.motivo_respaldo = f"feed RSS con error: {error}"
        logger.warning("%s: %s; se usa el listado HTML como respaldo.", self.nombre_fuente, self.motivo_respaldo)
        self.origen_ultima_lectura = "html"
        return self.COLLECTOR_HTML(timeout=self.timeout, config_path=self.config_path).recolectar()


class InfoYungasRSSCollector(_RSSConRespaldoHTML):
    CLAVE_CONFIG = "infoyungas"
    COLLECTOR_HTML = InfoYungasHTMLCollector


class JujuyAlMomentoRSSCollector(_RSSConRespaldoHTML):
    CLAVE_CONFIG = "jujuyalmomento"
    COLLECTOR_HTML = JujuyAlMomentoHTMLCollector


class TribunoJujuyRSSCollector(_RSSConRespaldoHTML):
    CLAVE_CONFIG = "tribuno_jujuy"
    COLLECTOR_HTML = TribunoJujuyHTMLCollector
