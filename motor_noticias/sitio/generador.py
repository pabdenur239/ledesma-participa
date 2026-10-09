"""Generador del sitio web público de Ledesma Participa.

Lee las noticias del PORTAL (`motor_noticias.portal`: lo publicado en redes
más la selección diaria de noticias válidas, 15–25 por día más urgentes) y
produce HTML estático y la API JSON de la app en `docs/` (GitHub Pages).
Web y app consumen exactamente la misma fuente lógica de contenido y de
clasificación (`motor_noticias.clasificacion`: territorio, categoría y
urgente, separados). Lo único que escribe en la base es la selección del
portal (`portal_seleccion`); no toca el circuito de publicación en Meta.

Etapa 1 (9/10/2026): portada mobile-first (urgente, clima + dólar,
principal, Libertador, Departamento Ledesma, Jujuy, Policiales, Salud,
Deportes, Servicios, Videos, Guía Comercial, redes), Guía Comercial,
Videos y API ampliada (portada.json, clima_dolar.json, guia_comercial.json,
videos.json) manteniendo los endpoints anteriores para la app publicada.
"""
import html
import json
import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Optional

from ..atribucion import atribucion
from ..clasificacion import clasificar_noticia
from ..db import Database
from ..entretenimiento import es_entretenimiento_o_curiosidad
from ..fechas import fecha_legible, parsear_fecha
from ..guia_comercial import comercios as cargar_comercios
from ..guia_comercial import ruta_imagen as ruta_imagen_comercio
from ..informe_diario_datos import datos_informe_de_noticia, leer_datos
from ..meta.identidad_visual import titular_placa
from ..motor_editorial import ZONA_JUJUY
from ..portal import completar_seleccion, es_informe_diario, noticias_del_portal
from ..regla_imagenes import evaluar_imagen
from ..scoring_editorial import evaluar_noticia, urgente_confirmado
from ..videos import cargar_videos
from . import plantillas
from .imagenes_web import ValidadorImagenes
from .urls import RAIZ_PROYECTO, SALIDA_DEFAULT, slugify, titulo_de  # noqa: F401 (slugify: API pública)

logger = logging.getLogger("motor_noticias.sitio.generador")

CONFIG_SITIO_PATH_DEFAULT = RAIZ_PROYECTO / "config" / "sitio.json"
ASSETS_FUENTE = Path(__file__).resolve().parent / "assets_fuente"

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

# Sección "territorial" de cada nota (migas, relacionadas y compatibilidad
# con la app publicada: `categoria_slug`/`categoria_etiqueta` de la API).
SECCION_TERRITORIAL = {
    "local": ("libertador", "Libertador Gral. San Martín"),
    "departamental": ("ledesma", "Departamento Ledesma"),
    "provincial": ("jujuy", "Jujuy"),
    "nacional": ("nacionales", "Nacionales"),
    "internacional": ("internacionales", "Internacionales"),
}
SECCION_POR_TERRITORIO = SECCION_TERRITORIAL  # nombre anterior

ETIQUETAS_SECCION = {
    "ultimas": "Últimas noticias",
    "libertador": "Libertador Gral. San Martín",
    "ledesma": "Departamento Ledesma",
    "jujuy": "Jujuy",
    "nacionales": "Nacionales",
    "internacionales": "Internacionales",
    "policiales": "Policiales",
    "salud": "Salud",
    "deportes": "Deportes",
    "gastronomia": "Gastronomía",
    "espectaculos": "Espectáculos",
    "politica": "Política",
    "servicios": "Servicios",
    "economia": "Economía",
    "educacion": "Educación",
    "cultura": "Cultura",
    "general": "General / Últimas",
    "entretenimiento": "Entretenimiento",
    "otras": "Otras noticias",
}
SLUGS_TERRITORIALES = ("libertador", "ledesma", "jujuy", "nacionales", "internacionales")
SLUGS_CATEGORIAS = (
    "policiales", "salud", "deportes", "servicios", "politica", "economia", "educacion", "cultura",
    "espectaculos", "gastronomia", "general",
)

# Portada (orden aprobado). Territorio y categoría nunca se mezclan:
# Policiales y Salud, Servicios y Deportes son secciones independientes.
SECCIONES_PORTADA = (
    ("libertador", "Libertador"),
    ("ledesma", "Departamento Ledesma"),
    ("jujuy", "Jujuy"),
    ("policiales", "Policiales"),
    ("salud", "Salud"),
    ("deportes", "Deportes"),
    ("servicios", "Servicios"),
)
POR_SECCION_PORTADA = 5
HORAS_RECIENTES_PORTADA = 72
DIAS_RECIENTES_LOCALES = 7  # Libertador/Ledesma tienen menos volumen
HORAS_URGENTES_PORTADA = 24
MAXIMO_URGENTES_PORTADA = 3

MAXIMO_ULTIMAS_HOME = 24
MAXIMO_POR_CATEGORIA = 120
MAXIMO_RELACIONADAS = 4
LONGITUD_RESUMEN = 200


