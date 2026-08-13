import argparse
import ctypes
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .ciclo_continuo import INTERVALO_SEGUNDOS_DEFAULT, ejecutar_ciclo
from .db import Database
from .redaccion import crear_redactor

DB_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "ledesma_participa.db"
LOCK_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "run_continuo.lock"
LOG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "logs" / "run_continuo.log"

logger = logging.getLogger("motor_noticias.continuo")

NOMBRE_SCRIPT_LOCK = "run_continuo.py"


class InstanciaEnEjecucion(RuntimeError):
    """Ya existe un lock activo y su proceso propietario sigue realmente
    corriendo: hay otra instancia activa."""


def _proceso_activo(pid: int) -> bool:
    """Best-effort, sin dependencias externas (solo stdlib: os/ctypes):
    True si existe un proceso vivo con ese PID en este sistema operativo.
    Windows y POSIX requieren mecanismos distintos, ninguno de los cuales
    necesita paquetes adicionales."""
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe, solo no tenemos permiso para señalizarlo
    except OSError:
        return False
    return True


def _leer_lock(lock_path: Path) -> Optional[dict]:
    """Devuelve la info del lock (al menos {"pid": int}), o None si el
    archivo no existe, está vacío o es ilegible/corrupto (lock inválido).
    Compatible con locks viejos que solo tenían el PID como texto plano."""
    try:
        contenido = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not contenido:
        return None
    if contenido.isdigit():
        return {"pid": int(contenido)}
    try:
        datos = json.loads(contenido)
    except json.JSONDecodeError:
        return None
    if not isinstance(datos, dict) or "pid" not in datos:
        return None
    try:
        datos["pid"] = int(datos["pid"])
    except (TypeError, ValueError):
        return None
    return datos


def _escribir_lock(lock_path: Path) -> None:
    datos = {
        "pid": os.getpid(),
        "script": NOMBRE_SCRIPT_LOCK,
        "iniciado_en": datetime.now(timezone.utc).isoformat(),
    }
    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(datos))


def tomar_lock(lock_path: Path, proceso_activo: Callable[[int], bool] = _proceso_activo) -> None:
    """Evita dos instancias reales simultáneas, sin dejarse bloquear por un
    lock obsoleto (p.ej. tras un apagado inesperado): si el archivo ya
    existe, se lee el PID que guarda y se comprueba si ese proceso sigue
    realmente activo.

    - Si el proceso sigue activo: es una instancia real -> `InstanciaEnEjecucion`.
    - Si el proceso ya no existe, o el archivo es inválido/corrupto/vacío
      (lock obsoleto): se elimina automáticamente y se reintenta una vez.
    - Si esa segunda escritura también choca (otra instancia lo tomó justo
      en el medio): se trata como conflicto real, nunca se sobreescribe a
      ciegas.

    `proceso_activo` es inyectable para tests 100% offline."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _escribir_lock(lock_path)
        return
    except FileExistsError:
        pass

    datos = _leer_lock(lock_path)
    pid_existente = datos.get("pid") if datos else None

    if pid_existente is not None and proceso_activo(pid_existente):
        raise InstanciaEnEjecucion(
            f"Ya hay una instancia de {NOMBRE_SCRIPT_LOCK} activa (PID {pid_existente}, lock en {lock_path})."
        )

    # Lock obsoleto (proceso ya no existe) o inválido (archivo corrupto/
    # vacío/sin PID legible): se limpia automáticamente y se continúa.
    logger.warning(
        "Lock obsoleto o inválido en %s (PID registrado: %s). Se elimina y se continúa.",
        lock_path,
        pid_existente,
    )
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass

    try:
        _escribir_lock(lock_path)
    except FileExistsError as error:
        raise InstanciaEnEjecucion(
            f"Ya hay una instancia de {NOMBRE_SCRIPT_LOCK} activa (lock en {lock_path})."
        ) from error


def liberar_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def configurar_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Motor continuo de noticias — Ledesma Participa")
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument(
        "--intervalo",
        type=int,
        default=INTERVALO_SEGUNDOS_DEFAULT,
        help=f"Segundos entre ciclos (default: {INTERVALO_SEGUNDOS_DEFAULT})",
    )
    parser.add_argument(
        "--redactor",
        choices=["mock", "ollama"],
        default=None,
        help=(
            "Override puntual del redactor a usar (mock u Ollama local). "
            "Si no se pasa, se usa config/redaccion.json → \"proveedor\"."
        ),
    )
    parser.add_argument("--lock", default=str(LOCK_PATH_DEFAULT), help="Ruta al archivo de lock")
    parser.add_argument("--log", default=str(LOG_PATH_DEFAULT), help="Ruta al archivo de log")
    parser.add_argument(
        "--max-ciclos",
        type=int,
        default=None,
        help=argparse.SUPPRESS,  # uso interno para pruebas: detiene el bucle tras N ciclos
    )
    return parser


def bucle_continuo(
    db: Database,
    redactor,
    intervalo_segundos: int,
    max_ciclos: Optional[int] = None,
    dormir=time.sleep,
) -> None:
    """Ejecuta un ciclo inmediatamente y luego repite cada `intervalo_segundos`.
    `dormir` es inyectable para pruebas (evita esperas reales). Se detiene
    limpiamente ante KeyboardInterrupt (Ctrl+C) o, si `max_ciclos` está
    definido, luego de esa cantidad de ciclos."""
    ciclos_ejecutados = 0
    logger.info("Motor continuo iniciado. Intervalo: %d segundos.", intervalo_segundos)
    try:
        while True:
            logger.info("Iniciando ciclo de recolección...")
            resumen = ejecutar_ciclo(db, redactor, intervalo_segundos=intervalo_segundos)
            logger.info(
                "Ciclo completado: %d fuentes, %d noticias nuevas, %d errores.",
                len(resumen.resultados),
                resumen.total_noticias_nuevas,
                resumen.total_errores,
            )
            for resultado in resumen.resultados:
                if resultado.resultado == "error":
                    logger.warning(
                        "Fuente %s con error: %s", resultado.identificador, resultado.mensaje_error
                    )
            ciclos_ejecutados += 1
            if max_ciclos is not None and ciclos_ejecutados >= max_ciclos:
                logger.info("Alcanzada la cantidad máxima de ciclos configurada (%d). Deteniendo.", max_ciclos)
                return
            logger.info("Próximo ciclo en %d segundos.", intervalo_segundos)
            dormir(intervalo_segundos)
    except KeyboardInterrupt:
        logger.info("Interrupción recibida (Ctrl+C). Cerrando motor continuo...")


def main(argv=None) -> int:
    args = construir_parser().parse_args(argv)
    configurar_logging(Path(args.log))
    lock_path = Path(args.lock)

    try:
        tomar_lock(lock_path)
    except InstanciaEnEjecucion as error:
        logger.error(str(error))
        return 1

    redactor = crear_redactor(args.redactor)
    db = Database(args.db)
    try:
        bucle_continuo(db, redactor, args.intervalo, max_ciclos=args.max_ciclos)
    finally:
        db.close()
        liberar_lock(lock_path)
        logger.info("Motor continuo detenido limpiamente.")
    return 0
