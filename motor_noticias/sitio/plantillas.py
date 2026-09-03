"""Plantillas HTML del sitio público (texto plano, sin motor de templates:
el proyecto no depende de Jinja2 ni de nada fuera de la librería estándar).
Toda variable interpolada que pueda contener texto de una noticia pasa por
`escapar()` antes de incrustarse."""
import html
from typing import Iterable, List, Optional

COLOR_FONDO_MARCA = "#1f1a10"
COLOR_ORO = "#d4af37"
COLOR_NARANJA = "#e8631c"


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
) -> str:
    css_href = css_href or f"{ruta_raiz}assets/site.css"
    metas_og = [
        _tag_meta("og:title", titulo_pagina, propiedad=True),
        _tag_meta("og:description", descripcion, propiedad=True),
        _tag_meta("og:type", tipo_og, propiedad=True),
        _tag_meta("og:url", url_canonica, propiedad=True),
        _tag_meta("og:site_name", "Ledesma Participa", propiedad=True),
        _tag_meta("twitter:card", "summary_large_image"),
        _tag_meta("twitter:title", titulo_pagina),
        _tag_meta("twitter:description", descripcion),
    ]
    if imagen_og:
        metas_og.append(_tag_meta("og:image", imagen_og, propiedad=True))
        metas_og.append(_tag_meta("twitter:image", imagen_og))

    return f"""<!DOCTYPE html>
<html lang="es-AR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escapar(titulo_pagina)}</title>
<meta name="description" content="{escapar(descripcion)}">
<link rel="canonical" href="{escapar(url_canonica)}">
<link rel="icon" href="{ruta_raiz}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{css_href}">
{chr(10).join(metas_og)}
</head>
<body>
"""


PIE_HTML_PLANTILLA = """
<footer class="pie">
  <div class="ancho">
    <p class="pie-marca">LEDESMA PARTICIPA</p>
    <p>{descripcion}</p>
    <p class="pie-enlaces">
      {enlaces_sociales}
      <a href="{ruta_raiz}contacto/">Contacto</a>
      <a href="{ruta_raiz}privacy.html">Privacidad</a>
      <a href="{ruta_raiz}data-deletion.html">Eliminación de datos</a>
    </p>
    <p class="pie-nota">Sitio generado automáticamente a partir de las publicaciones de Ledesma Participa. Contacto: {email}</p>
  </div>
</footer>
</body>
</html>
"""


def cierre_html(*, ruta_raiz: str, config_sitio: dict) -> str:
    enlaces = []
    if config_sitio.get("facebook_url"):
        enlaces.append(f'<a href="{escapar(config_sitio["facebook_url"])}" rel="noopener" target="_blank">Facebook</a>')
    if config_sitio.get("instagram_url"):
        enlaces.append(f'<a href="{escapar(config_sitio["instagram_url"])}" rel="noopener" target="_blank">Instagram</a>')
    return PIE_HTML_PLANTILLA.format(
        descripcion=escapar(config_sitio.get("descripcion", "")),
        enlaces_sociales="\n      ".join(enlaces),
        ruta_raiz=ruta_raiz,
        email=escapar(config_sitio.get("email_contacto", "")),
    )


SECCIONES_NAV = (
    ("libertador", "Libertador"),
    ("ledesma", "Ledesma"),
    ("jujuy", "Jujuy"),
    ("nacionales", "Nacionales"),
    ("entretenimiento", "Entretenimiento"),
)


def encabezado_html(*, ruta_raiz: str, seccion_activa: Optional[str] = None) -> str:
    items_nav = []
    for slug, etiqueta in SECCIONES_NAV:
        activa = ' class="activa"' if slug == seccion_activa else ""
        items_nav.append(f'<a href="{ruta_raiz}categoria/{slug}/"{activa}>{etiqueta}</a>')
    nav = "\n      ".join(items_nav)
    return f"""<header class="cabecera">
  <div class="ancho cabecera-fila">
    <a class="logo" href="{ruta_raiz}">LEDESMA <span>PARTICIPA</span></a>
    <input type="checkbox" id="menu-toggle" class="menu-toggle">
    <label for="menu-toggle" class="menu-boton" aria-label="Abrir menú">☰</label>
    <nav class="nav">
      {nav}
      <a href="{ruta_raiz}buscar/">Buscar</a>
      <a href="{ruta_raiz}contacto/">Contacto</a>
    </nav>
  </div>
</header>
"""


