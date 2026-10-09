"""Datos estructurados del informe de la mañana CLIMA + DÓLAR (Etapa 1,
9/10/2026): los guarda `informe_diario` al generarlo y los leen la placa
(`meta/identidad_visual.generar_pieza_clima_dolar`), el módulo de la
portada web y `api/clima_dolar.json` de la app. Un dato que la fuente no
entregó queda en null ("No disponible"), nunca inventado."""
import json
from pathlib import Path
from typing import Optional

DIRECTORIO_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "informe_diario"
PREFIJO_URL = "https://ledesma-participa.local/informe-diario/"


def guardar_datos(datos: dict, directorio: Optional[Path] = None) -> Path:
    directorio = Path(directorio or DIRECTORIO_DEFAULT)
    directorio.mkdir(parents=True, exist_ok=True)
    ruta = directorio / f"{datos['fecha']}.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def leer_datos(fecha: str, directorio: Optional[Path] = None) -> Optional[dict]:
    ruta = Path(directorio or DIRECTORIO_DEFAULT) / f"{fecha}.json"
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def datos_informe_de_noticia(noticia: dict, directorio: Optional[Path] = None) -> Optional[dict]:
    """Datos del informe si `noticia` es un informe diario con datos
    guardados; None en cualquier otro caso."""
    url = noticia.get("url_normalizada") or noticia.get("url_fuente") or ""
    if not url.startswith(PREFIJO_URL):
        return None
    return leer_datos(url[len(PREFIJO_URL):][:10], directorio)
