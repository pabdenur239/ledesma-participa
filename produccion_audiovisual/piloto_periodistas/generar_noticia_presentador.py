"""Piloto de UNA noticia con presentador/a virtual (Valentina Vega / Mateo Ferrer).

Un solo comando (desde la raiz del repo):
    .venv\\Scripts\\python.exe produccion_audiovisual\\piloto_periodistas\\generar_noticia_presentador.py
Opciones: --id ID (forzar noticia de la portada publica)  --presentador valentina|mateo  --horas 36
Retratos: recortes (sin regenerar rostros) de assets/presentadores/valentina y mateo.png (imagen oficial conjunta).
Voz: externa (--audios-dir / --audio, WAV/MP3) o Kokoro local por defecto. Sin lip-sync: retrato animado (zoom/pan) + motion graphics. NO publica nada.
"""
import argparse
import html
import json
import math
import re
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parents[1]))

import generar_piloto as gp  # noqa: E402
import generar_resumen_visual as g  # noqa: E402

W, H, FPS = g.W, g.H, g.FPS
OFICIAL = AQUI / "assets" / "presentadores" / "valentina y mateo.png"
# Recortes (izq, arriba, der, abajo) sobre la imagen conjunta oficial, proporcion 1080:900.
RECORTES = {"valentina": (30, 170, 650, 687), "mateo": (688, 150, 1333, 688)}
PRES = {"valentina": {"nombre": "Valentina Vega", "voz": "ef_dora"}, "mateo": {"nombre": "Mateo Ferrer", "voz": "em_alex"}}
TEMAS_DUROS = r"vuelco|choque|accidente|incendio|polic|robo|detenid|operativo|siniestro|deport"
PANEL_Y, PANEL_H = 190, 900


def cuerpo_noticia(n):
    """Texto periodistico de la nota: SOLO el contenedor <div class="noticia-cuerpo"> de nuestra pagina
    (nunca menu, pie, enlaces ni textos legales). Si no se puede aislar, usa la bajada de la portada."""
    try:
        h = g._get(n["url"]).decode("utf-8", "replace")
        m = re.search(r'<div class="noticia-cuerpo">(.*?)</div>', h, re.S)
        if m:
            ps = [html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in re.findall(r"<p[^>]*>(.*?)</p>", m.group(1), re.S)]
            ps = [re.sub(r"\s+", " ", p) for p in ps if p]
            if ps:
                return " ".join(ps[:3])
    except Exception:
        pass
    return n["bajada"] or ""


def elegir(horas, forzada, pres_forzado):
    cands = g.cargar_portada(horas, {forzada} if forzada else set(), 12 if not forzada else 1)
    if forzada:
        n = cands[0]
    else:
        # una noticia fuerte: mayor puntaje entre las que NO son avisos de servicio rutinarios
        fuertes = [c for c in cands if re.search(TEMAS_DUROS, c["titulo"].lower()) and c["_score"].get("clasificacion") != "normal"] or \
                  [c for c in cands if re.search(TEMAS_DUROS, c["titulo"].lower())]
        n = (fuertes or cands)[0]
    texto = (n["titulo"] + " " + (n["bajada"] or "")).lower()
    pres = pres_forzado or ("mateo" if re.search(TEMAS_DUROS, texto) or n.get("categoria_slug") in ("policiales", "deportes", "servicios") else "valentina")
    return n, pres


def retrato(pres):
    im = Image.open(OFICIAL).convert("RGB")
    l, t, r, b = RECORTES[pres]
    return im.crop((l, t, r, b))


def sintetizar(seg, pres, carpeta):
    from kokoro_onnx import Kokoro
    d = AQUI / "modelos_voz" / "kokoro"
    k = Kokoro(str(d / "kokoro-v1.0.onnx"), str(d / "voices-v1.0.bin"))
    sr, pcm, t = 24000, [], 0.0
    for s in seg:
        audio, sr = k.create(s["texto"], voice=PRES[pres]["voz"], speed=1.0, lang="es")
        datos = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
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


