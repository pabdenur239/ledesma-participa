"""Transcribe un audio externo (solo para sincronizar subtitulos; NO genera voz).
Uso (entorno con faster-whisper): python transcribir_audio.py AUDIO SALIDA.json"""
import glob, json, subprocess, sys
import numpy as np
from faster_whisper import WhisperModel
m = WhisperModel("small", device="cpu", compute_type="int8")
ff = glob.glob(str(__import__("pathlib").Path(__file__).resolve().parents[2] / ".venv/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-*.exe"))[0]
raw = subprocess.run([ff, "-v", "error", "-i", sys.argv[1], "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
segs, info = m.transcribe(audio, language="es", word_timestamps=True, vad_filter=False)
out = {"duracion": info.duration, "segmentos": [
    {"ini": s.start, "fin": s.end, "texto": s.text.strip(), "palabras": [{"p": w.word.strip(), "ini": w.start, "fin": w.end} for w in s.words]}
    for s in segs]}
json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for s in out["segmentos"]: print(round(s["ini"], 1), round(s["fin"], 1), s["texto"])
print("dur", info.duration)
