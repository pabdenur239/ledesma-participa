"""Secciones de servicio del sitio: Radio en vivo, TV en vivo, Multimedia y
Guía Comercial. Todo el contenido sale de config/*.json (radios, tv,
multimedia, comercios): agregar una radio, un canal, un video o un comercio
es editar el JSON, no la interfaz."""
import json
import re
import shutil
from pathlib import Path
from typing import List, Optional

from .plantillas import cabecera_html, cierre_html, encabezado_html, escapar

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = RAIZ_PROYECTO / "config"
ANCHO_MAX_IMAGEN_COMERCIO = 1000


def _cargar(nombre: str, config_dir: Optional[Path] = None) -> dict:
    try:
        with open((config_dir or CONFIG_DIR) / nombre, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _es_https(url: str) -> bool:
    return isinstance(url, str) and url.startswith("https://")


def _pagina(*, titulo, descripcion, url_canonica, ruta_raiz, config_sitio, cuerpo, activa, extra_head="", scripts="") -> str:
    return "\n".join(
        [
            cabecera_html(titulo_pagina=titulo, descripcion=descripcion, url_canonica=url_canonica, ruta_raiz=ruta_raiz),
            encabezado_html(ruta_raiz=ruta_raiz, seccion_activa=activa),
            f'<main class="ancho">{cuerpo}</main>',
            scripts,
            cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio),
        ]
    )


# ---------------------------------------------------------------- Radio

def radios_activas(config_dir: Optional[Path] = None) -> dict:
    """{ambito: [radios activas con fuente válida]} respetando el orden del padrón."""
    datos = _cargar("radios.json", config_dir)
    por_ambito: dict = {a["id"]: [] for a in datos.get("ambitos", [])}
    for r in datos.get("radios", []):
        if not r.get("activa"):
            continue
        if r.get("tipo") == "audio" and not _es_https(r.get("fuente")):
            continue
        if r.get("tipo") == "youtube" and not re.fullmatch(r"UC[\w-]{22}", r.get("fuente") or ""):
            continue
        if r.get("tipo") not in ("audio", "youtube"):
            continue
        por_ambito.setdefault(r.get("ambito"), []).append(r)
    return por_ambito


def _tarjeta_radio(r: dict) -> str:
    return (
        f'<article class="radio" data-radio-tipo="{escapar(r["tipo"])}" data-fuente="{escapar(r["fuente"])}" data-nombre="{escapar(r["nombre"])}">'
        f'<div class="radio-info"><h3>{escapar(r["nombre"])}</h3>'
        f'<p>{escapar(r.get("frecuencia", ""))} · {escapar(r.get("localidad", ""))}</p></div>'
        f'<button type="button" class="boton-radio" aria-label="Escuchar {escapar(r["nombre"])}">▶ Escuchar</button>'
        '</article>'
    )


def pagina_radio(*, ruta_raiz: str, config_sitio: dict, url_base: str, config_dir: Optional[Path] = None) -> str:
    datos = _cargar("radios.json", config_dir)
    activas = radios_activas(config_dir)
    bloques = []
    for ambito in datos.get("ambitos", []):
        radios = activas.get(ambito["id"], [])
        if not radios:
            continue
        bloques.append(
            f'<section class="bloque-radio" id="{escapar(ambito["id"])}"><h2 class="subtitulo">{escapar(ambito["etiqueta"])}</h2>'
            f'<div class="lista-radios">{"".join(_tarjeta_radio(r) for r in radios)}</div></section>'
        )
    atajos = "".join(
        f'<a href="#{escapar(a["id"])}">{escapar(a["etiqueta"])}</a>'
        for a in datos.get("ambitos", [])
        if activas.get(a["id"])
    )
    cuerpo = (
        '<h1 class="titulo-seccion">Radio en vivo</h1>'
        '<p class="bajada">Escuchá las radios de Libertador, el departamento Ledesma, Jujuy y el país. Las señales son las que cada emisora publica oficialmente.</p>'
        f'<nav class="atajos" aria-label="Ámbito">{atajos}</nav>'
        '<div id="reproductor-radio" class="reproductor-radio" hidden><p id="radio-sonando" class="radio-sonando"></p>'
        '<audio id="radio-audio" controls preload="none"></audio>'
        '<div id="radio-youtube"></div></div>'
        + ("".join(bloques) or '<p class="vacio">No hay radios disponibles por el momento.</p>')
    )
    return _pagina(
        titulo="Radio en vivo — Ledesma Participa",
        descripcion="Escuchá en vivo radios de Libertador, el departamento Ledesma, Jujuy y Argentina.",
        url_canonica=url_base, ruta_raiz=ruta_raiz, config_sitio=config_sitio, cuerpo=cuerpo, activa="radio",
        scripts=f'<script src="{ruta_raiz}assets/medios.js" data-base="{ruta_raiz}"></script>',
    )


