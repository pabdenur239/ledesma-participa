"""Control de calidad del texto antes de publicar (agregado 2/10/2026).

Problemas reales publicados que motivan cada regla:
- "Alerta amarilla en Jujuy por fuetes lluvias" (errata de la fuente).
- "La diputada… recibió al Foro de Hábitat Digo" (la fuente dice "Digno":
  la redacción automática deformó la palabra).
- "calzado del 21 al 36" reescrito como "entre el 21 y el 36 de este mes"
  (fecha imposible inventada al redactar).
- Titular "Cronograma: novedad de Prensa Jujuy (Gobierno de Jujuy)
  (28/09/2026)" (metadata técnica convertida en titular).
- Notas de El Tribuno cuyo cuerpo está vacío o repite el título.

Nunca se inventa información para reparar un texto. Las acciones posibles:
- "publicar": sin problemas.
- "usar_original": el problema lo introdujo la redacción automática y el
  texto original de la fuente está bien → se publica el texto de la fuente.
- "retener": no se puede corregir con seguridad → queda para revisión
  humana (no se publica automáticamente).
"""
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import List, NamedTuple, Optional

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "calidad_editorial.json"

LONGITUD_MINIMA_CUERPO = 40

MESES = {
    "enero": 31, "febrero": 29, "marzo": 31, "abril": 30, "mayo": 31, "junio": 30, "julio": 31,
    "agosto": 31, "septiembre": 30, "setiembre": 30, "octubre": 31, "noviembre": 30, "diciembre": 31,
}

_RE_FUENTE_FINAL = re.compile(r"(?im)^\s*(fuente( y nota completa)?\s*:|nota propia de ledesma participa).*$")
_RE_DIA_DE_MES = re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(MESES) + r")\b")
_RE_DIA_DE_ESTE_MES = re.compile(r"\b(?:el|al|y el)\s+(\d{1,2})\s+de\s+(?:este|ese|dicho)\s+mes\b")
_RE_FECHA_NUMERICA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_RE_PALABRA = re.compile(r"[a-záéíóúüñ]+")
_RE_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")


class ResultadoCalidad(NamedTuple):
    accion: str  # "publicar" | "usar_original" | "retener"
    problemas: List[str]

    @property
    def apta(self) -> bool:
        return self.accion != "retener"


