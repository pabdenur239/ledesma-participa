import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "localidades.json"


def cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


# Nombre propio del medio: aparece en la firma de toda nota de contenido
# propio ("Nota propia de Ledesma Participa…") y NO es una referencia
# geográfica. Se neutraliza antes de buscar localidades para que esa firma
# no clasifique la nota como del Departamento Ledesma (bug real: una nota
# reelaborada de alcance nacional quedó como "departamental" y se publicó
# como urgente local). "Departamento Ledesma" / "Ledesma" como lugar real
# siguen contando: solo se quita la secuencia exacta "ledesma participa".
MARCA_PROPIA_NORMALIZADA = "ledesma participa"


def _quitar_marca_propia(texto_norm: str) -> str:
    return texto_norm.replace(MARCA_PROPIA_NORMALIZADA, " ")


def _contiene_alguna(texto_norm: str, terminos: list) -> Optional[str]:
    """Busca cada término como palabra completa (límites \\b), no como
    substring crudo: un término corto como "Libertador" no debe disparar
    dentro de una palabra más larga que lo contiene, como "Libertadores"
    (p. ej. "Copa Libertadores", el torneo de fútbol) — bug real detectado
    en producción: noticias deportivas de Infobae/La Nación sobre la Copa
    Libertadores se clasificaban como territorio local de Libertador
    General San Martín y llegaron a publicarse."""
    for termino in terminos:
        patron = r"\b" + re.escape(_sin_acentos(termino)) + r"\b"
        if re.search(patron, texto_norm):
            return termino
    return None


def clasificar_relevancia(
    titulo: str, texto: str, localidad: Optional[str] = None, config: Optional[dict] = None
) -> dict:
    config = config or cargar_config()

    if localidad:
        localidad_norm = _sin_acentos(localidad)

        match = _contiene_alguna(localidad_norm, config["maxima_prioridad"])
        if match:
            return {
                "relevante": True,
                "motivo": f"Fuente institucional de '{match}' (máxima prioridad geográfica)",
                "localidad": match,
            }

        match = _contiene_alguna(localidad_norm, config["prioridad_alta"])
        if match:
            return {
                "relevante": True,
                "motivo": f"Fuente institucional de '{match}' (Departamento Ledesma, prioridad alta)",
                "localidad": match,
            }

    contenido = _quitar_marca_propia(_sin_acentos(f"{titulo} {texto}"))

    match = _contiene_alguna(contenido, config["maxima_prioridad"])
    if match:
        return {
            "relevante": True,
            "motivo": f"Menciona '{match}' (máxima prioridad geográfica)",
            "localidad": match,
        }

    match = _contiene_alguna(contenido, config["prioridad_alta"])
    if match:
        return {
            "relevante": True,
            "motivo": f"Menciona '{match}' (Departamento Ledesma, prioridad alta)",
            "localidad": match,
        }

    match = _contiene_alguna(contenido, config["jujuy"])
    if match:
        return {
            "relevante": False,
            "motivo": "Menciona Jujuy sin relación concreta con Libertador o Ledesma",
            "localidad": match,
        }

    return {
        "relevante": False,
        "motivo": "Sin relación geográfica con Libertador General San Martín o el Departamento Ledesma",
        "localidad": None,
    }
