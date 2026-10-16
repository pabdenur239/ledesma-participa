"""Piloto "LAS 2 NOTICIAS DEL DIA - LEDESMA PARTICIPA" (periodistas digitales).

Uso (desde la raiz del repo):
    .venv\\Scripts\\python.exe produccion_audiovisual\\piloto_periodistas\\generar_piloto.py
Opciones: --presentador valentina|mateo  --sin-vigencia  --noticias ID1 ID2
No publica nada. Solo lee la base y escribe en salidas/<fecha-hora>/.

Pasos: 1 seleccion -> 2 guion -> 3 audio (Piper, local) -> 4 subtitulos (ASS)
-> 5 presentador (portrait aprobado + lip-sync si hay herramienta) -> 6 ensamblado
-> 7 MP4 final 1080x1920.
"""
import argparse
import html
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
sys.path.insert(0, str(RAIZ))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from motor_noticias.scoring_editorial import evaluar_noticia  # noqa: E402

W, H = 1080, 1920
AZUL, DORADO, BLANCO = "#0A2540", "#C9A227", "#FFFFFF"
ASSETS = AQUI / "assets" / "presentadores"
VOCES = AQUI / "modelos_voz"
PRESENTADORES = {
    "valentina": {"nombre": "Valentina Vega", "voz": "es_AR-daniela-high", "foto": "valentina_vega.png"},
    "mateo": {"nombre": "Mateo Ferrer", "voz": "es_MX-claude-high", "foto": "mateo_ferrer.png"},
}
TEMAS_MATEO = ("policial", "politic", "deport", "servicio", "judicial", "accidente", "economi")


def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def correr(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"fallo {Path(str(cmd[0])).name}: {r.stderr[-1500:]}")
    return r.stderr


# ---------------------------------------------------------------- 1. seleccion
def seleccionar(db_path, forzadas, sin_vigencia):
    from motor_noticias.motor_editorial import _es_mismo_hecho
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    if forzadas:
        q = f"select * from noticias where id in ({','.join('?' * len(forzadas))})"
        filas = [dict(r) for r in con.execute(q, forzadas)]
    else:
        filas = [dict(r) for r in con.execute(
            "select * from noticias where estado in ('preparada','publicada') "
            "and coalesce(revision_estado,'') != 'rechazada' and coalesce(requiere_revision_especial,0)=0 "
            "and coalesce(urgente,0)=0 order by id desc limit 400")]
        if not sin_vigencia:
            from motor_noticias.motor_editorial import ANTIGUEDAD_MAXIMA_HORAS
            lim = (datetime.now(timezone.utc) - timedelta(hours=ANTIGUEDAD_MAXIMA_HORAS)).isoformat()
            filas = [f for f in filas if f["fecha_recoleccion"] >= lim]
    for f in filas:
        f["_score"] = evaluar_noticia(f)
        f["_total"] = f["_score"]["total"]
    filas.sort(key=lambda f: f["_total"], reverse=True)
    if forzadas:
        return filas[:2]
    elegidas = []
    for f in filas:
        titulo = f.get("titulo_revisado") or f.get("titulo_preparado") or f["titulo_original"]
        if not (f.get("texto_revisado") or f.get("texto_preparado") or f["texto_original"]):
            continue
        if any(_es_mismo_hecho(titulo, e["_titulo"]) for e in elegidas):
            continue
        f["_titulo"] = titulo
        elegidas.append(f)
        if len(elegidas) == 2:
            break
    if len(elegidas) < 2:
        raise SystemExit("No hay 2 noticias elegibles (probar --sin-vigencia si la base esta desactualizada).")
    return elegidas


def elegir_presentador(noticias):
    n = noticias[0]
    texto = f"{n.get('categoria_tematica') or ''} {n.get('categoria_riesgo') or ''} {n['titulo_original']}".lower()
    return "mateo" if any(t in texto for t in TEMAS_MATEO) else "valentina"


