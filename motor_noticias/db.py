import sqlite3
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
"""

# Columnas de revisión humana, agregadas en una migración no destructiva:
# una base ya existente conserva sus filas y solo suma estas columnas.
COLUMNAS_REVISION = {
    "revision_estado": "TEXT NOT NULL DEFAULT 'pendiente'",
    "fecha_revision": "TEXT",
    "titulo_revisado": "TEXT",
    "texto_revisado": "TEXT",
}


class Database:
    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrar_columnas_revision()

    def _migrar_columnas_revision(self):
        columnas_existentes = {
            fila[1] for fila in self.conn.execute("PRAGMA table_info(noticias)").fetchall()
        }
        for columna, definicion in COLUMNAS_REVISION.items():
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
                fecha_revision, titulo_revisado, texto_revisado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def close(self):
        self.conn.close()