def tarjeta_noticia(n: dict, *, ruta_raiz: str, destacada: bool = False) -> str:
    clase = "tarjeta tarjeta-destacada" if destacada else "tarjeta"
    if n["imagen_web"]:
        media = f'<img src="{escapar(n["imagen_web"])}" alt="" loading="lazy" width="600" height="600">'
    else:
        media = '<div class="tarjeta-sin-imagen" aria-hidden="true">LP</div>'
    return f"""<article class="{clase}">
  <a class="tarjeta-enlace" href="{ruta_raiz}{n['url_relativa']}">
    <div class="tarjeta-media">{media}<span class="etiqueta-seccion">{escapar(n['seccion_etiqueta'])}</span></div>
    <div class="tarjeta-cuerpo">
      <h2 class="tarjeta-titulo">{escapar(n['titulo'])}</h2>
      <p class="tarjeta-resumen">{escapar(n['resumen'])}</p>
      <p class="tarjeta-meta">{escapar(n['fecha_legible'])}{(' · ' + escapar(n['nombre_fuente'])) if n.get('nombre_fuente') else ''}</p>
    </div>
  </a>
</article>
"""


def grilla_noticias(noticias: Iterable[dict], *, ruta_raiz: str) -> str:
    return "\n".join(tarjeta_noticia(n, ruta_raiz=ruta_raiz) for n in noticias)


def pagina_index(*, destacadas: List[dict], ultimas: List[dict], ruta_raiz: str, config_sitio: dict, url_base: str) -> str:
    cuerpo_destacadas = "\n".join(
        tarjeta_noticia(n, ruta_raiz=ruta_raiz, destacada=(i == 0)) for i, n in enumerate(destacadas)
    )
    cuerpo_ultimas = grilla_noticias(ultimas, ruta_raiz=ruta_raiz)
    partes = [
        cabecera_html(
            titulo_pagina="Ledesma Participa — Noticias de Libertador Gral. San Martín y Ledesma",
            descripcion=config_sitio.get("descripcion", ""),
            url_canonica=url_base,
            ruta_raiz=ruta_raiz,
        ),
        encabezado_html(ruta_raiz=ruta_raiz),
        '<main class="ancho">',
    ]
    if destacadas:
        partes.append('<section class="seccion-destacadas"><h1 class="titulo-seccion">Destacadas</h1>')
        partes.append(f'<div class="grilla grilla-destacadas">{cuerpo_destacadas}</div></section>')
    partes.append('<section class="seccion-ultimas"><h2 class="titulo-seccion">Últimas noticias</h2>')
    if ultimas:
        partes.append(f'<div class="grilla">{cuerpo_ultimas}</div>')
    else:
        partes.append('<p class="vacio">Todavía no hay noticias publicadas.</p>')
    partes.append("</section></main>")
    partes.append(cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio))
    return "\n".join(partes)


def pagina_categoria(*, slug: str, etiqueta: str, noticias: List[dict], ruta_raiz: str, config_sitio: dict, url_base: str) -> str:
    titulo_pagina = f"{etiqueta} — Ledesma Participa"
    descripcion = f"Noticias de {etiqueta} publicadas por Ledesma Participa."
    partes = [
        cabecera_html(
            titulo_pagina=titulo_pagina,
            descripcion=descripcion,
            url_canonica=url_base,
            ruta_raiz=ruta_raiz,
        ),
        encabezado_html(ruta_raiz=ruta_raiz, seccion_activa=slug),
        f'<main class="ancho"><h1 class="titulo-seccion">{escapar(etiqueta)}</h1>',
    ]
    if noticias:
        partes.append(f'<div class="grilla">{grilla_noticias(noticias, ruta_raiz=ruta_raiz)}</div>')
    else:
        partes.append('<p class="vacio">Todavía no hay noticias publicadas en esta sección.</p>')
    partes.append("</main>")
    partes.append(cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio))
    return "\n".join(partes)


