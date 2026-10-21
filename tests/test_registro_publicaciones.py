"""Registro unico imagen/Reel: pruebas locales y simuladas (sin red, sin publicar nada real)."""
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from motor_noticias import registro_publicaciones as rp
from tests.test_meta_publicador import AHORA, FakeClienteMeta, _noticia
from motor_noticias.db import Database
from motor_noticias.meta.publicador import publicar_urgentes

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "produccion_audiovisual" / "piloto_periodistas"))
import cola_publicacion as cp  # noqa: E402


def video_news(i, titulo, url, bajada="Bajada de la nota."):
    return {"id": i, "titulo": titulo, "bajada": bajada, "fuente_url": url, "url": f"https://ledesmaparticipa.com.ar/noticias/{i}"}


class Prueba(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        os.environ["LEDESMA_COLA_DIR"] = self.tmp.name
        os.environ["LEDESMA_REGISTRO_PUBLICACIONES"] = str(Path(self.tmp.name) / "registro_publicaciones.json")

    def tearDown(self):
        os.environ.pop("LEDESMA_COLA_DIR", None)
        os.environ.pop("LEDESMA_REGISTRO_PUBLICACIONES", None)
        self.db.conn.close()
        self.tmp.cleanup()

    def _urgente(self, n, fake):
        self.db.guardar_agenda_item("2026-08-12", None, "urgente", "local", n.id, AHORA.isoformat())
        publicar_urgentes(self.db, "2026-08-12", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

    def test_imagen_publicada_rechaza_reel(self):
        n = _noticia(self.db, 1, titulo_original="Choque en la ruta 34 deja dos heridos en Libertador")
        self._urgente(n, FakeClienteMeta())
        redes = {(e["formato"], e["plataforma"]) for e in rp.entradas() if e["estado"] == "publicado"}
        self.assertEqual(redes, {("imagen", "facebook"), ("imagen", "instagram")})
        mismo_url = video_news(94000, "Titulo distinto", "http://a.com/1")  # otro ID, otro titulo, misma URL
        self.assertTrue(cp.es_duplicado(mismo_url, [])[0])
        self.assertFalse(cp.es_duplicado(video_news(94001, "Otra nota distinta sobre otro tema", "http://a.com/zzz"), [])[0])

    def test_reel_publicado_rechaza_imagen(self):
        rp.registrar(94002, "http://a.com/2", "Incendio en pastizales sobre la ruta 34", "texto", "reel", "facebook")
        rp.registrar(94002, "http://a.com/2", "Incendio en pastizales sobre la ruta 34", "texto", "reel", "instagram")
        n2 = _noticia(self.db, 2, url_fuente="http://a.com/2")
        fake = FakeClienteMeta()
        self._urgente(n2, fake)
        fila = self.db.obtener_programacion_meta("2026-08-12", "urgente-1", "facebook")
        self.assertEqual(fila["estado"], "duplicado")
        self.assertFalse([l for l in fake.llamadas if l[0].startswith("publicar")])
        self.assertTrue(any(e["estado"] == "omitida_por_duplicado" for e in rp.entradas()))

    def test_mismo_titulo_otro_id(self):
        rp.registrar(1, "http://x/1", "Choque fatal en la Ruta 34 cerca de Libertador", "texto", "reel", "facebook")
        ev = rp.evaluar(2, "http://otra/url", "Choque fatal en la Ruta 34: cerca de Libertador!", "otro texto", formato_propio="imagen")
        self.assertIsNotNone(ev["duplicado"])
        self.assertIn("titulo", ev["motivo"])

    def test_actualizacion_sustancial_si_titulo_distinto_no(self):
        base = "Incendio de pastizales en la ruta 34 de Libertador"
        txt = "Bomberos combaten un incendio de pastizales. La ruta esta cortada."
        rp.registrar(5, "http://f/5", base, txt, "reel", "facebook", ahora_=AHORA - timedelta(hours=4))
        # solo cambia el titulo / redaccion: NO es actualizacion
        ev = rp.evaluar(6, "http://f/6", "Incendio de pastizales en la ruta 34 de Libertador: bomberos trabajan", txt, ahora_=AHORA)
        self.assertIsNotNone(ev["duplicado"])
        # parte oficial con informacion nueva y comprobable: SI, vinculada a la original
        nuevo = ("Parte oficial: el incendio de pastizales fue controlado por brigadistas provinciales y la ruta 34 se habilito. "
                 "Hubo evacuacion preventiva de familias del paraje, sin heridos, y Vialidad restablecio el transito.")
        ev = rp.evaluar(7, "http://f/7", "Incendio de pastizales en la ruta 34: controlado y ruta habilitada", nuevo, ahora_=AHORA)
        self.assertIsNone(ev["duplicado"])
        self.assertIsNotNone(ev["actualiza_a"])
        eid = rp.registrar(7, "http://f/7", "Incendio de pastizales en la ruta 34: controlado y ruta habilitada", nuevo, "reel", "facebook",
                           actualiza_a=ev["actualiza_a"], ahora_=AHORA)
        self.assertEqual([e for e in rp.entradas() if e["id"] == eid][0]["actualiza_a"], ev["actualiza_a"])


if __name__ == "__main__":
    unittest.main()
