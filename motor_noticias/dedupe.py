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


# Localidades del departamento Ledesma y aledaños, más las ciudades de Jujuy
# que aparecen de forma recurrente en boletines de servicios ("Anuncian
# cortes de energía por tareas de mantenimiento en <localidad>"). Se usan
# solo para desempatar el gate de deduplicación de publicación: si dos
# títulos con fingerprint parecido nombran localidades distintas y ninguna
# en común, son avisos de dos lugares distintos, no la misma nota. Se
# normalizan sin acentos y se buscan con límites de palabra. "ledesma"
# (nombre del departamento entero) queda afuera a propósito: es demasiado
# amplio para discriminar un hecho puntual dentro de él.
LUGARES_DISCRIMINANTES = frozenset({
    "libertador general san martin", "libertador gral san martin", "libertador",
    "calilegua", "fraile pintado", "caimancito", "yuto", "el talar",
    "vinalito", "valle grande",
    "palma sola", "san pedro", "san salvador", "purmamarca", "perico",
    "palpala", "la quiaca", "humahuaca", "tilcara", "maimara", "abra pampa",
    "monterrico", "la mendieta", "el aguilar",
})

MESES_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "setiembre", "octubre", "noviembre", "diciembre",
)

_RE_FECHA_DMY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-]\d{2,4})?\b")
_RE_FECHA_DIA_MES = re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(MESES_ES) + r")\b")


def _lugares_mencionados(titulo_norm: str) -> frozenset:
    return frozenset(
        lugar for lugar in LUGARES_DISCRIMINANTES
        if re.search(r"\b" + re.escape(lugar) + r"\b", titulo_norm)
    )


def _fechas_calendario(titulo_norm: str) -> frozenset:
    firmas = set()
    for dia, mes in _RE_FECHA_DMY.findall(titulo_norm):
        firmas.add(("dmy", int(dia), int(mes)))
    for dia, mes in _RE_FECHA_DIA_MES.findall(titulo_norm):
        firmas.add(("dia_mes", int(dia), mes))
    return frozenset(firmas)


def refieren_a_hecho_distinto(titulo_a: str, titulo_b: str) -> bool:
    """True si dos títulos, aun con fingerprints de palabras parecidos
    (`es_mismo_contenido`), hablan claramente de hechos distintos porque
    nombran localidades distintas sin ninguna en común, o fechas de
    calendario distintas. Desactiva el falso positivo de deduplicación
    entre boletines recurrentes que comparten plantilla: el informe diario
    de clima/dólar de cada día, los avisos de "cortes de energía en
    <localidad>" de un pueblo y otro, la programación de partidos de una
    jornada y la siguiente."""
    a = _despojar_acentos((titulo_a or "").lower())
    b = _despojar_acentos((titulo_b or "").lower())

    lugares_a, lugares_b = _lugares_mencionados(a), _lugares_mencionados(b)
    if lugares_a and lugares_b and not (lugares_a & lugares_b):
        return True

    fechas_a, fechas_b = _fechas_calendario(a), _fechas_calendario(b)
    if fechas_a and fechas_b and not (fechas_a & fechas_b):
        return True

    return False
