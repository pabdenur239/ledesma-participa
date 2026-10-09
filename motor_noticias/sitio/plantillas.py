"""Plantillas HTML del sitio público (texto plano, sin motor de templates:
el proyecto no depende de Jinja2 ni de nada fuera de la librería estándar).
Toda variable interpolada que pueda contener texto de una noticia pasa por
`escapar()` antes de incrustarse.

Etapa 1 (9/10/2026): rediseño mobile-first con la identidad Versión C
(carbón + dorado, blanco para legibilidad; rojo solo para URGENTE, verde
para servicios). Portada: urgente, clima + dólar, noticia principal,
Libertador, Departamento Ledesma, Jujuy, Policiales, Salud, Deportes,
Servicios, Videos, Guía Comercial y redes. Nunca se muestra una sección
vacía.

Etapa 2 (9/10/2026): Multimedia y Radios en vivo (`pagina_multimedia`,
`pagina_radios`); el mini reproductor persistente vive en assets/radio.js."""
import html
import json
from typing import Iterable, List, Optional, Sequence, Tuple

from ..radios import ZONAS as ZONAS_RADIO

COLOR_FONDO_MARCA = "#111111"
COLOR_ORO = "#d4af37"
COLOR_NARANJA = "#e8631c"

# og:image para páginas sin imagen propia (portada, secciones, guía): el
# banner genérico de la marca. Lo fija el generador (URL absoluta) antes de
# renderizar; nunca se inventa una imagen de nota.
IMAGEN_OG_DEFAULT: Optional[str] = None


def escapar(texto: Optional[str]) -> str:
    return html.escape(texto or "", quote=True)


def _tag_meta(nombre: str, contenido: str, propiedad: bool = False) -> str:
    atributo = "property" if propiedad else "name"
    return f'<meta {atributo}="{nombre}" content="{escapar(contenido)}">'


def cabecera_html(
    *,
    titulo_pagina: str,
    descripcion: str,
    url_canonica: str,
    ruta_raiz: str,
    imagen_og: Optional[str] = None,
    tipo_og: str = "website",
    css_href: Optional[str] = None,
    datos_estructurados: Optional[dict] = None,
    metas_extra: Sequence[Tuple[str, str]] = (),
) -> str:
    css_href = css_href or f"{ruta_raiz}assets/site.css"
    imagen_og = imagen_og or IMAGEN_OG_DEFAULT
    metas_og = [
        _tag_meta("og:title", titulo_pagina, propiedad=True),
        _tag_meta("og:description", descripcion, propiedad=True),
        _tag_meta("og:type", tipo_og, propiedad=True),
        _tag_meta("og:url", url_canonica, propiedad=True),
        _tag_meta("og:site_name", "Ledesma Participa", propiedad=True),
        _tag_meta("og:locale", "es_AR", propiedad=True),
        _tag_meta("twitter:card", "summary_large_image"),
        _tag_meta("twitter:title", titulo_pagina),
        _tag_meta("twitter:description", descripcion),
    ]
    if imagen_og:
        metas_og.append(_tag_meta("og:image", imagen_og, propiedad=True))
        metas_og.append(_tag_meta("twitter:image", imagen_og))
    metas_og.extend(_tag_meta(nombre, valor, propiedad=True) for nombre, valor in metas_extra if valor)
    if datos_estructurados:
        # "</" se neutraliza para que ningún texto pueda cerrar el <script>.
        ld = json.dumps(datos_estructurados, ensure_ascii=False).replace("</", "<\\/")
        metas_og.append(f'<script type="application/ld+json">{ld}</script>')

    return f"""<!DOCTYPE html>
<html lang="es-AR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="{COLOR_FONDO_MARCA}">
<title>{escapar(titulo_pagina)}</title>
<meta name="description" content="{escapar(descripcion)}">
<link rel="canonical" href="{escapar(url_canonica)}">
<link rel="icon" href="{ruta_raiz}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{css_href}">
{chr(10).join(metas_og)}
</head>
<body>
"""


def _enlaces_sociales(config_sitio: dict) -> List[Tuple[str, str]]:
    enlaces = []
    if config_sitio.get("facebook_url"):
        enlaces.append(("Facebook", config_sitio["facebook_url"]))
    if config_sitio.get("instagram_url"):
        enlaces.append(("Instagram", config_sitio["instagram_url"]))
    return enlaces


PIE_HTML_PLANTILLA = """
<footer class="pie">
  <div class="ancho">
    <p class="pie-marca">LEDESMA <span>PARTICIPA</span></p>
    <p>{descripcion}</p>
    <p class="pie-enlaces">
      {enlaces_sociales}
      <a href="{ruta_raiz}guia-comercial/">Guía Comercial</a>
      <a href="{ruta_raiz}contacto/">Contacto</a>
      <a href="{ruta_raiz}privacy.html">Privacidad</a>
      <a href="{ruta_raiz}data-deletion.html">Eliminación de datos</a>
    </p>
    <p class="pie-nota">Cada nota indica su fuente original y enlaza a ella. Contacto: {email}</p>
  </div>
</footer>
{script_medicion}<script src="{ruta_raiz}assets/radio.js" defer></script>
</body>
</html>
"""


def script_medicion(config_sitio: dict, ruta_raiz: str, pagina: str = "", clave="") -> str:
    """Medición propia y anónima (Etapa 3, assets/medicion.js). Sin
    `medicion_endpoint` en config/sitio.json no se incluye nada."""
    endpoint = config_sitio.get("medicion_endpoint")
    if not endpoint:
        return ""
    return (
        f'<script src="{ruta_raiz}assets/medicion.js" data-endpoint="{escapar(endpoint)}" '
        f'data-pagina="{escapar(pagina)}" data-clave="{escapar(str(clave))}"></script>\n'
    )


def cierre_html(*, ruta_raiz: str, config_sitio: dict, pagina: str = "", clave="") -> str:
    enlaces = [
        f'<a href="{escapar(url)}" rel="noopener" target="_blank">{escapar(nombre)}</a>'
        for nombre, url in _enlaces_sociales(config_sitio)
    ]
    return PIE_HTML_PLANTILLA.format(
        script_medicion=script_medicion(config_sitio, ruta_raiz, pagina, clave),
        descripcion=escapar(config_sitio.get("descripcion", "")),
        enlaces_sociales="\n      ".join(enlaces),
        ruta_raiz=ruta_raiz,
        email=escapar(config_sitio.get("email_contacto", "")),
    )