# ----------------------------------------------------------------- TV

def canales_activos(config_dir: Optional[Path] = None) -> dict:
    datos = _cargar("tv.json", config_dir)
    por_region: dict = {g["id"]: [] for g in datos.get("regiones", [])}
    for c in datos.get("canales", []):
        if not c.get("activa"):
            continue
        if c.get("tipo") == "youtube" and not re.fullmatch(r"UC[\w-]{22}", c.get("fuente") or ""):
            continue
        if c.get("tipo") == "iframe" and not _es_https(c.get("fuente")):
            continue
        if c.get("tipo") not in ("youtube", "iframe"):
            continue
        por_region.setdefault(c.get("region"), []).append(c)
    return por_region


def pagina_tv(*, ruta_raiz: str, config_sitio: dict, url_base: str, config_dir: Optional[Path] = None) -> str:
    datos = _cargar("tv.json", config_dir)
    activos = canales_activos(config_dir)
    bloques = []
    for region in datos.get("regiones", []):
        canales = activos.get(region["id"], [])
        if not canales:
            continue
        botones = "".join(
            f'<button type="button" class="boton-tv" data-tv-tipo="{escapar(c["tipo"])}" data-fuente="{escapar(c["fuente"])}" '
            f'data-nombre="{escapar(c["nombre"])}">{escapar(c["nombre"])}</button>'
            for c in canales
        )
        bloques.append(f'<section class="bloque-tv"><h2 class="subtitulo">{escapar(region["etiqueta"])}</h2><div class="lista-tv">{botones}</div></section>')
    cuerpo = (
        '<h1 class="titulo-seccion">TV en vivo</h1>'
        '<p class="bajada">Señales informativas oficiales. Elegí un canal para verlo; se reproduce desde el canal oficial.</p>'
        '<div id="reproductor-tv" class="reproductor-tv" hidden><p id="tv-viendo" class="radio-sonando"></p><div id="tv-marco" class="tv-marco"></div></div>'
        + ("".join(bloques) or '<p class="vacio">No hay señales disponibles por el momento.</p>')
    )
    return _pagina(
        titulo="TV en vivo — Ledesma Participa",
        descripcion="Señales informativas oficiales de Jujuy y Argentina en vivo.",
        url_canonica=url_base, ruta_raiz=ruta_raiz, config_sitio=config_sitio, cuerpo=cuerpo, activa="tv",
        scripts=f'<script src="{ruta_raiz}assets/medios.js" data-base="{ruta_raiz}"></script>',
    )


# ---------------------------------------------------------- Multimedia

def _item_multimedia(i: dict) -> Optional[str]:
    titulo = escapar(i.get("titulo", ""))
    if re.fullmatch(r"[\w-]{11}", i.get("youtube") or ""):
        medio = (
            f'<div class="video-16-9"><iframe src="https://www.youtube-nocookie.com/embed/{escapar(i["youtube"])}" title="{titulo}" '
            'loading="lazy" allow="encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe></div>'
        )
    elif i.get("archivo") and re.fullmatch(r"[\w./-]+\.(mp4|webm)", i["archivo"]) and ".." not in i["archivo"]:
        medio = f'<video controls preload="none" playsinline src="__RAIZ__{escapar(i["archivo"])}"></video>'
    else:
        return None
    return f'<article class="multimedia-item">{medio}<h3>{titulo}</h3></article>'


def pagina_multimedia(*, ruta_raiz: str, config_sitio: dict, url_base: str, config_dir: Optional[Path] = None) -> str:
    datos = _cargar("multimedia.json", config_dir)
    bloques = []
    for sec in datos.get("secciones", []):
        items = [h for h in (_item_multimedia(i) for i in datos.get("items", []) if i.get("tipo") == sec["id"]) if h]
        if items:
            bloques.append(f'<section><h2 class="subtitulo">{escapar(sec["etiqueta"])}</h2><div class="grilla-multimedia">{"".join(items)}</div></section>')
    cuerpo = (
        '<h1 class="titulo-seccion">Multimedia</h1>'
        + ("".join(bloques) or '<p class="vacio">Pronto vas a encontrar acá videos, entrevistas y producciones propias.</p>')
    ).replace("__RAIZ__", ruta_raiz)
    return _pagina(
        titulo="Multimedia — Ledesma Participa",
        descripcion="Videos, entrevistas, producciones propias y clips de Ledesma Participa.",
        url_canonica=url_base, ruta_raiz=ruta_raiz, config_sitio=config_sitio, cuerpo=cuerpo, activa="multimedia",
    )


# ------------------------------------------------------ Guía Comercial

