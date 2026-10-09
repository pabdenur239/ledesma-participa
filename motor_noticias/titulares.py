"""Control de titulares (Etapa 3): mantiene el estándar
`[TERRITORIO] | TITULAR EN MAYÚSCULAS` y detecta lo que lo degrada — títulos
demasiado largos, texto cortado, frases sin información, clickbait y
exageración — sin reescribir ni mutilar el titular.

Lo único que se corrige en el texto es lo mecánico y seguro (espacios de más
y puntos suspensivos finales de un título que llegó cortado desde la
fuente). Todo lo demás queda como alerta registrada (`evaluar_titular`) para
la revisión y el informe interno: nunca se inventa ni se quita información
para cumplir el número de palabras (objetivo 8–12, orientativo)."""
import json
import re
from pathlib import Path
from typing import List, Optional

from .territorio import _sin_acentos

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "titulares.json"

PALABRAS_OBJETIVO_MIN = 8
PALABRAS_OBJETIVO_MAX = 12
PALABRAS_MAXIMO_TOLERADO = 18
PALABRAS_MINIMO_INFORMATIVO = 4

_RE_ESPACIOS = re.compile(r"\s+")
_RE_CORTE_FINAL = re.compile(r"\s*(\.\.\.|…)\s*$")
_RE_SIGNOS_REPETIDOS = re.compile(r"([!?¡¿])\1+")


def _cargar_config(path: Optional[Path] = None) -> dict:
    try:
        with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def limpiar_titular(titulo: str) -> str:
    """Solo correcciones mecánicas: espacios y puntos suspensivos finales
    (un "…" al final es casi siempre un título cortado por la fuente o el
    feed RSS). No cambia palabras."""
    limpio = _RE_ESPACIOS.sub(" ", titulo or "").strip()
    return _RE_CORTE_FINAL.sub("", limpio).strip()


def _normalizado(texto: str) -> str:
    return _sin_acentos(texto or "").lower()


def evaluar_titular(titulo: str, config: Optional[dict] = None) -> dict:
    """Devuelve {"palabras", "alertas": [...]} con alertas normalizadas:
    `largo`, `corto_sin_informacion`, `cortado`, `clickbait`, `exageracion`,
    `signos_repetidos`. Lista vacía = titular dentro del estándar."""
    config = config if config is not None else _cargar_config()
    original = _RE_ESPACIOS.sub(" ", titulo or "").strip()
    palabras = len(original.split())
    alertas: List[str] = []
    if palabras > PALABRAS_MAXIMO_TOLERADO:
        alertas.append("largo")
    if 0 < palabras < PALABRAS_MINIMO_INFORMATIVO:
        alertas.append("corto_sin_informacion")
    if _RE_CORTE_FINAL.search(original) or original.endswith((",", ":", ";", " -", " y", " de", " la", " el")):
        alertas.append("cortado")
    texto = _normalizado(original)
    if any(_normalizado(f) in texto for f in config.get("clickbait", [])):
        alertas.append("clickbait")
    if any(re.search(rf"\b{re.escape(_normalizado(f))}\b", texto) for f in config.get("exageracion", [])):
        alertas.append("exageracion")
    if _RE_SIGNOS_REPETIDOS.search(original):
        alertas.append("signos_repetidos")
    return {
        "palabras": palabras,
        "en_objetivo": PALABRAS_OBJETIVO_MIN <= palabras <= PALABRAS_OBJETIVO_MAX,
        "alertas": alertas,
    }
