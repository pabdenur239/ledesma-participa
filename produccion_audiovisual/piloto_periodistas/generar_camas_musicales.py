"""Genera las camas musicales propias (sintesis local con numpy, sin licencias de terceros).
Una pista fija por categoria en assets/musica/. Uso: .venv\Scripts\python.exe produccion_audiovisual\piloto_periodistas\generar_camas_musicales.py
Deterministico: siempre produce las mismas pistas."""
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
SR = 44100
NOTA = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def hz(n, octava):  # n: "C", "F#" ...
    semis = NOTA[n[0]] + (1 if "#" in n else 0) + 12 * (octava - 4) - 9
    return 440.0 * 2 ** (semis / 12)


def env(n, a=0.5, r=0.8):
    e = np.ones(n)
    na, nr = int(a * SR), int(r * SR)
    e[:na] = np.linspace(0, 1, na)
    e[-nr:] = np.linspace(1, 0, nr)
    return e


def pad(freqs, dur, a=0.6, r=0.9, det=0.003, brillo=0.25):
    t = np.arange(int(dur * SR)) / SR
    x = np.zeros_like(t)
    for f in freqs:
        for d in (1 - det, 1 + det):
            x += np.sin(2 * np.pi * f * d * t) + brillo * np.sin(2 * np.pi * 2 * f * d * t)
    return x / (len(freqs) * 2) * env(len(t), a, r)


def pluck(f, dur=1.2, amort=0.996):
    n = int(dur * SR)
    p = int(SR / f)
    buf = np.random.RandomState(int(f)).uniform(-1, 1, p)
    out = np.zeros(n)
    for i in range(n):
        out[i] = buf[i % p]
        buf[i % p] = amort * 0.5 * (buf[i % p] + buf[(i + 1) % p])
    return out


def poner(base, snd, t0, g=1.0):
    i = int(t0 * SR)
    j = min(len(base), i + len(snd))
    if i < len(base):
        base[i:j] += g * snd[: j - i]


def acorde(base, notas, oct_, t0, dur, g=1.0, **kw):
    poner(base, pad([hz(n, oct_) for n in notas], dur, **kw), t0, g)


def lowpass(x, fc):
    a = np.exp(-2 * np.pi * fc / SR)
    y = np.zeros_like(x)
    acc = 0.0
    for i, v in enumerate(x):  # lento pero corto; solo se usa en percusion
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def bombo(dur=0.25):
    t = np.arange(int(dur * SR)) / SR
    return np.sin(2 * np.pi * (50 + 90 * np.exp(-t * 28)) * t) * np.exp(-t * 14)


def hat(dur=0.05):
    r = np.random.RandomState(3).uniform(-1, 1, int(dur * SR))
    return np.diff(r, prepend=0) * np.exp(-np.arange(len(r)) / SR * 90)


def clima_servicios():  # limpio, informativo, discreto (C-Am-F-G, 72 bpm)
    L = 64.0
    x = np.zeros(int(L * SR))
    prog = [("C", "E", "G", "B"), ("A", "C", "E", "G"), ("F", "A", "C", "E"), ("G", "B", "D", "F#")]
    for k in range(16):
        acorde(x, prog[k % 4], 3, k * 4.0, 4.6, 0.8, a=0.9, r=1.4)
    arp = [("C", "E", "G"), ("A", "C", "E"), ("F", "A", "C"), ("G", "B", "D")]
    for k in range(16):
        for j, n in enumerate(arp[k % 4] + (arp[k % 4][1],)):
            poner(x, pluck(hz(n, 5), 1.0, 0.994), k * 4.0 + 0.5 + j * 0.8, 0.22)
    return x


def policial():  # tension sobria: drone menor + pulso grave + notas escasas (Am, 80 bpm)
    L = 64.0
    x = np.zeros(int(L * SR))
    for k in range(8):
        acorde(x, ("A", "E"), 2, k * 8.0, 8.8, 0.9, a=1.5, r=1.8, brillo=0.1)
        acorde(x, ("A", "C", "E"), 3, k * 8.0 + (0 if k % 2 == 0 else 4), 5.0, 0.35, a=1.0, r=1.5, brillo=0.05)
    bpm = 80
    for b in range(int(L * bpm / 60)):
        poner(x, bombo(0.3) * 0.5, b * 60 / bpm, 0.5 if b % 4 == 0 else 0.22)
    for k, n in enumerate(["E", "D", "C", "B", "A", "B", "C", "E"] * 2):
        poner(x, pluck(hz(n, 4), 2.0, 0.998), 3.5 + k * 4.0, 0.2)
    return x