# Navegación: (slug, etiqueta, ruta relativa a la raíz). El generador pasa
# solo las secciones con contenido; esta lista es el orden y el respaldo.
SECCIONES_NAV = (
    ("ultimas", "Últimas"),
    ("libertador", "Libertador"),
    ("ledesma", "Ledesma"),
    ("jujuy", "Jujuy"),
    ("policiales", "Policiales"),
    ("salud", "Salud"),
    ("deportes", "Deportes"),
    ("servicios", "Servicios"),
    ("nacionales", "Nacional"),
    ("internacionales", "Internacional"),
    ("politica", "Política"),
    ("economia", "Economía"),
    ("educacion", "Educación"),
    ("cultura", "Cultura"),
    ("espectaculos", "Espectáculos"),
    ("gastronomia", "Gastronomía"),
)


def _cta_seguir_cabecera(config_sitio: Optional[dict]) -> str:
    enlaces = _enlaces_sociales(config_sitio or {})
    if not enlaces:
        return ""
    botones = "".join(
        f'<a href="{escapar(url)}" rel="noopener" target="_blank" data-ev="follow_cta_click" data-k="{nombre.lower()}" '
        f'aria-label="Seguí Ledesma Participa en {escapar(nombre)}">{escapar(nombre)}</a>'
        for nombre, url in enlaces
    )
    return f'<div class="cabecera-seguir"><span>Seguí</span>{botones}</div>'


def encabezado_html(
    *, ruta_raiz: str, seccion_activa: Optional[str] = None, nav: Optional[Sequence[Tuple[str, str]]] = None,
    extras: Sequence[Tuple[str, str, str]] = (), config_sitio: Optional[dict] = None,
) -> str:
    """Cabecera fija: logo + buscador + menú. Debajo, la barra de secciones
    con desplazamiento horizontal (cómoda con el pulgar en el celular)."""
    nav = nav if nav is not None else SECCIONES_NAV
    items = []
    for slug, etiqueta in nav:
        activa = ' class="activa" aria-current="page"' if slug == seccion_activa else ""
        items.append(f'<a href="{ruta_raiz}categoria/{slug}/"{activa}>{escapar(etiqueta)}</a>')
    for slug, etiqueta, ruta in extras:
        activa = ' class="activa" aria-current="page"' if slug == seccion_activa else ""
        items.append(f'<a href="{ruta_raiz}{ruta}"{activa}>{escapar(etiqueta)}</a>')
    return f"""<header class="cabecera">
  <div class="ancho cabecera-fila">
    <a class="logo" href="{ruta_raiz}">LEDESMA <span>PARTICIPA</span></a>
    {_cta_seguir_cabecera(config_sitio)}
    <a class="cabecera-buscar" href="{ruta_raiz}buscar/" aria-label="Buscar">Buscar</a>
  </div>
  <nav class="nav" aria-label="Secciones">
    <div class="nav-pista">
      {chr(10).join(items)}
    </div>
  </nav>
</header>
"""


def insignias(n: dict, mostrar_territorio: bool = True, mostrar_categoria: bool = True) -> str:
    partes = []
    if n.get("urgente"):
        partes.append('<span class="insignia insignia-urgente">URGENTE</span>')
    if mostrar_territorio and n.get("territorio_etiqueta"):
        partes.append(f'<span class="insignia insignia-territorio">{escapar(n["territorio_etiqueta"])}</span>')
    if mostrar_categoria and n.get("categoria_tema_etiqueta"):
        clase = "insignia-servicio" if n.get("categoria_tema") == "servicios" else "insignia-categoria"
        partes.append(f'<span class="insignia {clase}">{escapar(n["categoria_tema_etiqueta"])}</span>')
    return f'<div class="insignias">{"".join(partes)}</div>' if partes else ""


def _media(n: dict, *, cargar: str = "lazy") -> str:
    """Foto real del hecho, o PLACA EDITORIAL GRÁFICA en CSS (carbón +
    dorado + titular + territorio) cuando no hay foto apta: nunca una imagen
    descontextualizada ni párrafos en miniatura."""
    if n.get("imagen_web"):
        return (
            f'<img src="{escapar(n["imagen_web"])}" alt="" loading="{cargar}" decoding="async" '
            f'width="800" height="500" referrerpolicy="no-referrer">'
        )
    clase = "placa-css placa-urgente" if n.get("urgente") else (
        "placa-css placa-servicio" if n.get("categoria_tema") == "servicios" else "placa-css")
    territorio = escapar(n.get("territorio_etiqueta") or "Ledesma Participa")
    return (
        f'<div class="{clase}" aria-hidden="true"><span class="placa-territorio">{territorio}</span>'
        f'<span class="placa-titulo">{escapar(n.get("titulo_placa") or n["titulo"])}</span>'
        f'<span class="placa-marca">LEDESMA PARTICIPA</span></div>'
    )


def tarjeta_noticia(n: dict, *, ruta_raiz: str, destacada: bool = False, variante: Optional[str] = None) -> str:
    """variante: "principal" (foto grande + bajada), "normal" (foto + titular)
    o "compacta" (miniatura a la izquierda, ideal para listas largas en el
    celular)."""
    variante = variante or ("principal" if destacada else "normal")
    clase = f"tarjeta tarjeta-{variante}" + (" tarjeta-con-urgente" if n.get("urgente") else "")
    resumen = f'<p class="tarjeta-resumen">{escapar(n["resumen"])}</p>' if variante == "principal" and n.get("resumen") else ""
    fuente = f' · {escapar(n["nombre_fuente"])}' if n.get("nombre_fuente") and variante != "compacta" else ""
    return f"""<article class="{clase}">
  <a class="tarjeta-enlace" href="{ruta_raiz}{n['url_relativa']}">
    <div class="tarjeta-media">{_media(n, cargar="eager" if variante == "principal" else "lazy")}</div>
    <div class="tarjeta-cuerpo">
      {insignias(n)}
      <h3 class="tarjeta-titulo">{escapar(n['titulo'])}</h3>
      {resumen}
      <p class="tarjeta-meta">{escapar(n['fecha_legible'])}{fuente}</p>
    </div>
  </a>
</article>
"""


