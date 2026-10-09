"""Taxonomía única de presentación para web y app (2/10/2026, rehecha en
la Etapa 1 el 9/10/2026).

Tres dimensiones distintas, nunca mezcladas (ver `motor_noticias/clasificacion.py`,
que las reúne):

- TERRITORIO (dónde): Libertador, Departamento Ledesma, Jujuy, Nacional,
  Internacional, con confianza propia. Sale de
  `territorio.clasificar_territorio` y se recalcula al presentar con la
  clasificación vigente, así una nota guardada con un territorio erróneo
  por una versión anterior no aparece en la sección equivocada.
- CATEGORÍA (de qué): Policiales, Salud, Deportes, Gastronomía,
  Espectáculos, Política, Servicios, Economía, Educación, Cultura o General
  / Últimas, por TEMA PRINCIPAL con confianza (`clasificar_categoria`,
  reglas en `config/categorias.json`), nunca por una palabra aislada.
- URGENTE: no es categoría; lo decide el scoring editorial único
  (`scoring_editorial.urgente_confirmado`).

No se fabrica contenido para llenar categorías: si no hay notas de una
categoría, la categoría queda vacía y no se muestra.
"""
import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import FrozenSet, Optional, Tuple
from urllib.parse import urlparse

from .models import OrigenIngreso
from .relevancia import cargar_config as cargar_localidades
from .territorio import _fuente_regional, clasificar_territorio

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "categorias.json"

TEMATICAS = (
    "policiales", "salud", "deportes", "gastronomia", "espectaculos",
    "politica", "servicios", "economia", "educacion", "cultura",
)
CATEGORIA_GENERAL = "general"

# Territorios que no se recalculan: no salen de un texto clasificable
# (publicación institucional, informe diario, resumen) o los fijó una fuente
# 100% local (collector municipal).
ORIGENES_TERRITORIO_FIJO = (OrigenIngreso.INSTITUCIONAL.value, OrigenIngreso.RESUMEN_DIARIO.value)


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


