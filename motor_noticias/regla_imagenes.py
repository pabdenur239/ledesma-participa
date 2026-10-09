"""Regla de imágenes (Etapa 1, 9/10/2026): nunca una imagen
descontextualizada (stock presentado como si fuera el hecho, una foto de
diarios para una protesta, un taller para un corte de agua…).

Orden obligatorio: 1) foto real del hecho; 2) foto oficial autorizada;
3) recurso claramente relacionado y permitido; 4) si no hay ninguna,
PLACA EDITORIAL GRÁFICA (`meta/identidad_visual.generar_pieza_feed` sin
foto). La foto que acompaña la nota en la fuente cuenta como 1–3 salvo que
sea de un banco de stock, un archivo genérico, o una foto de archivo que el
medio reutiliza para notas distintas (señal de ilustración, no del hecho).
Reglas en `config/imagenes.json`."""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "imagenes.json"


@lru_cache(maxsize=2)
def _config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cargar_config(path: Optional[Path] = None) -> dict:
    return _config(str(path or CONFIG_PATH_DEFAULT))


def evaluar_imagen(url: Optional[str], usos_en_otras_noticias: int = 0, config: Optional[dict] = None) -> Tuple[bool, str]:
    """(apta, motivo) para la imagen de la fuente de una noticia."""
    config = config or cargar_config()
    if not url:
        return False, "sin imagen de la fuente"
    partes = urlparse(url)
    dominio = (partes.netloc or "").lower()
    if any(stock in dominio for stock in config["dominios_stock"]):
        return False, f"banco de imágenes de stock ({dominio})"
    archivo = (partes.path.rsplit("/", 1)[-1] or "").lower()
    nombre = re.sub(r"\.[a-z0-9]+$", "", archivo)
    if any(nombre.startswith(p) for p in config["prefijos_genericos"]):
        return False, f"archivo genérico ({archivo})"
    if usos_en_otras_noticias > config["maximo_otras_noticias_con_misma_imagen"]:
        return False, f"foto de archivo reutilizada en {usos_en_otras_noticias} notas distintas"
    return True, "foto de la nota en la fuente"