def grilla_noticias(noticias: Iterable[dict], *, ruta_raiz: str, variante: str = "normal") -> str:
    return "\n".join(tarjeta_noticia(n, ruta_raiz=ruta_raiz, variante=variante) for n in noticias)


def bloque_urgentes(urgentes: List[dict], *, ruta_raiz: str) -> str:
    if not urgentes:
        return ""
    items = "\n".join(
        f'<li><a href="{ruta_raiz}{n["url_relativa"]}"><strong>{escapar(n.get("territorio_etiqueta") or "")}</strong> '
        f'{escapar(n["titulo"])}</a><span>{escapar(n["fecha_legible"])}</span></li>'
        for n in urgentes
    )
    return f"""<section class="bloque-urgente" aria-label="Urgente">
  <h2 class="bloque-urgente-titulo">URGENTE</h2>
  <ul>{items}</ul>
</section>"""


def _pesos(valor) -> str:
    if valor is None:
        return "No disponible"
    return "$" + f"{valor:,.0f}".replace(",", ".")


def bloque_clima_dolar(datos: Optional[dict], *, ruta_raiz: str, url_nota: Optional[str] = None) -> str:
    """Clima + Dólar de la mañana: lo que la fuente no entregó se muestra
    como "No disponible", nunca un valor inventado."""
    if not datos:
        return ""
    clima = datos.get("clima")
    if clima:
        bloque_clima = (
            f'<div class="cd-clima"><span class="cd-temp">{clima["temperatura_actual"]:.0f}°</span>'
            f'<span class="cd-detalle"><strong>{escapar(clima["descripcion"].capitalize())}</strong>'
            f'Mín {clima["temperatura_minima"]:.0f}° · Máx {clima["temperatura_maxima"]:.0f}° · '
            f'Lluvia {clima["probabilidad_lluvia"]:.0f}%</span></div>'
        )
    else:
        bloque_clima = '<div class="cd-clima"><span class="cd-detalle"><strong>Clima</strong>No disponible</span></div>'
    filas = []
    for clave, etiqueta in (("oficial", "Oficial"), ("blue", "Blue")):
        dolar = datos.get(clave)
        if dolar:
            filas.append(
                f'<tr><th scope="row">{etiqueta}</th><td>{_pesos(dolar["compra"])}</td><td>{_pesos(dolar["venta"])}</td></tr>'
            )
        else:
            filas.append(f'<tr><th scope="row">{etiqueta}</th><td colspan="2">No disponible</td></tr>')
    enlace = f'<a class="cd-enlace" href="{ruta_raiz}{url_nota}">Ver informe</a>' if url_nota else ""
    return f"""<section class="bloque-clima-dolar" aria-label="Clima y dólar">
  <div class="cd-encabezado"><h2>CLIMA + DÓLAR</h2><span>{escapar(datos.get("fecha_legible") or "")} · Libertador</span></div>
  <div class="cd-cuerpo">
    {bloque_clima}
    <table class="cd-dolar"><thead><tr><th>Dólar</th><th>Compra</th><th>Venta</th></tr></thead><tbody>{"".join(filas)}</tbody></table>
  </div>
  <p class="cd-pie">Actualizado {escapar(datos.get("actualizado") or "")} · Fuentes: {escapar(datos.get("fuentes") or "")} {enlace}</p>
</section>"""


def seccion_portada(slug: str, etiqueta: str, noticias: List[dict], *, ruta_raiz: str, ver_mas: Optional[str] = None) -> str:
    if not noticias:
        return ""
    ver_mas = ver_mas if ver_mas is not None else f"{ruta_raiz}categoria/{slug}/"
    primera, resto = noticias[0], noticias[1:]
    return f"""<section class="seccion-portada seccion-{escapar(slug)}">
  <div class="seccion-encabezado"><h2 class="titulo-seccion">{escapar(etiqueta)}</h2><a class="ver-mas" href="{ver_mas}">Ver más</a></div>
  <div class="grilla">{tarjeta_noticia(primera, ruta_raiz=ruta_raiz, variante="normal")}</div>
  <div class="lista-compacta">{grilla_noticias(resto, ruta_raiz=ruta_raiz, variante="compacta")}</div>
</section>"""


def tarjeta_video(v: dict, *, ruta_raiz: str) -> str:
    return f"""<article class="tarjeta-video">
  <a href="{ruta_raiz}videos/{escapar(v['id'])}/">
    <div class="video-miniatura"><img src="{escapar(v['miniatura'])}" alt="" loading="lazy" width="480" height="360" referrerpolicy="no-referrer"><span class="video-play" aria-hidden="true">▶</span></div>
    <h3>{escapar(v['titulo'])}</h3>
    {('<p class="tarjeta-meta">' + escapar(v['fuente']) + '</p>') if v.get('fuente') else ''}
  </a>
</article>"""


def bloque_videos(videos: List[dict], *, ruta_raiz: str) -> str:
    if not videos:
        return ""
    return f"""<section class="seccion-portada seccion-videos">
  <div class="seccion-encabezado"><h2 class="titulo-seccion">Videos</h2><a class="ver-mas" href="{ruta_raiz}videos/">Ver más</a></div>
  <div class="carril">{"".join(tarjeta_video(v, ruta_raiz=ruta_raiz) for v in videos[:6])}</div>
</section>"""


def tarjeta_comercio(c: dict, *, ruta_raiz: str) -> str:
    imagen = (
        f'<img src="{ruta_raiz}assets/guia/{escapar(c["imagenes"][0])}" alt="" loading="lazy" width="600" height="400">'
        if c.get("imagenes") else '<div class="placa-css placa-comercio" aria-hidden="true"><span class="placa-titulo">'
        + escapar(c["nombre"]) + "</span></div>"
    )
    rubro = f'<p class="comercio-rubro">{escapar(c["rubro"])}</p>' if c.get("rubro") else ""
    promo = f'<p class="comercio-promo">{escapar(c["promociones"][0])}</p>' if c.get("promociones") else ""
    medicion = _attrs_medicion("commercial_promo_open", c["slug"]) if c.get("promociones") else ""
    return f"""<article class="tarjeta-comercio">
  <a href="{ruta_raiz}guia-comercial/{escapar(c['slug'])}/"{medicion}>
    <div class="comercio-media">{imagen}</div>
    <div class="comercio-cuerpo"><h3>{escapar(c['nombre'])}</h3>{rubro}{promo}</div>
  </a>
</article>"""