@lru_cache(maxsize=2)
def _config_cacheada(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cargar_config(path: Optional[Path] = None) -> dict:
    return _config_cacheada(str(path or CONFIG_PATH_DEFAULT))


@lru_cache(maxsize=4096)
def _patron(termino: str) -> "re.Pattern":
    termino = _sin_acentos(termino).strip()
    raiz = termino.endswith("*")
    termino = termino.rstrip("*")
    return re.compile(r"\b" + re.escape(termino) + ("" if raiz else r"\b"))


def territorio_vigente(noticia: dict) -> Optional[str]:
    """Territorio con la clasificación vigente (ver docstring del módulo)."""
    return territorio_vigente_con_confianza(noticia)[0]


def territorio_vigente_con_confianza(noticia: dict) -> Tuple[Optional[str], float]:
    """(territorio, confianza) con la clasificación vigente. Los
    territorios fijados por el origen (institucional, informe diario,
    resumen) tienen confianza 1.0."""
    guardado = noticia.get("territorio")
    if noticia.get("origen_ingreso") in ORIGENES_TERRITORIO_FIJO or guardado == "institucional":
        return guardado, 1.0
    if (noticia.get("url_normalizada") or "").startswith("https://ledesma-participa.local/informe-diario/"):
        return guardado, 1.0
    nombre = noticia.get("nombre_fuente") or ""
    localidad_fuente = noticia.get("localidad") if nombre.lower().startswith("municipalidad") else None
    resultado = clasificar_territorio(
        noticia.get("titulo_original") or "",
        noticia.get("texto_original") or "",
        localidad_fuente=localidad_fuente,
        nombre_fuente=nombre,
        url=noticia.get("url_fuente"),
        categoria=noticia.get("categoria_tematica"),
    )
    nuevo = resultado["territorio"]
    # Una reelaboración propia hereda el territorio de la nota del medio;
    # si el texto reescrito ya no permite clasificarlo, se conserva. Para
    # el resto, el territorio guardado por una versión anterior no se reusa
    # (podía ser justamente el error que se corrige).
    if nuevo == "sin_clasificar" and guardado not in (None, "sin_clasificar"):
        local_dudoso = guardado in ("local", "departamental") and not _fuente_regional(nombre, cargar_localidades())
        propia = noticia.get("origen_ingreso") in (OrigenIngreso.CONTENIDO_PROPIO.value, OrigenIngreso.MANUAL.value)
        if propia or not local_dudoso:
            # Heredado de una clasificación anterior: confianza moderada.
            return guardado, 0.7
    return nuevo, resultado.get("confianza", 0.0)


def _coincidencias(terminos, texto: str, excluir: frozenset = frozenset()) -> frozenset:
    """Palabras/frases DISTINTAS del texto que coinciden con algún término
    (una misma palabra cuenta una sola vez aunque la detecten dos términos,
    p. ej. "vacunación" con "vacuna*" y "vacunacion"; y una palabra ya
    contada en el título no vuelve a sumar en el cuerpo)."""
    tramos = []
    for termino in set(terminos):
        for m in _patron(termino).finditer(texto):
            tramos.append((m.start(), m.end()))
    tramos.sort()
    palabras = set()
    fin_anterior = -1
    for inicio, fin in tramos:
        if inicio < fin_anterior:  # solapado con el anterior: misma palabra
            fin_anterior = max(fin_anterior, fin)
            continue
        fin_anterior = fin
        # La palabra completa (sin el sufijo cortado por una raíz).
        fin_palabra = fin
        while fin_palabra < len(texto) and texto[fin_palabra].isalnum():
            fin_palabra += 1
        palabras.add(texto[inicio:fin_palabra])
    return frozenset(palabras - set(excluir))


def _evidencia(categoria: dict, pesos: dict, titulo: str, cuerpo: str, segmentos: list, categoria_fuente) -> float:
    """Puntaje de UNA categoría para una nota (ver `config/categorias.json`)."""
    if any(_patron(t).search(titulo) for t in categoria.get("excluir_titulo", [])):
        return 0.0
    fuertes_titulo = _coincidencias(categoria["fuertes"], titulo)
    fuertes_cuerpo = _coincidencias(categoria["fuertes"], cuerpo, excluir=fuertes_titulo)
    puntaje = pesos["titulo_fuerte"] * min(len(fuertes_titulo), pesos["maximo_terminos_titulo"])
    puntaje += pesos["cuerpo_fuerte"] * min(len(fuertes_cuerpo), pesos["maximo_terminos_cuerpo"])
    if any(seg in categoria.get("secciones_url", []) for seg in segmentos):
        puntaje += pesos["seccion_url"]
    if categoria_fuente and categoria_fuente in categoria.get("fuentes", []):
        puntaje += pesos["fuente"]
    # Palabras débiles ("partido", "hospital", "asado"…): solo confirman una
    # categoría que ya tiene evidencia fuerte en el texto, nunca la deciden.
    if fuertes_titulo or fuertes_cuerpo:
        debiles_titulo = _coincidencias(categoria.get("debiles", []), titulo, excluir=fuertes_titulo)
        debiles_cuerpo = _coincidencias(categoria.get("debiles", []), cuerpo, excluir=fuertes_cuerpo | debiles_titulo)
        puntaje += min(
            pesos["titulo_debil"] * len(debiles_titulo) + pesos["cuerpo_debil"] * len(debiles_cuerpo),
            pesos["maximo_debiles"],
        )
    return puntaje


def resolver_categoria(candidata: Optional[str], confianza: float, config: Optional[dict] = None) -> Optional[str]:
    """Regla de umbrales: > umbral_automatico (0.85) asigna la categoría;
    entre umbral_general (0.50) y 0.85 la nota va a General / Últimas; por
    debajo no tiene categoría temática (no aparece en grillas temáticas,
    sí en su territorio y en el listado general de últimas)."""
    config = config or cargar_config()
    if candidata and confianza > config["umbral_automatico"]:
        return candidata
    if confianza >= config["umbral_general"]:
        return CATEGORIA_GENERAL
    return None


def clasificar_categoria(noticia: dict, config: Optional[dict] = None) -> dict:
    """Categoría temática por TEMA PRINCIPAL (Etapa 1, 9/10/2026): cada
    categoría suma evidencia (título, sección de la URL, temática de la
    fuente, bajada) y gana la de mayor puntaje; la confianza baja cuando
    otra categoría compite de cerca. Devuelve {valor, etiqueta, confianza,
    candidata, puntajes}. `valor` puede ser una categoría, "general" o None
    (ver `resolver_categoria`)."""
    config = config or cargar_config()
    url_informe = (noticia.get("url_normalizada") or noticia.get("url_fuente") or "")
    if url_informe.startswith("https://ledesma-participa.local/informe-diario/"):
        return _categoria("servicios", 1.0, "servicios", {}, config)
    if noticia.get("origen_ingreso") in ORIGENES_TERRITORIO_FIJO or noticia.get("territorio") == "institucional":
        return _categoria(None, 0.0, None, {}, config)

    titulo = _sin_acentos(
        " ".join(noticia.get(c) or "" for c in ("titulo_revisado", "titulo_preparado", "titulo_original"))
    )
    cuerpo = _sin_acentos((noticia.get("texto_original") or "")[: config["pesos"]["largo_cuerpo"]])
    segmentos = [_sin_acentos(s) for s in urlparse(noticia.get("url_fuente") or "").path.split("/") if s]
    puntajes = {
        nombre: _evidencia(cat, config["pesos"], titulo, cuerpo, segmentos, noticia.get("categoria_tematica"))
        for nombre, cat in config["categorias"].items()
    }
    ordenados = sorted(puntajes.items(), key=lambda par: par[1], reverse=True)
    candidata, mejor = ordenados[0]
    segundo = ordenados[1][1] if len(ordenados) > 1 else 0.0
    if mejor <= 0:
        return _categoria(None, 0.0, None, puntajes, config)
    confianza = 1 - math.exp(-mejor / config["escala_confianza"])
    # Competencia: una segunda categoría cercana baja la confianza; una
    # mención secundaria lejana casi no la afecta (proporción al cuadrado).
    confianza *= 1 - config["penalizacion_competencia"] * (segundo / mejor) ** 2
    confianza = round(confianza, 2)
    return _categoria(resolver_categoria(candidata, confianza, config), confianza, candidata, puntajes, config)


def _categoria(valor, confianza, candidata, puntajes, config) -> dict:
    return {
        "valor": valor,
        "etiqueta": config["etiquetas"].get(valor) if valor else None,
        "confianza": confianza,
        "candidata": candidata,
        "puntajes": puntajes,
    }


def tematicas(noticia: dict, config: Optional[dict] = None) -> FrozenSet[str]:
    """Compatibilidad: conjunto con la categoría temática asignada
    automáticamente (confianza > 0.85), vacío si la nota quedó en General
    o sin categoría."""
    valor = clasificar_categoria(noticia, config)["valor"]
    return frozenset([valor]) if valor in TEMATICAS else frozenset()


SECCION_TERRITORIAL = {
    "local": ("libertador", "Libertador Gral. San Martín"),
    "departamental": ("ledesma", "Departamento Ledesma"),
    "provincial": ("jujuy", "Jujuy"),
    "nacional": ("nacionales", "Nacionales"),
    "internacional": ("internacionales", "Internacionales"),
}

ETIQUETAS_TEMATICAS = {slug: cargar_config()["etiquetas"][slug] for slug in TEMATICAS + (CATEGORIA_GENERAL,)}