def cargar_config_sitio(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_SITIO_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)


def deploy_automatico_habilitado(path: Optional[Path] = None) -> bool:
    """Lee `config/sitio.json` → "deploy_automatico" (default `true` si el
    archivo falta o es inválido). Se relee en cada intento de despliegue,
    así se puede desactivar el push automático a GitHub sin reiniciar
    ningún proceso."""
    try:
        return bool(cargar_config_sitio(path).get("deploy_automatico", True))
    except (OSError, json.JSONDecodeError):
        return True


def _resumen_breve(texto: str, longitud_maxima: int = LONGITUD_RESUMEN) -> str:
    texto = (texto or "").strip()
    if len(texto) <= longitud_maxima:
        return texto
    recorte = texto[:longitud_maxima]
    ultimo_espacio = recorte.rfind(" ")
    if ultimo_espacio > 0:
        recorte = recorte[:ultimo_espacio]
    return recorte.rstrip(",.;: ") + "…"


_RE_ETIQUETA_HTML = re.compile(r"<[^>]{1,200}>")
_RE_LINEA_FUENTE = re.compile(r"^\s*fuente(\s+y\s+nota\s+completa)?\s*:", re.IGNORECASE)


def parrafos_web(texto: str) -> List[str]:
    """Párrafos legibles: sin etiquetas HTML crudas que traen algunos RSS
    (bug real: "<p>La noticia … fue publicada en …</p>" visible en la nota)
    y sin la línea "Fuente:" del texto (la fuente se muestra aparte, con
    su enlace)."""
    parrafos = []
    for bloque in _RE_ETIQUETA_HTML.sub("\n", html.unescape(texto or "")).split("\n"):
        bloque = re.sub(r"\s+", " ", bloque).strip()
        if bloque and not _RE_LINEA_FUENTE.match(bloque):
            parrafos.append(bloque)
    return parrafos


def _titulo_y_texto(noticia: dict) -> tuple:
    texto = noticia.get("texto_revisado") or noticia.get("texto_preparado") or noticia.get("texto_original") or ""
    return titulo_de(noticia), texto.strip()


def _parsear_fecha(valor: Optional[str]) -> Optional[datetime]:
    """RFC 2822 o ISO 8601; siempre aware (sin huso = hora de Jujuy)."""
    if not valor or not valor.strip():
        return None
    valor = valor.strip()
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


def _fecha_orden(dt: Optional[datetime]) -> datetime:
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def seccion_de(noticia: dict, titulo: str, texto: str, territorio: Optional[str] = None) -> tuple:
    territorio = territorio if territorio is not None else noticia.get("territorio")
    if territorio in SECCION_TERRITORIAL:
        return SECCION_TERRITORIAL[territorio]
    if es_entretenimiento_o_curiosidad(titulo, texto):
        return ("entretenimiento", "Entretenimiento")
    return ("otras", "Otras noticias")


def _imagen_web(noticia: dict, usos: dict, validador: Optional[ValidadorImagenes]) -> Optional[str]:
    """Regla de imágenes: foto de la fuente solo si es apta (no stock, no
    genérica, no foto de archivo reutilizada en otras notas) y responde; si
    no, None → la plantilla muestra la PLACA EDITORIAL GRÁFICA (CSS)."""
    ruta = noticia.get("imagen_publicacion_ruta")
    if not ruta or noticia.get("imagen_generada_automaticamente"):
        return None
    if ruta.startswith("http://") or ruta.startswith("https://"):
        if not evaluar_imagen(ruta, usos.get(ruta, 1) - 1)[0]:
            return None
        if validador is not None and not validador.es_valida(ruta):
            return None
        return ruta
    return ruta if Path(ruta).is_file() else None


def _resolver_imagen(ruta_original: Optional[str], salida_dir: Path, base_url: str) -> tuple:
    """(imagen_web relativa a la raíz del sitio, imagen_og absoluta). Copia
    archivos locales a assets/img/; una URL externa se referencia tal cual."""
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


def _momento_publico(noticia: dict, publicada_en: Optional[str]) -> tuple:
    """(momento, hora_conocida, momento_fuente, hora_fuente_conocida): la
    hora real de publicación en Ledesma Participa cuando existe; si no, la
    de la fuente; si no, la de ingreso. Nunca un "00:00" inventado."""
    fuente = parsear_fecha(noticia.get("fecha_fuente"))
    publicada = parsear_fecha(publicada_en)
    if publicada.momento is not None:
        return publicada.momento, True, fuente.momento, fuente.hora_conocida
    if fuente.momento is not None:
        return fuente.momento, fuente.hora_conocida, fuente.momento, fuente.hora_conocida
    ingreso = parsear_fecha(noticia.get("fecha_recoleccion"))
    return ingreso.momento, ingreso.hora_conocida, None, False


