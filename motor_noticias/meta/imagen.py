import hashlib
import textwrap
from pathlib import Path
from typing import List, Optional
from xml.sax.saxutils import escape as _escapar_xml

DIRECTORIO_PLACAS_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "placas"

ANCHO_PLACA = 1200
ALTO_PLACA = 1200

COLOR_MARCA = "#0d47a1"
COLOR_FONDO = "#ffffff"
COLOR_TITULO = "#1a1a1a"
COLOR_RESUMEN = "#444444"
COLOR_FOOTER_FONDO = "#f2f2f2"
COLOR_FOOTER_TEXTO = "#333333"

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


def _hash_contenido_placa(titulo: str, resumen: str, fuente: str, localidad: str) -> str:
    contenido = "|".join((titulo or "", resumen or "", fuente or "", localidad or ""))
    return hashlib.sha1(contenido.encode("utf-8")).hexdigest()[:16]


def generar_svg_placa(titulo: str, resumen: str, fuente: str = "", localidad: str = "") -> str:
    """Genera el marcado SVG de la placa. Formato 1200x1200, márgenes
    amplios y tipografía simple, pensado para legibilidad en Facebook."""
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
<text x="80" y="100" font-family="sans-serif" font-size="48" font-weight="bold" fill="#ffffff">LEDESMA PARTICIPA</text>
{elementos_titulo}{elementos_resumen}<rect x="0" y="{ALTO_PLACA - 140}" width="{ANCHO_PLACA}" height="140" fill="{COLOR_FOOTER_FONDO}"/>
<text x="80" y="{ALTO_PLACA - 85}" font-family="sans-serif" font-size="28" fill="{COLOR_FOOTER_TEXTO}">{_escapar_xml(pie_fuente)}</text>
<text x="80" y="{ALTO_PLACA - 45}" font-family="sans-serif" font-size="28" fill="{COLOR_FOOTER_TEXTO}">{_escapar_xml(pie_localidad)}</text>
</svg>
"""


def generar_placa(
    titulo: str,
    resumen: str,
    fuente: Optional[str] = None,
    localidad: Optional[str] = None,
    directorio_salida: Optional[Path] = None,
) -> Path:
    """Genera el archivo SVG de la placa para este contenido, o reutiliza el
    ya existente sin volver a escribirlo. El nombre del archivo depende
    únicamente del contenido (título, resumen, fuente, localidad): el mismo
    contenido siempre produce el mismo archivo."""
    directorio_salida = Path(directorio_salida or DIRECTORIO_PLACAS_DEFAULT)
    directorio_salida.mkdir(parents=True, exist_ok=True)

    identificador = _hash_contenido_placa(titulo, resumen, fuente or "", localidad or "")
    ruta = directorio_salida / f"placa_{identificador}.svg"

    if not ruta.exists():
        ruta.write_text(
            generar_svg_placa(titulo, resumen, fuente or "", localidad or ""), encoding="utf-8"
        )

    return ruta
