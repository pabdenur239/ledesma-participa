import json
import unicodedata
from pathlib import Path
from typing import Optional

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "riesgo_editorial.json"


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


def evaluar_riesgo_editorial(
    titulo_original: str,
    texto_original: str,
    titulo_preparado: Optional[str] = None,
    texto_preparado: Optional[str] = None,
    nombre_fuente: Optional[str] = None,
    config: Optional[dict] = None,
) -> dict:
    """Detecta por reglas simples y configurables (sin IA) si una noticia
    trata contenido político/institucional, que siempre debe pasar por
    revisión humana obligatoria antes de cualquier publicación."""
    config = config or cargar_config()
    contenido = _sin_acentos(
        " ".join(
            campo or ""
            for campo in (titulo_original, texto_original, titulo_preparado, texto_preparado, nombre_fuente)
        )
    )

    for categoria, terminos in config["categorias"].items():
        match = _contiene_alguna(contenido, terminos)
        if match:
            return {
                "requiere_revision_especial": True,
                "categoria_riesgo": categoria,
                "motivo": (
                    f"Menciona '{match}' (categoría: {categoria}); "
                    "requiere revisión humana obligatoria antes de publicar."
                ),
            }

    return {
        "requiere_revision_especial": False,
        "categoria_riesgo": None,
        "motivo": None,
    }
