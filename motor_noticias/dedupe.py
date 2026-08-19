import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PARAMETROS_TRACKING = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
}


def normalizar_url(url: str) -> str:
    partes = urlsplit(url.strip())
    netloc = partes.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = partes.path.rstrip("/")
    query = sorted(
        (k, v) for k, v in parse_qsl(partes.query) if k not in PARAMETROS_TRACKING
    )
    return urlunsplit(("https", netloc, path, urlencode(query), partes.fragment))


def hash_contenido(titulo: str, texto: str) -> str:
    contenido = f"{titulo.strip().lower()}|{texto.strip().lower()}"
    contenido = re.sub(r"\s+", " ", contenido)
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()


# Fingerprint de contenido por palabras clave del título: prioridad b) del
# gate de deduplicación antes de publicar (ver motor_noticias.meta.publicador),
# para el caso en que `hash_contenido` no alcanza porque dos fuentes distintas
# redactan la misma noticia con palabras diferentes (o el título cambia
# mínimamente entre una carga y otra). Palabras vacías españolas comunes,
# más un piso de longitud, para no comparar por artículos/preposiciones.
PALABRAS_VACIAS_ES = frozenset({
    "de", "la", "el", "en", "y", "a", "que", "con", "por", "para", "un",
    "una", "unos", "unas", "los", "las", "su", "sus", "al", "del", "se",
    "es", "ya", "mas", "como", "entre", "sin", "sobre", "tras", "ante",
    "asi", "que", "cual", "cuales", "este", "esta", "estos", "estas",
    "ese", "esa", "esos", "esas", "o", "u", "ni", "pero", "si", "no",
    "lo", "le", "les", "the", "todo", "toda", "todos", "todas", "sera",
    "son", "fue", "ser", "hay", "muy",
})
LONGITUD_MINIMA_PALABRA_CLAVE = 3
UMBRAL_PALABRAS_COMPARTIDAS = 3
UMBRAL_JACCARD = 0.2

# Palabras propias del proyecto que aparecen en casi cualquier nota local o
# provincial (nombres de lugar del propio padrón editorial) y por eso no
# cuentan para alcanzar el piso de palabras compartidas: por sí solas no son
# evidencia de que dos títulos hablen de la misma nota (ej. "Libertador"
# aparece tanto en notas genuinamente locales como, por homonimia, en notas
# nacionales sobre la película/cortometraje "El Libertador" — no son la
# misma noticia). Sí se cuentan para el cálculo de Jaccard.
PALABRAS_CONTEXTO_LOCAL = frozenset({"jujuy", "libertador", "ledesma"})


def _despojar_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def palabras_clave(titulo: str) -> frozenset:
    """Conjunto normalizado (sin acentos, minúsculas, sin palabras vacías ni
    palabras muy cortas) de palabras distintivas de un título — el
    fingerprint que se compara con `es_mismo_contenido`."""
    normalizado = _despojar_acentos(titulo.lower())
    tokens = re.findall(r"[a-z0-9]+", normalizado)
    return frozenset(
        token for token in tokens
        if len(token) >= LONGITUD_MINIMA_PALABRA_CLAVE and token not in PALABRAS_VACIAS_ES
    )


def es_mismo_contenido(palabras_a: frozenset, palabras_b: frozenset) -> bool:
    """True si dos fingerprints de título son lo bastante parecidos como
    para tratarse de la misma noticia. Exige un piso absoluto de palabras
    compartidas (evita que un solo nombre de lugar común, ej. "Jujuy",
    dispare un falso positivo entre dos notas distintas) y además una
    proporción mínima de solapamiento (Jaccard) sobre el total de palabras
    distintivas de ambos títulos."""
    compartidas = palabras_a & palabras_b
    compartidas_relevantes = compartidas - PALABRAS_CONTEXTO_LOCAL
    if len(compartidas_relevantes) < UMBRAL_PALABRAS_COMPARTIDAS:
        return False
    union = palabras_a | palabras_b
    if not union:
        return False
    return len(compartidas) / len(union) >= UMBRAL_JACCARD
