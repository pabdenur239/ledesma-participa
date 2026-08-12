"""Chequeo de disponibilidad de Ollama para la puesta en producción local en
Windows. Reutiliza `config/redaccion.json` (mismo archivo que ya configura
el redactor del proyecto — "endpoint" y "modelo", sin duplicar el valor en
otro lugar) para saber qué host y qué modelo verificar.

Nunca instala ni descarga nada, y nunca reemplaza Ollama por otro motor:
solo informa si está disponible y si el modelo configurado está instalado,
con reintentos acotados por si Ollama todavía está arrancando.

100% biblioteca estándar, testeable sin red inyectando `abrir_url`/`dormir`.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urlsplit, urlunsplit

MODELO_DEFAULT = "qwen3:1.7b"
ENDPOINT_DEFAULT = "http://127.0.0.1:11434/api/chat"
ESPERA_MAXIMA_DEFAULT = 60
INTERVALO_DEFAULT = 5
TIMEOUT_REQUEST = 5

# Códigos de salida: distintos a propósito para que quien invoque el script
# (check_ollama.ps1 / start_motor.ps1) pueda distinguir "no responde" de
# "responde pero falta el modelo" sin parsear el mensaje.
CODIGO_OK = 0
CODIGO_SIN_API = 1
CODIGO_SIN_MODELO = 2


def _url_base(endpoint: str) -> str:
    partes = urlsplit(endpoint)
    return urlunsplit((partes.scheme or "http", partes.netloc, "", "", ""))


def _leer_config(path: Optional[Path]) -> dict:
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _consultar_modelos(base_url: str, abrir_url: Callable) -> Optional[List[str]]:
    """Lista de nombres de modelos instalados, o None si la API no
    respondió (Ollama caído o todavía arrancando)."""
    try:
        with abrir_url(f"{base_url}/api/tags", timeout=TIMEOUT_REQUEST) as resp:
            datos = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    return [m.get("name", "") for m in datos.get("models", [])]


def verificar_ollama(
    base_url: str,
    modelo: str,
    espera_maxima_segundos: int = ESPERA_MAXIMA_DEFAULT,
    intervalo_segundos: int = INTERVALO_DEFAULT,
    abrir_url: Callable = urllib.request.urlopen,
    dormir: Callable = time.sleep,
) -> dict:
    """Reintenta durante `espera_maxima_segundos` (Ollama puede estar
    arrancando todavía) antes de reportar que no está disponible. Nunca
    sustituye nada: solo informa el resultado real, auditable en "motivo".
    `abrir_url`/`dormir` son inyectables para tests 100% offline."""
    intentos = max(1, espera_maxima_segundos // intervalo_segundos) if intervalo_segundos > 0 else 1

    for intento in range(1, intentos + 1):
        modelos = _consultar_modelos(base_url, abrir_url)
        if modelos is not None:
            modelo_presente = modelo in modelos
            return {
                "disponible": True,
                "modelo_presente": modelo_presente,
                "modelos_instalados": modelos,
                "intentos_realizados": intento,
                "motivo": (
                    "Ollama responde y el modelo está instalado."
                    if modelo_presente
                    else f"Ollama responde pero el modelo '{modelo}' no está instalado."
                ),
            }
        if intento < intentos:
            dormir(intervalo_segundos)

    return {
        "disponible": False,
        "modelo_presente": False,
        "modelos_instalados": [],
        "intentos_realizados": intentos,
        "motivo": f"Ollama no respondió en {base_url} tras {intentos} intento(s).",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Chequeo de disponibilidad de Ollama — Ledesma Participa")
    parser.add_argument("--config", default=None, help="Ruta a config/redaccion.json")
    parser.add_argument("--espera-maxima", type=int, default=ESPERA_MAXIMA_DEFAULT, dest="espera_maxima")
    parser.add_argument("--intervalo", type=int, default=INTERVALO_DEFAULT)
    args = parser.parse_args(argv)

    config = _leer_config(Path(args.config)) if args.config else {}
    endpoint = config.get("endpoint") or ENDPOINT_DEFAULT
    modelo = config.get("modelo") or MODELO_DEFAULT
    base_url = _url_base(endpoint)

    resultado = verificar_ollama(base_url, modelo, args.espera_maxima, args.intervalo)

    print(resultado["motivo"])
    if resultado["disponible"] and resultado["modelos_instalados"]:
        print(f"Modelos instalados: {', '.join(resultado['modelos_instalados'])}")

    if not resultado["disponible"]:
        return CODIGO_SIN_API
    if not resultado["modelo_presente"]:
        return CODIGO_SIN_MODELO
    return CODIGO_OK


if __name__ == "__main__":
    sys.exit(main())
