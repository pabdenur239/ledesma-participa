"""Animacion procedural del retrato del periodista (sin regenerar rostros, identidad intacta).

- Parpadeo: parpados sintetizados con la piel del propio retrato.
- Habla (aprox. por envolvente de audio, NO fonemas): leve descenso de mandibula/labio inferior.
- Cabeza/cuerpo: balanceo y giro minimos, respiracion, cabeceos de enfasis.
Todo escala con el tono editorial (tono_editorial.PARAMETROS). Manos/brazos: no implementado (no hay base estable).
"""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# coordenadas sobre los recortes oficiales (valentina 620x517, mateo 645x538)
GEOM = {
    "valentina": {"ojos": [(298, 208), (385, 217)], "boca": (330, 297), "ancho_boca": 62},
    "mateo": {"ojos": [(288, 218), (376, 209)], "boca": (340, 300), "ancho_boca": 62},
}


def envolvente_audio(muestras, sr, paso=0.04):
    """RMS normalizado (0..1) por ventana de 40 ms -> funcion env(t)."""
    n = max(int(sr * paso), 1)
    v = np.array([np.sqrt(np.mean(muestras[i:i + n].astype(np.float32) ** 2)) for i in range(0, len(muestras) - n, n)])
    v = v / (np.percentile(v, 95) + 1e-6)
    v = np.clip(np.convolve(v, np.ones(3) / 3, mode="same"), 0, 1)
    return lambda t: float(v[min(int(t / paso), len(v) - 1)]) if len(v) else 0.0


def envolvente_palabras(palabras):
    """Sin audio (prueba de flujo): pulsos silabicos solo mientras hay palabra. palabras = [(ini, fin)]."""
    def env(t):
        for a, b in palabras:
            if a <= t <= b:
                return 0.35 + 0.65 * abs(math.sin(math.pi * 4.2 * (t - a)))
        return 0.0
    return env


def _parpadeo(t, parpm, semilla):
    """0..1 de cierre del parpado. Intervalos irregulares deterministas."""
    rng = np.random.default_rng(semilla)
    media = 60.0 / parpm
    ts, x = [], 1.2
    while x < t + 5:
        x += float(rng.uniform(0.7, 1.3)) * media
        ts.append(x)
    for tk in ts:
        if 0 <= t - tk < 0.2:
            return math.sin(math.pi * (t - tk) / 0.2)
    return 0.0


def _parpados(im, ojos, cierre):
    if cierre < 0.05:
        return im
    for cx, cy in ojos:
        hw, hh = 30, 13
        piel = im.crop((cx - hw, cy + hh + 1, cx + hw, cy + hh + 1 + hh * 2)).resize((hw * 2, hh * 2), Image.BILINEAR)
        alto = max(int(hh * 2 * cierre), 1)
        m = Image.new("L", (hw * 2, hh * 2), 0)
        ImageDraw.Draw(m).ellipse([2, 0, hw * 2 - 2, hh * 2 - 1], fill=255)
        corte = Image.new("L", (hw * 2, hh * 2), 0)
        ImageDraw.Draw(corte).rectangle([0, 0, hw * 2, alto], fill=255)
        mask = Image.fromarray((np.asarray(m, np.float32) * np.asarray(corte, np.float32) / 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))
        im.paste(piel, (cx - hw, cy - hh), mask)
        if cierre > 0.6:  # linea de pestanas
            ImageDraw.Draw(im, "RGBA").line([(cx - hw + 6, cy - hh + alto - 3), (cx + hw - 6, cy - hh + alto - 3)], fill=(45, 32, 28, 110), width=2)
    return im


def _boca(im, centro, ancho, abre):
    """Estira hacia abajo la franja labio inferior/menton 'abre' px (<=3)."""
    if abre < 0.3:
        return im
    cx, cy = centro
    caja = (cx - ancho, cy + 2, cx + ancho, cy + 46)
    franja = im.crop(caja)
    alto = franja.height
    nuevo = franja.resize((franja.width, alto + int(round(abre))), Image.BICUBIC).crop((0, 0, franja.width, alto))
    m = Image.new("L", franja.size, 255).filter(ImageFilter.GaussianBlur(5))
    borde = Image.new("L", franja.size, 0)
    ImageDraw.Draw(borde).rectangle([6, 0, franja.width - 6, alto - 8], fill=255)
    im.paste(nuevo, caja[:2], borde.filter(ImageFilter.GaussianBlur(4)))
    return im


def animar(ret_base, pres, t, env, params, semilla=7):
    """Devuelve el retrato animado en el instante t (mismo tamanio que ret_base)."""
    g = GEOM[pres]
    im = ret_base.copy()
    im = _parpados(im, g["ojos"], _parpadeo(t, params["parpadeo"], semilla))
    im = _boca(im, g["boca"], g["ancho_boca"], 5.0 * params["boca"] * env(t))
    a = params["amp"]
    w, h = im.size
    ang = a * (0.45 * math.sin(2 * math.pi * t / 5.3) + 0.15 * math.sin(2 * math.pi * t / 2.1))
    dx = a * 3.0 * math.sin(2 * math.pi * t / 6.1)
    dy = a * 2.0 * math.sin(2 * math.pi * t / 3.7 + 1.0) + params["cabeceo"] * 3.0 * env(t) * math.sin(2 * math.pi * t / 1.3)
    im = im.rotate(ang, resample=Image.BICUBIC, center=(w * 0.5, h * 1.0), translate=(dx, dy))
    m = 14  # recorte interior para ocultar los bordes que deja la rotacion (+ respiracion)
    resp = m * (1 + 0.25 * math.sin(2 * math.pi * t / 4.0))
    return im.crop((int(resp), int(resp), int(w - resp), int(h - resp))).resize((w, h), Image.BICUBIC)
