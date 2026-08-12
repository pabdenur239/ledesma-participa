import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from .models import Estado, Noticia

SCHEMA = """
CREATE TABLE IF NOT EXISTS noticias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo_original TEXT NOT NULL,
    texto_original TEXT NOT NULL,
    url_fuente TEXT NOT NULL,
    url_normalizada TEXT NOT NULL,
    nombre_fuente TEXT,
    fecha_fuente TEXT,
    fecha_recoleccion TEXT NOT NULL,
    localidad TEXT,
    relevancia_local INTEGER,
    motivo_relevancia TEXT,
    titulo_preparado TEXT,
    texto_preparado TEXT,
    estado TEXT NOT NULL,
    hash_contenido TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_url_normalizada ON noticias(url_normalizada);

-- Salud del motor continuo (una fila por fuente, se sobrescribe en cada
-- ciclo) y el historial de ciclos ejecutados. Tablas nuevas: no afectan ni
-- alteran ninguna fila existente de `noticias`.
CREATE TABLE IF NOT EXISTS fuente_salud (
    nombre_fuente TEXT PRIMARY KEY,
    ultima_consulta TEXT,
    ultimo_resultado TEXT,
    elementos_obtenidos INTEGER NOT NULL DEFAULT 0,
    noticias_nuevas INTEGER NOT NULL DEFAULT 0,
    ultima_noticia_fecha TEXT,
    ultimo_error TEXT,
    fallos_consecutivos INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ciclo_ejecucion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_inicio TEXT NOT NULL,
    fecha_fin TEXT NOT NULL,
    intervalo_segundos INTEGER,
    total_fuentes INTEGER NOT NULL,
    total_noticias_nuevas INTEGER NOT NULL,
    total_errores INTEGER NOT NULL
);
"""

# Columnas agregadas en migraciones no destructivas: una base ya existente
# conserva sus filas y solo suma las columnas que le falten.
COLUMNAS_REVISION = {
    "revision_estado": "TEXT NOT NULL DEFAULT 'pendiente'",
    "fecha_revision": "TEXT",
    "titulo_revisado": "TEXT",
    "texto_revisado": "TEXT",
}

COLUMNAS_RIESGO_EDITORIAL = {
    "requiere_revision_especial": "INTEGER NOT NULL DEFAULT 0",
    "motivo_revision_especial": "TEXT",
    "categoria_riesgo": "TEXT",
}

COLUMNAS_IMAGEN = {
    "tiene_imagen_original": "INTEGER NOT NULL DEFAULT 0",
    "imagen_publicacion_ruta": "TEXT",
    "imagen_generada_automaticamente": "INTEGER NOT NULL DEFAULT 0",
}


