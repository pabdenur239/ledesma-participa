import hashlib
import io
import logging
import textwrap
from pathlib import Path
from typing import List, Optional
from xml.sax.saxutils import escape as _escapar_xml

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("motor_noticias.meta.imagen")

# ImageFont.load_default() (la fuente Aileron que trae Pillow embebida) no
# tiene los glifos de tildes/ñ/¿/¡ del español: los dibuja como un
# rectángulo de glifo faltante ("rítmica" sale como "r▯tmica"). Se resuelve
# una fuente real ya presente en el sistema (no se descarga ninguna): Arial
# en Windows, DejaVu Sans en la mayoría de las distros Linux, Arial/Helvetica
# en macOS. Solo si ninguna existe se cae de nuevo a load_default() (con una
# sola advertencia en el log) en vez de romper la generación de la placa.
_RUTAS_FUENTE_UNICODE = (
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)
_ruta_fuente_unicode_resuelta: Optional[str] = None
_avisado_sin_fuente_unicode = False


def _ruta_fuente_unicode() -> Optional[str]:
    global _ruta_fuente_unicode_resuelta, _avisado_sin_fuente_unicode
    if _ruta_fuente_unicode_resuelta is not None:
        return _ruta_fuente_unicode_resuelta
    for ruta in _RUTAS_FUENTE_UNICODE:
        if Path(ruta).is_file():
            _ruta_fuente_unicode_resuelta = ruta
            return ruta
    if not _avisado_sin_fuente_unicode:
        logger.warning(
            "No se encontró ninguna fuente con soporte de español (tildes/ñ/¿/¡) en el "
            "sistema; se usa ImageFont.load_default(), que no las dibuja correctamente."
        )
        _avisado_sin_fuente_unicode = True
    return None


def _cargar_fuente(size: int) -> ImageFont.ImageFont:
    ruta = _ruta_fuente_unicode()
    if ruta:
        return ImageFont.truetype(ruta, size)
    return ImageFont.load_default(size=size)

DIRECTORIO_PLACAS_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "placas"

# 1080x1080: tamaño cuadrado recomendado por Meta tanto para Facebook como
# para Instagram (evita recortes automáticos distintos por plataforma).
ANCHO_PLACA = 1080
ALTO_PLACA = 1080
MARGEN_X = 80
ALTO_BANDA_SUPERIOR = 160
ALTO_BANDA_FOOTER = 140

# 1080x1920 (9:16): formato vertical exigido por Meta para Instagram Stories
# (un feed placa 1:1 se recortaría). Mismo branding e identidad visual que
# la placa de feed, con bandas y márgenes reescalados para el lienzo más
# alto — no es una imagen distinta en estilo, solo en proporción.
ANCHO_STORY = 1080
ALTO_STORY = 1920
MARGEN_X_STORY = 80
ALTO_BANDA_SUPERIOR_STORY = 200
ALTO_BANDA_FOOTER_STORY = 180
MAXIMO_LINEAS_TITULO_STORY = 6
MAXIMO_LINEAS_RESUMEN_STORY = 8

# Identidad "Ledesma Participa": fondo oscuro, marca en dorado, título en
# blanco, acento naranja en el pie (fuente/localidad).
COLOR_MARCA = "#1f1a10"
COLOR_MARCA_TEXTO = "#d4af37"
COLOR_FONDO = "#141414"
COLOR_TITULO = "#ffffff"
COLOR_RESUMEN = "#e0d8c8"
COLOR_FOOTER_FONDO = "#1f1a10"
COLOR_FOOTER_TEXTO = "#e8631c"

# Usados por generar_svg_placa (envoltorio de texto por cantidad de
# caracteres, ya que el navegador es quien mide el ancho real).
ANCHO_MAXIMO_TITULO = 26
MAXIMO_LINEAS_TITULO = 4
INTERLINEADO_TITULO = 64
Y_TITULO_INICIAL = 420

