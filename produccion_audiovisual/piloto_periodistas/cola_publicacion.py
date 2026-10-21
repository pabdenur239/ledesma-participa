"""Registro persistente de noticias ya usadas en video + cola de publicacion de MP4 terminados.

Archivos (JSON, escritura atomica), en salidas/cola/ (no se versiona) o en $LEDESMA_COLA_DIR:
  registro_videos.json   -> noticias usadas: id, url, titulo, fecha/hora, tipo (programado_manana|programado_tarde|urgente)
  cola_publicacion.json  -> un elemento por MP4: estados generado | pendiente_revision | aprobado | publicado | error
Este modulo NO publica nada: solo guarda y cambia estados.
"""
import json
import os
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ESTADOS = ("generado", "pendiente_revision", "aprobado", "publicado", "error")
TIPOS = ("programado_manana", "programado_tarde", "urgente")
TZ = timezone(timedelta(hours=-3))  # Argentina (sin horario de verano)


def carpeta():
    d = Path(os.environ.get("LEDESMA_COLA_DIR") or AQUI / "salidas" / "cola")
    d.mkdir(parents=True, exist_ok=True)
    return d


def ahora():
    return datetime.now(TZ)


def _leer(nombre):
    try:
        return json.loads((carpeta() / nombre).read_text(encoding="utf-8"))
    except Exception:
        return []


def _guardar(nombre, datos):
    ruta = carpeta() / nombre
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ruta)


def _tokens(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return {w for w in re.findall(r"[a-z0-9]{4,}", t)}


def similitud(a, b):
    x, y = _tokens(a), _tokens(b)
    return len(x & y) / len(x | y) if x and y else 0.0


# ---------------------------------------------------------------- registro / duplicados
def registro():
    return _leer("registro_videos.json")


def es_duplicado(n, reg=None, permitir_ids=(), horas=96, ahora_=None, umbral=0.7):
    """(bool, motivo). Duplicado = mismo id, misma URL, o titulo casi igual en las ultimas `horas`.
    `permitir_ids`: ids con actualizacion sustancial comprobada (decision manual y documentada)."""
    if n["id"] in permitir_ids:
        return False, ""
    reg = registro() if reg is None else reg
    ahora_ = ahora_ or ahora()
    urls = {u for u in (n.get("url"), n.get("fuente_url")) if u}
    for r in reg:
        if r.get("noticia_id") == n["id"]:
            return True, f"ya usada como {r['tipo']} ({r['fecha_hora'][:16]})"
        if urls & {r.get("url"), r.get("fuente_url")}:
            return True, f"misma URL ya usada como {r['tipo']}"
        try:
            reciente = ahora_ - datetime.fromisoformat(r["fecha_hora"]) <= timedelta(hours=horas)
        except Exception:
            reciente = True
        if reciente and similitud(n["titulo"], r.get("titulo")) >= umbral:
            return True, f"titulo casi identico a noticia {r['noticia_id']} ({r['tipo']})"
    return False, ""


def registrar_uso(n, tipo, ahora_=None):
    assert tipo in TIPOS, tipo
    reg = registro()
    reg.append({"noticia_id": n["id"], "url": n.get("url"), "fuente_url": n.get("fuente_url"), "titulo": n["titulo"],
                "fecha_hora": (ahora_ or ahora()).isoformat(timespec="seconds"), "tipo": tipo})
    _guardar("registro_videos.json", reg)


# ---------------------------------------------------------------- cola
def cola():
    return _leer("cola_publicacion.json")


def encolar(n, tipo, presentador, mp4, texto_redes, hashtags, categoria, estado="pendiente_revision", error=None, ahora_=None):
    assert tipo in TIPOS and estado in ESTADOS
    t = (ahora_ or ahora()).isoformat(timespec="seconds")
    item = {"id": uuid.uuid4().hex[:12], "noticia_id": n["id"], "url": n.get("url"), "fuente_url": n.get("fuente_url"),
            "fuente": n.get("fuente_nombre"), "titulo": n["titulo"], "categoria": categoria, "presentador": presentador,
            "tipo": tipo, "generado_en": t, "ruta_mp4": str(mp4) if mp4 else None, "texto_redes": texto_redes,
            "hashtags": hashtags, "estado": estado, "error": error,
            "historial": [{"estado": "generado", "en": t}] + ([{"estado": estado, "en": t}] if estado != "generado" else [])}
    c = cola()
    c.append(item)
    _guardar("cola_publicacion.json", c)
    return item


_PERMITIDAS = {"generado": {"pendiente_revision", "aprobado", "error"}, "pendiente_revision": {"aprobado", "error"},
               "aprobado": {"publicado", "error", "pendiente_revision"}, "error": {"pendiente_revision", "aprobado"}, "publicado": set()}


def cambiar_estado(item_id, nuevo, nota=None):
    c = cola()
    for it in c:
        if it["id"] == item_id:
            if nuevo not in _PERMITIDAS[it["estado"]]:
                raise ValueError(f"transicion no permitida: {it['estado']} -> {nuevo}")
            it["estado"] = nuevo
            it["historial"].append({"estado": nuevo, "en": ahora().isoformat(timespec="seconds"), **({"nota": nota} if nota else {})})
            _guardar("cola_publicacion.json", c)
            return it
    raise KeyError(item_id)