def _decodificar(ruta, sr=24000):
    """WAV/MP3 externo -> int16 mono a 24 kHz (ffmpeg embebido)."""
    r = subprocess.run([gp.ffmpeg_exe(), "-v", "error", "-i", str(ruta), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise SystemExit(f"No se pudo leer el audio externo: {ruta}")
    return np.frombuffer(r.stdout, dtype=np.int16)


def _buscar(carpeta, clave):
    for ext in (".wav", ".mp3", ".m4a", ".flac", ".ogg"):
        f = Path(carpeta) / f"{clave}{ext}"
        if f.exists():
            return f
    raise SystemExit(f"Falta {clave}.wav/.mp3 en {carpeta}")


def audio_externo(seg, carpeta, audios_dir=None, audio_unico=None):
    """Voz externa (TTS comercial). Dos modos:
    --audios-dir D : D/apertura, titular, desarrollo, cierre (.wav/.mp3) -> sincronia exacta por segmento.
    --audio F      : un solo archivo con la locucion completa (texto de guion.txt, en orden); los limites
                     entre segmentos se estiman por proporcion de palabras."""
    sr = 24000
    if audios_dir:
        voces = [_decodificar(_buscar(audios_dir, x["clave"]), sr) for x in seg]
    else:
        todo = _decodificar(audio_unico, sr)
        pesos = np.array([len(x["texto"].split()) for x in seg], dtype=float)
        cortes = np.round(np.cumsum(pesos / pesos.sum()) * len(todo)).astype(int)
        voces = np.split(todo, cortes[:-1])
    pcm, t = [], 0.0
    for s_, datos in zip(seg, voces):
        pcm += [np.zeros(int(s_["lead"] * sr), dtype=np.int16), datos, np.zeros(int(s_["tail"] * sr), dtype=np.int16)]
        s_["voz_ini"] = t + s_["lead"]
        s_["ini"] = t
        t += s_["lead"] + len(datos) / sr + s_["tail"]
        s_["fin"] = t
    ruta = carpeta / "audio_final.wav"
    with wave.open(str(ruta), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(np.concatenate(pcm).tobytes())
    return ruta, t


def guion(n, pres, cuerpo):
    titulo = gp._limpiar(n["titulo"]).rstrip(".")
    oraciones = re.split(r"(?<=[.!?])\s+", gp._limpiar(cuerpo))
    desarrollo, pal = [], 0
    for o in oraciones:
        if pal + len(o.split()) > 60 and desarrollo:
            break
        desarrollo.append(o)
        pal += len(o.split())
    desarrollo = " ".join(desarrollo)
    if desarrollo and not re.search(r"[.!?]$", desarrollo):
        desarrollo = ""
    return [
        {"clave": "apertura", "lead": 0.15, "tail": 0.2, "texto": "Ledesma Participa."},
        {"clave": "titular", "lead": 0.1, "tail": 0.3, "texto": f"Soy {PRES[pres]['nombre']}. {titulo}."},
        {"clave": "desarrollo", "lead": 0.1, "tail": 0.4, "texto": desarrollo or gp._limpiar(n["bajada"] or "")},
        {"clave": "cierre", "lead": 0.1, "tail": 1.0, "texto": "Ampliá la información en Ledesma Participa."},
    ]


def panel_retrato(ret, t, dur):
    z = 1.0 + 0.07 * (t / max(dur, 0.1))
    w, h = ret.size
    cw, ch = w / z, h / z
    x0 = (w - cw) * (0.5 + 0.25 * math.sin(t * 0.5))
    y0 = (h - ch) * 0.35
    return ret.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((W, PANEL_H), Image.LANCZOS)


def frame(t, s, seg_total, ctx):
    n, ret, foto, blur = ctx["n"], ctx["ret"], ctx["foto"], ctx["blur"]
    lt, dur = t - s["ini"], s["fin"] - s["ini"]
    if s["clave"] == "apertura":
        pil = g.fondo_base(t)
        d = ImageDraw.Draw(pil, "RGBA")
        a = g.ease(lt / 0.5)
        d.text((W // 2, 860), "LEDESMA", font=g.fnt(int(118 * (0.85 + 0.15 * a))), fill=g.BLANCO + (int(255 * a),), anchor="mm")
        d.text((W // 2, 990), "PARTICIPA", font=g.fnt(int(118 * (0.85 + 0.15 * a))), fill=g.DORADO + (int(255 * a),), anchor="mm")
        d.rectangle([W // 2 - int(350 * a), 1070, W // 2 + int(350 * a), 1082], fill=g.DORADO)
        return pil
    pil = g.fondo_base(t)
    d = ImageDraw.Draw(pil, "RGBA")
    en_desarrollo = s["clave"] == "desarrollo" and foto is not None
    if en_desarrollo:
        pil.paste(blur, (0, PANEL_Y))
        pil.paste(g.kenburns(foto, lt, dur, W, PANEL_H), (0, PANEL_Y))
        # presentador en burbuja, abajo a la izquierda (no tapa el centro de la foto)
        b = 300
        cara = panel_retrato(ret, t, 999).resize((int(W * b / PANEL_H), b)).crop((int(W * b / PANEL_H) // 2 - b // 2, 0, int(W * b / PANEL_H) // 2 + b // 2, b))
        mask = Image.new("L", (b, b), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, b - 1, b - 1], fill=255)
        pil.paste(cara, (40, PANEL_Y + PANEL_H - b - 30), mask)
        d.ellipse([40, PANEL_Y + PANEL_H - b - 30, 40 + b, PANEL_Y + PANEL_H - 30], outline=g.DORADO + (255,), width=8)
    else:
        pil.paste(panel_retrato(ret, t - s["ini"] + (0 if s["clave"] == "titular" else 3), 12), (0, PANEL_Y))
    d.rectangle([0, PANEL_Y, W, PANEL_Y + PANEL_H], outline=g.DORADO + (255,), width=8)
    d.rectangle([0, 1090, W, 1430], fill=(7, 26, 46, 245))
    d.rectangle([0, 1090, W, 1102], fill=g.DORADO + (255,))
    tag, _ = g.etiqueta(n)
    nombre = PRES[ctx["pres"]]["nombre"].upper()
    nw = int(d.textlength(nombre, font=g.fnt(34)))
    ft = 44
    while ft > 28 and int(d.textlength(tag, font=g.fnt(ft))) + 60 + 60 + 30 > W - 60 - nw:  # la etiqueta no debe tapar el nombre
        ft -= 2
    cw = int(d.textlength(tag, font=g.fnt(ft))) + 60
    d.rectangle([60, 1130, 60 + cw, 1200], fill=g.DORADO + (255,))
    d.text((60 + cw // 2, 1165), tag, font=g.fnt(ft), fill=g.AZUL, anchor="mm")
    d.text((W - 60, 1165), nombre, font=g.fnt(34), fill=g.DORADO, anchor="rm")
    if s["clave"] == "cierre":
        d.text((60, 1250), "Ampliá la información en", font=g.fnt(50, False), fill=g.BLANCO)
        d.text((60, 1315), "ledesmaparticipa.com.ar", font=g.fnt(60), fill=g.DORADO)
    else:
        f = g.fnt(52)
        a = g.ease(lt / 0.45) if s["clave"] == "titular" else 1.0
        for i, l in enumerate(g.envolver(d, gp.titulo_corto(n["titulo"], 100), f, W - 120)[:3]):
            d.text((60, 1235 + i * 62 + int(30 * (1 - a))), l, font=f, fill=g.BLANCO + (int(255 * a),))
    g.cabecera(pil, 9)
    return pil


def renderizar(seg, cues, total, audio, salida, ctx):
    ff = gp.ffmpeg_exe()
    cmd = [ff, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(audio),
           "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
           "-shortest", "-movflags", "+faststart", str(salida)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for i in range(int(total * FPS)):
        t = i / FPS
        s = next((x for x in seg if x["ini"] <= t < x["fin"]), seg[-1])
        pil = frame(t, s, total, ctx)
        cue = next((c for c in cues if c[0] <= t < c[1]), None)
        if cue and s["clave"] != "apertura":
            g.subtitulo(pil, cue[2])
        p.stdin.write(np.asarray(pil, dtype=np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg fallo al codificar")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int)
    ap.add_argument("--presentador", choices=list(PRES))
    ap.add_argument("--horas", type=int, default=36)
    ap.add_argument("--audios-dir", help="carpeta con apertura/titular/desarrollo/cierre (.wav/.mp3) de la voz externa")
    ap.add_argument("--audio", help="un solo WAV/MP3 con toda la locucion (ver guion.txt)")
    ap.add_argument("--solo-guion", action="store_true", help="solo elige la noticia y escribe guion.txt/guion.json para el TTS")
    a = ap.parse_args()
    n, pres = elegir(a.horas, a.id, a.presentador)
    cuerpo = cuerpo_noticia(n)
    carpeta = AQUI / "salidas" / datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta.mkdir(parents=True)
    seg = guion(n, pres, cuerpo)
    (carpeta / "guion.txt").write_text("\n\n".join(s["texto"] for s in seg), encoding="utf-8")
    (carpeta / "guion.json").write_text(json.dumps([{"archivo": x["clave"], "texto": x["texto"]} for x in seg], ensure_ascii=False, indent=2), encoding="utf-8")
    if a.solo_guion:
        print("Guion para el TTS externo:", carpeta / "guion.json", "| presentador:", PRES[pres]["nombre"])
        return
    if a.audios_dir or a.audio:
        audio, total = audio_externo(seg, carpeta, a.audios_dir, a.audio)
    else:
        audio, total = sintetizar(seg, pres, carpeta)
    cues = g.subtitulos(seg, carpeta)
    foto = g.descargar_imagen(n.get("imagen"))
    blur = foto.resize((W, PANEL_H), Image.BILINEAR).filter(ImageFilter.GaussianBlur(24)) if foto is not None else None
    ret = retrato(pres)
    ret.save(carpeta / f"retrato_{pres}_recorte_oficial.png")
    final = carpeta / "noticia_con_presentador.mp4"
    renderizar(seg, cues, total, audio, final, {"n": n, "ret": ret, "foto": foto, "blur": blur, "pres": pres})
    meta = {"modo": "retrato animado (zoom/pan) + motion graphics, sin lip-sync", "presentador": PRES[pres]["nombre"],
            "voz": "externa" if (a.audios_dir or a.audio) else f"Kokoro {PRES[pres]['voz']}", "video": gp.verificar(final),
            "noticia": {"id": n["id"], "titulo": n["titulo"], "url": n["url"], "fuente_url": n["fuente_url"],
                        "fuente": n["fuente_nombre"], "fecha": n["fecha_iso"], "puntaje_total": n["_total"]}}
    (carpeta / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("MP4:", final)


if __name__ == "__main__":
    main()
