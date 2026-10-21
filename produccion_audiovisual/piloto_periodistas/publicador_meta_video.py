"""Preparacion de publicacion de videos en Facebook (Pagina) e Instagram (@ledesmaparticipa) via Meta Graph API.

ESTADO ACTUAL: PUBLICACION DESACTIVADA. Nada de este modulo se ejecuta desde el programador.
Reutiliza motor_noticias.meta.cliente.ClienteMetaGraphAPI y sus variables META_PAGE_ID / META_PAGE_ACCESS_TOKEN /
META_IG_USER_ID (no define configuracion nueva ni lee/imprime secretos).

Para activar mas adelante hacen falta TODAS estas condiciones:
  1. variable de entorno LEDESMA_VIDEO_PUBLICAR=1
  2. el elemento de la cola esta en estado `aprobado` (revision humana)
  3. llamar a publicar(item, dry_run=False)
Instagram exige una URL publica del MP4 (hosting aun no definido): sin `video_url` solo se publica Facebook.
"""
import os
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parents[1]))

import cola_publicacion as cp  # noqa: E402


def habilitada():
    return os.environ.get("LEDESMA_VIDEO_PUBLICAR") == "1"


def preparar(item):
    """Payload que se enviaria a Meta (sin red, sin token)."""
    texto = item["texto_redes"] + "\n\n" + " ".join(item["hashtags"])
    return {"facebook": {"descripcion": texto, "archivo": item["ruta_mp4"]},
            "instagram": {"caption": texto, "requiere_video_url_publica": True}}


def publicar(item, dry_run=True, video_url=None, cliente=None):
    """Devuelve {'dry_run': True, 'payload': ...} por defecto. La publicacion real solo ocurre con las 3 condiciones del docstring."""
    payload = preparar(item)
    if dry_run:
        return {"dry_run": True, "payload": payload}
    if not habilitada():
        raise PermissionError("Publicacion de videos desactivada (LEDESMA_VIDEO_PUBLICAR != 1).")
    if item["estado"] != "aprobado":
        raise PermissionError(f"El elemento esta en '{item['estado']}': solo se publica lo `aprobado`.")
    if not item.get("ruta_mp4") or not Path(item["ruta_mp4"]).exists():
        raise FileNotFoundError("MP4 inexistente")
    if cliente is None:
        from motor_noticias.meta.cliente import ClienteMetaGraphAPI
        cliente = ClienteMetaGraphAPI()
    ids = {"facebook": cliente.publicar_reel_facebook(Path(item["ruta_mp4"]), payload["facebook"]["descripcion"], dry_run=False)}
    if video_url:
        ids["instagram"] = cliente.publicar_reel_instagram(video_url, payload["instagram"]["caption"], dry_run=False)
    cp.cambiar_estado(item["id"], "publicado", nota=str(ids))
    return {"dry_run": False, "ids": ids}
