"""Detección determinística (sin IA) de contenido de entretenimiento,
espectáculos, curiosidades o tendencias virales: el último nivel de la
cascada editorial, solo para noticias `sin_clasificar` (sin relación
geográfica local/departamental/provincial ni marcador nacional) que de
otro modo dejarían la franja vacía."""
import json
import unicodedata
from pathlib import Path
from typing import Optional

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "entretenimiento.json"


def cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def es_entretenimiento_o_curiosidad(titulo: str, texto: str, config: Optional[dict] = None) -> bool:
    config = config or cargar_config()
    contenido_norm = _sin_acentos(f"{titulo or ''} {texto or ''}")
    return any(_sin_acentos(palabra) in contenido_norm for palabra in config["palabras_clave"])
