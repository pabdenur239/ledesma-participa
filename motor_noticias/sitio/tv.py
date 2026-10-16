"""TV en vivo (/tv/): señales informativas OFICIALES desde config/tv.json.

Solo se muestran canales con embed permitido: canal oficial de YouTube
(embed live_stream por ID de canal) o reproductor oficial del canal (iframe
https). No se descarga, graba ni retransmite nada. Para sumar una provincia o
canal se edita el JSON (regiones/canales), sin tocar código."""
import json
import re
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .plantillas import cabecera_html, cierre_html, encabezado_html, escapar

RAIZ = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH_DEFAULT = RAIZ / "config" / "tv.json"
_RE_YT = re.compile(r"^UC[\w-]{22}$")


def cargar_canales(path: Optional[Path] = None) -> List[dict]:
    """[{'region_id','region','canales':[...]}] solo con canales activos y válidos."""
    try:
        datos = json.loads((path or CONFIG_PATH_DEFAULT).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    grupos = []
    for region in datos.get("regiones", []):
        canales = []
        for c in datos.get("canales", []):
            if c.get("region") != region.get("id") or c.get("activa") is not True or not c.get("nombre"):
                continue
            fuente = c.get("fuente") or ""
            if c.get("tipo") == "youtube" and _RE_YT.match(fuente):
                canales.append(c)
            elif c.get("tipo") == "iframe" and fuente.startswith("https://"):
                canales.append(c)
        if canales:
            grupos.append({"region_id": region["id"], "region": region["etiqueta"], "canales": canales})
    return grupos


def cantidad_canales(grupos: List[dict]) -> int:
    return sum(len(g["canales"]) for g in grupos)


def pagina_tv(
    *, grupos: List[dict], ruta_raiz: str, config_sitio: dict, url_base: str,
    nav: Optional[Sequence[Tuple[str, str]]] = None, extras_nav: Sequence[Tuple[str, str, str]] = (),
) -> str:
    bloques = []
    for g in grupos:
        botones = "".join(
            f'<button type="button" class="boton boton-tv" data-tv-tipo="{escapar(c["tipo"])}" '
            f'data-fuente="{escapar(c["fuente"])}" data-nombre="{escapar(c["nombre"])}">{escapar(c["nombre"])}</button>'
            for c in g["canales"]
        )
        bloques.append(
            f'<section class="bloque-tv" id="tv-{escapar(g["region_id"])}"><h2 class="titulo-seccion">{escapar(g["region"])}</h2>'
            f'<div class="lista-tv">{botones}</div></section>'
        )
    cuerpo = "".join(bloques) or '<p class="vacio">Estamos sumando señales oficiales.</p>'
    return "\n".join(
        [
            cabecera_html(
                titulo_pagina="TV en vivo — Ledesma Participa",
                descripcion="Señales informativas oficiales de Jujuy y Argentina en vivo.",
                url_canonica=url_base, ruta_raiz=ruta_raiz,
            ),
            encabezado_html(config_sitio=config_sitio, ruta_raiz=ruta_raiz, seccion_activa="tv", nav=nav, extras=extras_nav),
            f"""<main class="ancho">
  <p class="migas"><a href="{ruta_raiz}multimedia/">Multimedia</a></p>
  <h1 class="titulo-seccion">TV en vivo</h1>
  <div id="reproductor-tv" class="reproductor-tv" hidden>
    <p id="tv-viendo" class="tv-viendo"></p>
    <div id="tv-marco" class="tv-marco"></div>
  </div>
  {cuerpo}
  <p class="radios-nota">Cada señal se reproduce desde su transmisión oficial. Ledesma Participa no graba ni retransmite señales.</p>
</main>""",
            f'<script src="{ruta_raiz}assets/tv.js" defer></script>',
            cierre_html(ruta_raiz=ruta_raiz, config_sitio=config_sitio),
        ]
    )
