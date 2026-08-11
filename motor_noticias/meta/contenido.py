import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..relevancia import cargar_config as cargar_config_localidades

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "meta.json"


def _cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def _contiene_alguna(texto_norm: str, terminos: list) -> bool:
    return any(_sin_acentos(termino) in texto_norm for termino in terminos)


@dataclass
class ContenidoFacebook:
    post_principal: str
    primer_comentario: str
    hashtags: List[str]
    imagen_url: Optional[str] = None
    imagen_generada_automaticamente: bool = False
    menciones: List[str] = field(default_factory=list)


def generar_hashtags(localidad: Optional[str], config: Optional[dict] = None) -> List[str]:
    """Genera hashtags de forma simple y determinística (sin IA): la base
    fija más, a lo sumo, un hashtag según la categoría geográfica de la
    localidad, para no producir listas excesivas."""
    config = config or _cargar_config()
    hashtags = [config["hashtag_base"]]
    if not localidad:
        return hashtags

    localidad_norm = _sin_acentos(localidad)
    config_localidades = cargar_config_localidades()
    hashtags_por_categoria = config["hashtags_por_categoria_localidad"]

    for categoria in ("maxima_prioridad", "prioridad_alta", "jujuy"):
        if _contiene_alguna(localidad_norm, config_localidades[categoria]):
            hashtags.append(hashtags_por_categoria[categoria])
            break

    return hashtags


def _resena_breve(texto: str, longitud_maxima: int) -> str:
    texto = texto.strip()
    if len(texto) <= longitud_maxima:
        return texto
    recorte = texto[:longitud_maxima]
    ultimo_espacio = recorte.rfind(" ")
    if ultimo_espacio > 0:
        recorte = recorte[:ultimo_espacio]
    return recorte.rstrip(",.;: ") + "…"


def _titulo_y_texto_finales(noticia: dict):
    titulo = noticia.get("titulo_revisado") or noticia.get("titulo_preparado") or ""
    texto = noticia.get("texto_revisado") or noticia.get("texto_preparado") or ""
    return titulo, texto


def generar_contenido_facebook(
    noticia: dict,
    incluir_menciones: Optional[bool] = None,
    menciones: Optional[List[str]] = None,
    config: Optional[dict] = None,
) -> ContenidoFacebook:
    """Genera el post principal y el primer comentario a partir de
    información ya validada de la noticia (titulo_revisado/texto_revisado,
    con fallback a titulo_preparado/texto_preparado). No vuelve a pedirle a
    ninguna IA que invente o amplíe hechos: es solo formateo editorial."""
    config = config or _cargar_config()
    titulo, texto = _titulo_y_texto_finales(noticia)
    reseña = _resena_breve(texto, config["longitud_maxima_resena"])

    post_principal = f"{titulo}\n\n{reseña}\n\n{config['cierre_post_principal']}"

    if incluir_menciones is None:
        incluir_menciones = config["menciones_habilitadas_por_defecto"]
    menciones_activas = list(menciones) if (incluir_menciones and menciones) else []

    hashtags = generar_hashtags(noticia.get("localidad"), config)

    partes_comentario = [texto]
    fuente = (noticia.get("nombre_fuente") or "").strip()
    if fuente:
        partes_comentario.append(f"Fuente: {fuente}")
    if menciones_activas:
        partes_comentario.append(" ".join(menciones_activas))
    partes_comentario.append(" ".join(hashtags))

    primer_comentario = "\n\n".join(partes_comentario)

    return ContenidoFacebook(
        post_principal=post_principal,
        primer_comentario=primer_comentario,
        hashtags=hashtags,
        imagen_url=None,
        menciones=menciones_activas,
    )