# ---------------------------------------------------------------- 2. guion
def _limpiar(t):
    t = html.unescape(t or "")
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"(?im)^\s*fuente.*$", "", t)
    t = re.sub(r"^[^.–]{0,40}®\s*[–-]\s*", "", t.strip())
    return re.sub(r"\s+", " ", t).strip()


def resumen_oral(texto, max_palabras=38):
    """Extractivo: toma oraciones completas de la fuente (sin agregar hechos)."""
    oraciones = re.split(r"(?<=[.!?])\s+", _limpiar(texto))
    out, n = [], 0
    for o in oraciones:
        p = len(o.split())
        if n + p > max_palabras and out:
            break
        if n + p > max_palabras + 12:
            continue
        out.append(o)
        n += p
        if n >= 22:
            break
    return " ".join(out)


def titulo_corto(t, maxc=70):
    t = _limpiar(t)
    return t if len(t) <= maxc else t[:maxc].rsplit(" ", 1)[0] + "…"


def generar_guion(noticias, pres):
    p = PRESENTADORES[pres]
    seg = [{"clave": "apertura", "texto": f"Ledesma Participa. Las dos noticias del día. Soy {p['nombre']}."}]
    for i, n in enumerate(noticias, 1):
        titulo = n.get("titulo_revisado") or n.get("titulo_preparado") or n["titulo_original"]
        cuerpo = n.get("texto_revisado") or n.get("texto_preparado") or n["texto_original"]
        intro = "Primera noticia." if i == 1 else "Segunda noticia."
        resumen = resumen_oral(cuerpo) or _limpiar(titulo)
        seg.append({"clave": f"noticia{i}", "titulo": titulo_corto(titulo), "texto": f"{intro} {_limpiar(titulo)}. {resumen}",
                    "ref": {"id": n["id"], "titulo": titulo, "url": n["url_fuente"], "fecha": n.get("fecha_fuente") or n["fecha_recoleccion"],
                            "fuente": n.get("nombre_fuente"), "imagen": n.get("imagen_publicacion_ruta")}})
    seg.append({"clave": "cierre", "texto": "Seguí toda la información en Ledesma Participa."})
    return seg


# ---------------------------------------------------------------- 3. audio
def sintetizar(seg, pres, carpeta):
    from piper import PiperVoice
    voz = PiperVoice.load(str(VOCES / f"{PRESENTADORES[pres]['voz']}.onnx"))
    for s in seg:
        ruta = carpeta / f"{s['clave']}.wav"
        with wave.open(str(ruta), "wb") as wf:
            voz.synthesize_wav(s["texto"], wf)
        with wave.open(str(ruta)) as wf:
            s["wav"] = ruta
            s["dur"] = wf.getnframes() / wf.getframerate()
    return seg


# ---------------------------------------------------------------- 4. subtitulos
def _t(s):
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


def trozos(texto, max_pal=5):
    pal = texto.split()
    return [" ".join(pal[i:i + max_pal]) for i in range(0, len(pal), max_pal)]


def subtitulos(seg, carpeta):
    ass = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "",
           "[V4+ Styles]",
           "Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV",
           "Style: Sub,Arial,74,&H00FFFFFF,&H00402508,&H80000000,1,1,5,0,2,90,90,380", "",
           "[Events]", "Format: Layer,Start,End,Style,Text"]
    srt, t0, k = [], 0.0, 1
    for s in seg:
        partes = trozos(s["texto"])
        total = sum(len(p.split()) for p in partes)
        t = t0
        for p in partes:
            d = s["dur"] * len(p.split()) / total
            ass.append(f"Dialogue: 0,{_t(t)},{_t(t + d)},Sub,{p}")
            f = lambda x: f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{x % 60:06.3f}".replace(".", ",")
            srt.append(f"{k}\n{f(t)} --> {f(t + d)}\n{p}\n")
            k += 1
            t += d
        s["t0"] = t0
        t0 += s["dur"]
    (carpeta / "subtitulos.ass").write_text("\n".join(ass), encoding="utf-8")
    (carpeta / "subtitulos.srt").write_text("\n".join(srt), encoding="utf-8")
    return t0


