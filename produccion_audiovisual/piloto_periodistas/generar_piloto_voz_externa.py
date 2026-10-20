"""Piloto de UNA noticia con presentadora y audio EXTERNO aprobado (sin TTS local).

1) transcribir (solo para subtitulos): venv_xtts\Scripts\python.exe produccion_audiovisual\piloto_periodistas\transcribir_audio.py AUDIO transcripcion.json
2) render: .venv\Scripts\python.exe produccion_audiovisual\piloto_periodistas\generar_piloto_voz_externa.py --audio AUDIO --transcripcion transcripcion.json --id ID --presentador valentina
La duracion del video = duracion exacta del audio. NO publica nada.
"""
import argparse
import json
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--transcripcion", required=True)
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--presentador", default="valentina", choices=list(gnp.PRES))
    ap.add_argument("--horas", type=int, default=240)
    ap.add_argument("--musica", default="auto", help="auto | clima_servicios|policial|politica|sociedad|deportes|urgente | none")
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
    ctx = {"n": n, "ret": ret, "foto": foto, "blur": blur, "pres": a.presentador}
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
        pil = gnp.frame(t, s, total, ctx)
        pil = apertura_overlay(pil, t)
        cue = next((c for c in cues if c[0] <= t < c[1]), None)
        if cue:
            g.subtitulo(pil, cue[2])
        p.stdin.write(np.asarray(pil, dtype=np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg fallo")
    meta = {"presentadora": gnp.PRES[a.presentador]["nombre"], "voz": f"externa aprobada: {Path(a.audio).name}",
            "video": gp.verificar(final), "duracion_audio_s": round(total, 2), "musica": mezcla,
            "noticia": {"id": n["id"], "titulo": n["titulo"], "url": n["url"], "fecha": n["fecha_iso"]}}
    (carpeta / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("MP4:", final)


def _f(x):
    return f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{x % 60:06.3f}".replace(".", ",")


if __name__ == "__main__":
    main()