ANCHO_MAXIMO_RESUMEN = 42
MAXIMO_LINEAS_RESUMEN = 5
INTERLINEADO_RESUMEN = 42


def _envolver_texto(texto: str, ancho_maximo: int, maximo_lineas: int) -> List[str]:
    """Envuelve texto de forma determinística: nunca corta una palabra al
    medio; si excede el máximo de líneas, la última termina con "…"."""
    if not texto or not texto.strip():
        return []
    return textwrap.wrap(
        texto.strip(),
        width=ancho_maximo,
        max_lines=maximo_lineas,
        placeholder=" …",
        break_long_words=False,
        break_on_hyphens=False,
    )


def _envolver_texto_pixeles(dibujo, texto: str, fuente, ancho_maximo_px: int, maximo_lineas: int) -> List[str]:
    """Igual que _envolver_texto, pero midiendo el ancho real en píxeles con
    la fuente que se va a usar para dibujar: evita que una línea se salga
    del lienzo por diferencias entre fuentes."""
    texto = (texto or "").strip()
    if not texto:
        return []
    palabras = texto.split()
    lineas: List[str] = []
    actual = ""
    indice = 0
    while indice < len(palabras) and len(lineas) < maximo_lineas:
        palabra = palabras[indice]
        candidato = f"{actual} {palabra}".strip()
        if dibujo.textlength(candidato, font=fuente) <= ancho_maximo_px or not actual:
            actual = candidato
            indice += 1
        else:
            lineas.append(actual)
            actual = ""
    if actual and len(lineas) < maximo_lineas:
        lineas.append(actual)

    hay_texto_restante = indice < len(palabras)
    if hay_texto_restante and lineas:
        ultima = lineas[-1]
        candidato = ultima + "…"
        while dibujo.textlength(candidato, font=fuente) > ancho_maximo_px and " " in ultima:
            ultima = ultima.rsplit(" ", 1)[0]
            candidato = ultima + "…"
        lineas[-1] = candidato

    return lineas


def _hash_contenido_placa(titulo: str, resumen: str, fuente: str, localidad: str) -> str:
    contenido = "|".join((titulo or "", resumen or "", fuente or "", localidad or ""))
    return hashlib.sha1(contenido.encode("utf-8")).hexdigest()[:16]


def generar_svg_placa(titulo: str, resumen: str, fuente: str = "", localidad: str = "") -> str:
    """Genera el marcado SVG de la placa. Se conserva como representación
    interna simple; el archivo publicable es el PNG de generar_placa()."""
    lineas_titulo = _envolver_texto(titulo, ANCHO_MAXIMO_TITULO, MAXIMO_LINEAS_TITULO)
    lineas_resumen = _envolver_texto(resumen, ANCHO_MAXIMO_RESUMEN, MAXIMO_LINEAS_RESUMEN)

    elementos_titulo = "".join(
        f'<text x="80" y="{Y_TITULO_INICIAL + i * INTERLINEADO_TITULO}" '
        f'font-family="sans-serif" font-size="52" font-weight="bold" fill="{COLOR_TITULO}">'
        f"{_escapar_xml(linea)}</text>\n"
        for i, linea in enumerate(lineas_titulo)
    )

    y_resumen_inicial = Y_TITULO_INICIAL + len(lineas_titulo) * INTERLINEADO_TITULO + 50
    elementos_resumen = "".join(
        f'<text x="80" y="{y_resumen_inicial + i * INTERLINEADO_RESUMEN}" '
        f'font-family="sans-serif" font-size="32" fill="{COLOR_RESUMEN}">'
        f"{_escapar_xml(linea)}</text>\n"
        for i, linea in enumerate(lineas_resumen)
    )

    pie_fuente = f"Fuente: {fuente}" if fuente else ""
    pie_localidad = f"Localidad: {localidad}" if localidad else ""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{ANCHO_PLACA}" height="{ALTO_PLACA}" viewBox="0 0 {ANCHO_PLACA} {ALTO_PLACA}">