def bloque_guia(comercios: List[dict], *, ruta_raiz: str) -> str:
    if not comercios:
        return ""
    return f"""<section class="seccion-portada seccion-guia" aria-label="Guía Comercial">
  <div class="seccion-encabezado"><h2 class="titulo-seccion">Guía Comercial</h2><a class="ver-mas" href="{ruta_raiz}guia-comercial/">Ver todos</a></div>
  <p class="guia-aviso">Espacio comercial: no es contenido periodístico.</p>
  <div class="carril">{"".join(tarjeta_comercio(c, ruta_raiz=ruta_raiz) for c in comercios)}</div>
</section>"""


def bloque_seguinos(config_sitio: dict) -> str:
    enlaces = _enlaces_sociales(config_sitio)
    if not enlaces:
        return ""
    botones = "".join(
        f'<a class="boton boton-red" href="{escapar(url)}" rel="noopener" target="_blank" '
        f'data-ev="follow_cta_click" data-k="{nombre.lower()}">{escapar(nombre)}</a>'
        for nombre, url in enlaces
    )
    return f"""<section class="bloque-seguinos">
  <h2>Seguí Ledesma Participa</h2>
  <p>Las noticias de Libertador y el Departamento Ledesma, también en redes.</p>
  <div class="botones">{botones}</div>
</section>"""


def bloque_radios_portada(cantidad_radios: int, *, ruta_raiz: str) -> str:
    if not cantidad_radios:
        return ""
    return f"""<section class="seccion-portada seccion-radios" aria-label="Radios en vivo">
  <div class="seccion-encabezado"><h2 class="titulo-seccion">Radios en vivo</h2><a class="ver-mas" href="{ruta_raiz}radios/">Ver todas</a></div>
  <p><a class="boton" href="{ruta_raiz}radios/">Escuchá las radios de la región</a></p>
</section>"""


def pagina_index(
    *,
    destacadas: List[dict],
    ultimas: List[dict],
    ruta_raiz: str,
    config_sitio: dict,
    url_base: str,
    portada: Optional[dict] = None,
    nav: Optional[Sequence[Tuple[str, str]]] = None,
    extras_nav: Sequence[Tuple[str, str, str]] = (),
) -> str:
    """Portada. `portada` (generador) trae: urgentes, clima_dolar
    (+url_informe), principal, secciones [(slug, etiqueta, noticias)],
    videos, comercios. Sin `portada` se usa el formato anterior
    (destacadas + últimas)."""
    partes = [
        cabecera_html(
            titulo_pagina="Ledesma Participa — Noticias de Libertador Gral. San Martín y Ledesma",
            descripcion=config_sitio.get("descripcion", ""),
            url_canonica=url_base,
            ruta_raiz=ruta_raiz,
        ),
        encabezado_html(config_sitio=config_sitio, ruta_raiz=ruta_raiz, nav=nav, extras=extras_nav),
        '<main class="ancho portada">',
        '<h1 class="solo-lectores">Ledesma Participa — Noticias de Libertador General San Martín y el Departamento Ledesma</h1>',
    ]
    if portada is None:
        if destacadas:
            partes.append('<div class="grilla">' + tarjeta_noticia(destacadas[0], ruta_raiz=ruta_raiz, destacada=True) + "</div>")
        if ultimas or destacadas[1:]:
            partes.append('<section class="seccion-portada"><h2 class="titulo-seccion">Últimas noticias</h2>')
            partes.append(f'<div class="lista-compacta">{grilla_noticias(destacadas[1:] + ultimas, ruta_raiz=ruta_raiz, variante="compacta")}</div></section>')
        if not destacadas and not ultimas:
            partes.append('<p class="vacio">Todavía no hay noticias publicadas.</p>')
    else:
        partes.append(bloque_urgentes(portada.get("urgentes", []), ruta_raiz=ruta_raiz))
        partes.append(bloque_clima_dolar(portada.get("clima_dolar"), ruta_raiz=ruta_raiz, url_nota=portada.get("url_informe")))
        if portada.get("principal"):
            partes.append('<section class="seccion-principal" aria-label="Noticia principal">'
                          + tarjeta_noticia(portada["principal"], ruta_raiz=ruta_raiz, variante="principal") + "</section>")
        for slug, etiqueta, noticias in portada.get("secciones", []):
            partes.append(seccion_portada(slug, etiqueta, noticias, ruta_raiz=ruta_raiz))
        partes.append(bloque_videos(portada.get("videos", []), ruta_raiz=ruta_raiz))
        partes.append(bloque_guia(portada.get("comercios", []), ruta_raiz=ruta_raiz))
        partes.append(bloque_radios_portada(portada.get("cantidad_radios", 0), ruta_raiz=ruta_raiz))
        partes.append(f'<p class="mas-noticias"><a class="boton" href="{ruta_raiz}categoria/ultimas/">Todas las últimas noticias</a></p>')
        partes.append(bloque_seguinos(config_sitio))
    partes.append("</main>")
    partes.append(cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio, pagina="home"))
    return "\n".join(p for p in partes if p)


