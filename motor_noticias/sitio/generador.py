"""Generador del sitio web público de Ledesma Participa.

Lee únicamente las noticias ya publicadas (`Database.listar_publicadas`,
`estado == 'publicada'`) y produce HTML estático en un directorio de
salida (por defecto `docs/`, ya usado por este repo para las páginas
legales servidas vía GitHub Pages). No escribe nada en la base de datos
ni toca el motor de recolección/publicación: es un proceso de solo
lectura que puede correrse las veces que haga falta.
"""
import json
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Optional

from ..db import Database
from ..entretenimiento import es_entretenimiento_o_curiosidad
from ..meta.imagen import COLOR_FONDO, COLOR_MARCA, COLOR_MARCA_TEXTO, COLOR_FOOTER_TEXTO
from ..motor_editorial import ZONA_JUJUY
from . import plantillas

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
CONFIG_SITIO_PATH_DEFAULT = RAIZ_PROYECTO / "config" / "sitio.json"
SALIDA_DEFAULT = RAIZ_PROYECTO / "docs"
ASSETS_FUENTE = Path(__file__).resolve().parent / "assets_fuente"

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

# territorio -> (slug de sección, etiqueta visible). "sin_clasificar" se
# reparte entre entretenimiento y el cajón residual "otras" según
# `es_entretenimiento_o_curiosidad` (mismo criterio ya usado por la cascada
# editorial para ese último nivel, sin duplicar la regla).
SECCION_POR_TERRITORIO = {
    "local": ("libertador", "Libertador Gral. San Martín"),
    "departamental": ("ledesma", "Departamento Ledesma"),
    "provincial": ("jujuy", "Jujuy"),
    "nacional": ("nacionales", "Nacionales"),
}

SECCIONES_NAV_SLUGS = [slug for slug, _ in plantillas.SECCIONES_NAV]

MAXIMO_ULTIMAS_HOME = 24
MAXIMO_POR_CATEGORIA = 120
MAXIMO_RELACIONADAS = 3
LONGITUD_RESUMEN = 200


def cargar_config_sitio(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_SITIO_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def slugify(texto: str, longitud_maxima: int = 70) -> str:
    base = _sin_acentos(texto)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:longitud_maxima].strip("-") or "nota"


def _resumen_breve(texto: str, longitud_maxima: int = LONGITUD_RESUMEN) -> str:
    texto = (texto or "").strip()
    if len(texto) <= longitud_maxima:
        return texto
    recorte = texto[:longitud_maxima]
    ultimo_espacio = recorte.rfind(" ")
    if ultimo_espacio > 0:
        recorte = recorte[:ultimo_espacio]
    return recorte.rstrip(",.;: ") + "…"


def _titulo_y_texto(noticia: dict) -> tuple:
    titulo = noticia.get("titulo_revisado") or noticia.get("titulo_preparado") or noticia.get("titulo_original") or ""
    texto = noticia.get("texto_revisado") or noticia.get("texto_preparado") or noticia.get("texto_original") or ""
    return titulo.strip(), texto.strip()


def _parsear_fecha(valor: Optional[str]) -> Optional[datetime]:
    """Intenta RFC 2822 (fecha_fuente típica de un feed RSS, p.ej. "Thu, 13
    Aug 2026 10:11:00 -0300") y después ISO 8601 (fecha_recoleccion, o
    fecha_fuente de collectors HTML/carga manual). Devuelve un datetime
    siempre aware: si el valor no trae huso horario (poco común, solo
    fechas sin hora tipeadas a mano) se asume que ya está en hora de Jujuy,
    igual que el resto del proyecto (ver ZONA_JUJUY en motor_editorial)."""
    if not valor or not valor.strip():
        return None
    valor = valor.strip()
    dt = None
    try:
        dt = parsedate_to_datetime(valor)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZONA_JUJUY)
    return dt


def _fecha_dt(noticia: dict) -> Optional[datetime]:
    return _parsear_fecha(noticia.get("fecha_fuente")) or _parsear_fecha(noticia.get("fecha_recoleccion"))


def _fecha_orden(dt: Optional[datetime]) -> datetime:
    """Valor siempre aware (UTC) para poder comparar/ordenar fechas de
    huso horario distinto sin mezclar aware/naive."""
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fecha_legible(dt: Optional[datetime]) -> str:
    """Formatea en hora de Jujuy (ZONA_JUJUY), sin importar el huso
    original de la fuente: la hora que ve el lector es siempre la local,
    igual que en el resto del sitio/las publicaciones de Meta."""
    if dt is None:
        return ""
    local = dt.astimezone(ZONA_JUJUY)
    return f"{local.day} de {MESES[local.month - 1]} de {local.year}, {local.hour:02d}:{local.minute:02d} hs"


