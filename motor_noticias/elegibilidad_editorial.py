import unicodedata

LONGITUD_MINIMA_TITULO = 8
LONGITUD_MINIMA_TEXTO = 40

# Gate mínimo de calidad, determinístico y sin IA: solo descarta contenido
# claramente no periodístico (publicidad, navegación, fragmentos vacíos).
# No evalúa importancia ni interés editorial — eso lo decide la cascada
# territorial del Motor Editorial, no este gate.
PATRONES_NO_PERIODISTICOS = (
    "publicidad",
    "suscribite",
    "suscribase",
    "suscribete",
    "newsletter",
    "anuncia con nosotros",
    "click aqui",
    "clic aqui",
    "todos los derechos reservados",
    "politica de privacidad",
    "terminos y condiciones",
    "menu principal",
    "iniciar sesion",
    "registrarse",
)


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def evaluar_elegibilidad_editorial(titulo: str, texto: str, fuente: str) -> dict:
    """Determina si una noticia SIN relevancia_local (provincial o nacional)
    puede de todos modos redactarse y quedar 'preparada' para que el Motor
    Editorial la considere en la cascada. Las noticias locales/departamentales
    no pasan por este gate: siguen preparándose siempre, igual que hoy."""
    titulo = (titulo or "").strip()
    texto = (texto or "").strip()
    fuente = (fuente or "").strip()

    if not fuente:
        return {"elegible": False, "motivo": "Sin fuente configurada."}

    if len(titulo) < LONGITUD_MINIMA_TITULO:
        return {"elegible": False, "motivo": "Título demasiado corto o vacío."}

    if len(texto) < LONGITUD_MINIMA_TEXTO:
        return {"elegible": False, "motivo": "Contenido insuficiente para publicar."}

    if titulo.lower() == texto.lower():
        return {
            "elegible": False,
            "motivo": "Título y texto idénticos: no aporta información propia.",
        }

    contenido_norm = _sin_acentos(f"{titulo} {texto}")
    for patron in PATRONES_NO_PERIODISTICOS:
        if patron in contenido_norm:
            return {
                "elegible": False,
                "motivo": f"Contenido no periodístico detectado ('{patron}').",
            }

    return {"elegible": True, "motivo": "Cumple los requisitos mínimos de calidad editorial."}
