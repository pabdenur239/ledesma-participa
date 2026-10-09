"""Taxonomía única de presentación para web y app (agregado 2/10/2026).

Dos dimensiones distintas, nunca mezcladas:

- TERRITORIO (dónde): locales (Libertador + resto del Departamento Ledesma),
  provinciales (resto de Jujuy), nacionales, internacionales. Sale de
  `territorio.clasificar_territorio` — se recalcula al presentar con la
  clasificación vigente, así una nota guardada con un territorio erróneo
  por una versión anterior (p. ej. "Chau anegamientos" de CABA guardada como
  Libertador por "Avenida del Libertador") no aparece en la sección
  equivocada ni en destacadas.
- TEMÁTICA (de qué): policiales, deportes, espectáculos, salud, gastronomía.
  Sale de la categoría temática de la fuente, la sección de la URL y el
  título/bajada. Una nota deportiva de Libertador es territorio = local y
  temática = deportes.

No se fabrica contenido para llenar categorías: si no hay notas de una
temática, la categoría queda vacía.
"""
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import FrozenSet, Optional
from urllib.parse import urlparse

from .models import OrigenIngreso
from .relevancia import cargar_config as cargar_localidades
from .territorio import _fuente_regional, clasificar_territorio

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "categorias.json"

TEMATICAS = ("policiales", "deportes", "espectaculos", "salud", "gastronomia")

# Territorios que no se recalculan: no salen de un texto clasificable
# (publicación institucional, informe diario, resumen) o los fijó una fuente
# 100% local (collector municipal).
ORIGENES_TERRITORIO_FIJO = (OrigenIngreso.INSTITUCIONAL.value, OrigenIngreso.RESUMEN_DIARIO.value)


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


@lru_cache(maxsize=2)
def _config_cacheada(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cargar_config(path: Optional[Path] = None) -> dict:
    return _config_cacheada(str(path or CONFIG_PATH_DEFAULT))


@lru_cache(maxsize=4096)
def _patron(termino: str) -> "re.Pattern":
    termino = _sin_acentos(termino).strip()
    raiz = termino.endswith("*")
    termino = termino.rstrip("*")
    return re.compile(r"\b" + re.escape(termino) + ("" if raiz else r"\b"))


def territorio_vigente(noticia: dict) -> Optional[str]:
    """Territorio con la clasificación vigente (ver docstring del módulo)."""
    guardado = noticia.get("territorio")
    if noticia.get("origen_ingreso") in ORIGENES_TERRITORIO_FIJO or guardado == "institucional":
        return guardado
    if (noticia.get("url_normalizada") or "").startswith("https://ledesma-participa.local/informe-diario/"):
        return guardado
    nombre = noticia.get("nombre_fuente") or ""
    localidad_fuente = noticia.get("localidad") if nombre.lower().startswith("municipalidad") else None
    resultado = clasificar_territorio(
        noticia.get("titulo_original") or "",
        noticia.get("texto_original") or "",
        localidad_fuente=localidad_fuente,
        nombre_fuente=nombre,
        url=noticia.get("url_fuente"),
        categoria=noticia.get("categoria_tematica"),
    )
    nuevo = resultado["territorio"]
    # Una reelaboración propia hereda el territorio de la nota del medio;
    # si el texto reescrito ya no permite clasificarlo, se conserva. Para
    # el resto, el territorio guardado por una versión anterior no se reusa
    # (podía ser justamente el error que se corrige).
    if nuevo == "sin_clasificar" and guardado not in (None, "sin_clasificar"):
        local_dudoso = guardado in ("local", "departamental") and not _fuente_regional(nombre, cargar_localidades())
        propia = noticia.get("origen_ingreso") in (OrigenIngreso.CONTENIDO_PROPIO.value, OrigenIngreso.MANUAL.value)
        if propia or not local_dudoso:
            return guardado
    return nuevo


def tematicas(noticia: dict, config: Optional[dict] = None) -> FrozenSet[str]:
    config = config or cargar_config()
    encontradas = set()
    categoria = noticia.get("categoria_tematica")
    if categoria in config["por_categoria_tematica"]:
        encontradas.add(config["por_categoria_tematica"][categoria])

    segmentos = [_sin_acentos(s) for s in urlparse(noticia.get("url_fuente") or "").path.split("/") if s]
    for tematica, secciones in config["secciones_url"].items():
        if any(seg in secciones for seg in segmentos):
            encontradas.add(tematica)

    titulo = _sin_acentos(
        " ".join(noticia.get(c) or "" for c in ("titulo_revisado", "titulo_preparado", "titulo_original"))
    )
    cuerpo = _sin_acentos((noticia.get("texto_original") or "")[:500])
    for tematica, terminos in config["terminos"].items():
        if any(_patron(t).search(titulo) for t in terminos):
            encontradas.add(tematica)
        elif sum(1 for t in set(terminos) if _patron(t).search(cuerpo)) >= 2:
            encontradas.add(tematica)
    return frozenset(t for t in encontradas if t in TEMATICAS)


SECCION_TERRITORIAL = {
    "local": ("libertador", "Libertador Gral. San Martín"),
    "departamental": ("ledesma", "Departamento Ledesma"),
    "provincial": ("jujuy", "Jujuy"),
    "nacional": ("nacionales", "Nacionales"),
    "internacional": ("internacionales", "Internacionales"),
}

ETIQUETAS_TEMATICAS = {
    "policiales": "Policiales",
    "deportes": "Deportes",
    "espectaculos": "Espectáculos",
    "salud": "Salud",
    "gastronomia": "Gastronomía",
}
