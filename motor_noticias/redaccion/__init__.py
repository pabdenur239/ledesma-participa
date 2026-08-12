from pathlib import Path
from typing import Optional

from .base import Redactor
from .mock import RedactorMock
from .ollama import RedactorOllama
from .ollama import _cargar_config as _cargar_config_redaccion

REDACTORES_DISPONIBLES = ("mock", "ollama")
# Fallback solo si config/redaccion.json falta o no trae "proveedor" — nunca
# lo que se espera que ocurra en un checkout ya configurado (ver esa clave).
# Nunca se hace red por accidente: mock es la opción segura por defecto.
PROVEEDOR_DEFAULT = "mock"


class ErrorConfiguracionRedactor(ValueError):
    """Valor de redactor inválido, ya sea del flag --redactor o de
    config/redaccion.json → "proveedor"."""


def _proveedor_configurado(config_path: Optional[Path] = None) -> str:
    config = _cargar_config_redaccion(config_path)
    return config.get("proveedor") or PROVEEDOR_DEFAULT


def crear_redactor(nombre: Optional[str] = None, config_path: Optional[Path] = None) -> Redactor:
    """Único punto de selección y configuración del redactor para todo el
    proyecto — reutilizado tal cual por la ejecución manual (`run.py` /
    `cli.py`), el Motor Continuo (`run_continuo.py` / `continuo_runner.py`)
    y el panel (`run_panel.py` / `panel/server.py`, carga manual incluida).

    Precedencia:
    1. `nombre` explícito (el flag `--redactor mock|ollama` de cada entry
       point, pensado como override puntual para pruebas/diagnóstico);
    2. si no se pasó nada, `config/redaccion.json` → "proveedor" (la MISMA
       configuración persistente para los tres procesos — no se duplica en
       ningún otro archivo);
    3. se valida el valor resuelto contra `REDACTORES_DISPONIBLES`;
    4. se instancia el redactor correspondiente.

    Nunca cambia de motor silenciosamente: si el proveedor configurado es
    "ollama", siempre se instancia `RedactorOllama` (que ya maneja sus
    propios errores en tiempo de redacción sin caer a mock — ver
    `redaccion/ollama.py`). Instanciar `RedactorOllama` aquí solo lee el
    archivo de configuración; no abre ninguna conexión de red (eso ocurre
    recién dentro de `.redactar()`)."""
    if nombre is None:
        nombre = _proveedor_configurado(config_path)

    if nombre not in REDACTORES_DISPONIBLES:
        raise ErrorConfiguracionRedactor(
            f"Redactor '{nombre}' inválido. Opciones válidas: {', '.join(REDACTORES_DISPONIBLES)}."
        )

    return RedactorOllama(config_path=config_path) if nombre == "ollama" else RedactorMock()
