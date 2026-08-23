"""Generación de video vertical (Reels) a partir del mismo material que ya
usa el resto del sistema — nunca inventa imágenes ni texto nuevo.

Reutiliza la placa de Instagram Story ya existente (`motor_noticias.meta.
imagen.generar_imagen_story_png`, mismo título/resumen/fuente/localidad ya
redactados y aprobados por el pipeline editorial) como plano principal, con
un efecto de zoom lento (Ken Burns) armado con `ffmpeg` — no hay ningún
generador de imágenes nuevo acá, solo composición de video sobre lo que ya
existe. Cierra con una placa de marca breve, propia y sin texto de ninguna
noticia. Sin audio real (silencio digital, nunca música externa): evita por
completo cualquier duda de copyright.

`ffmpeg`/`ffprobe` deben estar instalados en el sistema (no se agrega como
dependencia Python: se invoca como proceso externo, igual criterio que
`motor_noticias.meta.cliente` con la Graph API)."""
import io
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from .imagen import COLOR_FONDO, COLOR_MARCA, COLOR_MARCA_TEXTO, _cargar_fuente

logger = logging.getLogger("motor_noticias.meta.video")

ANCHO_REEL = 1080
ALTO_REEL = 1920
FPS_REEL = 30
DURACION_CIERRE_SEGUNDOS = 3.0
DURACION_TOTAL_DEFAULT_SEGUNDOS = 20.0
TIMEOUT_FFMPEG_SEGUNDOS = 120


class ErrorGeneracionVideo(RuntimeError):
    """Error controlado al generar el Reel: `ffmpeg`/`ffprobe` ausentes,
    fallo real del proceso, o el archivo resultante no cumple el formato
    exigido (9:16, duración dentro de rango)."""


@dataclass
class ResultadoVideoReel:
    ruta: Path
    ancho: int
    alto: int
    duracion_segundos: float


def _verificar_binarios_disponibles() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise ErrorGeneracionVideo(
            "ffmpeg/ffprobe no están instalados en este sistema: no se puede generar el Reel."
        )


def _generar_placa_cierre_png() -> bytes:
    """Placa de cierre breve, solo marca: mismos colores de identidad que
    el resto del sistema (`motor_noticias.meta.imagen`), sin texto de
    ninguna noticia — nunca cambia entre Reels."""
    imagen = Image.new("RGB", (ANCHO_REEL, ALTO_REEL), COLOR_MARCA)
    dibujo = ImageDraw.Draw(imagen)
    fuente_marca = _cargar_fuente(72)
    texto = "LEDESMA PARTICIPA"
    caja = dibujo.textbbox((0, 0), texto, font=fuente_marca)
    ancho_texto = caja[2] - caja[0]
    dibujo.text(
        ((ANCHO_REEL - ancho_texto) / 2, ALTO_REEL / 2 - 80), texto, font=fuente_marca, fill=COLOR_MARCA_TEXTO
    )
    fuente_subtitulo = _cargar_fuente(36)
    subtitulo = "ledesmaparticipa.com.ar"
    caja_sub = dibujo.textbbox((0, 0), subtitulo, font=fuente_subtitulo)
    ancho_sub = caja_sub[2] - caja_sub[0]
    dibujo.text(
        ((ANCHO_REEL - ancho_sub) / 2, ALTO_REEL / 2 + 20), subtitulo, font=fuente_subtitulo, fill=COLOR_FONDO
    )
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()


def _correr_ffmpeg(args: list) -> None:
    try:
        resultado = subprocess.run(
            args, capture_output=True, text=True, timeout=TIMEOUT_FFMPEG_SEGUNDOS,
        )
    except subprocess.TimeoutExpired as error:
        raise ErrorGeneracionVideo("ffmpeg no terminó dentro del tiempo esperado.") from error
    if resultado.returncode != 0:
        raise ErrorGeneracionVideo(f"ffmpeg falló: {resultado.stderr[-800:]}")


def _duracion_real_segundos(ruta_video: Path) -> float:
    resultado = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(ruta_video),
        ],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return float(resultado.stdout.strip())
    except ValueError as error:
        raise ErrorGeneracionVideo("No se pudo confirmar la duración real del video generado.") from error


def generar_video_reel(
    imagen_principal_png: bytes,
    ruta_salida: Path,
    duracion_total_segundos: float = DURACION_TOTAL_DEFAULT_SEGUNDOS,
    directorio_temporal: Optional[Path] = None,
) -> ResultadoVideoReel:
    """Compone el Reel: zoom lento sobre `imagen_principal_png` (ya con todo
    el texto real impreso — ver `motor_noticias.meta.imagen.
    generar_imagen_story_png`) más una placa de cierre de marca, sin audio
    real (pista de silencio digital, nunca música). Vertical 9:16, 1080x1920,
    ~`duracion_total_segundos` (15–30s recomendado). No inventa nada: la
    única entrada de contenido es la imagen ya generada por el pipeline
    editorial existente."""
    _verificar_binarios_disponibles()
    if not (15.0 <= duracion_total_segundos <= 30.0):
        raise ErrorGeneracionVideo("La duración del Reel debe estar entre 15 y 30 segundos.")

    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(directorio_temporal) if directorio_temporal else ruta_salida.parent
    tmp.mkdir(parents=True, exist_ok=True)

    ruta_principal = tmp / f"_reel_principal_{ruta_salida.stem}.png"
    ruta_cierre = tmp / f"_reel_cierre_{ruta_salida.stem}.png"
    ruta_principal.write_bytes(imagen_principal_png)
    ruta_cierre.write_bytes(_generar_placa_cierre_png())

    duracion_principal = duracion_total_segundos - DURACION_CIERRE_SEGUNDOS
    frames_zoom = round(duracion_principal * FPS_REEL)

    try:
        _correr_ffmpeg([
            "ffmpeg", "-y",
            "-loop", "1", "-t", str(duracion_principal), "-i", str(ruta_principal),
            "-loop", "1", "-t", str(DURACION_CIERRE_SEGUNDOS), "-i", str(ruta_cierre),
            "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
            "-filter_complex",
            (
                f"[0:v]scale={ANCHO_REEL}:{ALTO_REEL},"
                f"zoompan=z='min(zoom+0.0015,1.15)':d={frames_zoom}:s={ANCHO_REEL}x{ALTO_REEL}:fps={FPS_REEL}[v0];"
                f"[1:v]scale={ANCHO_REEL}:{ALTO_REEL},fps={FPS_REEL}[v1];"
                "[v0][v1]concat=n=2:v=1:a=0[vout]"
            ),
            "-map", "[vout]", "-map", "2:a",
            "-t", str(duracion_total_segundos),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
            "-c:a", "aac", "-b:a", "64k",
            "-movflags", "+faststart",
            str(ruta_salida),
        ])
    finally:
        ruta_principal.unlink(missing_ok=True)
        ruta_cierre.unlink(missing_ok=True)

    duracion_real = _duracion_real_segundos(ruta_salida)
    return ResultadoVideoReel(
        ruta=ruta_salida, ancho=ANCHO_REEL, alto=ALTO_REEL, duracion_segundos=duracion_real
    )
