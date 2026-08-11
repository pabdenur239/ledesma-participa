import sqlite3
import tempfile
import unittest
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia, RevisionEstado


def _noticia_preparada(**overrides) -> Noticia:
    base = dict(
        id=None,
        titulo_original="Título",
        texto_original="Texto",
        url_fuente="https://ejemplo.test/1",
        url_normalizada="https://ejemplo.test/1",
        nombre_fuente="Fuente",
        fecha_fuente="2026-08-01",
        fecha_recoleccion="2026-08-01T00:00:00",
        estado=Estado.PREPARADA.value,
        hash_contenido="hash-1",
        titulo_preparado="Título preparado",
        texto_preparado="Texto preparado",
    )
    base.update(overrides)
    return Noticia(**base)


class TestMigracion(unittest.TestCase):
    def test_migra_base_existente_sin_columnas_de_revision_sin_perder_datos(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "vieja.db"

            # Simula una base creada antes de agregar revisión humana.
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE noticias (
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
                """
            )
            conn.execute(
                """
                INSERT INTO noticias (
                    titulo_original, texto_original, url_fuente, url_normalizada,
                    nombre_fuente, fecha_fuente, fecha_recoleccion, estado, hash_contenido
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Noticia vieja",
                    "Texto viejo",
                    "https://ejemplo.test/vieja",
                    "https://ejemplo.test/vieja",
                    "Fuente vieja",
                    "2026-01-01",
                    "2026-01-01T00:00:00",
                    Estado.PREPARADA.value,
                    "hash-vieja",
                ),
            )
            conn.commit()
            conn.close()

            db = Database(db_path)
            try:
                filas = db.listar()
                self.assertEqual(len(filas), 1)
                self.assertEqual(filas[0]["titulo_original"], "Noticia vieja")
                self.assertEqual(filas[0]["revision_estado"], RevisionEstado.PENDIENTE.value)
                self.assertFalse(filas[0]["requiere_revision_especial"])
                self.assertIsNone(filas[0]["categoria_riesgo"])
            finally:
                db.close()

    def test_migra_base_con_revision_pero_sin_columnas_de_riesgo(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "intermedia.db"

            # Simula una base ya migrada con revisión humana (fase anterior)
            # pero todavía sin las columnas de riesgo editorial.
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE noticias (
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
                    hash_contenido TEXT NOT NULL UNIQUE,
                    revision_estado TEXT NOT NULL DEFAULT 'pendiente',
                    fecha_revision TEXT,
                    titulo_revisado TEXT,
                    texto_revisado TEXT
                );
                """
            )
            conn.execute(
                """
                INSERT INTO noticias (
                    titulo_original, texto_original, url_fuente, url_normalizada,
                    nombre_fuente, fecha_fuente, fecha_recoleccion, estado, hash_contenido,
                    revision_estado
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Noticia intermedia",
                    "Texto intermedio",
                    "https://ejemplo.test/intermedia",
                    "https://ejemplo.test/intermedia",
                    "Fuente",
                    "2026-02-01",
                    "2026-02-01T00:00:00",
                    Estado.PREPARADA.value,
                    "hash-intermedia",
                    RevisionEstado.APROBADA.value,
                ),
            )
            conn.commit()
            conn.close()

            db = Database(db_path)
            try:
                filas = db.listar()
                self.assertEqual(len(filas), 1)
                # la revisión humana previa se conserva intacta
                self.assertEqual(filas[0]["revision_estado"], RevisionEstado.APROBADA.value)
                # las columnas de riesgo aparecen con su valor por defecto
                self.assertFalse(filas[0]["requiere_revision_especial"])
                self.assertIsNone(filas[0]["categoria_riesgo"])
                self.assertIsNone(filas[0]["motivo_revision_especial"])
            finally:
                db.close()


class TestRevisionHumana(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_noticia_preparada_queda_pendiente_por_defecto(self):
        noticia = _noticia_preparada()
        self.db.guardar(noticia)
        guardada = self.db.obtener(noticia.id)
        self.assertEqual(guardada["revision_estado"], RevisionEstado.PENDIENTE.value)

    def test_aprobar_actualiza_estado_y_contenido_revisado(self):
        noticia = _noticia_preparada()
        self.db.guardar(noticia)
        self.db.actualizar_revision(
            noticia.id,
            RevisionEstado.APROBADA.value,
            titulo_revisado="Título editado",
            texto_revisado="Texto editado",
            fecha_revision="2026-08-11T00:00:00",
        )
        guardada = self.db.obtener(noticia.id)
        self.assertEqual(guardada["revision_estado"], RevisionEstado.APROBADA.value)
        self.assertEqual(guardada["titulo_revisado"], "Título editado")
        self.assertEqual(guardada["texto_revisado"], "Texto editado")
        # aprobar nunca cambia el estado principal a publicada
        self.assertEqual(guardada["estado"], Estado.PREPARADA.value)

    def test_rechazar_actualiza_estado(self):
        noticia = _noticia_preparada()
        self.db.guardar(noticia)
        self.db.actualizar_revision(noticia.id, RevisionEstado.RECHAZADA.value)
        guardada = self.db.obtener(noticia.id)
        self.assertEqual(guardada["revision_estado"], RevisionEstado.RECHAZADA.value)
        self.assertEqual(guardada["estado"], Estado.PREPARADA.value)

    def test_editar_sin_cambiar_estado_de_revision(self):
        noticia = _noticia_preparada()
        self.db.guardar(noticia)
        self.db.actualizar_revision(
            noticia.id,
            RevisionEstado.PENDIENTE.value,
            titulo_revisado="Título corregido a mano",
            texto_revisado="Texto corregido a mano",
        )
        guardada = self.db.obtener(noticia.id)
        self.assertEqual(guardada["revision_estado"], RevisionEstado.PENDIENTE.value)
        self.assertEqual(guardada["titulo_revisado"], "Título corregido a mano")
        self.assertEqual(guardada["texto_revisado"], "Texto corregido a mano")

    def test_guarda_y_recupera_campos_de_riesgo_editorial(self):
        noticia = _noticia_preparada(
            requiere_revision_especial=True,
            categoria_riesgo="institucional_municipal",
            motivo_revision_especial="Menciona 'Intendente'.",
        )
        self.db.guardar(noticia)
        guardada = self.db.obtener(noticia.id)
        self.assertTrue(guardada["requiere_revision_especial"])
        self.assertEqual(guardada["categoria_riesgo"], "institucional_municipal")
        self.assertEqual(guardada["motivo_revision_especial"], "Menciona 'Intendente'.")

    def test_listar_preparadas_filtra_por_revision_estado(self):
        pendiente = _noticia_preparada(
            hash_contenido="hash-a", url_fuente="https://ejemplo.test/a", url_normalizada="https://ejemplo.test/a"
        )
        aprobada = _noticia_preparada(
            hash_contenido="hash-b", url_fuente="https://ejemplo.test/b", url_normalizada="https://ejemplo.test/b"
        )
        descartada = _noticia_preparada(
            hash_contenido="hash-c",
            url_fuente="https://ejemplo.test/c",
            url_normalizada="https://ejemplo.test/c",
            estado=Estado.DESCARTADA.value,
        )
        self.db.guardar(pendiente)
        self.db.guardar(aprobada)
        self.db.guardar(descartada)
        self.db.actualizar_revision(aprobada.id, RevisionEstado.APROBADA.value)

        todas = self.db.listar_preparadas()
        pendientes = self.db.listar_preparadas(RevisionEstado.PENDIENTE.value)
        aprobadas = self.db.listar_preparadas(RevisionEstado.APROBADA.value)
        rechazadas = self.db.listar_preparadas(RevisionEstado.RECHAZADA.value)

        # "todas" son todas las PREPARADAS (no incluye la descartada)
        self.assertEqual({n["id"] for n in todas}, {pendiente.id, aprobada.id})
        self.assertEqual([n["id"] for n in pendientes], [pendiente.id])
        self.assertEqual([n["id"] for n in aprobadas], [aprobada.id])
        self.assertEqual(rechazadas, [])


if __name__ == "__main__":
    unittest.main()