def pagina_categoria(
    *, slug: str, etiqueta: str, noticias: List[dict], ruta_raiz: str, config_sitio: dict, url_base: str,
    nav: Optional[Sequence[Tuple[str, str]]] = None, extras_nav: Sequence[Tuple[str, str, str]] = (),
) -> str:
    titulo_pagina = f"{etiqueta} — Ledesma Participa"
    descripcion = f"Noticias de {etiqueta} en Ledesma Participa."
    partes = [
        cabecera_html(titulo_pagina=titulo_pagina, descripcion=descripcion, url_canonica=url_base, ruta_raiz=ruta_raiz),
        encabezado_html(config_sitio=config_sitio, ruta_raiz=ruta_raiz, seccion_activa=slug, nav=nav, extras=extras_nav),
        f'<main class="ancho"><h1 class="titulo-seccion">{escapar(etiqueta)}</h1>',
    ]
    if noticias:
        partes.append(f'<div class="grilla">{tarjeta_noticia(noticias[0], ruta_raiz=ruta_raiz, variante="normal")}</div>')
        partes.append(f'<div class="lista-compacta">{grilla_noticias(noticias[1:], ruta_raiz=ruta_raiz, variante="compacta")}</div>')
    else:
        partes.append('<p class="vacio">Todavía no hay noticias publicadas en esta sección.</p>')
    partes.append("</main>")
    partes.append(cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio, pagina="category", clave=slug))
    return "\n".join(partes)


def _botones_compartir(url: str, titulo: str) -> str:
    from urllib.parse import quote

    texto = quote(f"{titulo} {url}")
    return (
        '<div class="compartir"><span>Compartir:</span>'
        f'<a class="boton boton-chico" href="https://wa.me/?text={texto}" rel="noopener" target="_blank" data-ev="share_click" data-k="whatsapp">WhatsApp</a>'
        f'<a class="boton boton-chico" href="https://www.facebook.com/sharer/sharer.php?u={quote(url, safe="")}" rel="noopener" target="_blank" data-ev="share_click" data-k="facebook">Facebook</a>'
        "</div>"
    )


def pagina_noticia(
    *, n: dict, relacionadas: List[dict], ruta_raiz: str, config_sitio: dict, url_base: str,
    nav: Optional[Sequence[Tuple[str, str]]] = None, extras_nav: Sequence[Tuple[str, str, str]] = (),
    clima_dolar: Optional[dict] = None,
) -> str:
    titulo_pagina = f"{n['titulo']} — Ledesma Participa"
    parrafos = "\n".join(f"<p>{escapar(p)}</p>" for p in n["texto_parrafos"] if p.strip())
    if n.get("imagen_web"):
        figura = f'<figure class="noticia-figura"><img src="{escapar(n["imagen_web"])}" alt="{escapar(n["titulo"])}" referrerpolicy="no-referrer"></figure>'
    elif clima_dolar:
        figura = bloque_clima_dolar(clima_dolar, ruta_raiz=ruta_raiz)
    else:
        figura = f'<figure class="noticia-figura">{_media(n, cargar="eager")}</figure>'
    fuente_html = ""
    if n.get("url_fuente"):
        fuente_html = (
            f'<p class="noticia-fuente">Fuente y nota completa: '
            f'<a href="{escapar(n["url_fuente"])}" rel="noopener nofollow" target="_blank">'
            f'{escapar(n.get("nombre_fuente") or n["url_fuente"])}</a></p>'
        )
    elif n.get("nombre_fuente"):
        fuente_html = f'<p class="noticia-fuente">Fuente: {escapar(n["nombre_fuente"])}</p>'
    relacionadas_html = ""
    if relacionadas:
        relacionadas_html = (
            '<section class="seccion-relacionadas"><h2 class="titulo-seccion">También puede interesarte</h2>'
            f'<div class="lista-compacta">{grilla_noticias(relacionadas, ruta_raiz=ruta_raiz, variante="compacta")}</div></section>'
        )
    partes = [
        cabecera_html(
            titulo_pagina=titulo_pagina,
            descripcion=n["resumen"],
            url_canonica=url_base,
            ruta_raiz=ruta_raiz,
            imagen_og=n.get("imagen_og"),
            tipo_og="article",
            datos_estructurados=datos_news_article(n, url_base, config_sitio),
            metas_extra=(
                ("article:published_time", n.get("fecha_iso") or ""),
                ("article:modified_time", n.get("fecha_iso") or ""),
                ("article:section", n.get("seccion_etiqueta") or ""),
            ),
        ),
        encabezado_html(config_sitio=config_sitio, ruta_raiz=ruta_raiz, seccion_activa=n["seccion_slug"], nav=nav, extras=extras_nav),
        f"""<main class="ancho ancho-articulo">
<article class="noticia{' noticia-urgente' if n.get('urgente') else ''}">
  <p class="migas"><a href="{ruta_raiz}categoria/{n['seccion_slug']}/">{escapar(n['seccion_etiqueta'])}</a></p>
  {insignias(n)}
  <h1 class="noticia-titulo">{escapar(n['titulo'])}</h1>
  <p class="noticia-meta">{escapar(n['fecha_legible'])}{(' · ' + escapar(n['nombre_fuente'])) if n.get('nombre_fuente') else ''}</p>
  {('<p class="noticia-meta">Publicada originalmente por la fuente: ' + escapar(n['fecha_fuente_legible']) + '</p>') if n.get('fecha_fuente_legible') else ''}
  {figura}
  <div class="noticia-cuerpo">
  {parrafos}
  </div>
  {fuente_html}
  {_botones_compartir(url_base, n['titulo'])}
</article>
{relacionadas_html}
{bloque_seguinos(config_sitio)}
</main>""",
        cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio, pagina="article", clave=n["id"]),
    ]
    return "\n".join(partes)


def datos_news_article(n: dict, url: str, config_sitio: dict) -> dict:
    """Datos estructurados schema.org NewsArticle. Sin autor falso: autor y
    editor son la organización (Ledesma Participa) y la fuente original va
    en `isBasedOn`. `image` solo si la nota tiene una imagen real propia
    (nunca el banner genérico)."""
    nombre = config_sitio.get("nombre") or "Ledesma Participa"
    base = (config_sitio.get("base_url_produccion") or "").rstrip("/") + "/"
    organizacion = {"@type": "NewsMediaOrganization", "name": nombre, "url": base}
    datos = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": n["titulo"][:110],
        "description": n.get("resumen") or "",
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "url": url,
        "author": organizacion,
        "publisher": dict(organizacion, logo={"@type": "ImageObject", "url": base + "assets/img/og-default-v2.png"}),
        "inLanguage": "es-AR",
        "articleSection": n.get("seccion_etiqueta") or "",
    }
    if n.get("fecha_iso"):
        datos["datePublished"] = n["fecha_iso"]
        datos["dateModified"] = n["fecha_iso"]
    if n.get("imagen_og_propia"):
        datos["image"] = [n["imagen_og_propia"]]
    lugar = n.get("territorio_etiqueta_completa")
    if n.get("territorio") in ("local", "departamental", "provincial") and lugar:
        datos["contentLocation"] = {"@type": "Place", "name": lugar}
    if n.get("url_fuente"):
        datos["isBasedOn"] = n["url_fuente"]
    return datos


