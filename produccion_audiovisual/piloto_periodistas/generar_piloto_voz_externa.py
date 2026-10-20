"""Piloto de UNA noticia con presentadora y audio EXTERNO aprobado (sin TTS local).

1) transcribir (solo para subtitulos): venv_xtts\Scripts\python.exe produccion_audiovisual\piloto_periodistas\transcribir_audio.py AUDIO transcripcion.json
2) render: .venv\Scripts\python.exe produccion_audiovisual\piloto_periodistas\generar_piloto_voz_externa.py --audio AUDIO --transcripcion transcripcion.json --id ID --presentador valentina
La duracion del video = duracion exacta del audio. NO publica nada.
"""
import argparse
import json
import math
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parents[1]))

import generar_noticia_presentador as gnp  # noqa: E402
import generar_piloto as gp  # noqa: E402
import generar_resumen_visual as g  # noqa: E402
import mezcla_musical as mm  # noqa: E402
import seleccion_editorial as se  # noqa: E402

for _s in (sys.stdout, sys.stderr):  # consola de Windows (cp1252): no depender de PYTHONUTF8
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

W, H, FPS = g.W, g.H, g.FPS
CORRECCIONES = [(r"(?i)\bvientos sonda\b", "viento Zonda"), (r"(?i)\bsonda\b", "Zonda"), (r"(?i)\bzonda\b", "Zonda"),
                (r"(?i)\balcolizado\b", "alcoholizado"), (r"(?i)\bguacalera\b", "Huacalera"),
                (r"(?i)\bmúltiplo\b", "múltiple")]


def corregir(t):
    for pat, rep in CORRECCIONES:
        t = re.sub(pat, rep, t)
    return t


def cues_desde_palabras(tr, max_pal=4):
    pal = [w for s in tr["segmentos"] for w in s["palabras"]]
    cues = []
    for i in range(0, len(pal), max_pal):
        grupo = pal[i:i + max_pal]
        sig = pal[i + max_pal]["ini"] if i + max_pal < len(pal) else tr["duracion"]
        cues.append((grupo[0]["ini"], min(sig, grupo[-1]["fin"] + 0.5), " ".join(w["p"] for w in grupo)))
    # corregir sobre el texto completo conservando los limites de cada cue
    texto = corregir(" ".join(c[2] for c in cues)).split()
    n_orig = sum(len(c[2].split()) for c in cues)
    if len(texto) == n_orig:
        it = iter(texto)
        return [(a, b, " ".join(next(it) for _ in c.split())) for a, b, c in cues]
    return [(a, b, corregir(c)) for a, b, c in cues]  # "vientos sonda" -> "viento Zonda" cambia el conteo


def fases(tr):
    pal = [w for s in tr["segmentos"] for w in s["palabras"]]
    fines = [w["fin"] for w in pal if w["p"].endswith((".", "?", "!"))]
    total = tr["duracion"]
    t_titular = fines[1] if len(fines) > 1 else total * 0.3
    if total < 12:  # audio corto: titular al terminar la primera frase para que haya tramo con foto
        t_titular = max(fines[0] if fines else 0, 2.4)
    t_cierre = max([f for f in fines[:-1] if f < total - 3.0] or [total * 0.8])
    return t_titular, t_cierre, total


