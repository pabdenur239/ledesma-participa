"""Clasificación única de una noticia para web, app y push (Etapa 1,
9/10/2026): TERRITORIO, CATEGORÍA y URGENTE como tres dimensiones
separadas, cada una con su propia regla.

- territorio: {valor, etiqueta, confianza} — Libertador, Departamento
  Ledesma, Jujuy, Nacional, Internacional (`categorias.territorio_vigente_con_confianza`).
- categoria: {valor, etiqueta, confianza} — tema principal; General /
  Últimas con confianza intermedia; None con confianza baja
  (`categorias.clasificar_categoria`).
- urgente: bool — scoring editorial único (`scoring_editorial.urgente_confirmado`),
  el mismo que decide el circuito inmediato de Meta. Nunca es una categoría.
"""
from typing import Optional

from .categorias import clasificar_categoria, territorio_vigente_con_confianza
from .scoring_editorial import urgente_confirmado

# territorio interno -> (slug público, etiqueta). "sin_clasificar" e
# "institucional" no tienen territorio público.
TERRITORIOS_PUBLICOS = {
    "local": ("libertador", "Libertador General San Martín"),
    "departamental": ("ledesma", "Departamento Ledesma"),
    "provincial": ("jujuy", "Jujuy"),
    "nacional": ("nacional", "Nacional"),
    "internacional": ("internacional", "Internacional"),
}
# Rótulo corto para insignias en tarjetas (celular).
ETIQUETAS_CORTAS = {
    "libertador": "Libertador",
    "ledesma": "Dpto. Ledesma",
    "jujuy": "Jujuy",
    "nacional": "Nacional",
    "internacional": "Internacional",
}


def clasificar_territorio_publico(noticia: dict) -> dict:
    interno, confianza = territorio_vigente_con_confianza(noticia)
    slug, etiqueta = TERRITORIOS_PUBLICOS.get(interno, (None, None))
    return {
        "valor": slug, "etiqueta": etiqueta, "etiqueta_corta": ETIQUETAS_CORTAS.get(slug),
        "confianza": confianza if slug else 0.0, "interno": interno,
    }


def clasificar_noticia(noticia: dict, urgente: Optional[bool] = None) -> dict:
    """{territorio, categoria, urgente} de una noticia (dict con las
    columnas de `noticias`). `urgente` puede venir ya calculado."""
    categoria = clasificar_categoria(noticia)
    return {
        "territorio": clasificar_territorio_publico(noticia),
        "categoria": {k: categoria[k] for k in ("valor", "etiqueta", "confianza")},
        "urgente": urgente_confirmado(noticia) if urgente is None else bool(urgente),
    }