def pagina_guia(*, comercios: List[dict], ruta_raiz: str, config_sitio: dict, url_base: str,
                nav=None, extras_nav=()) -> str:
    partes = [
        cabecera_html(
            titulo_pagina="Guía Comercial — Ledesma Participa",
            descripcion="Guía Comercial Ledesma Participa: comercios y servicios de la zona.",
            url_canonica=url_base, ruta_raiz=ruta_raiz,
        ),
        encabezado_html(config_sitio=config_sitio, ruta_raiz=ruta_raiz, seccion_activa="guia-comercial", nav=nav, extras=extras_nav),
        '<main class="ancho"><h1 class="titulo-seccion">Guía Comercial</h1>',
        '<p class="guia-aviso">Espacio comercial: no es contenido periodístico.</p>',
        f'<div class="grilla grilla-comercios">{"".join(tarjeta_comercio(c, ruta_raiz=ruta_raiz) for c in comercios)}</div>'
        if comercios else '<p class="vacio">Todavía no hay comercios en la guía.</p>',
        "</main>",
        cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio, pagina="guia"),
    ]
    return "\n".join(partes)


def _evento_contacto_comercial(url: str) -> str:
    url = (url or "").lower()
    if "wa.me" in url or "whatsapp" in url:
        return "commercial_whatsapp_click"
    if "instagram.com" in url:
        return "commercial_instagram_click"
    return ""


def _attrs_medicion(evento: str, clave: str) -> str:
    return f' data-ev="{evento}" data-k="{escapar(clave)}"' if evento else ""


def pagina_comercio(*, c: dict, ruta_raiz: str, config_sitio: dict, url_base: str, nav=None, extras_nav=()) -> str:
    datos = []
    if c.get("rubro"):
        datos.append(("Rubro", escapar(c["rubro"])))
    if c.get("direccion"):
        datos.append(("Dirección", escapar(c["direccion"])))
    if c.get("horarios"):
        datos.append(("Horarios", escapar(c["horarios"])))
    if c.get("whatsapp_url"):
        datos.append(("WhatsApp", f'<a href="{escapar(c["whatsapp_url"])}" rel="noopener" target="_blank"'
                      f'{_attrs_medicion("commercial_whatsapp_click", c["slug"])}>{escapar(c["whatsapp"])}</a>'))
    if c.get("telefono"):
        datos.append(("Teléfono", escapar(c["telefono"])))
    if c.get("instagram_url"):
        datos.append(("Instagram", f'<a href="{escapar(c["instagram_url"])}" rel="noopener" target="_blank"'
                      f'{_attrs_medicion("commercial_instagram_click", c["slug"])}>{escapar(c["instagram"])}</a>'))
    if c.get("facebook"):
        datos.append(("Facebook", f'<a href="{escapar(c["facebook"])}" rel="noopener" target="_blank">Facebook</a>'))
    filas = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in datos)
    promos = ""
    if c.get("promociones"):
        promos = '<section class="comercio-promos"><h2>Promociones</h2><ul>' + "".join(
            f"<li>{escapar(p)}</li>" for p in c["promociones"]) + "</ul></section>"
    imagenes = "".join(
        f'<img src="{ruta_raiz}assets/guia/{escapar(img)}" alt="{escapar(c["nombre"])}" loading="lazy">' for img in c.get("imagenes", [])
    )
    boton = ""
    if c.get("contacto"):
        boton = (
            f'<a class="boton boton-contacto" href="{escapar(c["contacto"]["url"])}" rel="noopener" target="_blank"'
            f'{_attrs_medicion(_evento_contacto_comercial(c["contacto"]["url"]), c["slug"])}>{escapar(c["contacto"]["etiqueta"])}</a>'
        )
    partes = [
        cabecera_html(
            titulo_pagina=f"{c['nombre']} — Guía Comercial Ledesma Participa",
            descripcion=c.get("descripcion") or f"{c['nombre']} en la Guía Comercial Ledesma Participa.",
            url_canonica=url_base, ruta_raiz=ruta_raiz,
        ),
        encabezado_html(config_sitio=config_sitio, ruta_raiz=ruta_raiz, seccion_activa="guia-comercial", nav=nav, extras=extras_nav),
        f"""<main class="ancho ancho-articulo">
<article class="ficha-comercio">
  <p class="migas"><a href="{ruta_raiz}guia-comercial/">Guía Comercial</a></p>
  <p class="guia-aviso">Espacio comercial</p>
  <h1 class="noticia-titulo">{escapar(c['nombre'])}</h1>
  {('<p class="comercio-descripcion">' + escapar(c['descripcion']) + '</p>') if c.get('descripcion') else ''}
  {boton}
  {('<dl class="comercio-datos">' + filas + '</dl>') if filas else ''}
  {promos}
  {('<div class="comercio-galeria">' + imagenes + '</div>') if imagenes else ''}
</article>
</main>""",
        cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio, pagina="commercial", clave=c["slug"]),
    ]
    return "\n".join(partes)


def reproductor_youtube(v: dict) -> str:
    return (
        f'<div class="video-marco"><iframe src="{escapar(v["embed_url"])}" title="{escapar(v["titulo"])}" '
        'loading="lazy" allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
        'referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe></div>'
    )


