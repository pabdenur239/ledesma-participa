"""Deduplicación por ACONTECIMIENTO (agregado 2/10/2026).

La deduplicación por URL/hash/palabras del título (`dedupe.py`) no alcanza
cuando varios medios cuentan el mismo hecho con títulos distintos. Casos
reales que se publicaron dos o tres veces:

- "Jujuy: se busca a Anahí Carmen Bargas" (Jujuy al día) y "Buscan a dos
  personas desaparecidas" (El Tribuno): mismo pedido del CINDAC.
- "Jujuy: una pelea terminó con un hombre baleado…", "La terrible historia
  de 'Pato'…" y "Detuvieron a un hombre por balear a un vecino en
  Libertador": distintas etapas del mismo hecho.
- "Artistas jujeños restauran el Cristo Redentor de Valle Grande" y
  "Restauraron al Cristo Redentor de Valle Grande".

Cada noticia tiene una firma (personas, alias, tipo de hecho, etapa,
lugares, palabras clave, momento). Dos noticias son el mismo acontecimiento
si comparten una persona/alias, o si son del mismo tipo en el mismo lugar
con palabras clave en común (o, para tipos de hecho poco frecuentes —un
balazo, una búsqueda de persona—, en el mismo lugar y dentro de la ventana).

Una ACTUALIZACIÓN real (la persona apareció, hubo una detención, la alerta
cambió de nivel) no se bloquea: se publica identificada como evolución del
acontecimiento (`actualizacion_de`), nunca como noticia independiente.

Determinístico, sin IA. Términos en `config/eventos.json`.
"""
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

from .dedupe import PALABRAS_VACIAS_ES
from .fechas import momento_vigencia

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "eventos.json"
VENTANA_EVENTO_HORAS = 72


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


def _menciona(texto_norm: str, terminos: Iterable[str]) -> bool:
    return any(_patron(t).search(texto_norm) for t in terminos)


class Firma(NamedTuple):
    personas: frozenset  # cada persona = frozenset de tokens normalizados del nombre
    alias: frozenset
    tipo: Optional[str]
    etapa: int
    lugares: frozenset
    claves: frozenset
    momento: Optional[datetime]


_RE_NOMBRE_PROPIO = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+(?:de\s+|del\s+|de\s+la\s+)?[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3})\b"
)
_RE_ALIAS = re.compile(r"[\"“”'‘’«]([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,15})[\"“”'‘’»]")


def _personas(texto: str, config: dict) -> frozenset:
    """Nombres propios de 2+ palabras capitalizadas que no son
    instituciones ni lugares ("Anahí Carmen Bargas", "Franco Benjamín
    Santos"). Las mayúsculas del texto original son necesarias."""
    no_persona = {_sin_acentos(t) for t in config["palabras_no_persona"]}
    lugares = {_sin_acentos(l) for l in config["lugares"]}
    personas = set()
    for match in _RE_NOMBRE_PROPIO.finditer(texto or ""):
        tokens = [
            t for t in _sin_acentos(match.group(1)).split() if t not in ("de", "del", "la") and t not in no_persona
        ]
        if len(tokens) < 2 or " ".join(tokens) in lugares:
            continue
        personas.add(frozenset(tokens))
    return frozenset(personas)


def _alias(texto: str, config: dict) -> frozenset:
    no_persona = {_sin_acentos(t) for t in config["palabras_no_persona"]}
    return frozenset(
        a for a in (_sin_acentos(m.group(1)) for m in _RE_ALIAS.finditer(texto or ""))
        if a not in no_persona
    )


def _tipo_y_etapa(texto_norm: str, config: dict) -> tuple:
    """Tipo de hecho y etapa dentro de su evolución. Se elige la etapa más
    avanzada mencionada (una nota sobre la detención también nombra el
    balazo)."""
    for tipo, definicion in config["tipos"].items():
        etapas = definicion["etapas"]
        halladas = [i for i, terminos in enumerate(etapas) if _menciona(texto_norm, terminos)]
        if not halladas:
            continue
        # "detenido" o "imputado" solos no dicen qué hecho fue: el tipo se
        # asigna solo si aparece el hecho base (salvo tipos cuyas etapas
        # posteriores son inequívocas, como "apareció" en una búsqueda).
        if definicion.get("requiere_etapa_inicial", True) and 0 not in halladas:
            continue
        return tipo, max(halladas)
    return None, 0


def _lugares(texto_norm: str, config: dict) -> frozenset:
    lugares = {
        _sin_acentos(l) for l in config["lugares"] if _patron(l).search(texto_norm)
    }
    for barrio in re.findall(r"\bbarrio\s+([a-z0-9]+(?:\s+[a-z0-9]+){0,3})", texto_norm):
        lugares.add("barrio " + barrio.strip())
    return frozenset(lugares)


def _claves(texto_norm: str, config: dict) -> frozenset:
    excluir = PALABRAS_VACIAS_ES | {_sin_acentos(t) for t in config["palabras_genericas"]}
    return frozenset(
        t for t in re.findall(r"[a-z0-9]+", texto_norm) if len(t) >= 4 and t not in excluir
    )


def firma(noticia: dict, config: Optional[dict] = None) -> Firma:
    config = config or cargar_config()
    titulo = noticia.get("titulo_original") or ""
    texto = (noticia.get("texto_original") or "")[:600]
    crudo = f"{titulo}. {texto}"
    titulo_norm = _sin_acentos(titulo)
    crudo_norm = _sin_acentos(crudo)
    tipo, etapa = _tipo_y_etapa(crudo_norm, config)
    return Firma(
        personas=_personas(crudo, config),
        alias=_alias(crudo, config),
        tipo=tipo,
        etapa=etapa,
        lugares=_lugares(crudo_norm, config),
        claves=_claves(titulo_norm, config),
        momento=momento_vigencia(noticia),
    )