def seccion_de(noticia: dict, titulo: str, texto: str) -> tuple:
    territorio = noticia.get("territorio")
    if territorio in SECCION_POR_TERRITORIO:
        return SECCION_POR_TERRITORIO[territorio]
    if es_entretenimiento_o_curiosidad(titulo, texto):
        return ("entretenimiento", "Entretenimiento")
    return ("otras", "Otras noticias")


def _resolver_imagen(ruta_original: Optional[str], salida_dir: Path, base_url: str) -> tuple:
    """Devuelve (imagen_web_relativa_a_la_raiz_del_sitio, imagen_og_absoluta).
    Copia archivos locales (placas u originales) a assets/img/; una URL
    externa ya publicada (imagen_url de un collector) se referencia tal
    cual, sin descargarla."""
    if not ruta_original:
        return None, None
    if ruta_original.startswith("http://") or ruta_original.startswith("https://"):
        return ruta_original, ruta_original

    origen = Path(ruta_original)
    if not origen.is_file():
        return None, None

    destino_dir = salida_dir / "assets" / "img"
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / origen.name
    if not destino.exists():
        shutil.copyfile(origen, destino)

    relativa = f"assets/img/{origen.name}"
    return relativa, base_url.rstrip("/") + "/" + relativa


def _enriquecer(noticia: dict, salida_dir: Path, base_url: str) -> dict:
    titulo, texto = _titulo_y_texto(noticia)
    seccion_slug, seccion_etiqueta = seccion_de(noticia, titulo, texto)
    slug = slugify(titulo)
    imagen_web, imagen_og = _resolver_imagen(noticia.get("imagen_publicacion_ruta"), salida_dir, base_url)
    fecha_dt = _fecha_dt(noticia)

    return {
        "id": noticia["id"],
        "titulo": titulo,
        "texto_parrafos": [p.strip() for p in texto.split("\n") if p.strip()],
        "resumen": _resumen_breve(texto),
        "seccion_slug": seccion_slug,
        "seccion_etiqueta": seccion_etiqueta,
        "slug": slug,
        "url_relativa": f"noticias/{noticia['id']}-{slug}/",
        "fecha_legible": _fecha_legible(fecha_dt),
        "fecha_orden": _fecha_orden(fecha_dt),
        "nombre_fuente": (noticia.get("nombre_fuente") or "").strip(),
        "url_fuente": (noticia.get("url_fuente") or "").strip(),
        "imagen_web": imagen_web,
        "imagen_og": imagen_og,
    }


def _preparar_noticias(db: Database, salida_dir: Path, base_url: str) -> List[dict]:
    crudas = db.listar_publicadas()
    enriquecidas = [_enriquecer(n, salida_dir, base_url) for n in crudas]
    enriquecidas.sort(key=lambda n: (n["fecha_orden"], n["id"]), reverse=True)
    return enriquecidas


PRIORIDAD_SECCION = {"libertador": 0, "ledesma": 1, "jujuy": 2, "nacionales": 3, "entretenimiento": 4, "otras": 5}


def _elegir_destacadas(noticias: List[dict], cantidad: int = 3) -> List[dict]:
    ordenadas = sorted(
        enumerate(noticias),
        key=lambda par: (PRIORIDAD_SECCION.get(par[1]["seccion_slug"], 9), par[0]),
    )
    return [n for _, n in ordenadas[:cantidad]]


def _generar_imagen_og_default(salida_dir: Path) -> str:
    """Banner OG genérico (1200x630) para portada/categorías/artículos sin
    imagen propia, con la misma paleta de marca que las placas de Meta."""
    from PIL import Image, ImageDraw, ImageFont

    destino_dir = salida_dir / "assets" / "img"
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / "og-default.png"
    if destino.exists():
        return "assets/img/og-default.png"

    ancho, alto = 1200, 630
    imagen = Image.new("RGB", (ancho, alto), COLOR_FONDO)
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle([(0, 0), (ancho, 140)], fill=COLOR_MARCA)
    fuente_marca = ImageFont.load_default(size=54)
    dibujo.text((60, 45), "LEDESMA PARTICIPA", font=fuente_marca, fill=COLOR_MARCA_TEXTO)
    fuente_bajada = ImageFont.load_default(size=32)
    dibujo.text(
        (60, 230),
        "Noticias de Libertador Gral. San Martín\ny el Departamento Ledesma",
        font=fuente_bajada,
        fill="#e0d8c8",
    )
    dibujo.rectangle([(0, alto - 16), (ancho, alto)], fill=COLOR_FOOTER_TEXTO)
    imagen.save(destino, format="PNG")
    return "assets/img/og-default.png"


def _copiar_assets_estaticos(salida_dir: Path) -> None:
    destino = salida_dir / "assets"
    destino.mkdir(parents=True, exist_ok=True)
    for archivo in ASSETS_FUENTE.iterdir():
        shutil.copyfile(archivo, destino / archivo.name)