def pagina_videos(*, videos: List[dict], ruta_raiz: str, config_sitio: dict, url_base: str, nav=None, extras_nav=()) -> str:
    partes = [
        cabecera_html(titulo_pagina="Videos — Ledesma Participa", descripcion="Videos en Ledesma Participa.",
                      url_canonica=url_base, ruta_raiz=ruta_raiz),
        encabezado_html(config_sitio=config_sitio, ruta_raiz=ruta_raiz, seccion_activa="videos", nav=nav, extras=extras_nav),
        '<main class="ancho"><h1 class="titulo-seccion">Videos</h1>',
        f'<div class="grilla grilla-videos">{"".join(tarjeta_video(v, ruta_raiz=ruta_raiz) for v in videos)}</div>'
        if videos else '<p class="vacio">Todavía no hay videos.</p>',
        "</main>",
        cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio),
    ]
    return "\n".join(partes)


def pagina_video(*, v: dict, ruta_raiz: str, config_sitio: dict, url_base: str, nav=None, extras_nav=()) -> str:
    """Página propia de cada video: reproductor oficial de YouTube embebido
    (la app la abre en su WebView). Siempre indica el canal/fuente."""
    fuente = f'<p class="noticia-fuente">Fuente: {escapar(v["fuente"])} · <a href="{escapar(v["url_youtube"])}" rel="noopener" target="_blank">Ver en YouTube</a></p>' if v.get("fuente") else (
        f'<p class="noticia-fuente"><a href="{escapar(v["url_youtube"])}" rel="noopener" target="_blank">Ver en YouTube</a></p>')
    partes = [
        cabecera_html(titulo_pagina=f"{v['titulo']} — Videos — Ledesma Participa", descripcion=v.get("descripcion") or v["titulo"],
                      url_canonica=url_base, ruta_raiz=ruta_raiz, imagen_og=v["miniatura"], tipo_og="video.other"),
        encabezado_html(config_sitio=config_sitio, ruta_raiz=ruta_raiz, seccion_activa="videos", nav=nav, extras=extras_nav),
        f"""<main class="ancho ancho-articulo">
  <p class="migas"><a href="{ruta_raiz}videos/">Videos</a></p>
  <h1 class="noticia-titulo">{escapar(v['titulo'])}</h1>
  {reproductor_youtube(v)}
  {('<p>' + escapar(v['descripcion']) + '</p>') if v.get('descripcion') else ''}
  {fuente}
</main>""",
        cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio, pagina="video", clave=v["id"]),
    ]
    return "\n".join(partes)


ESTADOS_RADIO = {
    # estado_transmision → (texto visible, clase). Solo se muestra lo verificado.
    "en_vivo": ("EN VIVO", "radio-estado-vivo"),
    "no_disponible": ("Transmisión no disponible temporalmente", "radio-estado-caido"),
    "sin_transmision": ("Sin transmisión online disponible", "radio-estado-sin"),
}


def tarjeta_radio(r: dict) -> str:
    """[LOGO] NOMBRE / dial / localidad / [ESCUCHAR EN VIVO]. El botón usa
    solo la URL oficial; sin stream ni player oficial no hay botón."""
    nombre = escapar(r["nombre"])
    dial = escapar(r.get("dial") or "")
    texto_estado, clase_estado = ESTADOS_RADIO.get(r.get("estado_transmision"), ("", ""))
    estado = f'<p class="radio-estado {clase_estado}">{escapar(texto_estado)}</p>' if texto_estado else ""
    if r.get("logo_url"):
        logo = f'<img class="radio-logo" src="{escapar(r["logo_url"])}" alt="" loading="lazy" referrerpolicy="no-referrer">'
    else:
        iniciales = escapar("".join(p[0] for p in r["nombre"].split()[:2]).upper())
        logo = f'<div class="radio-logo radio-logo-placa" aria-hidden="true">{iniciales}</div>'
    etiqueta = escapar(f"Escuchar en vivo {r['nombre']} {r.get('dial') or ''}".strip())
    if r.get("stream_url"):
        accion = (
            f'<button type="button" class="boton boton-escuchar" data-radio-id="{escapar(r["id"])}" '
            f'data-stream="{escapar(r["stream_url"])}" data-tipo="{escapar(r.get("tipo_stream") or "")}" '
            f'data-nombre="{nombre}" data-dial="{dial}" '
            f'aria-label="{etiqueta}">&#9654; Escuchar en vivo</button>'
        )
    elif r.get("player_url"):
        accion = (
            f'<a class="boton boton-escuchar" href="{escapar(r["player_url"])}" target="_blank" rel="noopener" '
            f'aria-label="{etiqueta} (abre el reproductor oficial de la radio)">&#9654; Escuchar en vivo</a>'
        )
    else:
        accion = ""
    enlaces = " · ".join(
        f'<a href="{escapar(r[clave])}" target="_blank" rel="noopener">{texto}</a>'
        for clave, texto in (("sitio_web", "Sitio web"), ("facebook", "Facebook"), ("instagram", "Instagram"))
        if r.get(clave)
    )
    if r.get("stream_url") and r.get("player_url"):
        # Alternativa oficial si el navegador no reproduce el stream (p. ej. HLS).
        oficial = f'<a href="{escapar(r["player_url"])}" target="_blank" rel="noopener">Reproductor oficial</a>'
        enlaces = f"{enlaces} · {oficial}" if enlaces else oficial
    buscable = escapar(" ".join(filter(None, (r["nombre"], r.get("dial"), r.get("localidad"), r["zona"]))).lower())
    return f"""<article class="tarjeta-radio" data-zona="{escapar(r['zona_slug'])}" data-buscable="{buscable}">
  {logo}
  <div class="radio-cuerpo">
    <h2 class="radio-nombre">{nombre}</h2>
    {f'<p class="radio-dial">{dial}</p>' if dial else ''}
    {f'<p class="radio-localidad">{escapar(r["localidad"])}</p>' if r.get('localidad') else ''}
    {estado}
    {accion}
    {f'<p class="radio-enlaces">{enlaces}</p>' if enlaces else ''}
  </div>
</article>"""