<rect x="0" y="0" width="{ANCHO_PLACA}" height="{ALTO_PLACA}" fill="{COLOR_FONDO}"/>
<rect x="0" y="0" width="{ANCHO_PLACA}" height="160" fill="{COLOR_MARCA}"/>
<text x="80" y="100" font-family="sans-serif" font-size="48" font-weight="bold" fill="{COLOR_MARCA_TEXTO}">LEDESMA PARTICIPA</text>
{elementos_titulo}{elementos_resumen}<rect x="0" y="{ALTO_PLACA - 140}" width="{ANCHO_PLACA}" height="140" fill="{COLOR_FOOTER_FONDO}"/>
<text x="80" y="{ALTO_PLACA - 85}" font-family="sans-serif" font-size="28" fill="{COLOR_FOOTER_TEXTO}">{_escapar_xml(pie_fuente)}</text>
<text x="80" y="{ALTO_PLACA - 45}" font-family="sans-serif" font-size="28" fill="{COLOR_FOOTER_TEXTO}">{_escapar_xml(pie_localidad)}</text>
</svg>
"""


def generar_imagen_placa_png(titulo: str, resumen: str, fuente: str = "", localidad: str = "") -> bytes:
    """Dibuja la placa directamente como PNG (1200x1200) con Pillow: mismo
    branding, título, bajada, fuente y localidad que la versión SVG, listo
    para una futura subida por la Graph API (que no acepta SVG)."""
    imagen = Image.new("RGB", (ANCHO_PLACA, ALTO_PLACA), COLOR_FONDO)
    dibujo = ImageDraw.Draw(imagen)
    ancho_maximo_px = ANCHO_PLACA - 2 * MARGEN_X

    dibujo.rectangle([(0, 0), (ANCHO_PLACA, ALTO_BANDA_SUPERIOR)], fill=COLOR_MARCA)
    fuente_marca = _cargar_fuente(44)
    dibujo.text((MARGEN_X, 55), "LEDESMA PARTICIPA", font=fuente_marca, fill=COLOR_MARCA_TEXTO)

    fuente_titulo = _cargar_fuente(52)
    lineas_titulo = _envolver_texto_pixeles(
        dibujo, titulo, fuente_titulo, ancho_maximo_px, MAXIMO_LINEAS_TITULO
    )
    y = 380
    for linea in lineas_titulo:
        dibujo.text((MARGEN_X, y), linea, font=fuente_titulo, fill=COLOR_TITULO)
        y += 64

    fuente_resumen = _cargar_fuente(32)
    lineas_resumen = _envolver_texto_pixeles(
        dibujo, resumen, fuente_resumen, ancho_maximo_px, MAXIMO_LINEAS_RESUMEN
    )
    y += 30
    for linea in lineas_resumen:
        dibujo.text((MARGEN_X, y), linea, font=fuente_resumen, fill=COLOR_RESUMEN)
        y += 42

    y_footer = ALTO_PLACA - ALTO_BANDA_FOOTER
    dibujo.rectangle([(0, y_footer), (ANCHO_PLACA, ALTO_PLACA)], fill=COLOR_FOOTER_FONDO)
    fuente_footer = _cargar_fuente(26)
    if fuente:
        dibujo.text(
            (MARGEN_X, y_footer + 35), f"Fuente: {fuente}", font=fuente_footer, fill=COLOR_FOOTER_TEXTO
        )
    if localidad:
        dibujo.text(
            (MARGEN_X, y_footer + 80),
            f"Localidad: {localidad}",
            font=fuente_footer,
            fill=COLOR_FOOTER_TEXTO,
        )

    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()


def generar_placa(
    titulo: str,
    resumen: str,
    fuente: Optional[str] = None,
    localidad: Optional[str] = None,
    directorio_salida: Optional[Path] = None,
) -> Path:
    """Genera el archivo PNG de la placa para este contenido, o reutiliza el
    ya existente sin volver a escribirlo. El nombre del archivo depende
    únicamente del contenido (título, resumen, fuente, localidad): el mismo
    contenido siempre produce el mismo archivo."""
    directorio_salida = Path(directorio_salida or DIRECTORIO_PLACAS_DEFAULT)
    directorio_salida.mkdir(parents=True, exist_ok=True)

    identificador = _hash_contenido_placa(titulo, resumen, fuente or "", localidad or "")
    ruta = directorio_salida / f"placa_{identificador}.png"

    if not ruta.exists():
        datos_png = generar_imagen_placa_png(titulo, resumen, fuente or "", localidad or "")
        ruta.write_bytes(datos_png)

    return ruta


def generar_imagen_story_png(titulo: str, resumen: str, fuente: str = "", localidad: str = "") -> bytes:
    """Misma identidad visual que `generar_imagen_placa_png` (marca, colores,
    envoltorio de texto medido en píxeles) pero en el lienzo vertical 9:16
    que exige Meta para Instagram Stories. Todo el texto queda impreso en la
    propia imagen: las Stories publicadas por la API no admiten un caption
    aparte, así que no hay contenido "que dependa" de otro paso."""
    imagen = Image.new("RGB", (ANCHO_STORY, ALTO_STORY), COLOR_FONDO)
    dibujo = ImageDraw.Draw(imagen)
    ancho_maximo_px = ANCHO_STORY - 2 * MARGEN_X_STORY

    dibujo.rectangle([(0, 0), (ANCHO_STORY, ALTO_BANDA_SUPERIOR_STORY)], fill=COLOR_MARCA)
    fuente_marca = _cargar_fuente(52)
    dibujo.text((MARGEN_X_STORY, 75), "LEDESMA PARTICIPA", font=fuente_marca, fill=COLOR_MARCA_TEXTO)

    fuente_titulo = _cargar_fuente(60)
    lineas_titulo = _envolver_texto_pixeles(
        dibujo, titulo, fuente_titulo, ancho_maximo_px, MAXIMO_LINEAS_TITULO_STORY
    )
    y = 480
    for linea in lineas_titulo:
        dibujo.text((MARGEN_X_STORY, y), linea, font=fuente_titulo, fill=COLOR_TITULO)
        y += 74

    fuente_resumen = _cargar_fuente(38)
    lineas_resumen = _envolver_texto_pixeles(
        dibujo, resumen, fuente_resumen, ancho_maximo_px, MAXIMO_LINEAS_RESUMEN_STORY
    )
    y += 40
    for linea in lineas_resumen:
        dibujo.text((MARGEN_X_STORY, y), linea, font=fuente_resumen, fill=COLOR_RESUMEN)
        y += 50

    y_footer = ALTO_STORY - ALTO_BANDA_FOOTER_STORY
    dibujo.rectangle([(0, y_footer), (ANCHO_STORY, ALTO_STORY)], fill=COLOR_FOOTER_FONDO)
    fuente_footer = _cargar_fuente(32)
    if fuente:
        dibujo.text(
            (MARGEN_X_STORY, y_footer + 45), f"Fuente: {fuente}", font=fuente_footer, fill=COLOR_FOOTER_TEXTO
        )
    if localidad:
        dibujo.text(
            (MARGEN_X_STORY, y_footer + 100),
            f"Localidad: {localidad}",
            font=fuente_footer,
            fill=COLOR_FOOTER_TEXTO,
        )

    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()


def generar_story(
    titulo: str,
    resumen: str,
    fuente: Optional[str] = None,
    localidad: Optional[str] = None,
    directorio_salida: Optional[Path] = None,
) -> Path:
    """Genera el archivo PNG de la Story (9:16) para este contenido, o
    reutiliza el ya existente sin volver a escribirlo — mismo criterio que
    `generar_placa`. Prefijo `story_` (en vez de `placa_`) para que ambas
    imágenes de una misma noticia convivan en el mismo directorio sin
    pisarse: son archivos distintos, un formato distinto cada uno."""
    directorio_salida = Path(directorio_salida or DIRECTORIO_PLACAS_DEFAULT)
    directorio_salida.mkdir(parents=True, exist_ok=True)

    identificador = _hash_contenido_placa(titulo, resumen, fuente or "", localidad or "")
    ruta = directorio_salida / f"story_{identificador}.png"

    if not ruta.exists():
        datos_png = generar_imagen_story_png(titulo, resumen, fuente or "", localidad or "")
        ruta.write_bytes(datos_png)

    return ruta


# --- Identidad visual URGENTE (agregada 2/10/2026) -----------------------
# LEDESMA PARTICIPA + ROJO = INFORMACIÓN URGENTE. El rojo queda reservado
# EXCLUSIVAMENTE a las publicaciones del circuito urgente (clave
# "urgente-<id>" en `meta/publicador.py`): ni las placas normales ni las
# noticias simplemente "importantes" lo usan, para no desgastar la señal.
COLOR_URGENTE = "#d00000"
COLOR_URGENTE_OSCURO = "#7a0000"
COLOR_URGENTE_TEXTO = "#ffffff"
ALTO_BANDA_URGENTE = 250
ALTO_BANDA_TITULO_URGENTE = 330
MAXIMO_LINEAS_TITULO_URGENTE = 5
TIMEOUT_DESCARGA_IMAGEN = 15
MAX_BYTES_IMAGEN = 15 * 1024 * 1024


def _encabezado_urgente(dibujo: ImageDraw.ImageDraw) -> None:
    """Banda roja superior: "URGENTE" grande + identificación de la marca."""
    dibujo.rectangle([(0, 0), (ANCHO_PLACA, ALTO_BANDA_URGENTE)], fill=COLOR_URGENTE)
    dibujo.text((MARGEN_X, 40), "LEDESMA PARTICIPA", font=_cargar_fuente(40), fill=COLOR_URGENTE_TEXTO)
    dibujo.text((MARGEN_X, 95), "URGENTE", font=_cargar_fuente(130), fill=COLOR_URGENTE_TEXTO)


def _recortar_cuadrado(imagen: Image.Image) -> Image.Image:
    """Escala y recorta al centro a 1080x1080 (sin deformar la foto)."""
    imagen = imagen.convert("RGB")
    escala = max(ANCHO_PLACA / imagen.width, ALTO_PLACA / imagen.height)
    nueva = imagen.resize((max(1, round(imagen.width * escala)), max(1, round(imagen.height * escala))))
    x = (nueva.width - ANCHO_PLACA) // 2
    y = (nueva.height - ALTO_PLACA) // 2
    return nueva.crop((x, y, x + ANCHO_PLACA, y + ALTO_PLACA))


def generar_imagen_urgente_sin_foto_png(titulo: str, fuente: str = "") -> bytes:
    """Placa URGENTE para una noticia sin imagen: fondo rojo dominante,
    "URGENTE" grande, titular debajo en blanco (alto contraste) y la marca
    Ledesma Participa claramente presente arriba y en el pie."""
    imagen = Image.new("RGB", (ANCHO_PLACA, ALTO_PLACA), COLOR_URGENTE)
    dibujo = ImageDraw.Draw(imagen)
    _encabezado_urgente(dibujo)
    dibujo.rectangle([(MARGEN_X, ALTO_BANDA_URGENTE + 10), (ANCHO_PLACA - MARGEN_X, ALTO_BANDA_URGENTE + 18)],
                     fill=COLOR_URGENTE_TEXTO)

    fuente_titulo = _cargar_fuente(64)
    lineas = _envolver_texto_pixeles(
        dibujo, titulo, fuente_titulo, ANCHO_PLACA - 2 * MARGEN_X, MAXIMO_LINEAS_TITULO_URGENTE
    )
    y = ALTO_BANDA_URGENTE + 80
    for linea in lineas:
        dibujo.text((MARGEN_X, y), linea, font=fuente_titulo, fill=COLOR_URGENTE_TEXTO)
        y += 80

    y_footer = ALTO_PLACA - ALTO_BANDA_FOOTER
    dibujo.rectangle([(0, y_footer), (ANCHO_PLACA, ALTO_PLACA)], fill=COLOR_URGENTE_OSCURO)
    fuente_footer = _cargar_fuente(30)
    dibujo.text((MARGEN_X, y_footer + 30), "LEDESMA PARTICIPA · Información urgente",
                font=fuente_footer, fill=COLOR_URGENTE_TEXTO)
    if fuente:
        dibujo.text((MARGEN_X, y_footer + 78), f"Fuente: {fuente}", font=_cargar_fuente(26), fill=COLOR_URGENTE_TEXTO)

    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()


def generar_imagen_urgente_con_foto_png(foto: bytes, titulo: str) -> bytes:
    """Conserva la foto válida de la noticia (recortada a 1080x1080) y le
    agrega la banda roja "URGENTE" arriba y el titular legible sobre una
    franja inferior oscura con filete rojo. Lanza `OSError`/`ValueError`
    si los bytes no son una imagen válida."""
    imagen = _recortar_cuadrado(Image.open(io.BytesIO(foto)))
    dibujo = ImageDraw.Draw(imagen)
    _encabezado_urgente(dibujo)

    y_titulo = ALTO_PLACA - ALTO_BANDA_TITULO_URGENTE
    capa = Image.new("RGBA", (ANCHO_PLACA, ALTO_BANDA_TITULO_URGENTE), (0, 0, 0, 200))
    imagen.paste(capa, (0, y_titulo), capa)
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle([(0, y_titulo), (ANCHO_PLACA, y_titulo + 12)], fill=COLOR_URGENTE)
    fuente_titulo = _cargar_fuente(52)
    lineas = _envolver_texto_pixeles(dibujo, titulo, fuente_titulo, ANCHO_PLACA - 2 * MARGEN_X, 4)
    y = y_titulo + 40
    for linea in lineas:
        dibujo.text((MARGEN_X, y), linea, font=fuente_titulo, fill=COLOR_URGENTE_TEXTO)
        y += 64

    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()


def _descargar_imagen(url: str) -> bytes:
    import urllib.request

    peticion = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (LedesmaParticipa)"})
    with urllib.request.urlopen(peticion, timeout=TIMEOUT_DESCARGA_IMAGEN) as respuesta:
        return respuesta.read(MAX_BYTES_IMAGEN)


def generar_placa_urgente(
    titulo: str,
    fuente: Optional[str] = None,
    imagen_original: Optional[str] = None,
    directorio_salida: Optional[Path] = None,
    descargar=_descargar_imagen,
) -> Path:
    """Genera (o reutiliza, mismo criterio determinístico que
    `generar_placa`) la imagen URGENTE de una publicación. Si hay
    `imagen_original` (URL remota o ruta local) válida, la conserva con la
    banda roja; si no hay, o no se puede obtener/abrir, genera la placa roja
    sin foto — una urgente nunca queda sin imagen por esto."""
    directorio_salida = Path(directorio_salida or DIRECTORIO_PLACAS_DEFAULT)
    directorio_salida.mkdir(parents=True, exist_ok=True)
    identificador = _hash_contenido_placa(titulo, "", fuente or "", imagen_original or "")
    ruta = directorio_salida / f"urgente_{identificador}.png"
    if ruta.exists():
        return ruta

    datos_png = None
    if imagen_original:
        try:
            if imagen_original.startswith(("http://", "https://")):
                foto = descargar(imagen_original)
            else:
                foto = Path(imagen_original).read_bytes()
            datos_png = generar_imagen_urgente_con_foto_png(foto, titulo)
        except Exception as error:  # foto inválida o inaccesible: placa roja sin foto
            logger.warning("No se pudo usar la imagen original para la urgente (%s): %s", imagen_original, error)
    if datos_png is None:
        datos_png = generar_imagen_urgente_sin_foto_png(titulo, fuente or "")
    ruta.write_bytes(datos_png)
    return ruta
