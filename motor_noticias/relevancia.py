import json
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


def _contiene_alguna(texto_norm: str, terminos: list) -> Optional[str]:
    for termino in terminos:
        if _sin_acentos(termino) in texto_norm:
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

    contenido = _sin_acentos(f"{titulo} {texto}")

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
