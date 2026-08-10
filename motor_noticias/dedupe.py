import hashlib
import re
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
