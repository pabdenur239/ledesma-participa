"""Fuente y autoría públicas de una noticia (agregado 2/10/2026).

Problema reputacional real: notas reelaboradas a partir de TodoJujuy u
otros medios (Manos Abiertas, FMI, "Alerta amarilla…") se mostraban en la
web, Facebook e Instagram como "Fuente: Ledesma Participa (contenido
propio)", aunque el contenido venía de un medio. Internamente
`nombre_fuente` sigue siendo "Ledesma Participa (contenido propio)" (lo usan
la deduplicación y la regla de mezcla editorial), pero la presentación
pública separa siempre:

- fuente original: el medio o el organismo que publicó la información
  (con su enlace);
- redacción: "Ledesma Participa" solo cuando el texto lo redactó/resumió el
  propio medio a partir de esa fuente.

Solo es "Ledesma Participa" como fuente lo que el medio produjo
originalmente (institucional, informe diario, agenda propia sin una fuente
única).
"""
import re
from typing import NamedTuple, Optional

from .models import OrigenIngreso

NOMBRE_MEDIO = "Ledesma Participa"
NOMBRES_PROPIOS_INTERNOS = ("Ledesma Participa (contenido propio)", "Ledesma Participa")

_RE_LINEA_FUENTE = re.compile(r"(?im)^\s*fuente\s*:\s*(.+?)\s*(?:[—–-]\s*(https?://\S+))?\s*$")


class Atribucion(NamedTuple):
    fuente: str  # nombre público de la fuente original
    url: Optional[str]  # enlace a la nota original, si existe
    redaccion_propia: bool  # True: texto redactado/resumido por Ledesma Participa a partir de `fuente`

    @property
    def etiqueta(self) -> str:
        """Texto corto para mostrar: "TodoJujuy" o "TodoJujuy · resumen de
        Ledesma Participa"."""
        if self.redaccion_propia and self.fuente != NOMBRE_MEDIO:
            return f"{self.fuente} · resumen de {NOMBRE_MEDIO}"
        return self.fuente


def _fuente_declarada(noticia: dict) -> tuple:
    """Última línea "Fuente: X — url" del texto (la agregan la reelaboración
    y las notas de servicio de contenido propio)."""
    for campo in ("texto_revisado", "texto_preparado", "texto_original"):
        coincidencias = _RE_LINEA_FUENTE.findall(noticia.get(campo) or "")
        for nombre, url in reversed(coincidencias):
            nombre = nombre.strip().rstrip(".")
            if nombre and nombre not in NOMBRES_PROPIOS_INTERNOS:
                return nombre, (url or None)
    return None, None


def _url_publica(url: Optional[str]) -> Optional[str]:
    url = (url or "").strip()
    if not url or "ledesma-participa.local" in url or url.startswith("manual://"):
        return None
    return url


def atribucion(noticia: dict) -> Atribucion:
    nombre = (noticia.get("nombre_fuente") or "").strip()
    url = _url_publica(noticia.get("url_fuente"))
    origen = noticia.get("origen_ingreso")

    if origen == OrigenIngreso.CONTENIDO_PROPIO.value or nombre in NOMBRES_PROPIOS_INTERNOS:
        declarada, url_declarada = _fuente_declarada(noticia)
        if declarada:
            return Atribucion(declarada, url or _url_publica(url_declarada), True)
        return Atribucion(NOMBRE_MEDIO, url, False)
    if not nombre:
        return Atribucion(NOMBRE_MEDIO, url, False)
    return Atribucion(nombre, url, False)


def etiqueta_fuente(noticia: dict) -> str:
    return atribucion(noticia).etiqueta


def titulo_publico(noticia: dict, titulo: str) -> str:
    """Una ACTUALIZACIÓN de un acontecimiento ya publicado se rotula como
    tal (deduplicación por acontecimiento, `motor_noticias.eventos`)."""
    if noticia.get("actualizacion_de") and not titulo.upper().startswith("ACTUALIZACIÓN"):
        return f"ACTUALIZACIÓN: {titulo}"
    return titulo