def _comparten_persona(a: Firma, b: Firma) -> bool:
    for pa in a.personas:
        for pb in b.personas:
            if len(pa & pb) >= 2:
                return True
    return bool(a.alias & b.alias)


def mismo_acontecimiento(a: Firma, b: Firma, config: Optional[dict] = None) -> bool:
    config = config or cargar_config()
    if a.momento and b.momento and abs(a.momento - b.momento) > timedelta(hours=VENTANA_EVENTO_HORAS):
        return False
    if a.tipo and b.tipo and a.tipo != b.tipo:
        return False
    if _comparten_persona(a, b):
        # Una figura pública (el gobernador, un fiscal) aparece en muchas
        # notas distintas: compartir el nombre solo alcanza si además es el
        # mismo tipo de hecho, o hay palabras clave del título en común.
        tokens_personas = frozenset().union(*a.personas, *b.personas) if (a.personas or b.personas) else frozenset()
        if (a.tipo and a.tipo == b.tipo) or len((a.claves & b.claves) - tokens_personas) >= 2:
            return True
    if not (a.tipo and a.tipo == b.tipo):
        return False
    lugares_comunes = a.lugares & b.lugares
    if not lugares_comunes:
        # Sin localidad específica en ninguna de las dos (p. ej. una campaña
        # provincial): hace falta más coincidencia de palabras del título.
        if not a.lugares and not b.lugares:
            return len(a.claves & b.claves) >= 3
        return False
    if config["tipos"][a.tipo].get("poco_frecuente"):
        # Dos búsquedas (o dos balazos) con personas identificadas y
        # ninguna en común son hechos distintos aunque sea el mismo lugar.
        if a.personas and b.personas:
            return False
        return True
    return len(a.claves & b.claves) >= 2


class Relacion(NamedTuple):
    relacionada: dict
    es_actualizacion: bool


def buscar_relacion(
    noticia: dict, anteriores: Iterable[dict], config: Optional[dict] = None, cache: Optional[dict] = None
) -> Optional[Relacion]:
    """Primera noticia de `anteriores` que sea el mismo acontecimiento que
    `noticia`. `es_actualizacion` es True si `noticia` está en una etapa
    más avanzada que TODAS las anteriores del mismo acontecimiento (p. ej.
    la persona buscada apareció, hubo una detención): entonces se puede
    publicar como evolución. Si no, es un duplicado."""
    config = config or cargar_config()
    cache = cache if cache is not None else {}

    def _firma(n: dict) -> Firma:
        clave = n.get("id")
        if clave is None:
            return firma(n, config)
        if clave not in cache:
            cache[clave] = firma(n, config)
        return cache[clave]

    propia = _firma(noticia)
    relacionadas = [
        n for n in anteriores
        if n.get("id") != noticia.get("id") and mismo_acontecimiento(propia, _firma(n), config)
    ]
    if not relacionadas:
        return None
    etapa_maxima = max(_firma(n).etapa for n in relacionadas)
    es_actualizacion = propia.tipo is not None and propia.etapa > etapa_maxima
    base = min(relacionadas, key=lambda n: n.get("id") or 0)
    return Relacion(base, es_actualizacion)


def ventana_desde(ahora_utc: datetime) -> str:
    return (ahora_utc.astimezone(timezone.utc) - timedelta(hours=VENTANA_EVENTO_HORAS)).isoformat()


def relacion_editorial(
    noticia: dict, anteriores: list, config: Optional[dict] = None, cache: Optional[dict] = None
) -> Optional[Relacion]:
    """Único criterio de "ya se publicó/agendó esto" para todos los
    circuitos (franjas, urgentes, gate de publicación → Facebook,
    Instagram, Stories y, por consecuencia, web y app): primero la misma
    nota (URL normalizada o huella de palabras del título, `dedupe.py`),
    después el mismo acontecimiento contado distinto. Una misma nota nunca
    es actualización."""
    from .dedupe import es_mismo_contenido, palabras_clave, refieren_a_hecho_distinto

    url_propia = noticia.get("url_normalizada")
    momento_propio = momento_vigencia(noticia)
    ventana = timedelta(hours=VENTANA_EVENTO_HORAS)
    recientes = [
        a for a in anteriores
        if a.get("id") != noticia.get("id")
        and not (momento_propio and momento_vigencia(a) and abs(momento_propio - momento_vigencia(a)) > ventana)
    ]
    for anterior in recientes:
        if url_propia and anterior.get("url_normalizada") == url_propia:
            return Relacion(anterior, False)
    # El análisis por acontecimiento va antes que la huella del título: una
    # actualización real ("Apareció Anahí Carmen Bargas") comparte casi
    # todas las palabras con la nota original y no debe bloquearse.
    relacion = buscar_relacion(noticia, recientes, config, cache)
    if relacion is not None:
        return relacion
    titulo_propio = noticia.get("titulo_original") or ""
    palabras_propias = palabras_clave(titulo_propio)
    for anterior in recientes:
        titulo_anterior = anterior.get("titulo_original") or ""
        if palabras_propias and es_mismo_contenido(palabras_propias, palabras_clave(titulo_anterior)):
            if not refieren_a_hecho_distinto(titulo_propio, titulo_anterior):
                return Relacion(anterior, False)
    return None
