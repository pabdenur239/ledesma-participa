import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from .models import Estado, Noticia, RevisionEstado

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

-- Agenda editorial en cascada: una fila por espacio de publicación (franja
-- horaria fija) o por propuesta urgente (hora NULL). No reemplaza ninguna
-- fila existente que ya tenga noticia_id asignado: eso es lo que garantiza
-- que una decisión humana (aprobada/rechazada, vía revision_estado de la
-- propia noticia) nunca se pisa automáticamente en una regeneración.
CREATE TABLE IF NOT EXISTS agenda_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    hora TEXT,
    tipo TEXT NOT NULL DEFAULT 'normal',
    territorio TEXT,
    noticia_id INTEGER,
    creada_en TEXT NOT NULL,
    actualizada_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_agenda_fecha ON agenda_item(fecha);

-- Programación de publicación en Meta (Facebook/Instagram): una fila por
-- franja horaria fija x red social. UNIQUE(fecha, hora, red_social) impide
-- programar dos veces la misma franja en la misma red (sin duplicados). El
-- estado de cada red es independiente: un fallo en Instagram nunca toca la
-- fila de Facebook de la misma franja, y viceversa.
CREATE TABLE IF NOT EXISTS programacion_meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    hora TEXT NOT NULL,
    noticia_id INTEGER NOT NULL,
    red_social TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    meta_id TEXT,
    referencia_extra TEXT,
    intentos INTEGER NOT NULL DEFAULT 0,
    ultimo_error TEXT,
    creada_en TEXT NOT NULL,
    actualizada_en TEXT,
    publicada_en TEXT,
    UNIQUE(fecha, hora, red_social)
);
CREATE INDEX IF NOT EXISTS idx_programacion_meta_fecha ON programacion_meta(fecha);
CREATE INDEX IF NOT EXISTS idx_programacion_meta_estado ON programacion_meta(estado);
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

COLUMNAS_TERRITORIO = {
    "territorio": "TEXT",
    "motivo_territorio": "TEXT",
    "urgente": "INTEGER NOT NULL DEFAULT 0",
}

# Carga manual desde el panel (Cargar noticia): campo aditivo simple para
# distinguir origen sin migrar nada existente. `localidad_informada` es solo
# una pista editorial auditable (no se usa para forzar la clasificación
# territorial); `observacion_interna` es privada, nunca se muestra en el
# contenido preparado ni público.
COLUMNAS_INGRESO_MANUAL = {
    "origen_ingreso": "TEXT NOT NULL DEFAULT 'automatico'",
    "localidad_informada": "TEXT",
    "observacion_interna": "TEXT",
}

# Auditoría de aprobación automática (publicación en Meta sin revisión
# humana): distingue, para siempre, si una noticia llegó a "aprobada" por
# una persona en el panel o por el motor de elegibilidad automática. No
# cambia el significado de revision_estado, solo deja constancia del origen.
COLUMNAS_REVISION_AUTOMATICA = {
    "revision_automatica": "INTEGER NOT NULL DEFAULT 0",
}

# `referencia_extra` en programacion_meta: para la fila de Facebook, guarda
# el photo_id (distinto del post_id) para poder reobtener la URL pública de
# esa misma foto en un reintento posterior sin volver a subirla. Migración
# separada porque es una tabla distinta de `noticias`.
COLUMNAS_PROGRAMACION_META_EXTRA = {
    "referencia_extra": "TEXT",
}

