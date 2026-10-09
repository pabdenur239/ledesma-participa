"""Sección VIDEOS (Etapa 1, 9/10/2026): videos de YouTube con el
reproductor oficial embebido. Nunca se descargan ni se republican como
propios; un video sin ID de YouTube válido no se muestra. Estructura
preparada para Multimedia (`tipo`); entrevistas, podcast y radios no están
implementados (radios en vivo = Etapa 2)."""
import json
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "videos.json"
TIPOS_SOPORTADOS = ("video",)
_RE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtube-nocookie.com", "youtube-nocookie.com")


def id_youtube(url: Optional[str]) -> Optional[str]:
    """ID de 11 caracteres de una URL de YouTube (watch, youtu.be, shorts,
    embed, live) o None si la URL no es de YouTube o no es válida."""
    try:
        partes = urlparse((url or "").strip())
    except ValueError:
        return None
    if partes.scheme not in ("http", "https") or partes.netloc.lower() not in _HOSTS:
        return None
    if partes.netloc.lower() == "youtu.be":
        candidato = partes.path.strip("/").split("/")[0]
    elif partes.path == "/watch":
        candidato = (parse_qs(partes.query).get("v") or [""])[0]
    else:
        segmentos = [s for s in partes.path.split("/") if s]
        candidato = segmentos[1] if len(segmentos) >= 2 and segmentos[0] in ("shorts", "embed", "live") else ""
    return candidato if _RE_ID.match(candidato or "") else None


def url_embed(video_id: str) -> str:
    return f"https://www.youtube-nocookie.com/embed/{video_id}"


def cargar_videos(path: Optional[Path] = None) -> List[dict]:
    try:
        with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
            crudos = json.load(f).get("videos", [])
    except (OSError, json.JSONDecodeError):
        return []
    validos = []
    for crudo in crudos:
        video_id = id_youtube(crudo.get("url"))
        if not video_id or not (crudo.get("titulo") or "").strip() or (crudo.get("tipo") or "video") not in TIPOS_SOPORTADOS:
            continue
        validos.append({
            "id": video_id,
            "titulo": crudo["titulo"].strip(),
            "fuente": (crudo.get("fuente") or "").strip() or None,
            "fecha": crudo.get("fecha"),
            "descripcion": (crudo.get("descripcion") or "").strip() or None,
            "tipo": "video",
            "embed_url": url_embed(video_id),
            "miniatura": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "url_youtube": f"https://www.youtube.com/watch?v={video_id}",
        })
    validos.sort(key=lambda v: v.get("fecha") or "", reverse=True)
    return validos
