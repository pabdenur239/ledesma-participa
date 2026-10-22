"""Validacion obligatoria del guion de un Reel ANTES de sintetizar audio o publicar.

Solo afecta al circuito de Reels (producir_automatico / programador_audiovisual); las publicaciones normales
(imagenes/posts) no pasan por aqui. Si el guion falla: no se genera ni se publica el Reel y se registra la razon.

cierre_institucional() es la UNICA fuente del cierre: una frase fija de plantilla, nunca extraida del sitio.
"""
import re
import unicodedata

CIERRE = "Ampliá la información en Ledesma Participa."
MIN_PALABRAS_HECHOS = 14   # titulo + cuerpo sin cierre
MIN_PALABRAS_CUERPO = 5    # al menos una frase de contenido ademas del titular
MAX_PALABRAS = 140

# Navegacion, pie, legales, redes, llamados genericos, contacto.
CONTAMINACION = (r"facebook|instagram|twitter|whatsapp|youtube|tiktok|gu[ií]a comercial|contacto:|privacidad|eliminaci[oó]n de datos|"
                 r"pol[ií]tica de|t[eé]rminos|cookies|derechos reservados|cada nota indica|enlaza a ella|nota completa|"
                 r"seguinos|s[ií]guenos|suscrib|visit[aá] |ingres[aá] a|hac[eé] clic|clic aqu[ií]|men[uú] principal|"
                 r"@|https?:|www\.|\.com\b|\.ar\b|"
                 r"las noticias de libertador y el departamento|informaci[oó]n de libertador general san mart[ií]n y el departamento")


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


def _tokens(t):
    return set(re.findall(r"[a-z0-9]{4,}", _norm(t)))


def cierre_institucional():
    return CIERRE


def _frases(t):
    return [f.strip() for f in re.split(r"(?<=[.!?])\s+", t) if f.strip()]


def validar_guion(titulo, cuerpo_frases):
    """-> (ok, [motivos]). `titulo` y `cuerpo_frases` (lista) son el contenido periodistico SIN el cierre."""
    motivos = []
    titulo = (titulo or "").strip()
    frases = [f.strip() for f in cuerpo_frases if f and f.strip()]
    cuerpo = " ".join(frases)
    todo = f"{titulo}. {cuerpo}"
    m = re.search(CONTAMINACION, _norm(todo))
    if m:
        motivos.append(f"contaminacion: texto ajeno a la noticia ('{m.group(0).strip()}')")
    if len(titulo.split()) < 3:
        motivos.append("titulo ausente o demasiado corto")
    if len(cuerpo.split()) < MIN_PALABRAS_CUERPO:
        motivos.append("sin cuerpo: la noticia no tiene hechos mas alla del titular")
    if len(todo.split()) < MIN_PALABRAS_HECHOS:
        motivos.append(f"hechos insuficientes (<{MIN_PALABRAS_HECHOS} palabras)")
    if len(todo.split()) > MAX_PALABRAS:
        motivos.append("guion excesivamente largo")
    for f in frases:
        if not re.search(r"[.!?]$", f):
            motivos.append(f"frase incompleta: '{f[:50]}'")
        elif f.endswith(("…", "...")):
            motivos.append(f"frase cortada por la fuente: '{f[:50]}'")
        if re.search(r"(?:\b[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+\s+){4,}[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+", f):
            motivos.append(f"secuencia incoherente de palabras sin puntuacion: '{f[:50]}'")
    norm_f = [_norm(f).rstrip(".") for f in frases]
    if len(set(norm_f)) < len(norm_f):
        motivos.append("frases repetidas")
    tt = _tokens(titulo)
    if frases and tt and all(len(tt & _tokens(f)) / len(tt | _tokens(f)) > 0.85 for f in frases):
        motivos.append("el cuerpo repite el titular sin aportar hechos")
    return (not motivos), motivos
