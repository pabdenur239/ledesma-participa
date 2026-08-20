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

from .ciclo_continuo import (
    INTERVALO_SEGUNDOS_DEFAULT,
    ejecutar_ciclo,
    publicacion_meta_automatica_habilitada,
)
from .db import Database
from .institucional import HORA_INSTITUCIONAL
from .meta.cliente import ClienteMetaGraphAPI
from .meta.publicador import publicar_franja, publicar_urgentes, reintentar_publicaciones
from .motor_editorial import ZONA_JUJUY
from .redaccion import crear_redactor
from .sitio.deploy import desplegar_sitio
from .sitio.generador import SALIDA_DEFAULT, generar_sitio, deploy_automatico_habilitado

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


def _publicar_pendientes_meta(db: Database, fecha: str) -> None:
    """Publica de inmediato las propuestas urgentes del día y reintenta lo
    que haya quedado en error — mismo `publicar_urgentes`/
    `reintentar_publicaciones` que usan las tareas Windows
    MetaUrgentes/MetaReintentos, con el mismo tope conservador
    (`max_pendientes=1` por corrida, evita vaciar la cola de una sola vez).

    Corre acá, dentro del propio Motor Continuo (proceso persistente que ya
    demostró resistir suspensión/reanudación del equipo: simplemente
    retoma su bucle en cuanto el sistema operativo vuelve a darle CPU), como
    respaldo de esas tareas: si Task Scheduler no llega a disparar sus
    triggers repetitivos porque la notebook estuvo dormida (la falla real
    observada en producción), esta corrida igual saca la cola pendiente en
    el próximo ciclo del Motor — sin esperar a que la notebook esté
    despierta justo en el minuto exacto de una franja de Windows. Nunca
    reemplaza esas tareas (siguen activas, dan cobertura más fina cuando el
    equipo está despierto): es un segundo camino hacia el mismo estado ya
    protegido por la idempotencia de `programacion_meta`, así que ambos
    pueden correr sin riesgo de publicar dos veces lo mismo."""
    cliente_fb = ClienteMetaGraphAPI()
    cliente_ig = ClienteMetaGraphAPI()
    try:
        publicar_urgentes(db, fecha, cliente_fb=cliente_fb, cliente_ig=cliente_ig, max_pendientes=1)
    except Exception:  # nunca debe interrumpir el ciclo continuo
        logger.exception("Error publicando urgentes desde el Motor Continuo")

    try:
        reintentar_publicaciones(db, cliente_fb=cliente_fb, cliente_ig=cliente_ig, max_pendientes=1)
    except Exception:  # nunca debe interrumpir el ciclo continuo
        logger.exception("Error reintentando publicaciones desde el Motor Continuo")

    try:
        _publicar_institucional_si_corresponde(db, fecha, cliente_fb, cliente_ig)
    except Exception:  # nunca debe interrumpir el ciclo continuo
        logger.exception("Error publicando la institucional desde el Motor Continuo")


def _publicar_institucional_si_corresponde(db: Database, fecha: str, cliente_fb, cliente_ig) -> None:
    """Publica la franja fija institucional (19:30) una vez que esa hora ya
    llegó — no antes. No depende de ninguna tarea Windows nueva (no se creó
    ninguna): `publicar_franja` ya es idempotente por sí sola (una franja
    con ambas redes en 'publicado' se reporta como 'omitido' sin volver a
    tocar Meta), así que llamarla de nuevo en cada ciclo posterior a las
    19:30 es seguro — nunca produce una segunda copia el mismo día."""
    ahora_jujuy = datetime.now(ZONA_JUJUY)
    if ahora_jujuy.strftime("%H:%M") < HORA_INSTITUCIONAL:
        return
    publicar_franja(db, fecha, HORA_INSTITUCIONAL, cliente_fb=cliente_fb, cliente_ig=cliente_ig)


def _actualizar_sitio_web(db_path) -> None:
    """Regenera `docs/` a partir de lo ya publicado y lo despliega a GitHub
    (ver `motor_noticias.sitio.deploy`) — mismo respaldo que
    `_publicar_pendientes_meta`, por la misma razón: la tarea Windows
    SitioWeb depende de un trigger repetitivo que no sobrevive una
    suspensión larga del equipo, y sin el paso de deploy la web tampoco se
    actualizaba aunque la tarea sí llegara a correr (`docs/` se regeneraba
    localmente, pero nunca se empujaba a GitHub, que es lo único que
    GitHub Pages sirve de verdad). `desplegar_sitio` es idempotente (no
    commitea si no hay cambios reales) y no interrumpe nada si falla."""
    try:
        generar_sitio(db_path, SALIDA_DEFAULT)
    except Exception:  # nunca debe interrumpir el ciclo continuo
        logger.exception("Error regenerando el sitio web desde el Motor Continuo")
        return

    if not deploy_automatico_habilitado():
        return
    try:
        resultado = desplegar_sitio()
        if resultado.resultado == "error":
            logger.error("Error desplegando el sitio web: %s", resultado.detalle)
    except Exception:  # nunca debe interrumpir el ciclo continuo
        logger.exception("Error desplegando el sitio web desde el Motor Continuo")


def _ejecutar_publicacion_y_sitio(db: Database) -> None:
    if not publicacion_meta_automatica_habilitada():
        logger.info("Publicación automática de urgentes/reintentos/sitio deshabilitada (config).")
        return
    fecha = datetime.now(ZONA_JUJUY).strftime("%Y-%m-%d")
    _publicar_pendientes_meta(db, fecha)
    _actualizar_sitio_web(db.path)


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
            try:
                _ejecutar_publicacion_y_sitio(db)
            except Exception:  # nunca debe interrumpir el ciclo continuo
                logger.exception("Error en publicación/sitio dentro del ciclo del Motor Continuo")
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
