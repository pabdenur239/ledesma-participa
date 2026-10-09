"""URL pública de la nota propia en ledesmaparticipa.com.ar (una sola
definición para el generador del sitio y el copy de Meta)."""
import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

from ..atribucion import titulo_publico

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
SALIDA_DEFAULT = RAIZ_PROYECTO / "docs"
CONFIG_SITIO_PATH_DEFAULT = RAIZ_PROYECTO / "config" / "sitio.json"


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def slugify(texto: str, longitud_maxima: int = 70) -> str:
    base = _sin_acentos(texto)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:longitud_maxima].strip("-") or "nota"


def titulo_de(noticia: dict) -> str:
    titulo = (
        noticia.get("titulo_revisado") or noticia.get("titulo_preparado") or noticia.get("titulo_original") or ""
    ).strip()
    return titulo_publico(noticia, titulo)


def url_relativa_noticia(noticia: dict) -> str:
    return f"noticias/{noticia['id']}-{slugify(titulo_de(noticia))}/"


def base_url(config_path: Optional[Path] = None) -> str:
    try:
        with open(config_path or CONFIG_SITIO_PATH_DEFAULT, encoding="utf-8") as f:
            return (json.load(f).get("base_url_produccion") or "").rstrip("/") + "/"
    except (OSError, json.JSONDecodeError):
        return "https://ledesmaparticipa.com.ar/"


def url_nota_propia(noticia: dict, salida_dir: Optional[Path] = None) -> Optional[str]:
    """URL absoluta de la nota en ledesmaparticipa.com.ar SOLO si la página
    ya está generada (el sitio se regenera y despliega cada 15 minutos); si
    todavía no existe, None — nunca se enlaza una página que daría 404."""
    if noticia.get("id") is None:
        return None
    relativa = url_relativa_noticia(noticia)
    if not (Path(salida_dir or SALIDA_DEFAULT) / relativa / "index.html").is_file():
        return None
    return base_url() + relativa
