"""Locucion con ElevenLabs (voces aprobadas: Melanie = Valentina, Ignacio = Mateo).

Requiere la variable de entorno ELEVENLABS_API_KEY (nunca se muestra ni se registra). Las voces se resuelven por nombre
en la cuenta; opcionalmente ELEVENLABS_VOICE_MELANIE / ELEVENLABS_VOICE_IGNACIO fijan el voice_id.
Usa el endpoint with-timestamps: devuelve el MP3 y los tiempos por caracter -> subtitulos sincronizados sin STT.
"""
import base64
import json
import os
import urllib.request
from pathlib import Path

VOCES = {"valentina": "Melanie", "mateo": "Ignacio"}
MODELO = "eleven_multilingual_v2"
API = "https://api.elevenlabs.io/v1"


class SinCredenciales(RuntimeError):
    pass


def _clave():
    k = os.environ.get("ELEVENLABS_API_KEY")
    if not k:
        raise SinCredenciales("Falta la variable de entorno ELEVENLABS_API_KEY (no hay clave de ElevenLabs configurada).")
    return k


def _req(url, datos=None):
    r = urllib.request.Request(url, data=json.dumps(datos).encode() if datos is not None else None,
                               headers={"xi-api-key": _clave(), "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=120) as f:
        return json.loads(f.read())


CONFIG_VOCES = Path(__file__).resolve().parent / "config_voces.json"  # IDs publicos de voz (no secretos), local/ignorado por git


def voice_id(presentador):
    """Voice ID de la voz aprobada. Se resuelve por nombre UNA vez y queda guardado en config_voces.json."""
    nombre = VOCES[presentador]
    fijo = os.environ.get(f"ELEVENLABS_VOICE_{nombre.upper()}")
    if fijo:
        return fijo
    try:
        guardado = json.loads(CONFIG_VOCES.read_text(encoding="utf-8"))
    except Exception:
        guardado = {}
    if guardado.get(presentador):
        return guardado[presentador]
    vid = None
    for v in _req(f"{API}/voices")["voices"]:
        if v["name"].lower().startswith(nombre.lower()):
            vid = v["voice_id"]
            break
    if vid is None:  # voz de la Voice Library todavia no agregada a la cuenta: se agrega una vez
        for v in _req(f"{API}/shared-voices?search={nombre}&language=es&page_size=20").get("voices", []):
            if v["name"].lower().startswith(nombre.lower()):
                _req(f"{API}/voices/add/{v['public_owner_id']}/{v['voice_id']}", {"new_name": v["name"]})
                vid = v["voice_id"]
                break
    if vid is None:
        raise SinCredenciales(f"No se encontro la voz '{nombre}' en ElevenLabs.")
    guardado[presentador] = vid
    CONFIG_VOCES.write_text(json.dumps(guardado, indent=1), encoding="utf-8")
    return vid


def sintetizar(texto, presentador, salida_mp3):
    """Escribe el MP3 y devuelve [(palabra, ini, fin)] con tiempos reales."""
    r = _req(f"{API}/text-to-speech/{voice_id(presentador)}/with-timestamps?output_format=mp3_44100_128",
             {"text": texto, "model_id": MODELO})
    Path(salida_mp3).write_bytes(base64.b64decode(r["audio_base64"]))
    al = r["alignment"]  # caracteres del texto ORIGINAL (no el normalizado) -> subtitulos exactos del guion
    ch, a, b = al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]
    palabras, cur, ini = [], "", None
    for c, s, e in zip(ch, a, b):
        if c.isspace():
            if cur:
                palabras.append((cur, ini, fin))
            cur, ini = "", None
        else:
            ini = s if ini is None else ini
            cur, fin = cur + c, e
    if cur:
        palabras.append((cur, ini, fin))
    return palabras