# ---------------------------------------------------------------- 5/6. visual + ensamblado
def fuente(tam, bold=True):
    for n in ("arialbd.ttf" if bold else "arial.ttf", "segoeuib.ttf"):
        try:
            return ImageFont.truetype(n, tam)
        except OSError:
            pass
    return ImageFont.load_default()


def _ajustar(draw, texto, f, ancho):
    lineas, cur = [], ""
    for p in texto.split():
        if draw.textlength((cur + " " + p).strip(), font=f) <= ancho:
            cur = (cur + " " + p).strip()
        else:
            lineas.append(cur)
            cur = p
    return lineas + [cur]


def fondo(s, pres, carpeta):
    """Fondo 1080x1920 con branding; la zona del presentador queda para el overlay."""
    im = Image.new("RGB", (W, H), AZUL)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 170], fill="#071A2E")
    d.rectangle([0, 170, W, 182], fill=DORADO)
    d.text((W // 2, 85), "LEDESMA PARTICIPA", font=fuente(66), fill=BLANCO, anchor="mm")
    d.rectangle([0, 1000, W, 1010], fill=DORADO)
    d.text((60, 1040), PRESENTADORES[pres]["nombre"].upper() + " · PERIODISTA DIGITAL", font=fuente(34), fill=DORADO)
    if s["clave"].startswith("noticia"):
        ref = s["ref"]
        d.text((60, 1100), "LAS 2 NOTICIAS DEL DÍA · " + s["clave"][-1] + "/2", font=fuente(34, False), fill="#9FB3C8")
        f = fuente(54)
        y = 1160
        for l in _ajustar(d, s["titulo"], f, W - 120)[:3]:
            d.text((60, y), l, font=f, fill=BLANCO)
            y += 68
    else:
        d.text((W // 2, 1200), "LAS 2 NOTICIAS DEL DÍA", font=fuente(64), fill=BLANCO, anchor="mm")
        d.text((W // 2, 1290), "Información verificada de Ledesma y Jujuy", font=fuente(38, False), fill=DORADO, anchor="mm")
    d.rectangle([0, H - 40, W, H], fill=DORADO)
    ruta = carpeta / f"fondo_{s['clave']}.png"
    im.save(ruta)
    return ruta


def recurso_imagen(s, carpeta):
    """Imagen de apoyo: la placa propia de la noticia si existe (nunca se inventa una escena)."""
    ruta = (s.get("ref") or {}).get("imagen")
    if not ruta:
        return None
    p = Path(ruta)
    p = p if p.is_absolute() else RAIZ / ruta
    return p if p.exists() else None


def presentador_clip(pres, s, carpeta, ffmpeg):
    foto = ASSETS / PRESENTADORES[pres]["foto"]
    if not foto.exists():
        raise SystemExit(f"FALTA ASSET APROBADO: {foto}")
    salida = carpeta / f"pres_{s['clave']}.mp4"
    hook = AQUI / "herramientas" / "lipsync.cmd"  # opcional: LivePortrait/SadTalker -> mp4 (args: foto wav salida)
    if hook.exists():
        correr([hook, foto, s["wav"], salida])
        return salida
    # Sin lip-sync disponible: retrato aprobado con zoom lento (degradado, informado en metadata).
    vf = (f"scale=1000:1000:force_original_aspect_ratio=increase,crop=1000:1000,"
          f"zoompan=z='1+0.0006*on':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=840x840:fps=25")
    correr([ffmpeg, "-y", "-loop", "1", "-framerate", "25", "-i", foto, "-t", f"{s['dur']:.2f}", "-vf", vf,
            "-pix_fmt", "yuv420p", salida])
    return salida


def ensamblar(seg, pres, carpeta, final):
    ff = ffmpeg_exe()
    partes = []
    for s in seg:
        bg = fondo(s, pres, carpeta)
        clip = presentador_clip(pres, s, carpeta, ff)
        apoyo = recurso_imagen(s, carpeta)
        out = carpeta / f"seg_{s['clave']}.mp4"
        entradas = ["-loop", "1", "-framerate", "25", "-i", bg, "-i", clip, "-i", s["wav"]]
        filtro = "[0][1:v]overlay=120:200:shortest=1[a]"
        if apoyo:
            entradas += ["-loop", "1", "-framerate", "25", "-i", apoyo]
            filtro = ("[3:v]scale=300:300:force_original_aspect_ratio=increase,crop=300:300[ap];"
                      "[0][1:v]overlay=120:200:shortest=1[a0];[a0][ap]overlay=720:1030:shortest=1[a]")
        correr([ff, "-y", *entradas, "-filter_complex", filtro, "-map", "[a]", "-map", "2:a", "-t", f"{s['dur'] + 0.25:.2f}",
                "-af", "apad=pad_dur=0.25", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-r", "25", "-c:a", "aac", "-ar", "44100", out])
        partes.append(out)
    lista = carpeta / "lista.txt"
    lista.write_text("\n".join(f"file '{p.name}'" for p in partes), encoding="utf-8")
    sin_sub = carpeta / "sin_subtitulos.mp4"
    correr([ff, "-y", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", sin_sub])
    # Subtitulos: ruta relativa para evitar problemas de escape en Windows
    r = subprocess.run([ff, "-y", "-i", "sin_subtitulos.mp4", "-vf", "ass=subtitulos.ass", "-c:v", "libx264", "-preset", "fast",
                        "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", final.name],
                       cwd=carpeta, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError("fallo el quemado de subtitulos: " + r.stderr[-1500:])


def verificar(mp4):
    ff = ffmpeg_exe()
    r = subprocess.run([ff, "-i", str(mp4)], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r)
    res = re.search(r"Video:.*?(\d{3,4})x(\d{3,4})", r)
    d = int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3])
    return {"duracion_s": round(d, 1), "resolucion": f"{res[1]}x{res[2]}", "audio": "Audio:" in r, "es_9_16": int(res[1]) * 16 == int(res[2]) * 9}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(RAIZ / "data" / "ledesma_participa.db"))
    ap.add_argument("--presentador", choices=list(PRESENTADORES))
    ap.add_argument("--sin-vigencia", action="store_true")
    ap.add_argument("--assets-dir", help="solo para pruebas tecnicas")
    ap.add_argument("--noticias", nargs=2, type=int)
    a = ap.parse_args()
    global ASSETS
    if a.assets_dir:
        ASSETS = Path(a.assets_dir)

    noticias = seleccionar(a.db, a.noticias, a.sin_vigencia)
    pres = a.presentador or elegir_presentador(noticias)
    if not (ASSETS / PRESENTADORES[pres]["foto"]).exists():
        raise SystemExit(f"FALTA ASSET APROBADO: {ASSETS / PRESENTADORES[pres]['foto']}")
    carpeta = AQUI / "salidas" / datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta.mkdir(parents=True)
    seg = generar_guion(noticias, pres)
    (carpeta / "guion.txt").write_text("\n\n".join(s["texto"] for s in seg), encoding="utf-8")
    seg = sintetizar(seg, pres, carpeta)
    subtitulos(seg, carpeta)
    final = carpeta / "las_2_noticias_del_dia.mp4"
    ensamblar(seg, pres, carpeta, final)
    info = verificar(final)
    meta = {"presentador": PRESENTADORES[pres]["nombre"], "voz": PRESENTADORES[pres]["voz"], "video": info,
            "lipsync": (AQUI / "herramientas" / "lipsync.cmd").exists() or "no (retrato con zoom lento)",
            "noticias": [s["ref"] for s in seg if "ref" in s]}
    (carpeta / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2, default=str))
    print("MP4:", final)


if __name__ == "__main__":
    main()
