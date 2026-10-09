"""Validación de imágenes externas para la web (agregado 2/10/2026).

Causa real de las imágenes rotas en la web: Jujuy al Día bloquea el
hotlinking (HTTP 403 cuando el navegador envía un Referer de otro dominio,
200 sin Referer). Las <img> de la web se emiten con
`referrerpolicy="no-referrer"` (ver plantillas) y, además, cada URL externa
se valida una vez (sin Referer, como la pedirá el navegador): si no responde
con una imagen, la web usa la placa propia de la noticia en lugar de una
imagen rota. Los resultados se guardan en una caché con vencimiento para no
consultar las mismas URLs en cada regeneración del sitio.
"""
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

CACHE_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "imagenes_web.json"
VIGENCIA_OK = timedelta(days=7)
VIGENCIA_ERROR = timedelta(days=1)
MAXIMO_CONSULTAS_POR_CORRIDA = 80
TIMEOUT_SEGUNDOS = 8


def _consultar(url: str) -> bool:
    peticion = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (LedesmaParticipa)"})
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_SEGUNDOS) as respuesta:
            tipo = (respuesta.headers.get("Content-Type") or "").lower()
            respuesta.read(512)
            return respuesta.status == 200 and tipo.startswith("image/")
    except Exception:
        return False


class ValidadorImagenes:
    def __init__(
        self,
        cache_path: Optional[Path] = None,
        consultar: Callable[[str], bool] = _consultar,
        maximo_consultas: int = MAXIMO_CONSULTAS_POR_CORRIDA,
        ahora: Optional[datetime] = None,
    ):
        self.cache_path = Path(cache_path or CACHE_DEFAULT)
        self.consultar = consultar
        self.restantes = maximo_consultas
        self.ahora = ahora or datetime.now(timezone.utc)
        try:
            self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.cache = {}

    def es_valida(self, url: str) -> bool:
        """True si la URL responde con una imagen. Sin cupo de consultas en
        esta corrida, una URL nunca validada se da por buena (comportamiento
        anterior) y se validará en la próxima."""
        registro = self.cache.get(url)
        if registro:
            try:
                momento = datetime.fromisoformat(registro["ts"])
                vigencia = VIGENCIA_OK if registro["ok"] else VIGENCIA_ERROR
                if self.ahora - momento < vigencia:
                    return bool(registro["ok"])
            except (KeyError, ValueError):
                pass
        if self.restantes <= 0:
            return True if not registro else bool(registro.get("ok", True))
        self.restantes -= 1
        ok = bool(self.consultar(url))
        self.cache[url] = {"ok": ok, "ts": self.ahora.isoformat()}
        return ok

    def guardar(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache), encoding="utf-8")
        except OSError:
            pass