def apertura_overlay(pil, t, dur=1.8):
    if t >= dur:
        return pil
    a = 1.0 if t < 1.0 else 1 - g.ease((t - 1.0) / (dur - 1.0))
    marca = g.fondo_base(t)
    d = ImageDraw.Draw(marca, "RGBA")
    k = g.ease(t / 0.5)
    d.text((W // 2, 860), "LEDESMA", font=g.fnt(int(118 * (0.85 + 0.15 * k))), fill=g.BLANCO, anchor="mm")
    d.text((W // 2, 990), "PARTICIPA", font=g.fnt(int(118 * (0.85 + 0.15 * k))), fill=g.DORADO, anchor="mm")
    d.rectangle([W // 2 - int(350 * k), 1070, W // 2 + int(350 * k), 1082], fill=g.DORADO)
    return Image.blend(pil, marca, a)


# ---------------------------------------------------------------- composicion visual automatica (--visual auto)
def plan_visual(tr, hay_foto):
    """Lista de (ini, fin, modo) con modo pres | imagen | dividido. Sin imagen: periodista todo el video."""
    t_tit, t_cie, total = fases(tr)
    pal = [w for s in tr["segmentos"] for w in s["palabras"]]
    fines = [w["fin"] for w in pal if w["p"].endswith((".", "?", "!"))]
    t1 = max(fines[0] if fines else 3.0, 3.0)
    t1 = min(t1, total * 0.3)
    medio = t_cie - t1
    if not hay_foto or medio < 3.0:
        return [(0.0, total + 0.01, "pres")]
    plan = [(0.0, t1, "pres")]
    div = min(medio * 0.4, 5.0) if medio >= 7.0 else 0.0
    plan.append((t1, t_cie - div, "imagen"))
    if div:
        plan.append((t_cie - div, t_cie, "dividido"))
    plan.append((t_cie, total + 0.01, "pres"))
    return plan


def camara_retrato(ret, t, total):
    """Presentador ESTATICO: solo movimiento de camara continuo (zoom-in leve + paneo lento) sobre el retrato oficial.
    No toca rostro, ojos, boca, cabeza ni cuerpo: es un recorte con la misma relacion de aspecto, sin deformar."""
    p = min(max(t / max(total, 0.1), 0.0), 1.0)
    z = 1.0 + 0.08 * g.ease(p)
    w, h = ret.size
    cw, ch = w / z, h / z
    x0 = (w - cw) * (0.5 + 0.25 * math.sin(t * 0.3))
    y0 = (h - ch) * 0.35
    return ret.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((W, gnp.PANEL_H), Image.LANCZOS)


_FONDOS = {}


def _fondo_desenfocado(foto, w, h):
    k = (id(foto), w, h)
    if k not in _FONDOS:
        _FONDOS[k] = foto.resize((w, h), Image.BILINEAR).filter(ImageFilter.GaussianBlur(24))
    return _FONDOS[k]


def panel_imagen(foto, lt, dur, w, h):
    """Imagen completa (relacion de aspecto intacta, sin recorte) sobre fondo desenfocado, con zoom/paneo suave."""
    p = g.ease(min(max(lt / max(dur, 0.1), 0.0), 1.0))
    esc = min(w / foto.width, h / foto.height) * (1.0 + 0.06 * p)
    iw, ih = int(foto.width * esc), int(foto.height * esc)
    im = foto.resize((iw, ih), Image.LANCZOS)
    lienzo = _fondo_desenfocado(foto, w, h).copy()
    x = (w - iw) // 2 + int((0.5 - p) * 24 if iw > w else 0)
    lienzo.paste(im, (x, (h - ih) // 2))
    return lienzo


def panel_carrusel(fotos, lt, dur, w, h):
    """1 imagen: zoom/paneo. 2-3: se alternan en partes iguales con fundido suave de 0,5 s."""
    k = len(fotos)
    if k == 1:
        return panel_imagen(fotos[0], lt, dur, w, h)
    tramo = dur / k
    i = min(int(lt / tramo), k - 1)
    cur = panel_imagen(fotos[i], lt - i * tramo, tramo, w, h)
    if i > 0 and lt - i * tramo < 0.5:
        ant = panel_imagen(fotos[i - 1], tramo, tramo, w, h)
        return Image.blend(ant, cur, g.ease((lt - i * tramo) / 0.5))
    return cur


def frame_auto(t, plan, ctx, total, seg):
    modo = next((m for a_, b_, m in plan if a_ <= t < b_), "pres")
    ini = next((a_ for a_, b_, m in plan if a_ <= t < b_), 0.0)
    fin = next((b_ for a_, b_, m in plan if a_ <= t < b_), total)
    s = next((x for x in seg if x["ini"] <= t < x["fin"]), seg[-1])
    base = gnp.frame(t, s, total, {**ctx, "foto": None})  # periodista + panel inferior (titular / CTA)
    if modo == "pres":
        return base
    d = ImageDraw.Draw(base, "RGBA")
    y, h = gnp.PANEL_Y, gnp.PANEL_H
    if modo == "imagen":
        base.paste(panel_carrusel(ctx["fotos"], t - ini, fin - ini, W, h), (0, y))
    else:  # dividido: periodista arriba, imagen abajo
        mitad = h // 2
        pres = gnp.panel_retrato(ctx["ret"], t, 999).crop((0, 70, W, 70 + mitad))
        base.paste(pres, (0, y))
        base.paste(panel_carrusel(ctx["fotos"][:1], t - ini, fin - ini, W, mitad), (0, y + mitad))
        d.rectangle([0, y + mitad - 3, W, y + mitad + 3], fill=g.DORADO + (255,))
    d.rectangle([0, y, W, y + h], outline=g.DORADO + (255,), width=8)
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--transcripcion", required=True)
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--presentador", default="valentina", choices=list(gnp.PRES))
    ap.add_argument("--horas", type=int, default=240)
    ap.add_argument("--musica", default="auto", help="auto | clima_servicios|policial|politica|sociedad|deportes|urgente | none")
    ap.add_argument("--visual", default="clasico", choices=["clasico", "auto"],
                    help="clasico = disenio aprobado; auto = alterna periodista / imagen de la nota / dividido")
    a = ap.parse_args()

    tr = json.load(open(a.transcripcion, encoding="utf-8"))
    n = g.cargar_portada(a.horas, {a.id}, 1)[0]
    t_tit, t_cie, total = fases(tr)
    seg = [{"clave": "titular", "ini": 0.0, "fin": t_tit}, {"clave": "desarrollo", "ini": t_tit, "fin": t_cie},
           {"clave": "cierre", "ini": t_cie, "fin": total + 0.01}]
    cues = [(a_, b_, t_) for a_, b_, t_ in cues_desde_palabras(tr)]
    carpeta = AQUI / "salidas" / datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta.mkdir(parents=True)
    (carpeta / "guion.txt").write_text(" ".join(c[2] for c in cues), encoding="utf-8")
    (carpeta / "subtitulos.srt").write_text("\n".join(
        f"{i}\n{_f(c[0])} --> {_f(c[1])}\n{c[2]}\n" for i, c in enumerate(cues, 1)), encoding="utf-8")
    foto = g.descargar_imagen(n.get("imagen"))
    blur = foto.resize((W, gnp.PANEL_H), Image.BILINEAR).filter(ImageFilter.GaussianBlur(24)) if foto is not None else None
    ret = gnp.retrato(a.presentador)
    plan = plan_visual(tr, foto is not None) if a.visual == "auto" else None
    fotos = [foto] + [f for f in (g.descargar_imagen(u) for u in se.imagenes_extra(n)) if f is not None] if foto is not None else []
    ctx = {"fotos": fotos, "n": n, "ret": ret, "foto": foto, "blur": blur, "pres": a.presentador}
    reloj = {"t": 0.0}
    if a.visual == "auto":  # presentador a panel completo (dur<100): camara continua sobre el retrato estatico
        panel_original = gnp.panel_retrato
        gnp.panel_retrato = lambda r, t_, dur: camara_retrato(r, reloj["t"], total) if dur < 100 else panel_original(r, t_, dur)
    final = carpeta / ("valentina_alerta_jujuy.mp4" if a.presentador == "valentina" else f"{a.presentador}_noticia.mp4")
    audio_in, mezcla = str(a.audio), None
    if a.musica != "none":
        cat = mm.categoria_musical(n) if a.musica == "auto" else a.musica
        audio_in = str(carpeta / "audio_mezcla.wav")
        mezcla = mm.mezclar(a.audio, cat, audio_in)
    cmd = [gp.ffmpeg_exe(), "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", audio_in,
           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
           "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(final)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for i in range(int(round(total * FPS))):
        t = i / FPS
        s = next((x for x in seg if x["ini"] <= t < x["fin"]), seg[-1])
        reloj["t"] = t
        pil =frame_auto(t, plan, ctx, total, seg) if plan else gnp.frame(t, s, total, ctx)
        pil = apertura_overlay(pil, t)
        cue = next((c for c in cues if c[0] <= t < c[1]), None)
        if cue:
            g.subtitulo(pil, cue[2])
        p.stdin.write(np.asarray(pil, dtype=np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg fallo")
    meta = {"presentadora": gnp.PRES[a.presentador]["nombre"], "voz": f"externa aprobada: {Path(a.audio).name}",
            "video": gp.verificar(final), "duracion_audio_s": round(total, 2),
            "imagenes": len(fotos), "animacion_facial": None, "presentador_movimiento": "retrato estatico + zoom/paneo de camara" if plan else "clasico",
            "secuencia_visual": [(round(a_, 1), round(b_, 1), m) for a_, b_, m in plan] if plan else "clasico", "musica": mezcla,
            "noticia": {"id": n["id"], "titulo": n["titulo"], "url": n["url"], "fecha": n["fecha_iso"]}}
    (carpeta / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("MP4:", final)


def _f(x):
    return f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{x % 60:06.3f}".replace(".", ",")


if __name__ == "__main__":
    main()
