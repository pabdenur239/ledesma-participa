"""Publicacion automatica de videos (Reels) en Facebook (Pagina Ledesma Participa) e Instagram (@ledesmaparticipa).

Reutiliza motor_noticias.meta.cliente.ClienteMetaGraphAPI y las variables META_PAGE_ID / META_PAGE_ACCESS_TOKEN /
META_IG_USER_ID ya configuradas. No define credenciales nuevas y nunca las escribe en logs/cola (todo error se redacta).

Flujo por elemento de la cola: generado -> aprobado -> publicado (o error, con reintento solo de la red que fallo).
  * Facebook: sube el MP4 directo como Reel. Instagram: sube el MP4 directo (resumable), sin URL publica ni hosting.
    Instagram solo se intenta despues de que Facebook publico.
  * Idempotencia: el id de cada red se guarda apenas existe; una red ya publicada nunca se repite. Si el proceso muriera
    DENTRO de una llamada de publicacion (estado 'en_curso'), esa red NO se reintenta sola (podria estar publicada): queda en error.
Interruptor: config_publicacion.json -> {"publicacion_automatica": true|false, ...}.
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parents[1]))

import cola_publicacion as cp  # noqa: E402

CONFIG = AQUI / "config_publicacion.json"
DEFECTO = {"publicacion_automatica": False, "max_intentos": 4, "espera_reintento_min": 15, "espera_url_video_s": 240}
REDES = ("facebook", "instagram")


def config():
    try:
        return {**DEFECTO, **json.loads(CONFIG.read_text(encoding="utf-8"))}
    except Exception:
        return dict(DEFECTO)


def redactar(texto):
    """Quita tokens/secretos de un mensaje antes de guardarlo o loguearlo."""
    import os
    t = re.sub(r"(access_token|token|key|secret)=[^&\s'\"]+", r"\1=***", str(texto), flags=re.I)
    t = re.sub(r"\bEA[A-Za-z0-9]{20,}", "***", t)
    for v in ("META_PAGE_ACCESS_TOKEN", "ELEVENLABS_API_KEY"):
        if os.environ.get(v):
            t = t.replace(os.environ[v], "***")
    return t[:500]


def preparar(item):
    texto = item["texto_redes"] + "\n\n" + " ".join(item["hashtags"])
    return {"facebook": {"descripcion": texto, "archivo": item["ruta_mp4"]}, "instagram": {"caption": texto}}


def _reel_instagram_resumable(cliente, ruta, caption, espera_s=240):
    """Reel de Instagram subiendo el archivo directo (upload_type=resumable): no necesita URL publica ni hosting."""
    from motor_noticias.meta import cliente as mc
    ruta = Path(ruta)
    base = mc.GRAPH_API_BASE
    cuerpo, tipo = mc._multipart({"media_type": "REELS", "upload_type": "resumable", "caption": caption,
                                  "access_token": cliente._access_token})
    cont = cliente._peticion_json(f"{base}/{cliente.ig_user_id}/media", cuerpo, tipo)
    cid, uri = cont.get("id"), cont.get("uri")
    if not cid or not uri:
        raise RuntimeError(f"Instagram no devolvio contenedor/uri de subida: {redactar(cont)}")
    subida = cliente._peticion_binaria_json(uri, ruta.read_bytes(), {
        "Authorization": f"OAuth {cliente._access_token}", "offset": "0", "file_size": str(ruta.stat().st_size),
        "Content-Type": "application/octet-stream"})
    if not subida.get("success"):
        raise RuntimeError(f"Instagram no confirmo la subida: {redactar(subida)}")
    t0 = time.time()
    while True:
        st = cliente._peticion_get_json(f"{base}/{cid}", {"fields": "status_code,status", "access_token": cliente._access_token})
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR" or time.time() - t0 > espera_s:
            raise RuntimeError(f"Instagram no pudo procesar el video: {redactar(st)}")
        time.sleep(5)
    cuerpo, tipo = mc._multipart({"creation_id": cid, "access_token": cliente._access_token})
    pub = cliente._peticion_json(f"{base}/{cliente.ig_user_id}/media_publish", cuerpo, tipo)
    if not pub.get("id"):
        raise RuntimeError("Instagram no devolvio id de publicacion")
    return pub["id"]


def _guardar(item):
    c = cp.cola()
    for i, it in enumerate(c):
        if it["id"] == item["id"]:
            c[i] = item
    cp._guardar("cola_publicacion.json", c)


def _red(item, red):
    return item.setdefault("redes", {}).setdefault(red, {"estado": "pendiente", "intentos": 0})


def publicar(item_id, cliente=None, ahora_=None, log=print):
    """Intenta publicar lo que falte del elemento (solo `aprobado` o `error` reintentable). Devuelve el elemento actualizado."""
    cfg = config()
    c = {it["id"]: it for it in cp.cola()}
    item = c[item_id]
    if not cfg["publicacion_automatica"]:
        log("  publicacion automatica desactivada (config_publicacion.json)")
        return item
    if item["estado"] == "error":
        cp.cambiar_estado(item_id, "aprobado", "reintento")
        item = {it["id"]: it for it in cp.cola()}[item_id]
    if item["estado"] != "aprobado":
        raise PermissionError(f"estado '{item['estado']}': solo se publica lo aprobado")
    if not item.get("ruta_mp4") or not Path(item["ruta_mp4"]).exists():
        raise FileNotFoundError("MP4 inexistente")
    if cliente is None:
        from motor_noticias.meta.cliente import ClienteMetaGraphAPI
        cliente = ClienteMetaGraphAPI()
    p = preparar(item)
    ahora_ = ahora_ or cp.ahora()
    fallo = None
    for red in REDES:
        r = _red(item, red)
        if r["estado"] == "publicado":
            continue
        if r["estado"] == "en_curso":
            r.update(estado="incierto", error="el proceso se interrumpio durante la publicacion: verificar a mano, no se reintenta solo")
            fallo = fallo or r["error"]
            continue
        if r["estado"] == "incierto":
            fallo = fallo or r["error"]
            continue
        if red == "instagram" and _red(item, "facebook")["estado"] != "publicado":
            continue
        if r["intentos"] >= cfg["max_intentos"]:
            fallo = fallo or f"{red}: maximo de intentos"
            continue
        r.update(estado="en_curso", intentos=r["intentos"] + 1, error=None, ultimo_intento=ahora_.isoformat(timespec="seconds"))
        _guardar(item)  # marca ANTES de llamar: si el proceso muere, no se duplica
        try:
            if not r.get("id"):  # con id ya publicado antes: solo falta verificar, nunca se vuelve a publicar
                if red == "facebook":
                    r["id"] = item["fb_video_id"] = cliente.publicar_reel_facebook(Path(item["ruta_mp4"]), p["facebook"]["descripcion"], dry_run=False)
                else:
                    r["id"] = _reel_instagram_resumable(cliente, item["ruta_mp4"], p["instagram"]["caption"], cfg["espera_url_video_s"])
                _guardar(item)
            r["verificado"] = bool(cliente.verificar_publicacion(r["id"]))
            r.update(estado="publicado", publicado_en=cp.ahora().isoformat(timespec="seconds"))
            log(f"  {red}: publicado id={r['id']} verificado={r['verificado']}")
        except Exception as e:
            r.update(estado="error", error=redactar(e))
            fallo = fallo or f"{red}: {r['error']}"
            log(f"  {red}: ERROR {r['error']}")
        _guardar(item)
    todas = all(_red(item, rd)["estado"] == "publicado" for rd in REDES)
    nuevo = {it["id"]: it for it in cp.cola()}[item_id]
    nuevo.update(redes=item["redes"], fb_video_id=item.get("fb_video_id"), error=None if todas else fallo)
    _guardar(nuevo)
    if todas:
        cp.cambiar_estado(item_id, "publicado")
    elif nuevo["estado"] == "aprobado":
        cp.cambiar_estado(item_id, "error", fallo)
    return {it["id"]: it for it in cp.cola()}[item_id]


def reintentar_pendientes(cliente=None, ahora_=None, log=print):
    """Reintenta lo `error` con intentos disponibles y espera cumplida (solo las redes que fallaron)."""
    cfg = config()
    ahora_ = ahora_ or cp.ahora()
    for it in cp.cola():
        if it["estado"] != "error" or not it.get("redes"):
            continue
        redes = it["redes"].values()
        if any(r["estado"] in ("incierto",) for r in redes):
            continue
        ult = max((r.get("ultimo_intento") or "" for r in redes), default="")
        if ult and ahora_ - datetime.fromisoformat(ult) < timedelta(minutes=cfg["espera_reintento_min"]):
            continue
        if all(r["intentos"] >= cfg["max_intentos"] for r in redes if r["estado"] != "publicado"):
            continue
        log(f"  reintentando {it['id']} (noticia {it['noticia_id']})")
        publicar(it["id"], cliente, ahora_, log)
