"""Pruebas minimas de la programacion audiovisual (sin red, sin ElevenLabs, sin publicar)."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "produccion_audiovisual" / "piloto_periodistas"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cola_publicacion as cp  # noqa: E402
import programador_audiovisual as pa  # noqa: E402
import publicador_meta_video as pm  # noqa: E402

TZ = cp.TZ
AHORA = datetime(2026, 10, 21, 10, 30, tzinfo=TZ)


def nota(i, titulo, bajada, territorio="local", horas=1, loc="Libertador General San Martín", fuente="InfoYungas"):
    return {"id": i, "titulo": titulo, "bajada": bajada, "imagen": "http://x/i.jpg", "territorio": territorio, "localidad": loc,
            "fecha_iso": (AHORA - timedelta(hours=horas)).isoformat(), "fuente_nombre": fuente, "categoria_etiqueta": "Policiales",
            "url": f"https://ledesmaparticipa.com.ar/noticias/{i}", "fuente_url": f"https://fuente/{i}"}


NORMAL = nota(93704, "Efectivos de la Policía de Jujuy se capacitaron en intervención en situaciones de crisis",
              "Personal policial participó de una jornada de capacitación en Libertador General San Martín. Se trabajó en protocolos.", horas=10)
URGENTE = nota(1001, "Incendio de pastizales sobre la Ruta 34 obliga a cortar el tránsito en Libertador",
               "Bomberos trabajan en el lugar. La ruta permanece cortada en ambos sentidos.", horas=1)
MANTENIMIENTO = nota(95361, "Anuncian cortes de energía por tareas de mantenimiento en Vinalito", "Serán programados el miércoles.", "departamental")
POLITICA = nota(94621, "Milei atacó a Lula a días del balotaje", "Declaraciones del presidente.", "nacional")
VIEJA = nota(94822, "Camioneta volcó en la Cuesta de Lipán", "Un ocupante resultó herido de gravedad.", "provincial", horas=20)


class Prueba(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LEDESMA_COLA_DIR"] = self.tmp.name
        self.llamadas = []

    def tearDown(self):
        os.environ.pop("LEDESMA_COLA_DIR", None)
        self.tmp.cleanup()

    def gen(self, n, tipo, sin_voz):
        self.llamadas.append((n["id"], tipo))
        return Path(self.tmp.name) / f"{n['id']}.mp4"

    def test_urgencia(self):
        self.assertTrue(pa.evaluar_urgencia(URGENTE, AHORA)[0])
        self.assertFalse(pa.evaluar_urgencia(NORMAL, AHORA)[0])
        self.assertFalse(pa.evaluar_urgencia(MANTENIMIENTO, AHORA)[0])
        self.assertFalse(pa.evaluar_urgencia(POLITICA, AHORA)[0])
        self.assertFalse(pa.evaluar_urgencia(VIEJA, AHORA)[0])  # urgente por tema pero antigua

    def test_programada_normal(self):
        n, _ = pa.seleccionar_programada([POLITICA, NORMAL, MANTENIMIENTO], [], AHORA, puntaje=lambda n: 41)
        self.assertEqual(n["id"], 93704)
        n, motivo = pa.seleccionar_programada([NORMAL], [], AHORA, puntaje=lambda n: 10)
        self.assertIsNone(n)  # sin noticia suficientemente relevante: no hay video

    def test_flujo_cola_duplicados_y_no_publica(self):
        p = lambda n: 50  # noqa: E731
        orig = pa._puntaje
        pa._puntaje = p
        try:
            hechos = pa.tick([NORMAL, URGENTE], AHORA, generar=self.gen, log=lambda *a: None)
            self.assertEqual({(1001, "urgente"), (93704, "programado_manana")}, set(self.llamadas))
            self.assertTrue(all(h["estado"] == "pendiente_revision" for h in hechos))
            self.assertEqual(len(cp.cola()), 2)
            self.assertEqual(len(cp.registro()), 2)
            pa.tick([NORMAL, URGENTE], AHORA + timedelta(minutes=5), generar=self.gen, log=lambda *a: None)
            self.assertEqual(len(self.llamadas), 2)  # nada se repite
            # una urgente ya producida tampoco sale luego como programada (ni con otro id y mismo titulo)
            clon = dict(URGENTE, id=2002, url="https://x/2", fuente_url="https://y/2")
            self.assertTrue(cp.es_duplicado(clon, cp.registro(), ahora_=AHORA)[0])
            self.assertTrue(cp.es_duplicado(URGENTE, cp.registro(), ahora_=AHORA)[0])
            self.assertFalse(cp.es_duplicado(URGENTE, cp.registro(), permitir_ids={1001}, ahora_=AHORA)[0])
        finally:
            pa._puntaje = orig

    def test_texto_y_meta_sin_publicar(self):
        t, tags = pa.texto_redes(URGENTE, urgente=True)
        self.assertIn(URGENTE["titulo"].rstrip("."), t)
        self.assertIn("#LedesmaParticipa", tags)
        self.assertIn("#Urgente", tags)
        self.assertLess(len(pa.texto_redes(URGENTE, True)[0]), len(pa.texto_redes(NORMAL)[0]) + 200)
        it = cp.encolar(URGENTE, "urgente", "mateo", "x.mp4", t, tags, "policial")
        self.assertEqual(it["estado"], "pendiente_revision")
        self.assertTrue(pm.publicar(it)["dry_run"])
        with self.assertRaises(PermissionError):
            pm.publicar(it, dry_run=False)  # desactivada y sin aprobar
        with self.assertRaises(ValueError):
            cp.cambiar_estado(it["id"], "publicado")  # no se salta la revision


if __name__ == "__main__":
    unittest.main()