@lru_cache(maxsize=2)
def _config_cacheada(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def cargar_config(path: Optional[Path] = None) -> dict:
    return _config_cacheada(str(path or CONFIG_PATH_DEFAULT))


def _norm(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def _cuerpo_sin_atribucion(texto: str) -> str:
    return _RE_FUENTE_FINAL.sub("", texto or "").strip()


def _tokens(texto: str) -> List[str]:
    return _RE_PALABRA.findall((texto or "").lower())


def problemas_de_texto(titulo: str, texto: str, config: Optional[dict] = None) -> List[str]:
    """Problemas objetivos de un par título/cuerpo, sin comparar con nada."""
    config = config or cargar_config()
    problemas = []
    titulo = (titulo or "").strip()
    cuerpo = _cuerpo_sin_atribucion(texto)
    titulo_n, cuerpo_n = _norm(titulo), _norm(cuerpo)

    if len(cuerpo) < LONGITUD_MINIMA_CUERPO:
        problemas.append("cuerpo vacío o insuficiente")
    else:
        resto = cuerpo_n.replace(titulo_n, "", 1).strip(" .:-–—\n") if titulo_n else cuerpo_n
        tokens_t, tokens_c = set(_tokens(titulo_n)), set(_tokens(cuerpo_n))
        parecido = len(tokens_t & tokens_c) / len(tokens_t | tokens_c) if (tokens_t | tokens_c) else 0
        if len(resto) < 30 or (parecido >= 0.85 and len(cuerpo_n) < len(titulo_n) * 1.6):
            problemas.append("el cuerpo repite el título sin información propia")

    for patron in config.get("titulos_metadata", []):
        if re.search(patron, titulo, flags=re.IGNORECASE):
            problemas.append(f"titular con forma de metadata o nombre de archivo ({patron})")
            break
    if len(titulo) < 12:
        problemas.append("titular demasiado corto")

    texto_completo = f"{titulo}\n{cuerpo}"
    texto_completo_n = _norm(texto_completo)
    for marcador in config.get("placeholders", []):
        if re.search(marcador, texto_completo, flags=re.IGNORECASE):
            problemas.append(f"placeholder o texto técnico ({marcador})")
            break

    for dia, mes in _RE_DIA_DE_MES.findall(texto_completo_n):
        if not 1 <= int(dia) <= MESES[mes]:
            problemas.append(f"fecha imposible ({dia} de {mes})")
    for dia in _RE_DIA_DE_ESTE_MES.findall(texto_completo_n):
        if not 1 <= int(dia) <= 31:
            problemas.append(f"fecha imposible (el {dia} de este mes)")
    for dia, mes, _ in _RE_FECHA_NUMERICA.findall(texto_completo_n):
        if not (1 <= int(dia) <= 31 and 1 <= int(mes) <= 12):
            problemas.append(f"fecha imposible ({dia}/{mes})")

    erratas = {_norm(k): v for k, v in config.get("erratas_conocidas", {}).items() if not k.startswith("_")}
    for palabra in set(_tokens(texto_completo_n)):
        if palabra in erratas:
            problemas.append(f"errata evidente ('{palabra}' → '{erratas[palabra]}')")
    return problemas


def _distancia_uno(a: str, b: str) -> bool:
    """True si a y b difieren en exactamente una edición (sustitución,
    inserción o borrado de un carácter)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    # Flexión normal del español (singular/plural, género, persona verbal:
    # "lluvia/lluvias", "nuevo/nueva", "realiza/realizan"): cambia o agrega
    # solo la última letra. No es una palabra deformada.
    if a[:-1] == b[:-1] or a.startswith(b) or b.startswith(a):
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    corto, largo = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(largo)):
        if largo[:i] + largo[i + 1:] == corto:
            return True
    return False


def discrepancias_con_fuente(titulo_final: str, texto_final: str, titulo_orig: str, texto_orig: str) -> List[str]:
    """Cambios que la redacción automática introdujo y la fuente NO dice:
    números nuevos (cifras, días) y palabras deformadas (a una letra de una
    palabra de la fuente que no aparece tal cual)."""
    problemas = []
    original = _norm(f"{titulo_orig}\n{texto_orig}")
    final = _norm(f"{titulo_final}\n{_cuerpo_sin_atribucion(texto_final)}")
    if not original.strip():
        return problemas
    numeros_orig = set(_RE_NUMERO.findall(original))
    for numero in set(_RE_NUMERO.findall(final)) - numeros_orig:
        problemas.append(f"número que no está en la fuente ({numero})")
    # Solo nombres propios (palabras con mayúscula que no inician oración):
    # la redacción puede reformular libremente, pero deformar un nombre
    # ("Foro de Hábitat Digno" → "Digo") cambia el hecho.
    propios_orig = {_norm(p) for p in _nombres_propios(f"{titulo_orig}. {texto_orig}")}
    palabras_orig = set(_tokens(original))
    for palabra in {_norm(p) for p in _nombres_propios(f"{titulo_final}. {texto_final}")} - palabras_orig:
        if len(palabra) < 4:
            continue
        if any(_distancia_uno(palabra, p) for p in propios_orig if abs(len(p) - len(palabra)) <= 1 and len(p) >= 4):
            problemas.append(f"nombre propio deformado respecto de la fuente ('{palabra}')")
    return problemas


_RE_CAPITALIZADA = re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,}\b")


def _nombres_propios(texto: str) -> List[str]:
    """Palabras capitalizadas que no inician oración."""
    texto = texto or ""
    nombres = []
    for match in _RE_CAPITALIZADA.finditer(texto):
        previo = texto[:match.start()].rstrip()
        if previo and previo[-1] not in ".!?:¿¡\n\"“«(":
            nombres.append(match.group(0))
    return nombres


def _final(noticia: dict) -> tuple:
    titulo = noticia.get("titulo_revisado") or noticia.get("titulo_preparado") or noticia.get("titulo_original") or ""
    texto = noticia.get("texto_revisado") or noticia.get("texto_preparado") or noticia.get("texto_original") or ""
    return titulo, texto


def evaluar_calidad(noticia: dict, config: Optional[dict] = None) -> ResultadoCalidad:
    config = config or cargar_config()
    if noticia.get("origen_ingreso") in ("institucional", "resumen_diario"):
        return ResultadoCalidad("publicar", [])
    titulo, texto = _final(noticia)
    titulo_orig = noticia.get("titulo_original") or ""
    texto_orig = noticia.get("texto_original") or ""
    revisado_por_humano = bool(noticia.get("titulo_revisado") or noticia.get("texto_revisado")) and not noticia.get(
        "revision_automatica"
    )

    problemas_final = problemas_de_texto(titulo, texto, config)
    discrepancias = [] if revisado_por_humano else discrepancias_con_fuente(titulo, texto, titulo_orig, texto_orig)
    if not problemas_final and not discrepancias:
        return ResultadoCalidad("publicar", [])

    preparado_distinto = (titulo, texto) != (titulo_orig, texto_orig)
    if preparado_distinto and not revisado_por_humano:
        problemas_original = problemas_de_texto(titulo_orig, texto_orig, config)
        if not problemas_original:
            return ResultadoCalidad("usar_original", problemas_final + discrepancias)
    return ResultadoCalidad("retener", problemas_final + discrepancias)
