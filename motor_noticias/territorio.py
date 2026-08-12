import unicodedata
from typing import Optional

from .relevancia import cargar_config as cargar_config_localidades
from .relevancia import clasificar_relevancia

TERRITORIOS = ("local", "departamental", "provincial", "nacional", "sin_clasificar")


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def _contiene_alguna(texto_norm: str, terminos: list) -> Optional[str]:
    for termino in terminos:
        if _sin_acentos(termino) in texto_norm:
            return termino
    return None


def _nivel_desde_termino(termino: Optional[str], config: dict) -> Optional[str]:
    if termino is None:
        return None
    if termino in config.get("maxima_prioridad", []):
        return "local"
    if termino in config.get("prioridad_alta", []):
        return "departamental"
    if termino in config.get("jujuy", []):
        return "provincial"
    return None


def clasificar_territorio(
    titulo: str,
    texto: str,
    localidad_fuente: Optional[str] = None,
    config: Optional[dict] = None,
) -> dict:
    """Clasificación territorial determinística (sin IA) en cinco niveles:
    local, departamental, provincial, nacional, sin_clasificar.

    Reutiliza `clasificar_relevancia` sin modificarla: `relevancia_local`
    sigue significando exactamente lo mismo que hoy (relación directa con
    Libertador o el Departamento Ledesma). La clasificación territorial es
    una capa nueva encima de ese resultado, que además reconoce el nivel
    provincial (mención de Jujuy sin relación local) y agrega un nivel
    nacional explícito (config `localidades.json` → "nacional"), auditable
    mediante el motivo devuelto en cada caso."""
    config = config or cargar_config_localidades()

    resultado_relevancia = clasificar_relevancia(titulo, texto, localidad=localidad_fuente, config=config)
    nivel = _nivel_desde_termino(resultado_relevancia["localidad"], config)

    if nivel:
        return {
            "territorio": nivel,
            "motivo_territorio": resultado_relevancia["motivo"],
            "relevante": resultado_relevancia["relevante"],
            "motivo_relevancia": resultado_relevancia["motivo"],
            "localidad": resultado_relevancia["localidad"],
        }

    contenido_norm = _sin_acentos(f"{titulo} {texto}")
    termino_nacional = _contiene_alguna(contenido_norm, config.get("nacional", []))
    if termino_nacional:
        return {
            "territorio": "nacional",
            "motivo_territorio": f"Menciona '{termino_nacional}' (alcance nacional).",
            "relevante": resultado_relevancia["relevante"],
            "motivo_relevancia": resultado_relevancia["motivo"],
            "localidad": resultado_relevancia["localidad"],
        }

    return {
        "territorio": "sin_clasificar",
        "motivo_territorio": (
            "Sin relación identificable con Libertador General San Martín, el "
            "Departamento Ledesma, la provincia de Jujuy ni referencias nacionales explícitas."
        ),
        "relevante": resultado_relevancia["relevante"],
        "motivo_relevancia": resultado_relevancia["motivo"],
        "localidad": resultado_relevancia["localidad"],
    }