def _escribir(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")


def _construir_indice_busqueda(noticias: List[dict]) -> list:
    indice = []
    for n in noticias:
        buscable = _sin_acentos(
            " ".join([n["titulo"], n["resumen"], n["seccion_etiqueta"], n["nombre_fuente"]])
        )
        indice.append({
            "titulo": plantillas.escapar(n["titulo"]),
            "resumen": plantillas.escapar(n["resumen"]),
            "seccion": plantillas.escapar(n["seccion_etiqueta"]),
            "fecha": plantillas.escapar(n["fecha_legible"]),
            "imagen": n["imagen_web"] or "",
            "url": n["url_relativa"],
            "buscable": buscable,
        })
    return indice


def _sitemap_xml(urls: List[str]) -> str:
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entradas = "\n".join(
        f"  <url><loc>{plantillas.escapar(u)}</loc><lastmod>{hoy}</lastmod></url>" for u in urls
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{entradas}\n</urlset>\n'


def generar_sitio(
    db_path,
    salida_dir: Optional[Path] = None,
    base_url: Optional[str] = None,
    config_sitio_path: Optional[Path] = None,
) -> dict:
    salida_dir = Path(salida_dir or SALIDA_DEFAULT)
    config_sitio = cargar_config_sitio(config_sitio_path)
    base_url = (base_url or config_sitio.get("base_url_produccion") or "").rstrip("/") + "/"

    db = Database(db_path)
    try:
        noticias = _preparar_noticias(db, salida_dir, base_url)
    finally:
        db.close()

    _copiar_assets_estaticos(salida_dir)
    imagen_og_default_rel = _generar_imagen_og_default(salida_dir)
    imagen_og_default_abs = base_url + imagen_og_default_rel
    for n in noticias:
        if not n["imagen_og"]:
            n["imagen_og"] = imagen_og_default_abs

    urls_sitemap = [base_url, base_url + "buscar/"]

    # Portada.
    destacadas = _elegir_destacadas(noticias)
    ids_destacadas = {n["id"] for n in destacadas}
    ultimas = [n for n in noticias if n["id"] not in ids_destacadas][:MAXIMO_ULTIMAS_HOME]
    _escribir(
        salida_dir / "index.html",
        plantillas.pagina_index(
            destacadas=destacadas, ultimas=ultimas, ruta_raiz="", config_sitio=config_sitio, url_base=base_url
        ),
    )

    # Categorías (las 5 fijas siempre, más "otras" solo si tiene contenido).
    por_seccion: dict = {}
    for n in noticias:
        por_seccion.setdefault(n["seccion_slug"], []).append(n)

    slugs_a_generar = list(SECCIONES_NAV_SLUGS)
    if por_seccion.get("otras"):
        slugs_a_generar.append("otras")

    etiquetas = dict(plantillas.SECCIONES_NAV)
    etiquetas["otras"] = "Otras noticias"

    for slug in slugs_a_generar:
        items = por_seccion.get(slug, [])[:MAXIMO_POR_CATEGORIA]
        url_categoria = f"{base_url}categoria/{slug}/"
        _escribir(
            salida_dir / "categoria" / slug / "index.html",
            plantillas.pagina_categoria(
                slug=slug,
                etiqueta=etiquetas[slug],
                noticias=items,
                ruta_raiz="../../",
                config_sitio=config_sitio,
                url_base=url_categoria,
            ),
        )
        urls_sitemap.append(url_categoria)

    # Artículos.
    for n in noticias:
        relacionadas = [
            r for r in por_seccion.get(n["seccion_slug"], []) if r["id"] != n["id"]
        ][:MAXIMO_RELACIONADAS]
        url_articulo = base_url + n["url_relativa"]
        _escribir(
            salida_dir / n["url_relativa"] / "index.html",
            plantillas.pagina_noticia(
                n=n, relacionadas=relacionadas, ruta_raiz="../../", config_sitio=config_sitio, url_base=url_articulo
            ),
        )
        urls_sitemap.append(url_articulo)

    # Buscador.
    _escribir(
        salida_dir / "buscar" / "index.html",
        plantillas.pagina_buscar(ruta_raiz="../", config_sitio=config_sitio, url_base=base_url + "buscar/"),
    )
    _escribir(
        salida_dir / "assets" / "search-index.json",
        json.dumps(_construir_indice_busqueda(noticias), ensure_ascii=False),
    )

    # SEO técnico.
    _escribir(salida_dir / "sitemap.xml", _sitemap_xml(urls_sitemap))
    _escribir(
        salida_dir / "robots.txt",
        f"User-agent: *\nAllow: /\nSitemap: {base_url}sitemap.xml\n",
    )

    return {
        "noticias": len(noticias),
        "secciones": {slug: len(items) for slug, items in por_seccion.items()},
        "salida_dir": str(salida_dir),
    }
