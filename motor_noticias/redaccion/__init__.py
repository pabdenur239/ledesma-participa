from .base import Redactor
from .mock import RedactorMock
from .ollama import RedactorOllama

REDACTORES_DISPONIBLES = ("mock", "ollama")
REDACTOR_DEFAULT = "mock"


def crear_redactor(nombre: str = REDACTOR_DEFAULT) -> Redactor:
    """Único punto de selección del redactor ('mock' o 'ollama'), reutilizado
    tal cual por la ejecución manual (`cli.py`), el Motor Continuo
    (`continuo_runner.py`) y el panel (`panel/server.py`, carga manual
    incluida) — para que una noticia automática y una manual usen siempre
    exactamente el mismo redactor configurado, nunca circuitos distintos."""
    return RedactorOllama() if nombre == "ollama" else RedactorMock()