class Database:
    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrar_columnas(COLUMNAS_REVISION)
        self._migrar_columnas(COLUMNAS_RIESGO_EDITORIAL)
        self._migrar_columnas(COLUMNAS_IMAGEN)

    def _migrar_columnas(self, columnas: dict):
        columnas_existentes = {
            fila[1] for fila in self.conn.execute("PRAGMA table_info(noticias)").fetchall()
        }
        for columna, definicion in columnas.items():
            if columna not in columnas_existentes:
                self.conn.execute(f"ALTER TABLE noticias ADD COLUMN {columna} {definicion}")
        self.conn.commit()

    def existe_duplicado(self, url_normalizada: str, hash_contenido: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM noticias WHERE url_normalizada = ? OR hash_contenido = ? LIMIT 1",
            (url_normalizada, hash_contenido),
        )
        return cur.fetchone() is not None

    def guardar(self, noticia: Noticia) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO noticias (
                titulo_original, texto_original, url_fuente, url_normalizada,
                nombre_fuente, fecha_fuente, fecha_recoleccion, localidad,
                relevancia_local, motivo_relevancia, titulo_preparado,
                texto_preparado, estado, hash_contenido, revision_estado,
                fecha_revision, titulo_revisado, texto_revisado,
                requiere_revision_especial, motivo_revision_especial, categoria_riesgo,
                tiene_imagen_original, imagen_publicacion_ruta, imagen_generada_automaticamente
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                noticia.titulo_original,
                noticia.texto_original,
                noticia.url_fuente,
                noticia.url_normalizada,
                noticia.nombre_fuente,
                noticia.fecha_fuente,
                noticia.fecha_recoleccion,
                noticia.localidad,
                noticia.relevancia_local,
                noticia.motivo_relevancia,
                noticia.titulo_preparado,
                noticia.texto_preparado,
                noticia.estado,
                noticia.hash_contenido,
                noticia.revision_estado,
                noticia.fecha_revision,
                noticia.titulo_revisado,
                noticia.texto_revisado,
                noticia.requiere_revision_especial,
                noticia.motivo_revision_especial,
                noticia.categoria_riesgo,
                noticia.tiene_imagen_original,
                noticia.imagen_publicacion_ruta,
                noticia.imagen_generada_automaticamente,
            ),
        )
        self.conn.commit()
        noticia.id = cur.lastrowid
        return noticia.id

    def listar(self) -> list:
        cur = self.conn.execute("SELECT * FROM noticias ORDER BY id")
        return [dict(fila) for fila in cur.fetchall()]

    def listar_preparadas(self, filtro_revision: Optional[str] = None) -> list:
        """Noticias en estado preparada, opcionalmente filtradas por
        revision_estado ('pendiente', 'aprobada' o 'rechazada')."""
        if filtro_revision:
            cur = self.conn.execute(
                "SELECT * FROM noticias WHERE estado = ? AND revision_estado = ? ORDER BY id DESC",
                (Estado.PREPARADA.value, filtro_revision),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM noticias WHERE estado = ? ORDER BY id DESC",
                (Estado.PREPARADA.value,),
            )
        return [dict(fila) for fila in cur.fetchall()]

    def obtener(self, id_noticia: int) -> Optional[dict]:
        cur = self.conn.execute("SELECT * FROM noticias WHERE id = ?", (id_noticia,))
        fila = cur.fetchone()
        return dict(fila) if fila else None

    def actualizar_revision(
        self,
        id_noticia: int,
        revision_estado: str,
        titulo_revisado: Optional[str] = None,
        texto_revisado: Optional[str] = None,
        fecha_revision: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE noticias
            SET revision_estado = ?, titulo_revisado = ?, texto_revisado = ?, fecha_revision = ?
            WHERE id = ?
            """,
            (revision_estado, titulo_revisado, texto_revisado, fecha_revision, id_noticia),
        )
        self.conn.commit()

    def actualizar_imagen_publicacion(
        self,
        id_noticia: int,
        imagen_publicacion_ruta: Optional[str],
        imagen_generada_automaticamente: bool,
    ) -> None:
        self.conn.execute(
            """
            UPDATE noticias
            SET imagen_publicacion_ruta = ?, imagen_generada_automaticamente = ?
            WHERE id = ?
            """,
            (imagen_publicacion_ruta, imagen_generada_automaticamente, id_noticia),
        )
        self.conn.commit()

    def registrar_salud_fuente(
        self,
        nombre_fuente: str,
        resultado: str,
        elementos_obtenidos: int = 0,
        noticias_nuevas: int = 0,
        mensaje_error: Optional[str] = None,
        fecha_consulta: Optional[str] = None,
    ) -> None:
        """Registra el resultado de la última consulta a una fuente del motor
        continuo. `resultado` es "ok" o "error". Acumula fallos consecutivos
        (se resetea a 0 en cuanto la fuente vuelve a responder "ok") y solo
        actualiza `ultima_noticia_fecha` cuando esta consulta trajo alguna
        noticia nueva (no inferimos esa fecha de otra forma)."""
        fecha_consulta = fecha_consulta or datetime.now(timezone.utc).isoformat()
        existente = self.obtener_salud_fuente(nombre_fuente)

        fallos_consecutivos = 0 if resultado == "ok" else (existente["fallos_consecutivos"] if existente else 0) + 1
        ultima_noticia_fecha = existente["ultima_noticia_fecha"] if existente else None
        if noticias_nuevas > 0:
            ultima_noticia_fecha = fecha_consulta

        self.conn.execute(
            """
            INSERT INTO fuente_salud (
                nombre_fuente, ultima_consulta, ultimo_resultado, elementos_obtenidos,
                noticias_nuevas, ultima_noticia_fecha, ultimo_error, fallos_consecutivos
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(nombre_fuente) DO UPDATE SET
                ultima_consulta = excluded.ultima_consulta,
                ultimo_resultado = excluded.ultimo_resultado,
                elementos_obtenidos = excluded.elementos_obtenidos,
                noticias_nuevas = excluded.noticias_nuevas,
                ultima_noticia_fecha = excluded.ultima_noticia_fecha,
                ultimo_error = excluded.ultimo_error,
                fallos_consecutivos = excluded.fallos_consecutivos
            """,
            (
                nombre_fuente,
                fecha_consulta,
                resultado,
                elementos_obtenidos,
                noticias_nuevas,
                ultima_noticia_fecha,
                mensaje_error,
                fallos_consecutivos,
            ),
        )
        self.conn.commit()

    def obtener_salud_fuente(self, nombre_fuente: str) -> Optional[dict]:
        cur = self.conn.execute(
            "SELECT * FROM fuente_salud WHERE nombre_fuente = ?", (nombre_fuente,)
        )
        fila = cur.fetchone()
        return dict(fila) if fila else None

    def listar_salud_fuentes(self) -> list:
        cur = self.conn.execute("SELECT * FROM fuente_salud ORDER BY nombre_fuente")
        return [dict(fila) for fila in cur.fetchall()]

    def registrar_ciclo(
        self,
        fecha_inicio: str,
        fecha_fin: str,
        total_fuentes: int,
        total_noticias_nuevas: int,
        total_errores: int,
        intervalo_segundos: Optional[int] = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO ciclo_ejecucion (
                fecha_inicio, fecha_fin, intervalo_segundos, total_fuentes,
                total_noticias_nuevas, total_errores
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (fecha_inicio, fecha_fin, intervalo_segundos, total_fuentes, total_noticias_nuevas, total_errores),
        )
        self.conn.commit()

    def ultimo_ciclo(self) -> Optional[dict]:
        cur = self.conn.execute("SELECT * FROM ciclo_ejecucion ORDER BY id DESC LIMIT 1")
        fila = cur.fetchone()
        return dict(fila) if fila else None

    def ultima_noticia_relevante_fecha(self) -> Optional[str]:
        """Fecha de recolección de la noticia relevante (para Libertador o el
        Departamento Ledesma) más reciente, sin importar la fuente."""
        cur = self.conn.execute(
            "SELECT MAX(fecha_recoleccion) AS fecha FROM noticias WHERE relevancia_local = 1"
        )
        fila = cur.fetchone()
        return fila["fecha"] if fila and fila["fecha"] else None

    def close(self):
        self.conn.close()
