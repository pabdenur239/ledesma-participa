from .models import RevisionEstado


def puede_publicarse_automaticamente(noticia: dict) -> bool:
    """Función reutilizable para una futura etapa de publicación automática.

    No está conectada a ningún mecanismo de publicación (ni Facebook ni
    ningún otro). Por ahora siempre debe devolver False si la revisión
    humana no aprobó la noticia, o si existe cualquier condición de riesgo
    editorial obligatorio (contenido político/institucional)."""
    if noticia.get("revision_estado") != RevisionEstado.APROBADA.value:
        return False
    if noticia.get("requiere_revision_especial"):
        return False
    return True
