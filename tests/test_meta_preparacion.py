import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from motor_noticias.db import Database
from motor_noticias.meta.contenido import ContenidoFacebook
from motor_noticias.meta.preparacion import (
    ErrorPreparacionFacebook,
    preparar_publicacion,
    preparar_publicacion_story,
)
from motor_noticias.models import Estado, Noticia


def _noticia(**overrides) -> dict:
    base = dict(
        titulo_preparado="Título preparado",
        texto_preparado="Texto preparado con hechos verificados.",
        titulo_revisado=None,
        texto_revisado=None,
        nombre_fuente="Fuente",
        localidad="Libertador General San Martín",
        revision_estado="aprobada",
        requiere_revision_especial=False,
        tiene_imagen_original=False,
        imagen_publicacion_ruta=None,
        imagen_generada_automaticamente=False,
    )
    base.update(overrides)
    return base


class TestPrepararPublicacionConDirectorioAislado(unittest.TestCase):
    """Redirige la generación de placas a un directorio temporal para no
    escribir archivos reales del repositorio durante las pruebas."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.parche = patch(
            "motor_noticias.meta.imagen.DIRECTORIO_PLACAS_DEFAULT", Path(self.tmpdir.name)
        )
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        self.tmpdir.cleanup()


class TestPrepararPublicacion(TestPrepararPublicacionConDirectorioAislado):
    def test_pendiente_no_puede_prepararse(self):
        noticia = _noticia(revision_estado="pendiente")
        with self.assertRaises(ErrorPreparacionFacebook):
            preparar_publicacion(noticia)

    def test_rechazada_no_puede_prepararse(self):
        noticia = _noticia(revision_estado="rechazada")
        with self.assertRaises(ErrorPreparacionFacebook):
            preparar_publicacion(noticia)

    def test_aprobada_genera_vista_previa(self):
        contenido = preparar_publicacion(_noticia())
        self.assertIsInstance(contenido, ContenidoFacebook)
        self.assertIn("Título preparado", contenido.post_principal)

    def test_riesgo_politico_aprobado_permite_dry_run(self):
        noticia = _noticia(requiere_revision_especial=True)
        contenido = preparar_publicacion(noticia, dry_run=True)
        self.assertIsInstance(contenido, ContenidoFacebook)

    def test_riesgo_politico_aprobado_rechaza_publicacion_real(self):
        noticia = _noticia(requiere_revision_especial=True)
        with self.assertRaises(ErrorPreparacionFacebook):
            preparar_publicacion(noticia, dry_run=False)

    def test_sin_riesgo_politico_dry_run_sigue_funcionando(self):
        contenido = preparar_publicacion(_noticia(), dry_run=True)
        self.assertIsInstance(contenido, ContenidoFacebook)


class TestImagenEnPreparacion(TestPrepararPublicacionConDirectorioAislado):
    def test_sin_imagen_genera_placa(self):
        contenido = preparar_publicacion(_noticia())
        self.assertTrue(contenido.imagen_generada_automaticamente)
        self.assertIsNotNone(contenido.imagen_url)
        ruta = Path(contenido.imagen_url)
        self.assertTrue(ruta.exists())
        self.assertEqual(ruta.suffix, ".png")
        self.assertTrue(ruta.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_con_imagen_original_no_genera_placa(self):
        noticia = _noticia(
            tiene_imagen_original=True,
            imagen_publicacion_ruta="https://ejemplo.test/foto.jpg",
        )
        contenido = preparar_publicacion(noticia)
        self.assertFalse(contenido.imagen_generada_automaticamente)
        self.assertEqual(contenido.imagen_url, "https://ejemplo.test/foto.jpg")

    def test_riesgo_politico_aprobado_tambien_muestra_imagen_en_dry_run(self):
        noticia = _noticia(requiere_revision_especial=True)
        contenido = preparar_publicacion(noticia, dry_run=True)
        self.assertIsNotNone(contenido.imagen_url)

    def test_persiste_la_imagen_generada_en_la_base(self):
        with tempfile.TemporaryDirectory() as tmp_db:
            db = Database(Path(tmp_db) / "test.db")
            try:
                noticia_modelo = Noticia(
                    id=None,
                    titulo_original="Título original",
                    texto_original="Texto original.",
                    url_fuente="https://ejemplo.test/1",
                    url_normalizada="https://ejemplo.test/1",
                    nombre_fuente="Fuente",
                    fecha_fuente="2026-08-01",
                    fecha_recoleccion="2026-08-01T00:00:00",
                    estado=Estado.PREPARADA.value,
                    hash_contenido="hash-1",
                    titulo_preparado="Título preparado",
                    texto_preparado="Texto preparado con hechos verificados.",
                    revision_estado="aprobada",
                )
                db.guardar(noticia_modelo)
                noticia_dict = db.obtener(noticia_modelo.id)

                preparar_publicacion(noticia_dict, db=db)

                guardada = db.obtener(noticia_modelo.id)
                self.assertTrue(guardada["imagen_generada_automaticamente"])
                self.assertIsNotNone(guardada["imagen_publicacion_ruta"])
                ruta = Path(guardada["imagen_publicacion_ruta"])
                self.assertTrue(ruta.exists())
                self.assertEqual(ruta.suffix, ".png")
            finally:
                db.close()

    def test_generacion_repetida_no_regenera_innecesariamente(self):
        with tempfile.TemporaryDirectory() as tmp_db:
            db = Database(Path(tmp_db) / "test.db")
            try:
                noticia_modelo = Noticia(
                    id=None,
                    titulo_original="Título original",
                    texto_original="Texto original.",
                    url_fuente="https://ejemplo.test/1",
                    url_normalizada="https://ejemplo.test/1",
                    nombre_fuente="Fuente",
                    fecha_fuente="2026-08-01",
                    fecha_recoleccion="2026-08-01T00:00:00",
                    estado=Estado.PREPARADA.value,
                    hash_contenido="hash-1",
                    titulo_preparado="Título preparado",
                    texto_preparado="Texto preparado con hechos verificados.",
                    revision_estado="aprobada",
                )
                db.guardar(noticia_modelo)
                noticia_dict = db.obtener(noticia_modelo.id)

                contenido1 = preparar_publicacion(noticia_dict, db=db)
                mtime_original = Path(contenido1.imagen_url).stat().st_mtime_ns

                noticia_actualizada = db.obtener(noticia_modelo.id)
                contenido2 = preparar_publicacion(noticia_actualizada, db=db)

                self.assertEqual(contenido1.imagen_url, contenido2.imagen_url)
                self.assertEqual(Path(contenido2.imagen_url).stat().st_mtime_ns, mtime_original)
            finally:
                db.close()


class TestPrepararPublicacionStory(TestPrepararPublicacionConDirectorioAislado):
    def test_pendiente_no_puede_prepararse(self):
        noticia = _noticia(revision_estado="pendiente")
        with self.assertRaises(ErrorPreparacionFacebook):
            preparar_publicacion_story(noticia)

    def test_rechazada_no_puede_prepararse(self):
        noticia = _noticia(revision_estado="rechazada")
        with self.assertRaises(ErrorPreparacionFacebook):
            preparar_publicacion_story(noticia)

    def test_riesgo_politico_nunca_genera_story_ni_siquiera_de_prueba(self):
        # A diferencia del feed, la Story no tiene un modo "solo vista
        # previa": bloquea siempre que requiera revisión especial.
        noticia = _noticia(requiere_revision_especial=True)
        with self.assertRaises(ErrorPreparacionFacebook):
            preparar_publicacion_story(noticia)

    def test_aprobada_genera_una_placa_vertical_png(self):
        ruta_texto = preparar_publicacion_story(_noticia())
        ruta = Path(ruta_texto)
        self.assertTrue(ruta.exists())
        self.assertEqual(ruta.suffix, ".png")
        self.assertTrue(ruta.name.startswith("story_"))

    def test_reutiliza_imagen_story_ya_persistida_sin_regenerar(self):
        noticia = _noticia(imagen_story_ruta="/ruta/ya/persistida/story_x.png")
        ruta_texto = preparar_publicacion_story(noticia)
        self.assertEqual(ruta_texto, "/ruta/ya/persistida/story_x.png")

    def test_persiste_la_ruta_generada_en_la_base(self):
        with tempfile.TemporaryDirectory() as tmp_db:
            db = Database(Path(tmp_db) / "test.db")
            try:
                noticia_modelo = Noticia(
                    id=None,
                    titulo_original="Título original",
                    texto_original="Texto original.",
                    url_fuente="https://ejemplo.test/1",
                    url_normalizada="https://ejemplo.test/1",
                    nombre_fuente="Fuente",
                    fecha_fuente="2026-08-01",
                    fecha_recoleccion="2026-08-01T00:00:00",
                    estado=Estado.PREPARADA.value,
                    hash_contenido="hash-1",
                    titulo_preparado="Título preparado",
                    texto_preparado="Texto preparado con hechos verificados.",
                    revision_estado="aprobada",
                )
                db.guardar(noticia_modelo)
                noticia_dict = db.obtener(noticia_modelo.id)

                ruta_texto = preparar_publicacion_story(noticia_dict, db=db)

                guardada = db.obtener(noticia_modelo.id)
                self.assertEqual(guardada["imagen_story_ruta"], ruta_texto)
                self.assertTrue(Path(ruta_texto).exists())
            finally:
                db.close()

    def test_no_toca_la_imagen_de_feed(self):
        with tempfile.TemporaryDirectory() as tmp_db:
            db = Database(Path(tmp_db) / "test.db")
            try:
                noticia_modelo = Noticia(
                    id=None,
                    titulo_original="Título original",
                    texto_original="Texto original.",
                    url_fuente="https://ejemplo.test/1",
                    url_normalizada="https://ejemplo.test/1",
                    nombre_fuente="Fuente",
                    fecha_fuente="2026-08-01",
                    fecha_recoleccion="2026-08-01T00:00:00",
                    estado=Estado.PREPARADA.value,
                    hash_contenido="hash-1",
                    titulo_preparado="Título preparado",
                    texto_preparado="Texto preparado con hechos verificados.",
                    revision_estado="aprobada",
                )
                db.guardar(noticia_modelo)
                noticia_dict = db.obtener(noticia_modelo.id)

                preparar_publicacion(noticia_dict, db=db)
                preparar_publicacion_story(db.obtener(noticia_modelo.id), db=db)

                guardada = db.obtener(noticia_modelo.id)
                self.assertIsNotNone(guardada["imagen_publicacion_ruta"])
                self.assertIsNotNone(guardada["imagen_story_ruta"])
                self.assertNotEqual(guardada["imagen_publicacion_ruta"], guardada["imagen_story_ruta"])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