def comercios_activos(config_dir: Optional[Path] = None) -> List[dict]:
    datos = _cargar("comercios.json", config_dir)
    return [c for c in datos.get("comercios", []) if c.get("activo", True) and c.get("id") and c.get("nombre")]


def _slug_seguro(valor: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", (valor or "").lower()).strip("-")


def copiar_imagenes_comercio(salida_dir: Path, comercio: dict, config_dir: Optional[Path] = None) -> dict:
    """Copia (redimensionadas) las imágenes locales a assets/guia/<id>/ y
    devuelve {'logo': ruta|None, 'imagenes': [rutas]} relativas a la raíz del
    sitio. Las URLs https se usan tal cual."""
    datos = _cargar("comercios.json", config_dir)
    origen_dir = RAIZ_PROYECTO / datos.get("directorio_imagenes", "")
    slug = _slug_seguro(comercio["id"])
    resultado = {"logo": None, "imagenes": []}

    def resolver(nombre: str) -> Optional[str]:
        if _es_https(nombre):
            return nombre
        origen = origen_dir / Path(nombre).name
        if not nombre or not origen.is_file():
            return None
        destino = salida_dir / "assets" / "guia" / slug / (origen.stem + ".jpg")
        if not destino.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            try:
                from PIL import Image

                with Image.open(origen) as im:
                    im = im.convert("RGB")
                    im.thumbnail((ANCHO_MAX_IMAGEN_COMERCIO, ANCHO_MAX_IMAGEN_COMERCIO))
                    im.save(destino, "JPEG", quality=82, optimize=True)
            except Exception:
                shutil.copyfile(origen, destino.with_suffix(origen.suffix))
                return f"assets/guia/{slug}/{origen.stem}{origen.suffix}"
        return f"assets/guia/{slug}/{destino.name}"

    resultado["logo"] = resolver(comercio.get("logo", ""))
    resultado["imagenes"] = [r for r in (resolver(n) for n in comercio.get("imagenes", [])) if r]
    return resultado


def _ruta_img(ruta: str, ruta_raiz: str) -> str:
    return ruta if ruta.startswith("https://") else ruta_raiz + ruta


def _url_whatsapp(numero: str, comercio: str) -> str:
    digitos = re.sub(r"\D", "", numero or "")
    if not digitos:
        return ""
    if not digitos.startswith("54"):
        digitos = "549" + digitos
    from urllib.parse import quote

    return f"https://wa.me/{digitos}?text=" + quote(f"Hola, te vi en la Guía Comercial de Ledesma Participa ({comercio}).")


def _url_mapa(c: dict) -> str:
    lat, lng = c.get("lat"), c.get("lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    return ""


def _red(url: str, texto: str) -> str:
    if not _es_https(url):
        return ""
    return f'<a href="{escapar(url)}" rel="noopener nofollow" target="_blank">{texto}</a>'


def pagina_guia(*, comercios: List[dict], imagenes: dict, ruta_raiz: str, config_sitio: dict, url_base: str) -> str:
    rubros = sorted({c.get("rubro", "") for c in comercios if c.get("rubro")})
    filtro = ""
    if len(rubros) > 1:
        filtro = '<div class="filtro filtro-rubro" role="group" aria-label="Rubro"><button type="button" class="chip activo" data-rubro="">Todos</button>' + "".join(
            f'<button type="button" class="chip" data-rubro="{escapar(r)}">{escapar(r)}</button>' for r in rubros
        ) + "</div>"
    tarjetas = []
    for c in comercios:
        imgs = imagenes.get(c["id"], {"logo": None, "imagenes": []})
        portada = imgs["imagenes"][0] if imgs["imagenes"] else imgs["logo"]
        media = f'<img src="{escapar(_ruta_img(portada, ruta_raiz))}" alt="" loading="lazy">' if portada else '<div class="tarjeta-sin-imagen" aria-hidden="true">LP</div>'
        promo = f'<span class="etiqueta-promo">Promoción</span>' if c.get("promociones") else ""
        tarjetas.append(
            f'<article class="tarjeta comercio" data-rubro="{escapar(c.get("rubro", ""))}"><a class="tarjeta-enlace" href="{ruta_raiz}guia/{escapar(_slug_seguro(c["id"]))}/">'
            f'<div class="tarjeta-media">{media}{promo}</div><div class="tarjeta-cuerpo"><h2 class="tarjeta-titulo">{escapar(c["nombre"])}</h2>'
            f'<p class="tarjeta-resumen">{escapar(c.get("descripcion", ""))}</p>'
            f'<p class="tarjeta-meta">{escapar(c.get("rubro", ""))}{" · " if c.get("rubro") and c.get("localidad") else ""}{escapar(c.get("localidad", ""))}</p></div></a></article>'
        )
    cuerpo = (
        '<h1 class="titulo-seccion">Guía Comercial</h1>'
        '<p class="bajada">Comercios y servicios de Libertador y la región, con sus datos, promociones y contacto directo.</p>'
        + filtro
        + (f'<div class="grilla" id="grilla-guia">{"".join(tarjetas)}</div>' if tarjetas else '<p class="vacio">Pronto vas a encontrar acá los comercios de la región.</p>')
        + f'<p class="nota-guia">¿Tenés un comercio? Escribinos a <a href="mailto:{escapar(config_sitio.get("email_contacto", ""))}">{escapar(config_sitio.get("email_contacto", ""))}</a> para sumarlo a la guía.</p>'
    )
    return _pagina(
        titulo="Guía Comercial — Ledesma Participa",
        descripcion="Comercios y servicios de Libertador General San Martín y el departamento Ledesma.",
        url_canonica=url_base, ruta_raiz=ruta_raiz, config_sitio=config_sitio, cuerpo=cuerpo, activa="guia",
        scripts=f'<script src="{ruta_raiz}assets/medios.js" data-base="{ruta_raiz}"></script>',
    )


def pagina_comercio(*, c: dict, imgs: dict, ruta_raiz: str, config_sitio: dict, url_base: str) -> str:
    """Plantilla única de ficha de comercio (mini página)."""
    nombre = c["nombre"]
    logo = f'<img class="comercio-logo" src="{escapar(_ruta_img(imgs["logo"], ruta_raiz))}" alt="Logo de {escapar(nombre)}">' if imgs.get("logo") else ""
    fotos = "".join(
        f'<a href="{escapar(_ruta_img(i, ruta_raiz))}" target="_blank" rel="noopener"><img src="{escapar(_ruta_img(i, ruta_raiz))}" alt="{escapar(nombre)}" loading="lazy"></a>'
        for i in imgs.get("imagenes", [])
    )
    datos = []
    if c.get("direccion") or c.get("localidad"):
        datos.append(f'<li><strong>Dirección:</strong> {escapar(", ".join(x for x in (c.get("direccion"), c.get("localidad")) if x))}</li>')
    if c.get("horarios"):
        datos.append(f'<li><strong>Horarios:</strong> {escapar(c["horarios"])}</li>')
    if c.get("telefono"):
        tel = re.sub(r"[^\d+]", "", c["telefono"])
        datos.append(f'<li><strong>Teléfono:</strong> <a href="tel:{escapar(tel)}">{escapar(c["telefono"])}</a></li>')
    mapa = _url_mapa(c)
    if mapa:
        datos.append(f'<li><a href="{escapar(mapa)}" rel="noopener" target="_blank">Ver ubicación en el mapa</a></li>')
    redes = [x for x in (_red(c.get("instagram"), "Instagram"), _red(c.get("facebook"), "Facebook"), _red(c.get("sitio_web"), "Sitio web")) if x]
    if redes:
        datos.append(f'<li><strong>Redes:</strong> {" · ".join(redes)}</li>')
    promos = ""
    if c.get("promociones"):
        promos = '<section class="promos"><h2 class="subtitulo">Promociones</h2><ul>' + "".join(f"<li>{escapar(p)}</li>" for p in c["promociones"]) + "</ul></section>"
    wa = _url_whatsapp(c.get("whatsapp", ""), nombre)
    boton = f'<a class="boton-contacto" href="{escapar(wa)}" rel="noopener" target="_blank">Contactar por WhatsApp</a>' if wa else ""
    migas = f'<p class="migas"><a href="{ruta_raiz}guia/">Guía Comercial</a></p>'
    jsonld = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": nombre, "description": c.get("descripcion", ""), "url": url_base}
    if c.get("direccion"):
        jsonld["address"] = {"@type": "PostalAddress", "streetAddress": c["direccion"], "addressLocality": c.get("localidad", ""), "addressCountry": "AR"}
    cuerpo = (
        f'{migas}<article class="comercio-ficha"><header class="comercio-cab">{logo}<div><h1 class="titulo-seccion">{escapar(nombre)}</h1>'
        f'<p class="tarjeta-meta">{escapar(c.get("rubro", ""))}</p></div></header>'
        f'<p>{escapar(c.get("descripcion", ""))}</p>{boton}'
        f'{("<div class=galeria>" + fotos + "</div>") if fotos else ""}{promos}'
        f'<ul class="comercio-datos">{"".join(datos)}</ul></article>'
        f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/")}</script>'
    )
    return _pagina(
        titulo=f"{nombre} — Guía Comercial — Ledesma Participa",
        descripcion=c.get("descripcion") or f"{nombre} en la Guía Comercial de Ledesma Participa.",
        url_canonica=url_base, ruta_raiz=ruta_raiz, config_sitio=config_sitio, cuerpo=cuerpo, activa="guia",
    )
