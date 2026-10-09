import json
import re
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


def _coincide_patron(texto_norm: str, patrones) -> Optional[str]:
    """Familias de palabras (regex de `patrones` en riesgo_editorial.json):
    reconocen variantes ("agredió", "agresiones", "golpeó") sin depender de
    una palabra exacta. Bug real: "una joven denunció una brutal agresión
    de su hermano" no se detectaba porque ningún término exacto coincidía."""
    for patron in patrones:
        encontrado = re.search(patron, texto_norm)
        if encontrado:
            return encontrado.group(0)
    return None


def _categorias_exceptuadas_por_busqueda_oficial(contenido_norm: str, config: dict) -> set:
    """Una búsqueda oficial de persona desaparecida (CINDAC, Policía…) no se
    bloquea automáticamente por mencionar a un menor o términos judiciales
    del propio pedido: es información pública necesaria. Violencia o muerte
    siguen reteniéndose (no se exceptúan)."""
    regla = config.get("busqueda_oficial")
    if not regla:
        return set()
    if not any(re.search(p, contenido_norm) for p in regla["patrones"]):
        return set()
    if not any(re.search(p, contenido_norm) for p in regla["organismos"]):
        return set()
    return set(regla.get("categorias_exceptuadas", []))


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

    patrones = {k: v for k, v in config.get("patrones", {}).items() if not k.startswith("_")}
    exceptuadas = _categorias_exceptuadas_por_busqueda_oficial(contenido, config)
    for categoria, terminos in config["categorias"].items():
        if categoria in exceptuadas:
            continue
        match = _contiene_alguna(contenido, terminos) or _coincide_patron(contenido, patrones.get(categoria, ()))
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