# Placa vertical (9:16) para Instagram Stories: columna aparte de
# `imagen_publicacion_ruta` (la placa cuadrada del feed) porque son dos
# imágenes distintas de la misma noticia. Igual criterio de reutilización:
# una vez generada, no se regenera en reintentos posteriores.
COLUMNAS_STORY = {
    "imagen_story_ruta": "TEXT",
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
        self._migrar_columnas(COLUMNAS_TERRITORIO)
        self._migrar_columnas(COLUMNAS_INGRESO_MANUAL)
        self._migrar_columnas(COLUMNAS_REVISION_AUTOMATICA)
        self._migrar_columnas(COLUMNAS_PROGRAMACION_META_EXTRA, tabla="programacion_meta")
        self._migrar_columnas(COLUMNAS_STORY)

    def _migrar_columnas(self, columnas: dict, tabla: str = "noticias"):
        """Migración no destructiva, aditiva y segura entre procesos: varios
        procesos cortos (MetaPublicar, MetaUrgentes, SitioWeb, etc.) pueden
        abrir la misma base casi al mismo tiempo, cada uno con su propio
        `PRAGMA table_info` desactualizado en el instante en que otro ya
        agregó la columna — bug real visto en producción (dos tareas
        arrancando en el mismo segundo). Si el `ALTER TABLE` choca porque
        la columna ya existe (el otro proceso ganó la carrera), se trata
        como éxito: la columna ya está, que es exactamente lo que se
        buscaba. Cualquier otro error de `ALTER TABLE` sigue propagándose
        tal cual (nunca se oculta un fallo real de esquema)."""
        columnas_existentes = {
            fila[1] for fila in self.conn.execute(f"PRAGMA table_info({tabla})").fetchall()
        }
        for columna, definicion in columnas.items():
            if columna not in columnas_existentes:
                try:
                    self.conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")
                except sqlite3.OperationalError as error:
                    if "duplicate column name" not in str(error):
                        raise
        self.conn.commit()

    def existe_duplicado(self, url_normalizada: str, hash_contenido: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM noticias WHERE url_normalizada = ? OR hash_contenido = ? LIMIT 1",
            (url_normalizada, hash_contenido),
        )
        return cur.fetchone() is not None

    def noticias_publicadas_recientes(self, fecha_limite: str, excluir_id: Optional[int] = None) -> list:
        """Noticias ya publicadas (`estado = 'publicada'`) desde
        `fecha_limite`, para el gate de deduplicación por contenido antes de
        publicar (ver `motor_noticias.meta.publicador`): compara una
        candidata nueva contra lo que ya salió, sin importar por qué
        circuito (franja fija, urgente o reintento) haya salido."""
        query = (
            "SELECT id, url_normalizada, titulo_original, texto_original "
            "FROM noticias WHERE estado = ? AND fecha_recoleccion >= ?"
        )
        params: list = [Estado.PUBLICADA.value, fecha_limite]
        if excluir_id is not None:
            query += " AND id != ?"
            params.append(excluir_id)
        cur = self.conn.execute(query, params)
        return [dict(fila) for fila in cur.fetchall()]

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
                tiene_imagen_original, imagen_publicacion_ruta, imagen_generada_automaticamente,
                territorio, motivo_territorio, urgente,
                origen_ingreso, localidad_informada, observacion_interna, revision_automatica
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                noticia.territorio,
                noticia.motivo_territorio,
                noticia.urgente,
                noticia.origen_ingreso,
                noticia.localidad_informada,
                noticia.observacion_interna,
                int(noticia.revision_automatica),
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

    def listar_publicadas(self) -> list:
        """Noticias ya publicadas, más nuevas primero: única lectura que usa
        el generador del sitio web público (motor_noticias/sitio). No
        escribe nada; no interfiere con el pipeline de publicación."""
        cur = self.conn.execute(
            "SELECT * FROM noticias WHERE estado = ? ORDER BY fecha_recoleccion DESC, id DESC",
            (Estado.PUBLICADA.value,),
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
        automatica: bool = False,
    ) -> None:
        self.conn.execute(
            """
            UPDATE noticias
            SET revision_estado = ?, titulo_revisado = ?, texto_revisado = ?, fecha_revision = ?,
                revision_automatica = ?
            WHERE id = ?
            """,
            (revision_estado, titulo_revisado, texto_revisado, fecha_revision, int(automatica), id_noticia),
        )
        self.conn.commit()

    def actualizar_estado_noticia(self, id_noticia: int, estado: str) -> None:
        self.conn.execute("UPDATE noticias SET estado = ? WHERE id = ?", (estado, id_noticia))
        self.conn.commit()

    def obtener_por_url(self, url_normalizada: str) -> Optional[dict]:
        cur = self.conn.execute(
            "SELECT * FROM noticias WHERE url_normalizada = ? LIMIT 1", (url_normalizada,)
        )
        fila = cur.fetchone()
        return dict(fila) if fila else None

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

    def actualizar_imagen_story(self, id_noticia: int, imagen_story_ruta: Optional[str]) -> None:
        self.conn.execute(
            "UPDATE noticias SET imagen_story_ruta = ? WHERE id = ?",
            (imagen_story_ruta, id_noticia),
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

    def marcar_urgente(self, id_noticia: int, urgente: bool = True) -> None:
        self.conn.execute(
            "UPDATE noticias SET urgente = ? WHERE id = ?", (1 if urgente else 0, id_noticia)
        )
        self.conn.commit()

    def candidato_editorial(
        self, territorio: str, excluidos_ids: set, fecha_limite: str
    ) -> Optional[dict]:
        """Mejor candidato `preparada` de un territorio dado para la cascada
        del Motor Editorial: no rechazado, no usado en ninguna agenda previa,
        no marcado con riesgo editorial obligatorio (esos quedan disponibles
        para revisión humana en el panel, pero nunca ocupan automáticamente
        una franja), y dentro de la antigüedad máxima permitida. El más
        reciente primero."""
        query = (
            "SELECT * FROM noticias WHERE estado = ? AND territorio = ? "
            "AND revision_estado != ? AND fecha_recoleccion >= ? "
            "AND (requiere_revision_especial = 0 OR requiere_revision_especial IS NULL)"
        )
        params: list = [Estado.PREPARADA.value, territorio, RevisionEstado.RECHAZADA.value, fecha_limite]
        if excluidos_ids:
            placeholders = ",".join("?" * len(excluidos_ids))
            query += f" AND id NOT IN ({placeholders})"
            params.extend(sorted(excluidos_ids))
        query += " ORDER BY fecha_recoleccion DESC LIMIT 1"
        cur = self.conn.execute(query, params)
        fila = cur.fetchone()
        return dict(fila) if fila else None

    def candidatos_urgentes(self, excluidos_ids: set, fecha_limite: str) -> list:
        """Noticias locales/departamentales marcadas urgentes, `preparada`,
        no rechazadas, sin riesgo editorial obligatorio, no usadas todavía
        en ninguna agenda."""
        query = (
            "SELECT * FROM noticias WHERE estado = ? AND urgente = 1 "
            "AND territorio IN ('local', 'departamental') "
            "AND revision_estado != ? AND fecha_recoleccion >= ? "
            "AND (requiere_revision_especial = 0 OR requiere_revision_especial IS NULL)"
        )
        params: list = [Estado.PREPARADA.value, RevisionEstado.RECHAZADA.value, fecha_limite]
        if excluidos_ids:
            placeholders = ",".join("?" * len(excluidos_ids))
            query += f" AND id NOT IN ({placeholders})"
            params.extend(sorted(excluidos_ids))
        query += " ORDER BY fecha_recoleccion DESC"
        cur = self.conn.execute(query, params)
        return [dict(fila) for fila in cur.fetchall()]

    def noticias_ids_usadas_en_agenda(self) -> set:
        cur = self.conn.execute("SELECT DISTINCT noticia_id FROM agenda_item WHERE noticia_id IS NOT NULL")
        return {fila["noticia_id"] for fila in cur.fetchall()}

    def obtener_agenda_item(self, fecha: str, hora: Optional[str]) -> Optional[dict]:
        cur = self.conn.execute(
            "SELECT * FROM agenda_item WHERE fecha = ? AND hora = ? AND tipo = 'normal'",
            (fecha, hora),
        )
        fila = cur.fetchone()
        return dict(fila) if fila else None

    def obtener_agenda_item_por_id(self, id_item: int) -> Optional[dict]:
        cur = self.conn.execute("SELECT * FROM agenda_item WHERE id = ?", (id_item,))
        fila = cur.fetchone()
        return dict(fila) if fila else None

    def guardar_agenda_item(
        self,
        fecha: str,
        hora: Optional[str],
        tipo: str,
        territorio: Optional[str],
        noticia_id: Optional[int],
        creada_en: str,
        actualizada_en: Optional[str] = None,
        id_existente: Optional[int] = None,
    ) -> int:
        actualizada_en = actualizada_en or creada_en
        if id_existente:
            self.conn.execute(
                "UPDATE agenda_item SET territorio = ?, noticia_id = ?, actualizada_en = ? WHERE id = ?",
                (territorio, noticia_id, actualizada_en, id_existente),
            )
            self.conn.commit()
            return id_existente

        cur = self.conn.execute(
            """
            INSERT INTO agenda_item (fecha, hora, tipo, territorio, noticia_id, creada_en, actualizada_en)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (fecha, hora, tipo, territorio, noticia_id, creada_en, actualizada_en),
        )
        self.conn.commit()
        return cur.lastrowid

    def listar_agenda(self, fecha: Optional[str] = None) -> list:
        if fecha:
            cur = self.conn.execute(
                "SELECT * FROM agenda_item WHERE fecha = ? ORDER BY tipo DESC, hora IS NULL, hora",
                (fecha,),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM agenda_item ORDER BY fecha DESC, tipo DESC, hora IS NULL, hora"
            )
        return [dict(fila) for fila in cur.fetchall()]

    def obtener_programacion_meta(self, fecha: str, hora: str, red_social: str) -> Optional[dict]:
        cur = self.conn.execute(
            "SELECT * FROM programacion_meta WHERE fecha = ? AND hora = ? AND red_social = ?",
            (fecha, hora, red_social),
        )
        fila = cur.fetchone()
        return dict(fila) if fila else None

    def reservar_programacion_meta(
        self, fecha: str, hora: str, noticia_id: int, red_social: str, creada_en: str
    ) -> int:
        """Crea (o devuelve, sin tocar) la fila de programación de una franja
        x red social. Idempotente: si ya existe una fila para esa franja y
        red, nunca la duplica ni la pisa (evita reprogramar/republicar).

        Claim atómico entre workers concurrentes: el SELECT previo no basta
        por sí solo (dos procesos pueden pasar ambos el SELECT antes de que
        cualquiera haga el INSERT — ventana de carrera real). La garantía de
        unicidad real es `UNIQUE(fecha, hora, red_social)` en el propio
        motor de SQLite: si dos workers intentan reservar la misma franja al
        mismo tiempo, solo uno consigue insertar; el otro recibe
        `IntegrityError` acá mismo y, en vez de propagar el error (lo que
        tumbaría a ese worker antes de llegar a publicar), relee la fila que
        el otro worker ya creó y la devuelve — igual que si hubiera llegado
        un instante después. Así nunca hay dos filas para la misma franja x
        red, y el worker que pierde la carrera queda bloqueado antes de
        cualquier POST a Meta, no crasheado."""
        existente = self.obtener_programacion_meta(fecha, hora, red_social)
        if existente:
            return existente["id"]
        try:
            cur = self.conn.execute(
                """
                INSERT INTO programacion_meta (fecha, hora, noticia_id, red_social, estado, creada_en)
                VALUES (?, ?, ?, ?, 'pendiente', ?)
                """,
                (fecha, hora, noticia_id, red_social, creada_en),
            )
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            self.conn.rollback()
            ganador = self.obtener_programacion_meta(fecha, hora, red_social)
            if ganador is None:
                raise  # no debería pasar: el conflicto UNIQUE implica que existe
            return ganador["id"]

    def actualizar_programacion_meta(
        self,
        id_programacion: int,
        estado: str,
        meta_id: Optional[str] = None,
        referencia_extra: Optional[str] = None,
        ultimo_error: Optional[str] = None,
        intentos: Optional[int] = None,
        actualizada_en: Optional[str] = None,
        publicada_en: Optional[str] = None,
    ) -> None:
        """`referencia_extra`, si no se pasa explícitamente, conserva el
        valor existente (mismo criterio que `intentos`): por ejemplo, un
        reintento de Instagram no debe borrar el photo_id de Facebook que
        ya se guardó en un intento anterior."""
        actual = self.conn.execute(
            "SELECT intentos, referencia_extra FROM programacion_meta WHERE id = ?", (id_programacion,)
        ).fetchone()
        if actual is None:
            return
        nuevos_intentos = intentos if intentos is not None else actual["intentos"]
        nueva_referencia_extra = referencia_extra if referencia_extra is not None else actual["referencia_extra"]
        self.conn.execute(
            """
            UPDATE programacion_meta
            SET estado = ?, meta_id = ?, referencia_extra = ?, ultimo_error = ?, intentos = ?,
                actualizada_en = ?, publicada_en = ?
            WHERE id = ?
            """,
            (
                estado,
                meta_id,
                nueva_referencia_extra,
                ultimo_error,
                nuevos_intentos,
                actualizada_en,
                publicada_en,
                id_programacion,
            ),
        )
        self.conn.commit()

    def listar_programacion_meta(self, fecha: Optional[str] = None) -> list:
        if fecha:
            cur = self.conn.execute(
                "SELECT * FROM programacion_meta WHERE fecha = ? ORDER BY hora, red_social", (fecha,)
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM programacion_meta ORDER BY fecha DESC, hora, red_social"
            )
        return [dict(fila) for fila in cur.fetchall()]

    def listar_programacion_meta_para_reintentar(self, max_intentos: int) -> list:
        cur = self.conn.execute(
            "SELECT * FROM programacion_meta WHERE estado = 'error' AND intentos < ? "
            "ORDER BY fecha, hora",
            (max_intentos,),
        )
        return [dict(fila) for fila in cur.fetchall()]

    def close(self):
        self.conn.close()
