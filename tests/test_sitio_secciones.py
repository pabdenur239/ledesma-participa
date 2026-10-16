import json
import re
import tempfile
import unittest
from pathlib import Path

from motor_noticias.sitio import secciones
from motor_noticias.sitio.generador import generar_sitio
from motor_noticias.db import Database

CONFIG_SITIO = {"descripcion": "d", "email_contacto": "a@b.c", "base_url_produccion": "https://x.test"}
RAIZ = Path(__file__).resolve().parent.parent


class SeccionesTest(unittest.TestCase):
    def test_radios_activas_son_validas_e_incluyen_orion(self):
        activas = secciones.radios_activas()
        todas = [r for lista in activas.values() for r in lista]
        self.assertEqual(len(todas), 10)
        orion = [r for r in activas["localidad"] if r["id"] == "fm-orion-106-3"]
        self.assertEqual(len(orion), 1)
        for r in todas:
            if r["tipo"] == "audio":
                self.assertTrue(r["fuente"].startswith("https://"))

    def test_radio_inactiva_o_insegura_no_se_muestra(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "radios.json").write_text(json.dumps({
                "ambitos": [{"id": "localidad", "etiqueta": "Localidad"}],
                "radios": [
                    {"id": "a", "nombre": "A", "ambito": "localidad", "activa": False, "tipo": "audio", "fuente": "https://ok"},
                    {"id": "b", "nombre": "B", "ambito": "localidad", "activa": True, "tipo": "audio", "fuente": "http://inseguro"},
                    {"id": "c", "nombre": "C", "ambito": "localidad", "activa": True, "tipo": "audio", "fuente": "https://ok/stream"},
                ]}), encoding="utf-8")
            activas = secciones.radios_activas(Path(d))
            self.assertEqual([r["id"] for r in activas["localidad"]], ["c"])

    def test_tv_jujuy_y_nacionales(self):
        activos = secciones.canales_activos()
        self.assertEqual(len(activos["jujuy"]), 1)
        self.assertEqual(len(activos["nacionales"]), 6)

    def test_sitio_generado_tiene_secciones_y_ficha(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "t.db"
            Database(db).close()
            salida = Path(d) / "salida"
            generar_sitio(db, salida, base_url="https://x.test")
            for ruta in ("radio", "tv", "multimedia", "guia", "guia/dosis-jeans"):
                self.assertTrue((salida / ruta / "index.html").is_file(), ruta)
            portada = (salida / "index.html").read_text(encoding="utf-8")
            for destino in ("radio/", "tv/", "multimedia/", "guia/"):
                self.assertIn(f'href="{destino}"', portada)
            self.assertIn('data-geo="libertador"', portada)
            self.assertIn('data-tema="policiales"', portada)
            self.assertNotIn("Google Play", portada)
            ficha = (salida / "guia/dosis-jeans/index.html").read_text(encoding="utf-8")
            self.assertIn("wa.me/5493886576721", ficha)
            self.assertIn("Tucumán 314", ficha)
            for src in re.findall(r'src="(\.\./\.\./assets/guia/[^"]+)"', ficha):
                self.assertTrue((salida / "guia/dosis-jeans" / src).resolve().is_file(), src)


if __name__ == "__main__":
    unittest.main()