def pagina_radios(*, radios: List[dict], ruta_raiz: str, config_sitio: dict, url_base: str, nav=None, extras_nav=()) -> str:
    zonas_con_radios = [(e, s) for e, s in ZONAS_RADIO if any(r["zona_slug"] == s for r in radios)]
    filtros = ""
    if radios:
        chips = ['<button type="button" class="chip-zona" data-zona="" aria-pressed="true">Todas</button>']
        chips += [f'<button type="button" class="chip-zona" data-zona="{s}" aria-pressed="false">{escapar(e)}</button>'
                  for e, s in zonas_con_radios]
        filtros = f"""<div class="radios-filtros" role="group" aria-label="Filtrar por zona">{''.join(chips)}</div>
  <label class="radios-buscar"><span class="solo-lectores">Buscar radio</span>
    <input type="search" id="radios-buscar" placeholder="Buscar por nombre, dial o localidad" autocomplete="off"></label>"""
    cuerpo = (
        f'<div class="grilla-radios" id="radios-lista">{"".join(tarjeta_radio(r) for r in radios)}</div>'
        '<p class="vacio" id="radios-sin-resultados" hidden>No hay radios para ese filtro.</p>'
        if radios else
        '<p class="vacio">Estamos sumando las radios de la zona. Solo incluimos emisoras con transmisión oficial.</p>'
    )
    partes = [
        cabecera_html(titulo_pagina="Radios en vivo — Ledesma Participa",
                      descripcion="Radios de Libertador, el Departamento Ledesma, Jujuy y Argentina en vivo.",
                      url_canonica=url_base, ruta_raiz=ruta_raiz),
        encabezado_html(config_sitio=config_sitio, ruta_raiz=ruta_raiz, seccion_activa="radios", nav=nav, extras=extras_nav),
        f"""<main class="ancho">
  <p class="migas"><a href="{ruta_raiz}multimedia/">Multimedia</a></p>
  <h1 class="titulo-seccion">Radios en vivo</h1>
  {filtros}
  {cuerpo}
  <p class="radios-nota">Cada radio se escucha desde su transmisión oficial. Ledesma Participa no graba ni retransmite señales.</p>
</main>""",
        cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio),
    ]
    return "\n".join(partes)


def pagina_multimedia(*, hay_videos: bool, cantidad_radios: int, ruta_raiz: str, config_sitio: dict, url_base: str,
                      nav=None, extras_nav=()) -> str:
    """Multimedia: Videos, Radios en vivo y, como próximamente (sin
    enlace), Entrevistas y Podcast."""
    def item(titulo: str, detalle: str, ruta: Optional[str]) -> str:
        if ruta:
            return (f'<li><a class="multimedia-item" href="{ruta_raiz}{ruta}"><strong>{titulo}</strong>'
                    f'<span>{detalle}</span></a></li>')
        return (f'<li><div class="multimedia-item multimedia-proximamente" aria-disabled="true"><strong>{titulo}</strong>'
                f'<span>{detalle}</span></div></li>')
    radios_detalle = (f"{cantidad_radios} emisora{'s' if cantidad_radios != 1 else ''} con transmisión oficial"
                      if cantidad_radios else "Libertador, Departamento Ledesma, Jujuy y Argentina")
    partes = [
        cabecera_html(titulo_pagina="Multimedia — Ledesma Participa", descripcion="Videos y radios en vivo en Ledesma Participa.",
                      url_canonica=url_base, ruta_raiz=ruta_raiz),
        encabezado_html(config_sitio=config_sitio, ruta_raiz=ruta_raiz, seccion_activa="multimedia", nav=nav, extras=extras_nav),
        f"""<main class="ancho">
  <h1 class="titulo-seccion">Multimedia</h1>
  <ul class="lista-multimedia">
    {item("Videos", "Reproductor oficial de YouTube" if hay_videos else "Todavía no hay videos", "videos/")}
    {item("Radios en vivo", radios_detalle, "radios/")}
    {item("Entrevistas", "Próximamente", None)}
    {item("Podcast", "Próximamente", None)}
  </ul>
</main>""",
        cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio),
    ]
    return "\n".join(partes)


def pagina_contacto(*, ruta_raiz: str, config_sitio: dict, url_base: str, nav=None, extras_nav=()) -> str:
    email = config_sitio.get("email_contacto", "")
    sitio = (config_sitio.get("base_url_produccion") or "").rstrip("/") + "/"
    nombre = config_sitio.get("nombre", "Ledesma Participa")
    partes = [
        cabecera_html(
            titulo_pagina="Contacto — Ledesma Participa",
            descripcion="Datos de contacto de Ledesma Participa: correo, sitio web y vías de consulta.",
            url_canonica=url_base,
            ruta_raiz=ruta_raiz,
        ),
        encabezado_html(config_sitio=config_sitio, ruta_raiz=ruta_raiz, nav=nav, extras=extras_nav),
        f"""<main class="ancho ancho-articulo">
  <h1 class="titulo-seccion">Contacto</h1>
  <p>Para consultas, correcciones, información, reclamos o contacto con
  {escapar(nombre)}, podés comunicarte a través del correo indicado.</p>
  <ul>
    <li><strong>Medio:</strong> {escapar(nombre)}</li>
    <li><strong>Correo:</strong> <a href="mailto:{escapar(email)}">{escapar(email)}</a></li>
    <li><strong>Sitio:</strong> <a href="{escapar(sitio)}">{escapar(sitio)}</a></li>
  </ul>
</main>""",
        cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio),
    ]
    return "\n".join(partes)


def pagina_buscar(*, ruta_raiz: str, config_sitio: dict, url_base: str, nav=None, extras_nav=()) -> str:
    partes = [
        cabecera_html(
            titulo_pagina="Buscar — Ledesma Participa",
            descripcion="Buscador de noticias publicadas por Ledesma Participa.",
            url_canonica=url_base,
            ruta_raiz=ruta_raiz,
        ),
        encabezado_html(config_sitio=config_sitio, ruta_raiz=ruta_raiz, nav=nav, extras=extras_nav),
        f"""<main class="ancho">
  <h1 class="titulo-seccion">Buscar noticias</h1>
  <input type="search" id="buscador-input" class="buscador-input" placeholder="Escribí un tema, barrio o palabra clave…" autofocus>
  <div id="buscador-resultados" class="lista-compacta"></div>
  <p id="buscador-vacio" class="vacio" hidden>Sin resultados. Probá con otra palabra.</p>
</main>
<script src="{ruta_raiz}assets/site.js" data-base="{ruta_raiz}"></script>""",
        cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio),
    ]
    return "\n".join(partes)
