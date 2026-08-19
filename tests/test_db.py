import sqlite3
import tempfile
import unittest
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def _noticia(self, **overrides) -> Noticia:
        base = dict(
            id=None,
            titulo_original="Título",
            texto_original="Texto",
            url_fuente="https://ejemplo.test/1",
            url_normalizada="https://ejemplo.test/1",
            nombre_fuente="Fuente",
            fecha_fuente="2026-08-01",
            fecha_recoleccion="2026-08-01T00:00:00",
            estado=Estado.ENCONTRADA.value,
            hash_contenido="hash-1",
        )
        base.update(overrides)
        return Noticia(**base)

    def test_crea_base_de_datos_si_no_existe(self):
        self.assertTrue(self.db_path.exists())

    def test_guardar_y_listar(self):
        noticia = self._noticia()
        self.db.guardar(noticia)
        self.assertIsNotNone(noticia.id)
        self.assertEqual(len(self.db.listar()), 1)

    def test_existe_duplicado_por_hash(self):
        self.db.guardar(self._noticia())
        self.assertTrue(self.db.existe_duplicado("https://otra.test/x", "hash-1"))

    def test_existe_duplicado_por_url_normalizada(self):
        self.db.guardar(self._noticia())
        self.assertTrue(self.db.existe_duplicado("https://ejemplo.test/1", "otro-hash"))

    def test_no_existe_duplicado(self):
        self.db.guardar(self._noticia())
        self.assertFalse(self.db.existe_duplicado("https://otra.test/x", "otro-hash"))


class TestMigrarColumnasConcurrente(unittest.TestCase):
    """Bug real visto en producción: dos tareas (SitioWeb y MetaUrgentes)
    arrancaron en el mismo segundo, cada una abriendo su propia conexión a
    la misma base. Ambas vieron la columna nueva como ausente (su propio
    `PRAGMA table_info` todavía no la tenía) y ambas intentaron el mismo
    `ALTER TABLE ADD COLUMN`: la segunda reventaba con
    `sqlite3.OperationalError: duplicate column name`, tumbando esa tarea
    entera (SitioWeb terminó con código de salida 1)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_columna_ya_agregada_por_otro_proceso_no_revienta(self):
        # Simula la carrera: la columna ya existe de verdad en la tabla
        # (como si otro proceso la hubiera agregado un instante antes),
        # pero se le pide a _migrar_columnas que la agregue de nuevo.
        self.db.conn.execute("ALTER TABLE noticias ADD COLUMN columna_de_prueba TEXT")
        self.db.conn.commit()

        self.db._migrar_columnas({"columna_de_prueba": "TEXT"})  # no debe lanzar

        columnas = {
            fila[1] for fila in self.db.conn.execute("PRAGMA table_info(noticias)").fetchall()
        }
        self.assertIn("columna_de_prueba", columnas)

    def test_segunda_apertura_de_la_misma_base_no_revienta(self):
        # Caso real: una segunda instancia de Database sobre el mismo
        # archivo (como ocurre cuando dos procesos cortos distintos abren
        # la base casi al mismo tiempo) no debe fallar en la migración.
        db2 = Database(self.db_path)  # no debe lanzar
        db2.close()

    def test_otro_error_real_de_alter_table_sigue_propagandose(self):
        # Un error de esquema genuino (no la carrera de "ya existe") no
        # debe quedar silenciado: acá la definición es SQL sintácticamente
        # inválido, un error totalmente distinto de "duplicate column name".
        with self.assertRaises(sqlite3.OperationalError):
            self.db._migrar_columnas({"columna_rota": "TEXT NOT NULL DEFAULT"})


class TestReservarProgramacionMetaClaimAtomico(unittest.TestCase):
    """Bug real corregido: `reservar_programacion_meta` hacía SELECT y
    después INSERT sin que fueran atómicos entre sí. Dos workers (dos
    procesos/conexiones distintas apuntando a la misma franja) podían pasar
    ambos el SELECT antes de que cualquiera insertara, y el segundo INSERT
    chocaba contra `UNIQUE(fecha, hora, red_social)` con un
    `sqlite3.IntegrityError` sin manejar — el worker que "pierde la
    carrera" debe quedar bloqueado (reutilizar la fila que ganó), nunca
    crashear."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_llamar_dos_veces_devuelve_el_mismo_id_sin_duplicar_la_fila(self):
        id1 = self.db.reservar_programacion_meta("2026-08-12", "09:00", 1, "facebook", "2026-08-12T09:00:00")
        id2 = self.db.reservar_programacion_meta("2026-08-12", "09:00", 1, "facebook", "2026-08-12T09:00:00")

        self.assertEqual(id1, id2)
        filas = self.db.listar_programacion_meta("2026-08-12")
        self.assertEqual(len(filas), 1)

    def test_conflicto_unique_directo_en_la_tabla_no_revienta_el_claim(self):
        # Simula la ventana de carrera real: dos "workers" insertan la misma
        # franja sin que ninguno haya visto todavía la fila del otro (el
        # SELECT de reservar_programacion_meta no alcanza a evitarlo por sí
        # solo). El segundo INSERT directo sobre la tabla dispara el mismo
        # IntegrityError que dispararía un segundo proceso concurrente real.
        creada_en = "2026-08-12T09:00:00"
        self.db.conn.execute(
            "INSERT INTO programacion_meta (fecha, hora, noticia_id, red_social, estado, creada_en) "
            "VALUES (?, ?, ?, ?, 'pendiente', ?)",
            ("2026-08-12", "09:00", 1, "facebook", creada_en),
        )
        self.db.conn.commit()

        # El "segundo worker" nunca vio la fila anterior (su propio SELECT
        # ya había corrido antes) pero su INSERT sí choca contra el UNIQUE:
        # debe resolverse releyendo la fila ganadora, no propagar la excepción.
        ganador_id = self.db.reservar_programacion_meta(
            "2026-08-12", "09:00", 1, "facebook", creada_en
        )

        filas = self.db.listar_programacion_meta("2026-08-12")
        self.assertEqual(len(filas), 1)
        self.assertEqual(ganador_id, filas[0]["id"])

    def test_franjas_distintas_no_se_pisan(self):
        id_fb = self.db.reservar_programacion_meta("2026-08-12", "09:00", 1, "facebook", "2026-08-12T09:00:00")
        id_ig = self.db.reservar_programacion_meta("2026-08-12", "09:00", 1, "instagram", "2026-08-12T09:00:00")
        id_story = self.db.reservar_programacion_meta(
            "2026-08-12", "09:00", 1, "instagram_story", "2026-08-12T09:00:00"
        )

        self.assertEqual(len({id_fb, id_ig, id_story}), 3)
        self.assertEqual(len(self.db.listar_programacion_meta("2026-08-12")), 3)


if __name__ == "__main__":
    unittest.main()
