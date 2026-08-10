import sqlite3
from pathlib import Path
from typing import Union

from .models import Noticia

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


class Database:
    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
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
                texto_preparado, estado, hash_contenido
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        self.conn.commit()
        noticia.id = cur.lastrowid
        return noticia.id

    def listar(self) -> list:
        cur = self.conn.execute("SELECT * FROM noticias ORDER BY id")
        return [dict(fila) for fila in cur.fetchall()]

    def close(self):
        self.conn.close()
