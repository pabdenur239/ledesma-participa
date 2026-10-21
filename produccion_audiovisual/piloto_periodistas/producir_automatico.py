"""Produccion audiovisual automatica de UNA noticia (no publica nada).

noticia publicada (portada.json) -> seleccion editorial -> presentador -> guion -> ElevenLabs (con tiempos) ->
render (generar_piloto_voz_externa.py --visual auto: periodista / imagen de la nota / dividido) -> MP4 1080x1920.

Uso:  .venv\\Scripts\\python.exe produccion_audiovisual\\piloto_periodistas\\producir_automatico.py [--id ID] [--horas 48] [--sin-voz]
Requiere ELEVENLABS_API_KEY. --sin-voz = prueba del flujo visual SIN locucion (pista silenciosa, tiempos estimados, sin musica).
"""
import argparse
import json
import os
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path

if not sys.flags.utf8_mode:  # Windows: equivale a PYTHONUTF8=1 sin que el usuario lo defina (consola cp1252, open() sin encoding)
    raise SystemExit(subprocess.call([sys.executable, "-X", "utf8", *sys.argv], env={**os.environ, "PYTHONUTF8": "1"}))

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import mezcla_musical as mm  # noqa: E402
import seleccion_editorial as se  # noqa: E402
import voz_elevenlabs as ve  # noqa: E402


def _transcripcion(palabras):
    """[(palabra, ini, fin)] -> estructura que consume generar_piloto_voz_externa (una 'frase' por segmento)."""
    segs, cur = [], []
    for p, a, b in palabras:
        cur.append({"p": p, "ini": a, "fin": b})
        if p.endswith((".", "?", "!")):
            segs.append({"ini": cur[0]["ini"], "fin": b, "texto": " ".join(w["p"] for w in cur), "palabras": cur})
            cur = []
    if cur:
        segs.append({"ini": cur[0]["ini"], "fin": cur[-1]["fin"], "texto": " ".join(w["p"] for w in cur), "palabras": cur})
    return segs


def _estimar(texto):
    """SOLO para --sin-voz: tiempos estimados (~0,36 s/palabra + pausa en puntuacion)."""
    t, out = 0.3, []
    for p in texto.split():
        d = 0.36 + 0.02 * max(len(p) - 6, 0)
        out.append((p, round(t, 3), round(t + d, 3)))
        t += d + (0.45 if p.endswith((".", "?", "!")) else 0.0)
    return out, t + 0.6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, help="forzar una noticia (por defecto: seleccion automatica)")
    ap.add_argument("--horas", type=int, default=48)
    ap.add_argument("--sin-voz", action="store_true")
    ap.add_argument("--max-palabras", type=int, default=62, help="tope de palabras del guion (no se rellena si la nota es corta)")
    a = ap.parse_args()

    n, motivo = se.seleccionar(a.horas, a.id)
    pres = se.presentador_para(n)
    cat = mm.categoria_musical(n)
    if not a.sin_voz and not os.environ.get("ELEVENLABS_API_KEY"):
        raise SystemExit("Falta ELEVENLABS_API_KEY. Configurala SOLO en tu entorno local (PowerShell):\n"
                         "  [Environment]::SetEnvironmentVariable('ELEVENLABS_API_KEY','<tu clave>','User')  y abri una terminal nueva.\n"
                         "No la pegues en codigo ni en archivos del repo.")
    texto, _ = se.guion_automatico(n, a.max_palabras)
    carpeta = AQUI / "salidas" / ("auto_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    carpeta.mkdir(parents=True)
    (carpeta / "guion.txt").write_text(texto, encoding="utf-8")
    print(f"Noticia {n['id']}: {n['titulo']} | {n['fuente_nombre']} | {pres} | {cat} | {motivo}\nLocucion: {texto}")

    audio = carpeta / "locucion.mp3"
    if a.sin_voz:
        palabras, dur = _estimar(texto)
        audio = carpeta / "pista_silenciosa_prueba.wav"
        with wave.open(str(audio), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(b"\x00\x00" * int(dur * 24000))
    else:
        palabras = ve.sintetizar(texto, pres, audio)  # SinCredenciales si falta la clave
        import generar_noticia_presentador as gnp
        dur = len(gnp._decodificar(audio, 24000)) / 24000
    tr = {"duracion": dur, "segmentos": _transcripcion(palabras)}
    ruta_tr = carpeta / "transcripcion.json"
    ruta_tr.write_text(json.dumps(tr, ensure_ascii=False, indent=1), encoding="utf-8")

    cmd = [sys.executable, str(AQUI / "generar_piloto_voz_externa.py"), "--audio", str(audio), "--transcripcion", str(ruta_tr),
           "--id", str(n["id"]), "--presentador", pres, "--horas", str(max(a.horas, 240)), "--visual", "auto",
           "--musica", "none" if a.sin_voz else cat]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    sys.stdout.write(r.stdout[-1500:])
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-1500:])
        raise SystemExit("fallo el render")
    if not a.sin_voz:
        se.marcar_producida(n["id"])


if __name__ == "__main__":
    main()
