"""Cama musical por categoria + mezcla con ducking. La voz siempre domina.
categoria_musical(noticia) -> clave de config_musica.json | mezclar(voz, categoria, salida) -> stats"""
import json
import re
import subprocess
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
SR = 44100


def cfg():
    return json.load(open(AQUI / "config_musica.json", encoding="utf-8"))


def categoria_musical(n):
    c = cfg()
    if n.get("urgente"):
        return "urgente"
    texto = (n.get("titulo", "") + " " + (n.get("bajada") or "")).lower()
    for cat in ("policial", "deportes", "politica", "clima_servicios"):
        if any(re.search(k, texto) for k in c["palabras_clave"][cat]):
            return cat
    slug = n.get("categoria_slug")
    return {"policiales": "policial", "deportes": "deportes", "servicios": "clima_servicios"}.get(slug, c["categoria_por_defecto"])


def _leer(ruta):
    import imageio_ffmpeg
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(ruta), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                       capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def _rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)


def mezclar(voz_path, categoria, salida_wav):
    import wave
    c = cfg()
    m = c["mezcla"]
    voz = _leer(voz_path)
    musica = _leer(AQUI / c["pistas"][categoria])
    n = len(voz)
    musica = np.tile(musica, int(np.ceil(n / len(musica))))[:n]
    # nivel: RMS de la musica = RMS de la voz (solo tramos con habla) + musica_db_bajo_voz
    ventana = int(0.05 * SR)
    rms_v = np.sqrt(np.convolve(voz ** 2, np.ones(ventana) / ventana, mode="same"))
    habla = rms_v > 0.1 * rms_v.max()
    voz_db = _rms_db(voz[habla])
    musica *= 10 ** ((voz_db + m["musica_db_bajo_voz"] - _rms_db(musica)) / 20)
    # ducking: la musica baja ducking_db mientras habla la voz (ataque 50 ms, relajacion 400 ms)
    obj = habla.astype(np.float32)
    a_att, a_rel = np.exp(-1 / (0.05 * SR)), np.exp(-1 / (0.4 * SR))
    env = np.zeros(n, dtype=np.float32)
    e = 0.0
    paso = 200  # suavizado por bloques
    for i in range(0, n, paso):
        o = obj[i:i + paso].mean()
        k = a_att if o > e else a_rel
        e = o + (e - o) * k ** paso
        env[i:i + paso] = e
    musica *= 10 ** (-m["ducking_db"] * env / 20)
    # fades
    fi, fo = int(m["fade_in_s"] * SR), int(m["fade_out_s"] * SR)
    musica[:fi] *= np.linspace(0, 1, fi)
    musica[-fo:] *= np.linspace(1, 0, fo)
    mix = voz + musica
    pico = np.max(np.abs(mix))
    if pico > 0.97:
        mix *= 0.97 / pico
    with wave.open(str(salida_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((mix * 32767).astype(np.int16).tobytes())
    hablando = env > 0.9
    return {"categoria": categoria, "pista": c["pistas"][categoria],
            "voz_db": round(float(voz_db), 1),
            "musica_vs_voz_db_sin_duck": m["musica_db_bajo_voz"],
            "musica_vs_voz_db_mientras_habla": round(float(_rms_db(musica[hablando]) - voz_db), 1) if hablando.any() else None}
