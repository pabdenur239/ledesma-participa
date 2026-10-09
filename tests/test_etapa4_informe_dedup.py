"""Etapa 4: el informe diario de Clima + Dólar (título fijo desde la Etapa 1)
no debe quedar bloqueado como duplicado del informe del día anterior
(caso real en producción, 9/10/2026, 07:30)."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.dedupe import hash_contenido, normalizar_url
from motor_noticias.informe_diario import NOMBRE_FUENTE, TITULO_INFORME
from motor_noticias.meta.publicador import _buscar_duplicado_ya_publicado
from motor_noticias.models import Estado, Noticia

AHORA = datetime(2026, 10, 9, 10, 30, tzinfo=timezone.utc)
TEXTO = (
    "Clima en Libertador General San Martín: actual 22 °C, mínima 15 °C, "
    "máxima 31 °C. Dólar oficial y blue: compra y venta. Fuentes: Open-Meteo "
    "y DolarApi."
)


def _informe(db, fecha_iso, recoleccion, estado, texto=TEXTO):
    url = f"https://ledesma-participa.local/informe-diario/{fecha_iso}"
    noticia = Noticia(
        id=None, titulo_original=TITULO_INFORME, texto_original=texto,
        url_fuente=url, nombre_fuente=NOMBRE_FUENTE, fecha_fuente="",
        fecha_recoleccion=recoleccion.isoformat(), estado=estado,
        hash_contenido=hash_contenido(TITULO_INFORME, texto + url),
        url_normalizada=normalizar_url(url), territorio="local",
        titulo_preparado=TITULO_INFORME, texto_preparado=texto,
    )
    nid = db.guardar(noticia)
    return dict(id=nid, url_normalizada=noticia.url_normalizada,
                titulo_original=TITULO_INFORME, texto_original=texto,
                nombre_fuente=NOMBRE_FUENTE, estado=estado)


class TestInformeDiarioNoEsDuplicadoDelDeAyer(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_informe_de_hoy_no_se_bloquea_por_el_de_ayer(self):
        _informe(self.db, "2026-10-08", AHORA - timedelta(days=1), Estado.PUBLICADA.value)
        hoy = _informe(self.db, "2026-10-09", AHORA, Estado.PREPARADA.value)
        self.assertIsNone(_buscar_duplicado_ya_publicado(self.db, hoy, AHORA))

    def test_mismo_informe_del_mismo_dia_sigue_bloqueado(self):
        _informe(self.db, "2026-10-09", AHORA - timedelta(minutes=5), Estado.PUBLICADA.value)
        otro = _informe(self.db, "2026-10-09", AHORA, Estado.PREPARADA.value, texto=TEXTO + " Actualizado.")
        self.assertIsNotNone(_buscar_duplicado_ya_publicado(self.db, otro, AHORA))


if __name__ == "__main__":
    unittest.main()
