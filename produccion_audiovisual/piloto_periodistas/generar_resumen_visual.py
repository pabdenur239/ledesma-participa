"""Resumen "LAS 2 NOTICIAS DEL DIA" en modo sin conductor (voice-over visual).

Un solo comando (desde la raiz del repo):
    .venv\\Scripts\\python.exe produccion_audiovisual\\piloto_periodistas\\generar_resumen_visual.py
Opciones: --ids ID1 ID2 (forzar noticias de la portada publica)  --horas 36
Fuente de noticias: https://ledesmaparticipa.com.ar/api/portada.json (solo lectura, ya publicadas/vetadas).
Se vuelven a aplicar scoring y riesgo editorial. NO publica nada. Salida: salidas/<fecha>/.
"""
import argparse
import io
import json
import math
import re
import subprocess
import sys
import urllib.request
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parents[1]))

import generar_piloto as gp  # noqa: E402
from motor_noticias.motor_editorial import _es_mismo_hecho  # noqa: E402
from motor_noticias.riesgo_editorial import evaluar_riesgo_editorial  # noqa: E402
from motor_noticias.scoring_editorial import evaluar_noticia  # noqa: E402

W, H, FPS = 1080, 1920, 25
AZUL, DORADO, BLANCO, ROJO = (10, 37, 64), (201, 162, 39), (255, 255, 255), (200, 20, 30)
VOZ = "valentina"  # solo se usa el modelo de voz es_AR (locucion); no hay presentador en pantalla
API = "https://ledesmaparticipa.com.ar/api/portada.json"
ETIQUETA_URGENTE = "URGENTE"


# ------------------------------------------------------------ noticias
def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "LedesmaParticipa-piloto/1.0"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def cargar_portada(horas, ids):
    d = json.loads(_get(API))
    todas = {}
    for n in [d.get("principal")] + list(d.get("urgentes") or []) + [n for s in d["secciones"] for n in s["noticias"]]:
        if n and n.get("id") not in todas:
            todas[n["id"]] = n
    lim = datetime.now(timezone.utc) - timedelta(hours=horas)
    cands = []
    for n in todas.values():
        if ids and n["id"] not in ids:
            continue
        if not ids and datetime.fromisoformat(n["fecha_iso"]) < lim:
            continue
        if not ids and re.search(r"se busca|desaparec|paradero|extravi|menor|ni(?:ñ|n)[oa]", (n["titulo"] + " " + (n["bajada"] or "")).lower()):
            continue  # personas buscadas / menores: no van en el resumen audiovisual
        reg = {"titulo_original": n["titulo"], "texto_original": n["bajada"] or "", "titulo_preparado": n["titulo"],
               "texto_preparado": n["bajada"] or "", "url_fuente": n["fuente_url"], "nombre_fuente": n["fuente_nombre"],
               "fecha_recoleccion": n["fecha_iso"], "localidad": n.get("localidad"), "territorio": n.get("territorio")}
        if not ids and evaluar_riesgo_editorial(n["titulo"], n["bajada"] or "", None, None, n["fuente_nombre"])["requiere_revision_especial"]:
            continue
        n["_score"] = evaluar_noticia(reg)
        n["_total"] = n["_score"]["total"]
        n["_imagen_ok"] = bool(n.get("imagen"))
        cands.append(n)
    cands.sort(key=lambda n: (n["_imagen_ok"], n["_total"]), reverse=True)
    elegidas = []
    for n in cands:
        if any(_es_mismo_hecho(n["titulo"], e["titulo"]) for e in elegidas):
            continue
        elegidas.append(n)
        if len(elegidas) == 2:
            return elegidas
    raise SystemExit("No hay 2 noticias aptas en la portada publica.")


def descargar_imagen(url):
    if not url:
        return None
    for u in (url.split("?")[0], url):
        try:
            return Image.open(io.BytesIO(_get(u))).convert("RGB")
        except Exception:
            continue
    return None


