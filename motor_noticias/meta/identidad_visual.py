"""Identidad visual VERSIÓN C (Etapa 1, 9/10/2026): sistema reutilizable de
piezas para Facebook/Instagram, generado por código (sin navegador ni
edición manual en cada publicación automática). Canva sigue siendo el
laboratorio creativo manual; acá se replican sus reglas.

Marca madre: negro/carbón + dorado, blanco para legibilidad.
Uso funcional del color: ROJO = urgente (exclusivo), VERDE = servicios.

Plantillas (todas con titular dominante, territorio visible, logo
discreto, alto contraste y como mucho ~10 palabras de titular — nunca
párrafos completos en miniatura):
- noticia con foto real (`generar_pieza_feed(..., foto=bytes)`);
- noticia sin foto: PLACA EDITORIAL GRÁFICA (negro/dorado + titular +
  territorio + categoría);
- urgente (rojo), servicio (verde), institucional (dorado);
- clima + dólar (`generar_pieza_clima_dolar`);
- Story 1080x1920, carrusel de 3–5 placas y cuadros de Reel (ver
  `generar_story_pieza`, `generar_carrusel`, `cuadros_reel`).

Feed: 1080x1350 (4:5, el máximo vertical que Instagram acepta en el feed).
"""
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

DIRECTORIO_FUENTES = Path(__file__).resolve().parent / "fuentes"

ANCHO_FEED, ALTO_FEED = 1080, 1350
ANCHO_STORY, ALTO_STORY = 1080, 1920
MARGEN = 72

CARBON = (17, 17, 17)
CARBON_2 = (28, 27, 24)
DORADO = (212, 175, 55)
BLANCO = (255, 255, 255)
GRIS = (200, 196, 186)
ROJO = (200, 16, 46)
VERDE = (30, 142, 62)

MAXIMO_PALABRAS_TITULAR = 10

# tipo de pieza -> color de acento
ACENTOS = {
    "noticia": DORADO,
    "urgente": ROJO,
    "servicio": VERDE,
    "institucional": DORADO,
}

ETIQUETAS_TERRITORIO = {
    "libertador": "LIBERTADOR",
    "ledesma": "DEPARTAMENTO LEDESMA",
    "jujuy": "JUJUY",
    "nacional": "NACIONAL",
    "internacional": "INTERNACIONAL",
}


def _fuente(peso: str, tamano: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(DIRECTORIO_FUENTES / f"Montserrat-{peso}.ttf"), tamano)


def titular_placa(titulo: str, maximo_palabras: int = MAXIMO_PALABRAS_TITULAR) -> str:
    """Titular corto para la placa (~8–10 palabras principales). Prefiere
    cortar en un separador natural (":", " - ", ",") antes que a mitad de
    frase; si no hay, recorta palabras con "…". El titular completo va
    siempre en el texto de la publicación."""
    titulo = re.sub(r"\s+", " ", (titulo or "").strip())
    palabras = titulo.split(" ")
    # "Aproximado": hasta un 30% más se deja completo (cortar a mitad de
    # frase quita más sentido del que aporta acortar dos palabras).
    if len(palabras) <= round(maximo_palabras * 1.3):
        return titulo
    for separador in (": ", " - ", " — ", ", ", "; "):
        if separador in titulo:
            primera = titulo.split(separador, 1)[0].strip()
            if 4 <= len(primera.split(" ")) <= maximo_palabras:
                return primera
    recorte = palabras[:maximo_palabras]
    while recorte and len(recorte[-1]) <= 3:  # no terminar en "de", "la", "y"…
        recorte.pop()
    return " ".join(recorte).rstrip(",.;:") + "…"


def _envolver(dibujo: ImageDraw.ImageDraw, texto: str, fuente, ancho_maximo: int) -> List[str]:
    lineas: List[str] = []
    actual = ""
    for palabra in texto.split():
        candidato = f"{actual} {palabra}".strip()
        if dibujo.textlength(candidato, font=fuente) <= ancho_maximo or not actual:
            actual = candidato
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def _titular_ajustado(dibujo, texto: str, ancho: int, maximo_lineas: int, tamanos: Sequence[int]):
    """(fuente, líneas) con el tamaño más grande que entra en
    `maximo_lineas`: el titular siempre domina la pieza."""
    for tamano in tamanos:
        fuente = _fuente("ExtraBold", tamano)
        lineas = _envolver(dibujo, texto, fuente, ancho)
        if len(lineas) <= maximo_lineas:
            return fuente, lineas
    fuente = _fuente("ExtraBold", tamanos[-1])
    return fuente, _envolver(dibujo, texto, fuente, ancho)[:maximo_lineas]


