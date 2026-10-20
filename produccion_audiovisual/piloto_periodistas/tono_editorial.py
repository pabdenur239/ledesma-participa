"""Clasificacion simple del tono editorial de una noticia -> parametros de actuacion del periodista.

Tonos: positiva | neutra | seria | triste | urgente | policial. Ante duda: neutra (o seria si hay impacto).
Con los assets actuales (UNA imagen de referencia por presentador) la expresion base no se puede reescribir:
el tono modula la ACTUACION (amplitud de movimiento de cabeza, cabeceo, parpadeo, apertura de boca).
"""
import re

REGLAS = [
    ("urgente", None),  # n["urgente"]
    ("policial", r"\b(choque|accidente|vuelco|incendio|robo|asalto|balacera|siniestro|detenid[oa]s?|polic[ií]a(l|les)? (inform|investig|detuv|secuestr))"),
    ("triste", r"fallec|duelo|pesar|tragedia|despedida|v[ií]ctima|homenaje p[oó]stumo"),
    ("seria", r"alerta|emergencia|advierten|advierte|riesgo|estafa|denunci|crisis|inseguridad|corte de (energ|agua)|sin (luz|agua)"),
    ("positiva", r"celebr|festej|inaugur|campe[oó]n|se impuso|gan[oó]|logr[oó]|premio|[eé]xito|fiesta|aniversario|entreg[oó] (certificados|premios)|finaliz[oó]"),
]

# amp: amplitud de movimiento de cabeza; cabeceo: asentimientos de enfasis; boca: apertura relativa; parpadeo: parpadeos/min
PARAMETROS = {
    "positiva": {"amp": 1.00, "cabeceo": 0.8, "boca": 1.00, "parpadeo": 16},
    "neutra":   {"amp": 0.80, "cabeceo": 0.6, "boca": 0.95, "parpadeo": 15},
    "seria":    {"amp": 0.55, "cabeceo": 0.5, "boca": 0.90, "parpadeo": 13},
    "triste":   {"amp": 0.45, "cabeceo": 0.4, "boca": 0.85, "parpadeo": 12},
    "urgente":  {"amp": 0.60, "cabeceo": 1.0, "boca": 0.95, "parpadeo": 12},
    "policial": {"amp": 0.55, "cabeceo": 0.7, "boca": 0.90, "parpadeo": 12},
}


def clasificar(n):
    texto = (n["titulo"] + " " + (n.get("bajada") or "")).lower()
    for tono, rx in REGLAS:
        if tono == "urgente":
            if n.get("urgente"):
                return tono
        elif re.search(rx, texto):
            return tono
    return "neutra"
