import re
import unicodedata
from typing import Optional
from urllib.parse import urlparse

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


def _contiene_alguna_palabra(texto_norm: str, terminos: list) -> Optional[str]:
    """Como `_contiene_alguna`, pero exige límites de palabra: evita falsos
    positivos de subcadena (p.ej. que 'Nación' matchee dentro de
    'combinación'). Se usa para los marcadores nacionales/internacionales,
    que son términos más cortos y genéricos que las localidades."""
    for termino in terminos:
        patron = r"\b" + re.escape(_sin_acentos(termino)) + r"\b"
        if re.search(patron, texto_norm):
            return termino
    return None


def _primer_segmento_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    segmentos = [s for s in urlparse(url).path.split("/") if s]
    return segmentos[0] if segmentos else None


def _es_medio_nacional(nombre_fuente: Optional[str], config: dict) -> bool:
    if not nombre_fuente:
        return False
    medios = {_sin_acentos(m) for m in config.get("medios_nacionales", [])}
    return _sin_acentos(nombre_fuente) in medios


def _evidencia_internacional(
    contenido_norm: str, categoria: Optional[str], url: Optional[str], config: dict
) -> Optional[str]:
    """Evidencia determinística de que el contenido es de alcance
    internacional (no argentino): mención explícita de país/región
    extranjera en el texto, o sección/categoría/URL correspondiente a
    cobertura internacional."""
    termino = _contiene_alguna_palabra(contenido_norm, config.get("internacional", []))
    if termino:
        return f"menciona '{termino}'"

    secciones = {_sin_acentos(s) for s in config.get("secciones_internacionales", [])}

    segmento = _primer_segmento_url(url)
    if segmento and _sin_acentos(segmento) in secciones:
        return f"sección de URL '{segmento}'"

    if categoria and _sin_acentos(categoria) in secciones:
        return f"categoría '{categoria}'"

    return None


def _seccion_ambigua(categoria: Optional[str], url: Optional[str], config: dict) -> Optional[str]:
    """Secciones como deportes/espectáculos suelen incluir contenido
    extranjero (clubes, selecciones, figuras de otros países) sin que el
    texto mencione un país reconocible en `config["internacional"]`. Para
    esas secciones el fallback nacional (paso C) no alcanza por sí solo:
    se exige evidencia explícita (marcador nacional del paso A) en vez de
    asumir alcance argentino por defecto."""
    ambiguas = {_sin_acentos(s) for s in config.get("secciones_ambiguas", [])}

    segmento = _primer_segmento_url(url)
    if segmento and _sin_acentos(segmento) in ambiguas:
        return f"sección de URL '{segmento}'"

    if categoria and _sin_acentos(categoria) in ambiguas:
        return f"categoría '{categoria}'"

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
    nombre_fuente: Optional[str] = None,
    url: Optional[str] = None,
    categoria: Optional[str] = None,
) -> dict:
    """Clasificación territorial determinística (sin IA) en cinco niveles:
    local, departamental, provincial, nacional, sin_clasificar.

    Reutiliza `clasificar_relevancia` sin modificarla: `relevancia_local`
    sigue significando exactamente lo mismo que hoy (relación directa con
    Libertador o el Departamento Ledesma). La clasificación territorial es
    una capa nueva encima de ese resultado, que además reconoce el nivel
    provincial (mención de Jujuy sin relación local) y el nacional, en dos
    pasos: (1) marcadores nacionales explícitos en el contenido (config
    `localidades.json` → "nacional"); (2) para medios configurados como
    nacionales (`config["medios_nacionales"]`, p.ej. La Nación e Infobae),
    un fallback que asume alcance nacional cuando no hay evidencia de
    contenido internacional (`config["internacional"]` /
    `config["secciones_internacionales"]`, evaluada sobre título+texto,
    `categoria` y el primer segmento de `url`). Nunca se asigna "nacional"
    solo por el nombre de la fuente: siempre requiere ausencia de evidencia
    internacional. Todo queda auditable en el `motivo_territorio`
    devuelto."""
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

    termino_nacional = _contiene_alguna_palabra(contenido_norm, config.get("nacional", []))
    if termino_nacional:
        return {
            "territorio": "nacional",
            "motivo_territorio": f"Menciona '{termino_nacional}' (alcance nacional).",
            "relevante": resultado_relevancia["relevante"],
            "motivo_relevancia": resultado_relevancia["motivo"],
            "localidad": resultado_relevancia["localidad"],
        }

    motivo_sin_clasificar = (
        "Sin relación identificable con Libertador General San Martín, el "
        "Departamento Ledesma, la provincia de Jujuy ni referencias nacionales explícitas."
    )

    if _es_medio_nacional(nombre_fuente, config):
        evidencia_internacional = _evidencia_internacional(contenido_norm, categoria, url, config)
        seccion_ambigua = None if evidencia_internacional else _seccion_ambigua(categoria, url, config)

        if not evidencia_internacional and not seccion_ambigua:
            return {
                "territorio": "nacional",
                "motivo_territorio": (
                    f"Medio nacional configurado ('{nombre_fuente}'), sin evidencia de contenido "
                    "internacional y sin clasificación local/departamental/provincial: se asume "
                    "sección argentina/general del medio."
                ),
                "relevante": resultado_relevancia["relevante"],
                "motivo_relevancia": resultado_relevancia["motivo"],
                "localidad": resultado_relevancia["localidad"],
            }
        if evidencia_internacional:
            motivo_sin_clasificar = (
                f"Medio nacional configurado ('{nombre_fuente}'), pero con evidencia de contenido "
                f"internacional ({evidencia_internacional}) sin impacto argentino explícito."
            )
        else:
            motivo_sin_clasificar = (
                f"Medio nacional configurado ('{nombre_fuente}'), pero la sección es ambigua "
                f"({seccion_ambigua}, propensa a contenido extranjero) y no hay ningún marcador "
                "nacional explícito en el contenido."
            )

    return {
        "territorio": "sin_clasificar",
        "motivo_territorio": motivo_sin_clasificar,
        "relevante": resultado_relevancia["relevante"],
        "motivo_relevancia": resultado_relevancia["motivo"],
        "localidad": resultado_relevancia["localidad"],
    }