def _pastilla(dibujo, xy, texto: str, fondo, color_texto, tamano: int = 28) -> int:
    """Badge (territorio / URGENTE / categoría). Devuelve el x final."""
    fuente = _fuente("ExtraBold", tamano)
    x, y = xy
    ancho = int(dibujo.textlength(texto, font=fuente))
    alto = tamano + 22
    dibujo.rounded_rectangle([(x, y), (x + ancho + 36, y + alto)], radius=alto // 2, fill=fondo)
    dibujo.text((x + 18, y + 9), texto, font=fuente, fill=color_texto)
    return x + ancho + 36


def _logo(dibujo, ancho: int, y: int, acento) -> None:
    """Logo discreto: filete de acento + LEDESMA PARTICIPA."""
    fuente = _fuente("Bold", 26)
    texto = "LEDESMA PARTICIPA"
    dibujo.rectangle([(MARGEN, y + 12), (MARGEN + 44, y + 16)], fill=acento)
    dibujo.text((MARGEN + 58, y), texto, font=fuente, fill=DORADO)


def _recortar_cover(foto: Image.Image, ancho: int, alto: int) -> Image.Image:
    foto = foto.convert("RGB")
    escala = max(ancho / foto.width, alto / foto.height)
    nueva = foto.resize((max(1, round(foto.width * escala)), max(1, round(foto.height * escala))), Image.LANCZOS)
    x = (nueva.width - ancho) // 2
    y = (nueva.height - alto) // 3  # sesgo hacia arriba: rostros/escena
    return nueva.crop((x, y, x + ancho, y + alto))


def _degradado_inferior(imagen: Image.Image, desde_y: int, opacidad_max: int = 238) -> None:
    ancho, alto = imagen.size
    capa = Image.new("L", (1, alto), 0)
    for y in range(alto):
        if y >= desde_y:
            capa.putpixel((0, y), int(opacidad_max * min(1.0, (y - desde_y) / max(1, (alto - desde_y) * 0.55))))
    mascara = capa.resize((ancho, alto))
    negro = Image.new("RGB", (ancho, alto), CARBON)
    imagen.paste(negro, (0, 0), mascara)


def _png(imagen: Image.Image) -> bytes:
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


@dataclass
class DatosPieza:
    titulo: str
    territorio: Optional[str] = None  # slug público: libertador, ledesma, jujuy, nacional, internacional
    categoria: Optional[str] = None  # etiqueta visible de la categoría (Policiales, Servicios…)
    tipo: str = "noticia"  # noticia | urgente | servicio | institucional


def _encabezado_badges(dibujo, datos: DatosPieza, x: int, y: int, acento) -> None:
    if datos.tipo == "urgente":
        x = _pastilla(dibujo, (x, y), "URGENTE", ROJO, BLANCO) + 14
    territorio = ETIQUETAS_TERRITORIO.get(datos.territorio or "")
    if territorio:
        fondo = BLANCO if datos.tipo == "urgente" else DORADO
        x = _pastilla(dibujo, (x, y), territorio, fondo, CARBON) + 14
    if datos.categoria and datos.tipo != "urgente":
        color = VERDE if datos.tipo == "servicio" else (60, 58, 52)
        _pastilla(dibujo, (x, y), datos.categoria.upper(), color, BLANCO, tamano=24)


def generar_pieza_feed(datos: DatosPieza, foto: Optional[bytes] = None, ancho: int = ANCHO_FEED, alto: int = ALTO_FEED) -> bytes:
    """Pieza de feed 1080x1350. Con `foto` (bytes de una imagen real del
    hecho, ya validada por la regla de imágenes): foto a sangre + degradado
    + titular. Sin foto: placa editorial gráfica negro/dorado. Lanza
    OSError/ValueError si `foto` no es una imagen válida."""
    acento = ACENTOS.get(datos.tipo, DORADO)
    texto = titular_placa(datos.titulo)
    if foto is not None:
        imagen = _recortar_cover(Image.open(io.BytesIO(foto)), ancho, alto)
        _degradado_inferior(imagen, int(alto * 0.38))
        dibujo = ImageDraw.Draw(imagen)
        fuente, lineas = _titular_ajustado(dibujo, texto, ancho - 2 * MARGEN, 4, (78, 72, 66, 60, 56))
        interlineado = int(fuente.size * 1.12)
        y_logo = alto - 96
        y = y_logo - 40 - interlineado * len(lineas)
        dibujo.rectangle([(MARGEN, y - 34), (MARGEN + 120, y - 26)], fill=acento)
        _encabezado_badges(dibujo, datos, MARGEN, y - 34 - 72, acento)
        for linea in lineas:
            dibujo.text((MARGEN, y), linea, font=fuente, fill=BLANCO)
            y += interlineado
        if datos.tipo == "urgente":
            dibujo.rectangle([(0, 0), (ancho, 14)], fill=ROJO)
        _logo(dibujo, ancho, y_logo, acento)
        return _png(imagen)

    imagen = Image.new("RGB", (ancho, alto), CARBON)
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle([(0, 0), (ancho, alto)], outline=CARBON_2, width=36)
    dibujo.rectangle([(36, 36), (ancho - 36, alto - 36)], outline=acento, width=3)
    if datos.tipo == "urgente":
        # Banda roja URGENTE (el rojo queda reservado a urgentes) + territorio.
        dibujo.rectangle([(36, 36), (ancho - 36, 200)], fill=ROJO)
        dibujo.text((MARGEN + 10, 62), "URGENTE", font=_fuente("ExtraBold", 92), fill=BLANCO)
        y_badges = 250
        if datos.territorio in ETIQUETAS_TERRITORIO:
            _pastilla(dibujo, (MARGEN + 10, y_badges), ETIQUETAS_TERRITORIO[datos.territorio], BLANCO, CARBON)
    else:
        y_badges = 130
        _encabezado_badges(dibujo, datos, MARGEN + 10, y_badges, acento)
    fuente, lineas = _titular_ajustado(dibujo, texto, ancho - 2 * MARGEN - 50, 6, (96, 88, 80, 72, 66, 60))
    interlineado = int(fuente.size * 1.13)
    alto_bloque = interlineado * len(lineas)
    zona_sup, zona_inf = y_badges + 90, alto - 180
    y = zona_sup + max(0, (zona_inf - zona_sup - alto_bloque) // 2)
    dibujo.rectangle([(MARGEN + 10, y + 8), (MARGEN + 22, y + alto_bloque - 16)], fill=acento)
    for linea in lineas:
        dibujo.text((MARGEN + 50, y), linea, font=fuente, fill=BLANCO)
        y += interlineado
    _logo(dibujo, ancho, alto - 120, acento)
    return _png(imagen)


def generar_story_pieza(datos: DatosPieza, foto: Optional[bytes] = None) -> bytes:
    """Story 1080x1920 con el mismo sistema (titular, territorio, logo)."""
    return generar_pieza_feed(datos, foto=foto, ancho=ANCHO_STORY, alto=ALTO_STORY)


def generar_pieza_texto(numero: str, texto: str, territorio: Optional[str], tipo: str = "noticia",
                        ancho: int = ANCHO_FEED, alto: int = ALTO_FEED) -> bytes:
    """Placa de dato (carrusel / Reel): un dato corto, grande y legible."""
    acento = ACENTOS.get(tipo, DORADO)
    imagen = Image.new("RGB", (ancho, alto), CARBON)
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle([(36, 36), (ancho - 36, alto - 36)], outline=acento, width=3)
    if territorio in ETIQUETAS_TERRITORIO:
        _pastilla(dibujo, (MARGEN + 10, 130), ETIQUETAS_TERRITORIO[territorio], DORADO, CARBON)
    dibujo.text((MARGEN + 10, 230), numero, font=_fuente("ExtraBold", 120), fill=acento)
    fuente = _fuente("SemiBold", 56)
    y = 420
    for linea in _envolver(dibujo, texto, fuente, ancho - 2 * MARGEN - 20)[:9]:
        dibujo.text((MARGEN + 10, y), linea, font=fuente, fill=BLANCO)
        y += 72
    _logo(dibujo, ancho, alto - 120, acento)
    return _png(imagen)


CTAS_CIERRE = (
    "Seguí Ledesma Participa para enterarte de lo que pasa en tu ciudad.",
    "Más información en ledesmaparticipa.com.ar",
)


def generar_pieza_cierre(texto: str = CTAS_CIERRE[0], ancho: int = ANCHO_FEED, alto: int = ALTO_FEED) -> bytes:
    imagen = Image.new("RGB", (ancho, alto), CARBON)
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle([(36, 36), (ancho - 36, alto - 36)], outline=DORADO, width=3)
    fuente_marca = _fuente("ExtraBold", 92)
    y = alto // 2 - 220
    for linea in ("LEDESMA", "PARTICIPA"):
        w = dibujo.textlength(linea, font=fuente_marca)
        dibujo.text(((ancho - w) / 2, y), linea, font=fuente_marca, fill=DORADO)
        y += 108
    fuente = _fuente("SemiBold", 46)
    y += 60
    for linea in _envolver(dibujo, texto, fuente, ancho - 2 * MARGEN - 40):
        w = dibujo.textlength(linea, font=fuente)
        dibujo.text(((ancho - w) / 2, y), linea, font=fuente, fill=BLANCO)
        y += 60
    sitio = "ledesmaparticipa.com.ar"
    fuente_sitio = _fuente("Bold", 34)
    w = dibujo.textlength(sitio, font=fuente_sitio)
    dibujo.text(((ancho - w) / 2, alto - 170), sitio, font=fuente_sitio, fill=GRIS)
    return _png(imagen)


def oraciones(texto: str) -> List[str]:
    partes = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡\"“0-9])", re.sub(r"\s+", " ", (texto or "").strip()))
    return [p.strip() for p in partes if len(p.strip()) > 1]


def datos_breves(texto: str, cantidad: int = 3, maximo_palabras: int = 28) -> List[str]:
    """2–3 datos cortos y completos del texto ya redactado (nunca se
    inventa: son oraciones del propio texto; las demasiado largas se
    omiten en vez de cortarse a mitad)."""
    elegidas = [o for o in oraciones(texto) if 4 <= len(o.split()) <= maximo_palabras]
    return elegidas[:cantidad]


def generar_carrusel(datos: DatosPieza, texto: str, foto: Optional[bytes] = None) -> List[bytes]:
    """Carrusel de 3–5 placas: portada + 1–3 datos + cierre. Devuelve []
    si el texto no da al menos un dato completo (no se rellena)."""
    datos_texto = datos_breves(texto)
    if not datos_texto:
        return []
    placas = [generar_pieza_feed(datos, foto=foto)]
    total = len(datos_texto)
    for i, dato in enumerate(datos_texto, 1):
        placas.append(generar_pieza_texto(f"{i}/{total}", dato, datos.territorio, datos.tipo))
    placas.append(generar_pieza_cierre())
    return placas


@dataclass
class CuadroReel:
    png: bytes
    segundos: float
    tramo: str  # gancho | datos | cierre


def cuadros_reel(datos: DatosPieza, texto: str, foto: Optional[bytes] = None) -> List[CuadroReel]:
    """Guion visual de un Reel de 10–20 s: 0–2 s gancho (titular), 2–10 s
    2–3 datos, cierre + CTA hasta completar. Devuelve [] si no hay al
    menos 2 datos completos: no se genera Reel para cualquier noticia."""
    datos_texto = datos_breves(texto, cantidad=3)
    if len(datos_texto) < 2:
        return []
    cuadros = [CuadroReel(generar_story_pieza(datos, foto=foto), 2.0, "gancho")]
    por_dato = 8.0 / len(datos_texto)
    for i, dato in enumerate(datos_texto, 1):
        cuadros.append(CuadroReel(
            generar_pieza_texto(f"{i}/{len(datos_texto)}", dato, datos.territorio, datos.tipo, ANCHO_STORY, ALTO_STORY),
            por_dato, "datos",
        ))
    cuadros.append(CuadroReel(generar_pieza_cierre(CTAS_CIERRE[0], ANCHO_STORY, ALTO_STORY), 5.0, "cierre"))
    return cuadros


# --- Clima + Dólar ---------------------------------------------------------

NO_DISPONIBLE = "No disponible"


def _formato_pesos(valor: Optional[float]) -> str:
    if valor is None:
        return NO_DISPONIBLE
    return "$" + f"{valor:,.0f}".replace(",", ".")


def generar_pieza_clima_dolar(datos: dict, ancho: int = ANCHO_FEED, alto: int = ALTO_FEED) -> bytes:
    """Placa del informe de la mañana. `datos` = estructura guardada por
    `motor_noticias.informe_diario` ({fecha_legible, clima|None,
    oficial|None, blue|None, actualizado, fuentes}). Lo que falta se
    muestra como "No disponible": nunca se inventa un valor."""
    imagen = Image.new("RGB", (ancho, alto), CARBON)
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle([(36, 36), (ancho - 36, alto - 36)], outline=DORADO, width=3)
    dibujo.text((MARGEN + 10, 100), "CLIMA + DÓLAR", font=_fuente("ExtraBold", 84), fill=DORADO)
    dibujo.text((MARGEN + 10, 200), "INFORME DE LA MAÑANA", font=_fuente("Bold", 40), fill=BLANCO)
    x_fin = _pastilla(dibujo, (MARGEN + 10, 265), "LIBERTADOR", DORADO, CARBON, tamano=24)
    dibujo.text((x_fin + 18, 272), datos.get("fecha_legible") or "", font=_fuente("Medium", 30), fill=GRIS)

    clima = datos.get("clima")
    y = 370
    dibujo.rounded_rectangle([(MARGEN, y), (ancho - MARGEN, y + 380)], radius=24, fill=CARBON_2)
    dibujo.text((MARGEN + 36, y + 28), "CLIMA", font=_fuente("Bold", 30), fill=VERDE)
    if clima:
        dibujo.text((MARGEN + 36, y + 70), f"{clima['temperatura_actual']:.0f}°", font=_fuente("ExtraBold", 170), fill=BLANCO)
        fuente_det = _fuente("SemiBold", 36)
        x_det = MARGEN + 400
        dibujo.text((x_det, y + 90), clima["descripcion"].capitalize()[:26], font=fuente_det, fill=BLANCO)
        dibujo.text((x_det, y + 150), f"Mín {clima['temperatura_minima']:.0f}° · Máx {clima['temperatura_maxima']:.0f}°", font=fuente_det, fill=GRIS)
        dibujo.text((x_det, y + 210), f"Lluvia: {clima['probabilidad_lluvia']:.0f}%", font=fuente_det, fill=GRIS)
    else:
        dibujo.text((MARGEN + 36, y + 150), NO_DISPONIBLE, font=_fuente("Bold", 56), fill=GRIS)

    y = 790
    dibujo.rounded_rectangle([(MARGEN, y), (ancho - MARGEN, y + 330)], radius=24, fill=CARBON_2)
    dibujo.text((MARGEN + 36, y + 28), "DÓLAR", font=_fuente("Bold", 30), fill=VERDE)
    dibujo.text((MARGEN + 380, y + 28), "COMPRA", font=_fuente("Bold", 26), fill=GRIS)
    dibujo.text((MARGEN + 660, y + 28), "VENTA", font=_fuente("Bold", 26), fill=GRIS)
    for i, (clave, etiqueta) in enumerate((("oficial", "Oficial"), ("blue", "Blue"))):
        fila_y = y + 100 + i * 110
        dolar = datos.get(clave)
        dibujo.text((MARGEN + 36, fila_y), etiqueta, font=_fuente("ExtraBold", 54), fill=BLANCO)
        if dolar:
            dibujo.text((MARGEN + 380, fila_y), _formato_pesos(dolar["compra"]), font=_fuente("ExtraBold", 54), fill=DORADO)
            dibujo.text((MARGEN + 660, fila_y), _formato_pesos(dolar["venta"]), font=_fuente("ExtraBold", 54), fill=DORADO)
        else:
            dibujo.text((MARGEN + 380, fila_y + 8), NO_DISPONIBLE, font=_fuente("Bold", 40), fill=GRIS)

    pie = f"Actualizado {datos.get('actualizado') or '—'} · Fuentes: {datos.get('fuentes') or 'Open-Meteo / DolarApi'}"
    dibujo.text((MARGEN + 10, alto - 190), pie, font=_fuente("Medium", 26), fill=GRIS)
    _logo(dibujo, ancho, alto - 120, VERDE)
    return _png(imagen)
