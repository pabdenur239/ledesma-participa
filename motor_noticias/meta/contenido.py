import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..atribucion import atribucion, titulo_publico
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




# CTA breve y variable (Etapa 1): nunca siempre el mismo. Se elige de forma
# determinística por id de noticia para que un reintento produzca
# exactamente el mismo texto.
CTAS = (
    "Más información en Ledesma Participa.",
    "Seguimos actualizando esta noticia.",
    "Seguí Ledesma Participa para enterarte de lo que pasa en tu ciudad.",
    "Leé la nota completa en ledesmaparticipa.com.ar.",
)
MAXIMO_PARRAFOS = 4
MAXIMO_CARACTERES_CUERPO = 1100

ETIQUETAS_TERRITORIO_COPY = {
    "libertador": "LIBERTADOR",
    "ledesma": "DEPARTAMENTO LEDESMA",
    "jujuy": "JUJUY",
    "nacional": "NACIONAL",
    "internacional": "INTERNACIONAL",
}

_RE_URL = re.compile(r"https?://\S+")
_RE_LINEA_FUENTE = re.compile(r"(?im)^\s*fuente(?:\s+y\s+nota\s+completa)?\s*:.*$")
_RE_ORACION = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡\"“0-9])")


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
    return titulo_publico(noticia, titulo), texto


def parrafos_copy(texto: str) -> List[str]:
    """Párrafos del cuerpo (1: qué ocurrió y dónde; 2: dato principal o
    consecuencia; 3: estado actual / qué sigue; 4 solo si aporta). Se arman
    con oraciones COMPLETAS del texto ya redactado — nunca se corta una
    oración ni se inventa nada; las líneas "Fuente:" y las URLs del texto
    se quitan (la fuente va aparte, al final)."""
    limpio = _RE_LINEA_FUENTE.sub("", texto or "")
    limpio = _RE_URL.sub("", limpio)
    oraciones = [o.strip() for o in _RE_ORACION.split(re.sub(r"\s+", " ", limpio).strip()) if o.strip()]
    parrafos: List[str] = []
    total = 0
    for oracion in oraciones:
        if total + len(oracion) > MAXIMO_CARACTERES_CUERPO and parrafos:
            break
        if len(parrafos) < MAXIMO_PARRAFOS:
            parrafos.append(oracion)
        else:
            parrafos[-1] = f"{parrafos[-1]} {oracion}"
        total += len(oracion)
    return parrafos


def etiqueta_territorio_copy(noticia: dict) -> Optional[str]:
    from ..clasificacion import clasificar_territorio_publico

    return ETIQUETAS_TERRITORIO_COPY.get(clasificar_territorio_publico(noticia)["valor"] or "")


def encabezado_copy(noticia: dict, titulo: str, urgente: bool = False) -> str:
    """[TERRITORIO] | TITULAR EN MAYÚSCULAS (URGENTE adelante si corresponde)."""
    partes = []
    if urgente:
        partes.append("URGENTE")
    territorio = etiqueta_territorio_copy(noticia)
    if territorio:
        partes.append(territorio)
    partes.append(titulo.strip().upper())
    return " | ".join(partes)


def cta_para(noticia: dict, hay_nota_propia: bool = True) -> str:
    """CTA variable; si la nota propia todavía no está publicada en
    ledesmaparticipa.com.ar, nunca uno que remita a ella."""
    opciones = CTAS if hay_nota_propia else tuple(c for c in CTAS if "ledesmaparticipa.com.ar" not in c)
    return opciones[(noticia.get("id") or 0) % len(opciones)]


def _cuerpo_publicacion(noticia: dict, incluir_enlace: bool, urgente: bool = False) -> str:
    from ..sitio.urls import url_nota_propia

    titulo, texto = _titulo_y_texto_finales(noticia)
    partes = [encabezado_copy(noticia, titulo, urgente)]
    partes.extend(parrafos_copy(texto))
    autoria = atribucion(noticia)
    propia = url_nota_propia(noticia)
    cierre = []
    if autoria.fuente:
        cierre.append(f"Fuente: {autoria.etiqueta}")
    cierre.append(cta_para(noticia, hay_nota_propia=propia is not None))
    if incluir_enlace:
        if propia:
            cierre.append(propia)
        elif autoria.url:
            # Sin nota propia todavía: se mantiene el enlace verificable a
            # la nota original (atribución), nunca se omite la fuente.
            cierre.append(f"Nota original: {autoria.url}")
    partes.append("\n".join(cierre))
    return "\n\n".join(p for p in partes if p)


def generar_contenido_facebook(
    noticia: dict,
    incluir_menciones: Optional[bool] = None,
    menciones: Optional[List[str]] = None,
    config: Optional[dict] = None,
    urgente: bool = False,
) -> ContenidoFacebook:
    """Copy de Facebook con el formato de la Etapa 1 (9/10/2026), armado
    solo a partir de información ya validada de la noticia (sin IA):

        [TERRITORIO] | TITULAR EN MAYÚSCULAS
        párrafos 1–3 (4 solo si aporta), con oraciones completas
        Fuente: [fuente]
        CTA breve y variable
        enlace a la nota propia en ledesmaparticipa.com.ar (o, si todavía
        no existe, a la nota original)
        hashtags (a lo sumo dos)

    Autosuficiente: nunca usa ni promete un primer comentario
    (`primer_comentario` queda vacío)."""
    config = config or _cargar_config()
    if incluir_menciones is None:
        incluir_menciones = config["menciones_habilitadas_por_defecto"]
    menciones_activas = list(menciones) if (incluir_menciones and menciones) else []
    hashtags = generar_hashtags(noticia.get("localidad"), config)

    partes = [_cuerpo_publicacion(noticia, incluir_enlace=True, urgente=urgente)]
    if menciones_activas:
        partes.append(" ".join(menciones_activas))
    partes.append(" ".join(hashtags))
    return ContenidoFacebook(
        post_principal="\n\n".join(partes),
        primer_comentario="",
        hashtags=hashtags,
        imagen_url=None,
        menciones=menciones_activas,
    )


def generar_caption_instagram(noticia: dict, config: Optional[dict] = None, urgente: bool = False) -> str:
    """Mismo formato que Facebook. Instagram no hace clickeables los
    enlaces del caption: en vez de la URL va el CTA hacia
    ledesmaparticipa.com.ar."""
    config = config or _cargar_config()
    hashtags = generar_hashtags(noticia.get("localidad"), config)
    return "\n\n".join([_cuerpo_publicacion(noticia, incluir_enlace=False, urgente=urgente), " ".join(hashtags)])
