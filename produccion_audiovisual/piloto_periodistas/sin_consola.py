"""Windows: evita que cada subproceso (ffmpeg, python, tasklist) abra una ventana de
consola cuando el piloto corre desde la tarea programada (pythonw). Basta con
importar este modulo antes de usar subprocess."""
import os
import subprocess

if os.name == "nt" and not getattr(subprocess.Popen, "_sin_consola", False):
    _init = subprocess.Popen.__init__

    def _init_sin_consola(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        _init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _init_sin_consola
    subprocess.Popen._sin_consola = True