def politica():  # institucional, serio y neutro (D mayor/menor sobrio, 60 bpm)
    L = 64.0
    x = np.zeros(int(L * SR))
    prog = [("D", "A", "D"), ("G", "B", "D"), ("A", "C#", "E"), ("D", "F#", "A")]
    for k in range(16):
        notas = prog[k % 4]
        acorde(x, [n for n in notas], 3, k * 4.0, 4.8, 0.7, a=1.2, r=1.6, brillo=0.4)
        poner(x, pluck(hz(notas[0], 2), 3.0, 0.9985), k * 4.0, 0.5)
    return x


def sociedad():  # calida y cercana: pentatonica mayor con plucks suaves (G, 84 bpm)
    L = 64.0
    x = np.zeros(int(L * SR))
    prog = [("G", "B", "D"), ("E", "G", "B"), ("C", "E", "G"), ("D", "F#", "A")]
    for k in range(16):
        acorde(x, prog[k % 4], 3, k * 4.0, 4.6, 0.55, a=0.8, r=1.2, brillo=0.2)
    melo = ["D", "E", "G", "A", "G", "E", "D", "B"]
    paso = 60 / 84 * 1.0
    for i in range(int(L / paso) - 2):
        n = melo[(i * 3) % len(melo)]
        poner(x, pluck(hz(n, 4 + (i % 7 == 0)), 1.2, 0.995), i * paso, 0.3 if i % 2 == 0 else 0.2)
    return x


def deportes():  # dinamica y enerjica (120 bpm)
    L = 64.0
    x = np.zeros(int(L * SR))
    paso = 60 / 120
    prog = ["A", "A", "F", "G"]
    for b in range(int(L / paso)):
        t = b * paso
        poner(x, bombo(), t, 0.9 if b % 2 == 0 else 0.0)
        poner(x, hat(), t + paso / 2, 0.35)
        if b % 4 == 2:
            poner(x, hat(0.12), t, 0.5)
        nota = prog[(b // 8) % 4]
        poner(x, pad([hz(nota, 2)], 0.3, 0.01, 0.1, brillo=0.8), t, 0.7)
        if b % 8 in (0, 3, 6):
            acorde(x, (nota, "C" if nota != "F" else "A", "E"), 4, t, 0.45, 0.35, a=0.02, r=0.2, brillo=0.6)
    return x


def urgente():  # breve y reconocible: motivo de dos tonos ascendentes repetido (8 s, loop)
    L = 8.0
    x = np.zeros(int(L * SR))
    for k in range(4):
        for j, (n, o) in enumerate((("E", 5), ("B", 5))):
            t = k * 2.0 + j * 0.45
            tt = np.arange(int(0.4 * SR)) / SR
            poner(x, np.sin(2 * np.pi * hz(n, o) * tt) * np.exp(-tt * 5) * 0.8, t, 1.0)
        acorde(x, ("E", "B"), 2, k * 2.0, 2.0, 0.5, a=0.02, r=0.8, brillo=0.3)
    return x


PISTAS = {"clima_servicios": clima_servicios, "policial": policial, "politica": politica, "sociedad": sociedad,
          "deportes": deportes, "urgente": urgente}


def guardar(x, ruta):
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.8
    wav = ruta.with_suffix(".wav")
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((x * 32767).astype(np.int16).tobytes())
    import imageio_ffmpeg
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "128k",
                        str(ruta.with_suffix(".mp3"))])
    if r.returncode == 0:
        wav.unlink()
    return ruta.with_suffix(".mp3" if r.returncode == 0 else ".wav")


if __name__ == "__main__":
    destino = AQUI / "assets" / "musica"
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, f in PISTAS.items():
        print(guardar(f(), destino / nombre))