CACHE_CLASIFICACION_DEFAULT = RAIZ_PROYECTO / "data" / "cache" / "clasificacion_portal.json"
VERSION_CACHE_CLASIFICACION = "etapa1-v1"  # subir si cambia la lógica de clasificación
CONFIGS_CLASIFICACION = ("categorias.json", "localidades.json", "scoring_editorial.json", "entretenimiento.json")


class CacheClasificacion:
    """Clasificación (territorio/categoría/urgente) ya calculada por
    noticia: es determinística para un mismo contenido y una misma
    configuración, y recalcularla para ~2000 notas en cada regeneración
    del sitio (cada 15 min) costaría minutos. Se invalida sola si cambia el
    contenido de la nota o cualquiera de las configuraciones de reglas."""

    def __init__(self, ruta: Optional[Path] = None):
        self.ruta = Path(ruta or CACHE_CLASIFICACION_DEFAULT)
        firma = [VERSION_CACHE_CLASIFICACION]
        for nombre in CONFIGS_CLASIFICACION:
            archivo = RAIZ_PROYECTO / "config" / nombre
            firma.append(f"{nombre}:{archivo.stat().st_mtime_ns if archivo.exists() else 0}")
        self.firma = "|".join(firma)
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            datos = {}
        self.items = datos.get("items", {}) if datos.get("firma") == self.firma else {}
        self.usados: dict = {}

    @staticmethod
    def _clave(noticia: dict) -> str:
        campos = ("hash_contenido", "titulo_revisado", "titulo_preparado", "texto_revisado", "texto_preparado",
                  "urgente", "origen_ingreso", "territorio", "categoria_tematica", "fecha_recoleccion")
        return f"{noticia['id']}|" + "|".join(str(noticia.get(c) or "") for c in campos)

    def obtener(self, noticia: dict) -> dict:
        clave = self._clave(noticia)
        valor = self.items.get(clave)
        if valor is None:
            urgente = urgente_confirmado(noticia)
            valor = {"urgente": urgente, "clasificacion": clasificar_noticia(noticia, urgente=urgente)}
        self.usados[clave] = valor
        return valor

    def guardar(self) -> None:
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.ruta.write_text(json.dumps({"firma": self.firma, "items": self.usados}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            logger.warning("No se pudo guardar la caché de clasificación del portal.")


def _enriquecer(
    noticia: dict,
    salida_dir: Path,
    base_url: str,
    publicada_en: Optional[str] = None,
    validador: Optional[ValidadorImagenes] = None,
    usos_imagen: Optional[dict] = None,
    ahora: Optional[datetime] = None,
    cache: Optional[CacheClasificacion] = None,
) -> dict:
    titulo, texto = _titulo_y_texto(noticia)
    if cache is not None:
        calculado = cache.obtener(noticia)
        urgente, clasificacion = calculado["urgente"], calculado["clasificacion"]
    else:
        urgente = urgente_confirmado(noticia)
        clasificacion = clasificar_noticia(noticia, urgente=urgente)
    territorio_interno = clasificacion["territorio"]["interno"]
    seccion_slug, seccion_etiqueta = seccion_de(noticia, titulo, texto, territorio_interno)
    categoria = clasificacion["categoria"]
    imagen_web, imagen_og = _resolver_imagen(_imagen_web(noticia, usos_imagen or {}, validador), salida_dir, base_url)
    fecha_dt, hora_conocida, fuente_dt, hora_fuente_conocida = _momento_publico(noticia, publicada_en)
    autoria = atribucion(noticia)
    fecha_fuente_legible = ""
    if fuente_dt is not None and fecha_dt is not None and abs((fecha_dt - fuente_dt).total_seconds()) > 3600:
        fecha_fuente_legible = fecha_legible(fuente_dt, hora_fuente_conocida)
    slug = slugify(titulo)
    return {
        "id": noticia["id"],
        "titulo": titulo,
        "titulo_placa": titular_placa(titulo),
        "texto_parrafos": parrafos_web(texto),
        "resumen": _resumen_breve(" ".join(parrafos_web(texto))),
        "seccion_slug": seccion_slug,
        "seccion_etiqueta": seccion_etiqueta,
        "slug": slug,
        "url_relativa": f"noticias/{noticia['id']}-{slug}/",
        "fecha_legible": fecha_legible(fecha_dt, hora_conocida),
        "fecha_orden": _fecha_orden(fecha_dt),
        "fecha_fuente_legible": fecha_fuente_legible,
        # Fuente real (nunca "contenido propio" para una nota de un medio).
        "nombre_fuente": autoria.etiqueta,
        "url_fuente": autoria.url or "",
        "imagen_web": imagen_web,
        "imagen_og": imagen_og,
        # Clasificación única (territorio / categoría / urgente separados).
        "territorio": territorio_interno,
        "territorio_slug": clasificacion["territorio"]["valor"],
        "territorio_etiqueta": clasificacion["territorio"].get("etiqueta_corta") or clasificacion["territorio"]["etiqueta"],
        "territorio_etiqueta_completa": clasificacion["territorio"]["etiqueta"],
        "territorio_confianza": clasificacion["territorio"]["confianza"],
        "categoria_tema": categoria["valor"],
        "categoria_tema_etiqueta": categoria["etiqueta"] if categoria["valor"] not in (None, "general") else None,
        "categoria_confianza": categoria["confianza"],
        "tematicas": [categoria["valor"]] if categoria["valor"] not in (None, "general") else [],
        "urgente": urgente,
        "categoria_tematica": noticia.get("categoria_tematica"),
        "localidad": noticia.get("localidad"),
        "es_informe": es_informe_diario(noticia),
        "datos_informe": datos_informe_de_noticia(noticia),
        # Solo hace falta para elegir la noticia principal (últimas 72 h).
        "puntaje": evaluar_noticia(noticia, ahora)["total"]
        if _fecha_orden(fecha_dt) >= (ahora or datetime.now(timezone.utc)) - timedelta(hours=HORAS_RECIENTES_PORTADA)
        else 0,
    }


def _preparar_noticias(
    db: Database, salida_dir: Path, base_url: str, validador: Optional[ValidadorImagenes] = None,
    ahora: Optional[datetime] = None,
) -> List[dict]:
    try:
        completar_seleccion(db, ahora)
    except Exception:  # la selección nunca debe impedir regenerar el sitio
        logger.exception("Portal: no se pudo completar la selección; se usa la existente.")
    crudas = noticias_del_portal(db, ahora)
    publicadas_en = db.fechas_publicacion()
    usos_imagen: dict = {}
    for n in crudas:
        ruta = n.get("imagen_publicacion_ruta")
        if ruta:
            usos_imagen.setdefault(ruta, set()).add(n.get("titulo_original"))
    usos = {ruta: len(titulos) for ruta, titulos in usos_imagen.items()}
    cache = CacheClasificacion()
    enriquecidas = [
        _enriquecer(n, salida_dir, base_url, publicadas_en.get(n["id"]), validador, usos, ahora, cache) for n in crudas
    ]
    cache.guardar()
    enriquecidas.sort(key=lambda n: (n["fecha_orden"], n["id"]), reverse=True)
    return enriquecidas


PRIORIDAD_SECCION = {
    "libertador": 0, "ledesma": 1, "jujuy": 2, "nacionales": 3, "internacionales": 4, "entretenimiento": 5, "otras": 6,
}


def _elegir_destacadas(noticias: List[dict], cantidad: int = 3) -> List[dict]:
    ordenadas = sorted(
        enumerate(noticias),
        key=lambda par: (PRIORIDAD_SECCION.get(par[1]["seccion_slug"], 9), par[0]),
    )
    return [n for _, n in ordenadas[:cantidad]]


def _filtro_seccion(slug: str):
    if slug == "ultimas":
        return lambda n: True
    if slug in ("libertador", "ledesma", "jujuy", "nacionales", "internacionales"):
        return lambda n: n["seccion_slug"] == slug
    if slug == "entretenimiento":
        return lambda n: n["seccion_slug"] == "entretenimiento" or n["categoria_tema"] == "espectaculos"
    if slug == "otras":
        return lambda n: n["seccion_slug"] == "otras"
    return lambda n: n["categoria_tema"] == slug


def _recientes(noticias: List[dict], ahora: datetime, horas: float) -> List[dict]:
    limite = ahora - timedelta(hours=horas)
    return [n for n in noticias if n["fecha_orden"] >= limite]


def armar_portada(noticias: List[dict], ahora: datetime, videos: List[dict], comercios: List[dict], clima_dolar) -> dict:
    """Portada: prioriza contenido reciente; el histórico queda en las
    secciones. Nunca una sección vacía ni una nota repetida en dos
    secciones de la portada. Los informes de clima/dólar no compiten como
    noticia (tienen su módulo propio): así no monopolizan ninguna sección."""
    lista = [n for n in noticias if not n["es_informe"]]
    urgentes = [n for n in _recientes(lista, ahora, HORAS_URGENTES_PORTADA) if n["urgente"]][:MAXIMO_URGENTES_PORTADA]
    # Noticia principal: la de mayor puntaje editorial de las últimas 24 h
    # (72 h si no hay), priorizando Libertador / Ledesma / Jujuy: lo
    # nacional solo encabeza si no hay nada de la región.
    recientes = _recientes(lista, ahora, 24) or _recientes(lista, ahora, HORAS_RECIENTES_PORTADA) or lista[:10]
    regionales = [n for n in recientes if n["territorio"] in ("local", "departamental", "provincial")]
    principal = max(regionales or recientes, key=lambda n: (n["puntaje"], n["fecha_orden"]), default=None)
    usados = {principal["id"]} if principal else set()
    secciones = []
    for slug, etiqueta in SECCIONES_PORTADA:
        horas = DIAS_RECIENTES_LOCALES * 24 if slug in ("libertador", "ledesma") else HORAS_RECIENTES_PORTADA
        filtro = _filtro_seccion(slug)
        items = [n for n in _recientes(lista, ahora, horas) if filtro(n) and n["id"] not in usados][:POR_SECCION_PORTADA]
        if items:
            usados.update(n["id"] for n in items)
            secciones.append((slug, etiqueta, items))
    return {
        "urgentes": urgentes,
        "clima_dolar": clima_dolar,
        "principal": principal,
        "secciones": secciones,
        "videos": videos,
        "comercios": comercios,
    }


def _escribir(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")


def _copiar_assets_estaticos(salida_dir: Path) -> None:
    destino = salida_dir / "assets"
    destino.mkdir(parents=True, exist_ok=True)
    for archivo in ASSETS_FUENTE.iterdir():
        shutil.copyfile(archivo, destino / archivo.name)


def _generar_imagen_og_default(salida_dir: Path) -> str:
    """Banner OG genérico (1200x630) con la identidad Versión C."""
    from PIL import Image, ImageDraw

    from ..meta.identidad_visual import CARBON, DORADO, _fuente

    destino_dir = salida_dir / "assets" / "img"
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / "og-default-v2.png"
    if destino.exists():
        return "assets/img/og-default-v2.png"
    imagen = Image.new("RGB", (1200, 630), CARBON)
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle([(30, 30), (1170, 600)], outline=DORADO, width=3)
    dibujo.text((90, 200), "LEDESMA", font=_fuente("ExtraBold", 110), fill=(255, 255, 255))
    dibujo.text((90, 320), "PARTICIPA", font=_fuente("ExtraBold", 110), fill=DORADO)
    dibujo.text((90, 470), "Libertador Gral. San Martín · Departamento Ledesma · Jujuy", font=_fuente("SemiBold", 30), fill=(220, 214, 200))
    imagen.save(destino, format="PNG", optimize=True)
    return "assets/img/og-default-v2.png"


def _copiar_imagenes_guia(salida_dir: Path, comercios: List[dict]) -> None:
    """Imágenes de la Guía Comercial optimizadas para la web (≤1200 px)."""
    from PIL import Image

    destino_dir = salida_dir / "assets" / "guia"
    destino_dir.mkdir(parents=True, exist_ok=True)
    for comercio in comercios:
        for nombre in comercio["imagenes"]:
            destino = destino_dir / nombre
            origen = ruta_imagen_comercio(nombre)
            if destino.exists() and destino.stat().st_mtime >= origen.stat().st_mtime:
                continue
            with Image.open(origen) as imagen:
                imagen = imagen.convert("RGB")
                imagen.thumbnail((1200, 1200))
                imagen.save(destino, format="JPEG", quality=82, optimize=True)


def _construir_indice_busqueda(noticias: List[dict]) -> list:
    from .urls import _sin_acentos

    indice = []
    for n in noticias:
        buscable = _sin_acentos(
            " ".join([n["titulo"], n["resumen"], n["seccion_etiqueta"], n["nombre_fuente"], n.get("categoria_tema_etiqueta") or ""])
        )
        indice.append({
            "titulo": plantillas.escapar(n["titulo"]),
            "resumen": plantillas.escapar(n["resumen"]),
            "seccion": plantillas.escapar(n.get("territorio_etiqueta") or n["seccion_etiqueta"]),
            "fecha": plantillas.escapar(n["fecha_legible"]),
            "imagen": plantillas.escapar(n["imagen_web"] or ""),
            "url": n["url_relativa"],
            "buscable": buscable,
        })
    return indice


# ---------------------------------------------------------------------------
# API JSON de solo lectura (app móvil): mismos datos y misma clasificación
# que el sitio, como JSON estático bajo docs/api/. Nunca incluye campos de
# trabajo interno. Se mantienen los endpoints y campos que usa la app ya
# publicada (feed, urgentes, categorias, categoria/<slug>, noticia/<id>) y
# se agregan los de la Etapa 1.
CATEGORIAS_API = (
    # Compatibilidad con la app publicada (no cambiar estos slugs).
    ("locales", "Locales", lambda n: n["territorio"] in ("local", "departamental")),
    ("provinciales", "Provinciales", lambda n: n["territorio"] == "provincial"),
    ("nacionales", "Nacionales", lambda n: n["territorio"] == "nacional"),
    # Solo territorio: una nota de la Selección argentina en un medio
    # internacional es NACIONAL (bug corregido: antes entraba por la
    # categoría temática de la fuente).
    ("internacionales", "Internacionales", lambda n: n["territorio"] == "internacional"),
    ("policiales", "Policiales", lambda n: n["categoria_tema"] == "policiales"),
    ("espectaculos", "Espectáculos", lambda n: n["categoria_tema"] == "espectaculos"),
    ("salud", "Salud", lambda n: n["categoria_tema"] == "salud"),
    ("gastronomia", "Gastronomía", lambda n: n["categoria_tema"] == "gastronomia"),
    ("deportes", "Deportes", lambda n: n["categoria_tema"] == "deportes"),
    # Etapa 1.
    ("ultimas", "Últimas", lambda n: True),
    ("libertador", "Libertador", lambda n: n["territorio"] == "local"),
    ("ledesma", "Departamento Ledesma", lambda n: n["territorio"] == "departamental"),
    ("jujuy", "Jujuy", lambda n: n["territorio"] == "provincial"),
    ("servicios", "Servicios", lambda n: n["categoria_tema"] == "servicios"),
    ("politica", "Política", lambda n: n["categoria_tema"] == "politica"),
    ("economia", "Economía", lambda n: n["categoria_tema"] == "economia"),
    ("educacion", "Educación", lambda n: n["categoria_tema"] == "educacion"),
    ("cultura", "Cultura", lambda n: n["categoria_tema"] == "cultura"),
    ("general", "General / Últimas", lambda n: n["categoria_tema"] == "general"),
)
MAXIMO_FEED_API = 100
MAXIMO_URGENTES_API = 20
MAXIMO_POR_CATEGORIA_API = 100

# Google Play "News and Magazines": el contenido mostrado como normal en la
# app tiene menos de 3 meses. El detalle por id sigue disponible.
DIAS_MAXIMO_CONTENIDO_APP = 90


def _es_reciente_para_app(n: dict) -> bool:
    limite = datetime.now(timezone.utc) - timedelta(days=DIAS_MAXIMO_CONTENIDO_APP)
    return n["fecha_orden"] >= limite


def _url_absoluta(ruta: Optional[str], base_url: str) -> Optional[str]:
    if not ruta:
        return None
    if ruta.startswith("http://") or ruta.startswith("https://"):
        return ruta
    return base_url + ruta


def _datos_api_resumen(n: dict, base_url: str) -> dict:
    return {
        "id": n["id"],
        "titulo": n["titulo"],
        "bajada": n["resumen"],
        "imagen": _url_absoluta(n["imagen_web"], base_url),
        "fecha_iso": n["fecha_orden"].isoformat(),
        "fecha_legible": n["fecha_legible"],
        "categoria_slug": n["seccion_slug"],
        "categoria_etiqueta": n["seccion_etiqueta"],
        "localidad": n["localidad"],
        "territorio": n["territorio"],
        "tematicas": n["tematicas"],
        "urgente": n["urgente"],
        "url": base_url + n["url_relativa"],
        "fuente_nombre": n["nombre_fuente"],
        "fuente_url": n["url_fuente"] or None,
        # Etapa 1: clasificación separada (territorio / categoría / urgente).
        "clasificacion": {
            "territorio": {
                "valor": n["territorio_slug"], "etiqueta": n["territorio_etiqueta"], "confianza": n["territorio_confianza"],
            },
            "categoria": {
                "valor": n["categoria_tema"],
                "etiqueta": ETIQUETAS_SECCION.get(n["categoria_tema"]) if n["categoria_tema"] else None,
                "confianza": n["categoria_confianza"],
            },
            "urgente": n["urgente"],
        },
        "territorio_etiqueta": n["territorio_etiqueta"],
        "categoria_tema": n["categoria_tema"],
        "categoria_tema_etiqueta": n["categoria_tema_etiqueta"],
        "titulo_placa": n["titulo_placa"],
    }


def _datos_api_detalle(n: dict, base_url: str) -> dict:
    datos = _datos_api_resumen(n, base_url)
    datos["texto_parrafos"] = n["texto_parrafos"]
    return datos


def _datos_api_comercio(c: dict, base_url: str) -> dict:
    datos = {k: c[k] for k in (
        "slug", "nombre", "rubro", "descripcion", "direccion", "whatsapp", "telefono", "instagram", "facebook",
        "horarios", "promociones", "contacto",
    )}
    datos["logo"] = None
    datos["imagenes"] = [f"{base_url}assets/guia/{img}" for img in c["imagenes"]]
    datos["url"] = f"{base_url}guia-comercial/{c['slug']}/"
    return datos


def _datos_api_video(v: dict, base_url: str) -> dict:
    datos = dict(v)
    datos["url"] = f"{base_url}videos/{v['id']}/"
    return datos


def _escribir_api_json(
    salida_dir: Path, noticias: List[dict], base_url: str, portada: Optional[dict] = None,
    comercios: Optional[List[dict]] = None, videos: Optional[List[dict]] = None, clima_dolar: Optional[dict] = None,
) -> None:
    _escribir(salida_dir / "api" / "version.json", json.dumps({"generado_en": datetime.now(timezone.utc).isoformat()}))

    noticias_app = [n for n in noticias if _es_reciente_para_app(n) and not n.get("es_informe")]

    # Feed (Últimas): cronológico — lo más nuevo primero. Antes ordenaba
    # todo por territorio, lo que dejaba una nota local de hace semanas por
    # encima de lo de hoy.
    feed = [_datos_api_resumen(n, base_url) for n in noticias_app[:MAXIMO_FEED_API]]
    _escribir(salida_dir / "api" / "feed.json", json.dumps(feed, ensure_ascii=False))

    urgentes = [_datos_api_resumen(n, base_url) for n in noticias_app if n["urgente"]][:MAXIMO_URGENTES_API]
    _escribir(salida_dir / "api" / "urgentes.json", json.dumps(urgentes, ensure_ascii=False))

    categorias_meta = []
    for slug, etiqueta, filtro in CATEGORIAS_API:
        items = [_datos_api_resumen(n, base_url) for n in noticias_app if filtro(n)][:MAXIMO_POR_CATEGORIA_API]
        _escribir(salida_dir / "api" / "categoria" / f"{slug}.json", json.dumps(items, ensure_ascii=False))
        categorias_meta.append({"slug": slug, "etiqueta": etiqueta, "cantidad": len(items)})
    _escribir(salida_dir / "api" / "categorias.json", json.dumps(categorias_meta, ensure_ascii=False))

    for n in noticias:
        _escribir(
            salida_dir / "api" / "noticia" / f"{n['id']}.json",
            json.dumps(_datos_api_detalle(n, base_url), ensure_ascii=False),
        )

    comercios = comercios or []
    videos = videos or []
    _escribir(salida_dir / "api" / "guia_comercial.json",
              json.dumps([_datos_api_comercio(c, base_url) for c in comercios], ensure_ascii=False))
    _escribir(salida_dir / "api" / "videos.json",
              json.dumps([_datos_api_video(v, base_url) for v in videos], ensure_ascii=False))
    _escribir(salida_dir / "api" / "clima_dolar.json", json.dumps(clima_dolar, ensure_ascii=False))
    if portada is not None:
        datos_portada = {
            "urgentes": [_datos_api_resumen(n, base_url) for n in portada["urgentes"]],
            "clima_dolar": clima_dolar,
            "principal": _datos_api_resumen(portada["principal"], base_url) if portada["principal"] else None,
            "secciones": [
                {"slug": slug, "etiqueta": etiqueta, "noticias": [_datos_api_resumen(n, base_url) for n in items]}
                for slug, etiqueta, items in portada["secciones"]
            ],
            "videos": [_datos_api_video(v, base_url) for v in videos[:6]],
            "guia_comercial": [_datos_api_comercio(c, base_url) for c in comercios],
        }
        _escribir(salida_dir / "api" / "portada.json", json.dumps(datos_portada, ensure_ascii=False))


def _sitemap_xml(urls: List[str]) -> str:
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entradas = "\n".join(
        f"  <url><loc>{plantillas.escapar(u)}</loc><lastmod>{hoy}</lastmod></url>" for u in urls
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{entradas}\n</urlset>\n'


def _clima_dolar_vigente(ahora: datetime) -> tuple:
    """(datos, url_relativa de la nota) del informe de hoy; si todavía no
    salió, el de ayer. Nada más viejo (no se muestra un dólar de días)."""
    hoy = ahora.astimezone(ZONA_JUJUY).date()
    for fecha in (hoy, hoy - timedelta(days=1)):
        datos = leer_datos(fecha.isoformat())
        if datos:
            return datos, fecha.isoformat()
    return None, None


def generar_sitio(
    db_path,
    salida_dir: Optional[Path] = None,
    base_url: Optional[str] = None,
    config_sitio_path: Optional[Path] = None,
    ahora: Optional[datetime] = None,
) -> dict:
    salida_dir = Path(salida_dir or SALIDA_DEFAULT)
    config_sitio = cargar_config_sitio(config_sitio_path)
    base_url = (base_url or config_sitio.get("base_url_produccion") or "").rstrip("/") + "/"
    ahora = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)

    db = Database(db_path)
    validador = ValidadorImagenes()
    try:
        noticias = _preparar_noticias(db, salida_dir, base_url, validador, ahora)
    finally:
        db.close()
        validador.guardar()

    _copiar_assets_estaticos(salida_dir)
    imagen_og_default_abs = base_url + _generar_imagen_og_default(salida_dir)
    for n in noticias:
        if not n["imagen_og"]:
            n["imagen_og"] = imagen_og_default_abs

    comercios = cargar_comercios()
    _copiar_imagenes_guia(salida_dir, comercios)
    videos = cargar_videos()
    clima_dolar, fecha_informe = _clima_dolar_vigente(ahora)
    url_informe = next(
        (n["url_relativa"] for n in noticias if n["es_informe"] and fecha_informe and n["url_relativa"]
         and (n.get("datos_informe") or {}).get("fecha") == fecha_informe),
        None,
    )

    # Secciones: territorio y categoría, independientes. "Últimas" y las
    # listas excluyen los informes de clima/dólar (módulo propio).
    lista = [n for n in noticias if not n["es_informe"]]
    por_seccion = {}
    for slug in ("ultimas",) + SLUGS_TERRITORIALES + SLUGS_CATEGORIAS + ("entretenimiento", "otras"):
        filtro = _filtro_seccion(slug)
        por_seccion[slug] = [n for n in lista if filtro(n)]

    # Navegación: solo secciones con contenido (nunca una sección vacía).
    nav = [(slug, etiqueta) for slug, etiqueta in plantillas.SECCIONES_NAV if por_seccion.get(slug)]
    extras_nav = []
    if videos:
        extras_nav.append(("videos", "Videos", "videos/"))
    if comercios:
        extras_nav.append(("guia-comercial", "Guía Comercial", "guia-comercial/"))
    kw_nav = {"nav": nav, "extras_nav": extras_nav}

    urls_sitemap = [base_url, base_url + "buscar/"]

    portada = armar_portada(noticias, ahora, videos, comercios, clima_dolar)
    portada["url_informe"] = url_informe
    _escribir(
        salida_dir / "index.html",
        plantillas.pagina_index(
            destacadas=[], ultimas=[], ruta_raiz="", config_sitio=config_sitio, url_base=base_url, portada=portada, **kw_nav
        ),
    )

    slugs_a_generar = ["ultimas"] + list(SLUGS_TERRITORIALES) + list(SLUGS_CATEGORIAS) + ["entretenimiento"]
    if por_seccion.get("otras"):
        slugs_a_generar.append("otras")
    for slug in slugs_a_generar:
        items = por_seccion.get(slug, [])[:MAXIMO_POR_CATEGORIA]
        url_categoria = f"{base_url}categoria/{slug}/"
        _escribir(
            salida_dir / "categoria" / slug / "index.html",
            plantillas.pagina_categoria(
                slug=slug, etiqueta=ETIQUETAS_SECCION[slug], noticias=items, ruta_raiz="../../",
                config_sitio=config_sitio, url_base=url_categoria, **kw_nav,
            ),
        )
        if items:
            urls_sitemap.append(url_categoria)

    for n in noticias:
        relacionadas = [r for r in por_seccion.get(n["seccion_slug"], []) if r["id"] != n["id"]][:MAXIMO_RELACIONADAS]
        url_articulo = base_url + n["url_relativa"]
        _escribir(
            salida_dir / n["url_relativa"] / "index.html",
            plantillas.pagina_noticia(
                n=n, relacionadas=relacionadas, ruta_raiz="../../", config_sitio=config_sitio, url_base=url_articulo,
                clima_dolar=n.get("datos_informe"), **kw_nav,
            ),
        )
        urls_sitemap.append(url_articulo)

    # Guía Comercial (contenido comercial, separado de las noticias).
    _escribir(
        salida_dir / "guia-comercial" / "index.html",
        plantillas.pagina_guia(comercios=comercios, ruta_raiz="../", config_sitio=config_sitio,
                               url_base=base_url + "guia-comercial/", **kw_nav),
    )
    urls_sitemap.append(base_url + "guia-comercial/")
    for c in comercios:
        url_ficha = f"{base_url}guia-comercial/{c['slug']}/"
        _escribir(
            salida_dir / "guia-comercial" / c["slug"] / "index.html",
            plantillas.pagina_comercio(c=c, ruta_raiz="../../", config_sitio=config_sitio, url_base=url_ficha, **kw_nav),
        )
        urls_sitemap.append(url_ficha)

    # Videos (reproductor oficial de YouTube embebido).
    _escribir(
        salida_dir / "videos" / "index.html",
        plantillas.pagina_videos(videos=videos, ruta_raiz="../", config_sitio=config_sitio,
                                 url_base=base_url + "videos/", **kw_nav),
    )
    for v in videos:
        url_video = f"{base_url}videos/{v['id']}/"
        _escribir(
            salida_dir / "videos" / v["id"] / "index.html",
            plantillas.pagina_video(v=v, ruta_raiz="../../", config_sitio=config_sitio, url_base=url_video, **kw_nav),
        )
        urls_sitemap.append(url_video)
    if videos:
        urls_sitemap.append(base_url + "videos/")

    _escribir(
        salida_dir / "buscar" / "index.html",
        plantillas.pagina_buscar(ruta_raiz="../", config_sitio=config_sitio, url_base=base_url + "buscar/", **kw_nav),
    )
    _escribir(
        salida_dir / "assets" / "search-index.json",
        json.dumps(_construir_indice_busqueda(lista), ensure_ascii=False),
    )

    _escribir(
        salida_dir / "contacto" / "index.html",
        plantillas.pagina_contacto(ruta_raiz="../", config_sitio=config_sitio, url_base=base_url + "contacto/", **kw_nav),
    )
    urls_sitemap.append(base_url + "contacto/")

    _escribir_api_json(salida_dir, noticias, base_url, portada, comercios, videos, clima_dolar)

    _escribir(salida_dir / "sitemap.xml", _sitemap_xml(urls_sitemap))
    _escribir(salida_dir / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {base_url}sitemap.xml\n")

    return {
        "noticias": len(noticias),
        "secciones": {slug: len(items) for slug, items in por_seccion.items() if items},
        "salida_dir": str(salida_dir),
    }
