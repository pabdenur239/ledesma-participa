import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia, OrigenIngreso
from motor_noticias.motor_editorial import HORA_RESUMEN_DEL_DIA, ZONA_JUJUY
from motor_noticias.resumen_dia import CANTIDAD_MINIMA, reservar_franja_resumen_del_dia

AHORA = datetime(2026, 8, 21, 22, 30, tzinfo=ZONA_JUJUY)


def _publicada(db, territorio, titulo, id_sufijo):
    n = Noticia(
        id=None,
        titulo_original=titulo,
        texto_original="Texto de prueba con contenido suficiente.",
        url_fuente=f"https://ejemplo.test/{id_sufijo}",
        url_normalizada=f"https://ejemplo.test/{id_sufijo}",
        nombre_fuente="Fuente de prueba",
        fecha_fuente="",
        fecha_recoleccion=(AHORA.astimezone(timezone.utc) - timedelta(hours=2)).isoformat(),
        estado=Estado.PUBLICADA.value,
        hash_contenido=f"hash-{id_sufijo}",
        territorio=territorio,
        motivo_territorio="prueba",
        titulo_preparado=titulo,
        texto_preparado="Texto preparado.",
    )
    db.guardar(n)
    return n


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()


class TestResumenDelDia(BaseTest):
    def test_sin_candidatas_suficientes_queda_sin_candidato(self):
        for i in range(CANTIDAD_MINIMA - 1):
            _publicada(self.db, "local", f"Nota {i}", f"n{i}")

        entrada = reservar_franja_resumen_del_dia(self.db, ahora=AHORA)

        self.assertEqual(entrada.estado, "sin_candidato")
        self.assertIsNone(entrada.noticia_id)

    def test_con_candidatas_suficientes_crea_el_resumen(self):
        for i in range(CANTIDAD_MINIMA + 1):
            _publicada(self.db, "local" if i < 3 else "provincial", f"Nota {i}", f"n{i}")

        entrada = reservar_franja_resumen_del_dia(self.db, ahora=AHORA)

        self.assertEqual(entrada.estado, "creado")
        self.assertEqual(entrada.hora, HORA_RESUMEN_DEL_DIA)
        noticia = self.db.obtener(entrada.noticia_id)
        self.assertEqual(noticia["origen_ingreso"], OrigenIngreso.RESUMEN_DIARIO.value)
        for i in range(3):
            self.assertIn(f"Nota {i}", noticia["texto_preparado"])
        self.assertIn("ledesmaparticipa.com.ar", noticia["texto_preparado"])

    def test_prioriza_locales_y_departamentales(self):
        for i in range(8):
            _publicada(self.db, "nacional", f"Nacional {i}", f"nac{i}")
        local = _publicada(self.db, "local", "Local importante", "loc1")
        depto = _publicada(self.db, "departamental", "Departamental importante", "dep1")

        entrada = reservar_franja_resumen_del_dia(self.db, ahora=AHORA)
        noticia = self.db.obtener(entrada.noticia_id)

        self.assertIn(local.titulo_preparado, noticia["texto_preparado"])
        self.assertIn(depto.titulo_preparado, noticia["texto_preparado"])

    def test_llamar_dos_veces_no_duplica(self):
        for i in range(CANTIDAD_MINIMA + 1):
            _publicada(self.db, "local", f"Nota {i}", f"n{i}")

        entrada_1 = reservar_franja_resumen_del_dia(self.db, ahora=AHORA)
        entrada_2 = reservar_franja_resumen_del_dia(self.db, ahora=AHORA)

        self.assertEqual(entrada_1.noticia_id, entrada_2.noticia_id)
        self.assertEqual(entrada_2.estado, "existente")
        resumenes = [n for n in self.db.listar() if n["origen_ingreso"] == OrigenIngreso.RESUMEN_DIARIO.value]
        self.assertEqual(len(resumenes), 1)


if __name__ == "__main__":
    unittest.main()