# ------------------------------------------------------------ guion
def guion(noticias):
    seg = [{"clave": "apertura", "lead": 0.4, "tail": 0.4,
            "texto": "Ledesma Participa. Las dos noticias del día."}]
    for i, n in enumerate(noticias, 1):
        resumen = gp.resumen_oral(n["bajada"] or "", 40) if n["bajada"] else ""
        if resumen and not re.search(r"[.!?]$", resumen):
            resumen = ""  # bajada cortada: no se lee media frase
        intro = "Primera noticia." if i == 1 else "Segunda noticia."
        titulo = gp._limpiar(n["titulo"]).rstrip(".")
        seg.append({"clave": f"noticia{i}", "lead": 1.1, "tail": 0.5, "titulo": n["titulo"], "noticia": n,
                    "texto": f"{intro} {titulo}. {resumen}".strip()})
    seg.append({"clave": "cierre", "lead": 0.3, "tail": 1.2,
                "texto": "Seguí toda la información en Ledesma Participa."})
    return seg


def armar_audio(seg, carpeta):
    gp.sintetizar(seg, VOZ, carpeta)
    sr = 22050
    pcm, t = [], 0.0
    for s in seg:
        with wave.open(str(s["wav"])) as wf:
            sr = wf.getframerate()
            datos = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        pcm.append(np.zeros(int(s["lead"] * sr), dtype=np.int16))
        s["voz_ini"] = t + s["lead"]
        pcm.append(datos)
        pcm.append(np.zeros(int(s["tail"] * sr), dtype=np.int16))
        s["ini"] = t
        t += s["lead"] + len(datos) / sr + s["tail"]
        s["fin"] = t
    ruta = carpeta / "audio_final.wav"
    with wave.open(str(ruta), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(np.concatenate(pcm).tobytes())
    return ruta, t


def subtitulos(seg, carpeta):
    srt, k, cues = [], 1, []
    for s in seg:
        partes = gp.trozos(s["texto"], 4)
        total = sum(len(p.split()) for p in partes)
        dur = s["fin"] - s["tail"] - s["voz_ini"]
        t = s["voz_ini"]
        for p in partes:
            d = dur * len(p.split()) / total
            cues.append((t, t + d, p))
            f = lambda x: f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{x % 60:06.3f}".replace(".", ",")
            srt.append(f"{k}\n{f(t)} --> {f(t + d)}\n{p}\n")
            k += 1
            t += d
    (carpeta / "subtitulos.srt").write_text("\n".join(srt), encoding="utf-8")
    return cues


# ------------------------------------------------------------ render
def fuente(tam, bold=True):
    return ImageFont.truetype("bahnschrift.ttf" if bold else "arial.ttf", tam) if bold else ImageFont.truetype("arial.ttf", tam)


F = {}


def fnt(tam, bold=True):
    k = (tam, bold)
    if k not in F:
        try:
            F[k] = ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", tam)
        except OSError:
            F[k] = ImageFont.load_default()
    return F[k]


def ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def envolver(draw, texto, f, ancho):
    lineas, cur = [], ""
    for p in texto.split():
        if draw.textlength((cur + " " + p).strip(), font=f) <= ancho:
            cur = (cur + " " + p).strip()
        else:
            lineas.append(cur)
            cur = p
    return lineas + [cur]


def fondo_base(t):
    """Azul noche con degradado vertical y destellos dorados en movimiento."""
    y = np.linspace(0, 1, H)[:, None, None]
    top, bot = np.array([14, 52, 88]), np.array([6, 22, 40])
    im = (top * (1 - y) + bot * y).astype(np.uint8)
    im = np.broadcast_to(im, (H, W, 3)).copy()
    pil = Image.fromarray(im)
    d = ImageDraw.Draw(pil, "RGBA")
    for i in range(3):  # lineas diagonales doradas que derivan (referencia sutil a las Yungas: lineas de relieve)
        off = ((t * 90 + i * 520) % (W + H)) - H
        d.line([(off, H), (off + H * 0.6, 0)], fill=DORADO + (38,), width=6)
    return pil


def cabecera(pil, t):
    d = ImageDraw.Draw(pil, "RGBA")
    d.rectangle([0, 0, W, 170], fill=(7, 26, 46, 255))
    d.text((W // 2, 82), "LEDESMA PARTICIPA", font=fnt(68), fill=BLANCO, anchor="mm")
    d.rectangle([0, 170, int(W * ease(t / 0.6)) if t < 0.6 else W, 180], fill=DORADO)


def kenburns(img, t, dur, ancho, alto):
    z = 1.0 + 0.14 * (t / max(dur, 0.1))
    r = max(ancho / img.width, alto / img.height) * z
    nw, nh = int(img.width * r) + 1, int(img.height * r) + 1
    g = img.resize((nw, nh), Image.BILINEAR)
    x, y = (nw - ancho) // 2, (nh - alto) // 2
    return g.crop((x, y, x + ancho, y + alto))


def escena_apertura(t, dur):
    pil = fondo_base(t)
    d = ImageDraw.Draw(pil, "RGBA")
    a = ease(t / 0.7)
    rad = int(120 + 700 * ease(t / 1.4))
    d.ellipse([W // 2 - rad, 760 - rad, W // 2 + rad, 760 + rad], outline=DORADO + (int(150 * (1 - ease(t / 1.4))),), width=10)
    f = fnt(int(118 * (0.85 + 0.15 * a)))
    d.text((W // 2, 760), "LEDESMA", font=f, fill=BLANCO + (int(255 * a),), anchor="mm")
    d.text((W // 2, 760 + 130), "PARTICIPA", font=f, fill=DORADO + (int(255 * a),), anchor="mm")
    w = int(700 * ease((t - 0.4) / 0.7))
    d.rectangle([W // 2 - w // 2, 1010, W // 2 + w // 2, 1022], fill=DORADO)
    b = ease((t - 0.8) / 0.6)
    d.text((W // 2, 1120 + int(40 * (1 - b))), "LAS 2 NOTICIAS DEL DÍA", font=fnt(66), fill=BLANCO + (int(255 * b),), anchor="mm")
    d.text((W // 2, 1210), datetime.now().strftime("%d/%m/%Y"), font=fnt(40, False), fill=DORADO + (int(255 * b),), anchor="mm")
    return pil


def etiqueta(n):
    if n.get("urgente"):
        return ETIQUETA_URGENTE, "urgente"
    if n.get("categoria_slug") == "policiales":
        return "POLICIALES", "policial"
    return (n.get("categoria_etiqueta") or "NOTICIA").upper(), "normal"


def escena_noticia(t, dur, s, img, bg_blur, num):
    n = s["noticia"]
    tag, estilo = etiqueta(n)
    pil = fondo_base(t)
    # zona de foto
    if img is not None:
        pil.paste(bg_blur, (0, 190))
        foto = kenburns(img, t, dur, W, 900)
        pil.paste(foto, (0, 190))
    d = ImageDraw.Draw(pil, "RGBA")
    if img is None:  # placa limpia con titulo: nunca se inventa una escena
        d.rectangle([0, 190, W, 1090], fill=(7, 26, 46, 255))
        d.text((W // 2, 640), f"NOTICIA {num}", font=fnt(150), fill=DORADO, anchor="mm")
    # marco / tratamiento segun tipo
    if estilo == "urgente":
        pulso = 0.5 + 0.5 * math.sin(t * 7)
        d.rectangle([0, 190, W, 1090], outline=ROJO + (int(160 + 95 * pulso),), width=18)
        d.rectangle([0, 1090, W, 1430], fill=(120, 8, 16, 255))
    elif estilo == "policial":
        d.rectangle([0, 190, W, 1090], outline=DORADO + (255,), width=14)
        d.rectangle([0, 1090, W, 1430], fill=(4, 14, 26, 255))
    else:
        d.rectangle([0, 190, W, 1090], outline=DORADO + (255,), width=6)
        d.rectangle([0, 1090, W, 1430], fill=(7, 26, 46, 245))
    d.rectangle([0, 1090, W, 1102], fill=ROJO + (255,) if estilo == "urgente" else DORADO + (255,))
    # chip + numero
    cw = int(d.textlength(tag, font=fnt(44))) + 60
    cx = int(60 - (cw + 60) * (1 - ease((t - 1.0) / 0.5)))
    d.rectangle([cx, 1130, cx + cw, 1200], fill=(ROJO if estilo == "urgente" else DORADO) + (255,))
    d.text((cx + cw // 2, 1165), tag, font=fnt(44), fill=BLANCO if estilo == "urgente" else AZUL, anchor="mm")
    d.text((W - 60, 1165), f"{num}/2", font=fnt(48), fill=DORADO if estilo != "urgente" else BLANCO, anchor="rm")
    # titulo
    f = fnt(52)
    lineas = envolver(d, gp.titulo_corto(n["titulo"], 100), f, W - 120)[:3]
    for i, l in enumerate(lineas):
        a = ease((t - 1.1 - 0.12 * i) / 0.45)
        d.text((60, 1235 + i * 62 + int(30 * (1 - a))), l, font=f, fill=BLANCO + (int(255 * a),))
    # separador: panel dorado que barre de izquierda a derecha en el lead
    if t < 1.05:
        p = t / 1.05
        x0 = int(W * ease((p - 0.45) / 0.55))
        x1 = int(W * min(1.0, ease(p / 0.45)))
        if x1 > x0:
            d.rectangle([x0, 0, x1, H], fill=DORADO + (255,))
            if p < 0.6:
                d.text((W // 2, H // 2), f"NOTICIA {num}", font=fnt(130), fill=AZUL, anchor="mm")
    cabecera(pil, 9)
    return pil


def escena_cierre(t, dur):
    pil = fondo_base(t + 3)
    d = ImageDraw.Draw(pil, "RGBA")
    a = ease(t / 0.6)
    d.text((W // 2, 760), "LEDESMA", font=fnt(118), fill=BLANCO + (int(255 * a),), anchor="mm")
    d.text((W // 2, 890), "PARTICIPA", font=fnt(118), fill=DORADO + (int(255 * a),), anchor="mm")
    d.rectangle([W // 2 - 350, 980, W // 2 + 350, 992], fill=DORADO)
    b = ease((t - 0.5) / 0.6)
    d.text((W // 2, 1090), "Seguí toda la información", font=fnt(52), fill=BLANCO + (int(255 * b),), anchor="mm")
    d.text((W // 2, 1170), "ledesmaparticipa.com.ar", font=fnt(54), fill=DORADO + (int(255 * b),), anchor="mm")
    return pil


def subtitulo(pil, texto):
    d = ImageDraw.Draw(pil, "RGBA")
    f = fnt(76)
    lineas = envolver(d, texto, f, W - 140)
    y = 1560
    for l in lineas:
        d.text((W // 2, y), l, font=f, fill=BLANCO, anchor="mm", stroke_width=7, stroke_fill=(4, 14, 26))
        y += 92


def renderizar(seg, cues, total, audio, salida, ff):
    for s in seg:
        n = s.get("noticia")
        if n:
            s["img"] = descargar_imagen(n.get("imagen"))
            s["blur"] = None
            if s["img"] is not None:
                im = s["img"]
                s["blur"] = im.resize((W, 900), Image.BILINEAR).filter(ImageFilter.GaussianBlur(24))
    cmd = [ff, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(audio),
           "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
           "-shortest", "-movflags", "+faststart", str(salida)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    nframes = int(total * FPS)
    for i in range(nframes):
        t = i / FPS
        s = next((x for x in seg if x["ini"] <= t < x["fin"]), seg[-1])
        lt, dur = t - s["ini"], s["fin"] - s["ini"]
        if s["clave"] == "apertura":
            pil = escena_apertura(lt, dur)
        elif s["clave"] == "cierre":
            pil = escena_cierre(lt, dur)
        else:
            pil = escena_noticia(lt, dur, s, s["img"], s["blur"], s["clave"][-1])
        cue = next((c for c in cues if c[0] <= t < c[1]), None)
        if cue:
            subtitulo(pil, cue[2])
        p.stdin.write(np.asarray(pil, dtype=np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg fallo al codificar")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs=2, type=int)
    ap.add_argument("--horas", type=int, default=36)
    a = ap.parse_args()
    noticias = cargar_portada(a.horas, set(a.ids or []))
    carpeta = AQUI / "salidas" / datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta.mkdir(parents=True)
    seg = guion(noticias)
    (carpeta / "guion.txt").write_text("\n\n".join(s["texto"] for s in seg), encoding="utf-8")
    audio, total = armar_audio(seg, carpeta)
    cues = subtitulos(seg, carpeta)
    final = carpeta / "las_2_noticias_del_dia.mp4"
    renderizar(seg, cues, total, audio, final, gp.ffmpeg_exe())
    meta = {"modo": "voice-over visual (sin conductor)", "voz": gp.PRESENTADORES[VOZ]["voz"], "video": gp.verificar(final),
            "noticias": [{"id": n["id"], "titulo": n["titulo"], "url": n["url"], "fuente_url": n["fuente_url"],
                          "fuente": n["fuente_nombre"], "fecha": n["fecha_iso"], "urgente": n.get("urgente"),
                          "puntaje_total": n["_total"]} for n in noticias]}
    (carpeta / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("MP4:", final)


if __name__ == "__main__":
    main()