def pagina_noticia(*, n: dict, relacionadas: List[dict], ruta_raiz: str, config_sitio: dict, url_base: str) -> str:
    titulo_pagina = f"{n['titulo']} — Ledesma Participa"
    parrafos = "\n".join(f"<p>{escapar(p)}</p>" for p in n["texto_parrafos"] if p.strip())
    if n["imagen_web"]:
        figura = f'<figure class="noticia-figura"><img src="{escapar(n["imagen_web"])}" alt="{escapar(n["titulo"])}"></figure>'
    else:
        figura = ""
    fuente_html = ""
    if n.get("url_fuente"):
        fuente_html = (
            f'<p class="noticia-fuente">Fuente y nota completa: '
            f'<a href="{escapar(n["url_fuente"])}" rel="noopener nofollow" target="_blank">'
            f'{escapar(n.get("nombre_fuente") or n["url_fuente"])}</a></p>'
        )
    relacionadas_html = ""
    if relacionadas:
        relacionadas_html = (
            '<section class="seccion-relacionadas"><h2 class="titulo-seccion">Más de ' + escapar(n["seccion_etiqueta"]) + '</h2>'
            f'<div class="grilla">{grilla_noticias(relacionadas, ruta_raiz=ruta_raiz)}</div></section>'
        )
    partes = [
        cabecera_html(
            titulo_pagina=titulo_pagina,
            descripcion=n["resumen"],
            url_canonica=url_base,
            ruta_raiz=ruta_raiz,
            imagen_og=n.get("imagen_og"),
            tipo_og="article",
        ),
        encabezado_html(ruta_raiz=ruta_raiz, seccion_activa=n["seccion_slug"]),
        f"""<main class="ancho ancho-articulo">
<article class="noticia">
  <p class="migas"><a href="{ruta_raiz}categoria/{n['seccion_slug']}/">{escapar(n['seccion_etiqueta'])}</a></p>
  <h1 class="noticia-titulo">{escapar(n['titulo'])}</h1>
  <p class="noticia-meta">{escapar(n['fecha_legible'])}{(' · ' + escapar(n['nombre_fuente'])) if n.get('nombre_fuente') else ''}</p>
  {figura}
  <div class="noticia-cuerpo">
  {parrafos}
  </div>
  {fuente_html}
</article>
{relacionadas_html}
</main>""",
        cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio),
    ]
    return "\n".join(partes)


def pagina_contacto(*, ruta_raiz: str, config_sitio: dict, url_base: str) -> str:
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
        encabezado_html(ruta_raiz=ruta_raiz),
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


def pagina_buscar(*, ruta_raiz: str, config_sitio: dict, url_base: str) -> str:
    partes = [
        cabecera_html(
            titulo_pagina="Buscar — Ledesma Participa",
            descripcion="Buscador de noticias publicadas por Ledesma Participa.",
            url_canonica=url_base,
            ruta_raiz=ruta_raiz,
        ),
        encabezado_html(ruta_raiz=ruta_raiz),
        f"""<main class="ancho">
  <h1 class="titulo-seccion">Buscar noticias</h1>
  <input type="search" id="buscador-input" class="buscador-input" placeholder="Escribí un tema, barrio o palabra clave…" autofocus>
  <div id="buscador-resultados" class="grilla"></div>
  <p id="buscador-vacio" class="vacio" hidden>Sin resultados. Probá con otra palabra.</p>
</main>
<script src="{ruta_raiz}assets/site.js" data-base="{ruta_raiz}"></script>""",
        cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio),
    ]
    return "\n".join(partes)
