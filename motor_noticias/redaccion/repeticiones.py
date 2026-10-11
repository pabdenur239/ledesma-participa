import re
import unicodedata

# Oraciones: corte tras . ! ? seguido de espacio y mayúscula/número/comilla
# (igual criterio que `meta/contenido._RE_ORACION`; no corta "21.883,42").
_RE_ORACION = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡\"“0-9])")
_RE_NUMERO = re.compile(r"\d+(?:[.,]\d+)*")
_RE_PALABRA = re.compile(r"[a-zñ]{4,}")

# Proporción de la oración nueva que ya dijo UNA oración anterior para
# considerarla repetida.
UMBRAL_REPETICION = 0.8
MINIMO_TERMINOS = 4


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def _terminos(oracion: str):
    norm = _sin_acentos(oracion)
    numeros = set(_RE_NUMERO.findall(norm))
    palabras = set(_RE_PALABRA.findall(_RE_NUMERO.sub(" ", norm)))
    return numeros, palabras


def _repite(oracion: str, anteriores: list) -> bool:
    numeros, palabras = _terminos(oracion)
    total = len(numeros) + len(palabras)
    if total < MINIMO_TERMINOS:
        return False
    for nums_prev, pals_prev in anteriores:
        # Nunca se descarta una oración que aporta un dato numérico nuevo.
        if not numeros <= nums_prev:
            continue
        if (len(numeros) + len(palabras & pals_prev)) / total >= UMBRAL_REPETICION:
            return True
    return False


def quitar_oraciones_repetidas(texto: str) -> str:
    """Quita las oraciones que repiten sustancialmente (≥ 80 % de sus
    palabras y todos sus números) a una oración anterior del mismo texto.
    Conserva el orden, los saltos de párrafo, las líneas "Fuente:" y toda
    oración con un dato nuevo. Bug real (11/10/2026): la redacción de una
    nota de EFE repitió tres veces "en 2008 el salario medio anual era de
    21.883,42 euros y en 2024 alcanzó 29.540,26 euros…"."""
    if not texto:
        return texto
    anteriores = []
    lineas = []
    for linea in texto.split("\n"):
        conservadas = []
        for oracion in _RE_ORACION.split(linea.strip()):
            if not oracion:
                continue
            if _repite(oracion, anteriores):
                continue
            conservadas.append(oracion)
            anteriores.append(_terminos(oracion))
        if conservadas or not linea.strip():
            lineas.append(" ".join(conservadas))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()
