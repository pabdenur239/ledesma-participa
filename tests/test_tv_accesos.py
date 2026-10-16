import json
import tempfile
import unittest
from pathlib import Path

from motor_noticias import radios
from motor_noticias.sitio import plantillas, tv

CONFIG_SITIO = {"descripcion": "d", "email_contacto": "a@b.c", "base_url_produccion": "https://x.test"}


class TestTV(unittest.TestCase):
    def test_config_real_jujuy_y_nacionales(self):
        grupos = {g["region_id"]: g["canales"] for g in tv.cargar_canales()}
        self.assertEqual(len(grupos["jujuy"]), 1)
        self.assertEqual(len(grupos["nacionales"]), 6)

    def test_canal_inactivo_o_invalido_no_se_muestra(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tv.json"
            p.write_text(json.dumps({
                "regiones": [{"id": "jujuy", "etiqueta": "Jujuy"}],
                "canales": [
                    {"nombre": "A", "region": "jujuy", "tipo": "youtube", "fuente": "UCj6PcyLvpnIRT_2W_mwa9Aw", "activa": False},
                    {"nombre": "B", "region": "jujuy", "tipo": "iframe", "fuente": "http://inseguro", "activa": True},
                    {"nombre": "C", "region": "jujuy", "tipo": "youtube", "fuente": "no-es-un-id", "activa": True},
                    {"nombre": "D", "region": "jujuy", "tipo": "iframe", "fuente": "https://ok/player", "activa": True},
                ]}), encoding="utf-8")
            grupos = tv.cargar_canales(p)
            self.assertEqual([c["nombre"] for c in grupos[0]["canales"]], ["D"])

    def test_pagina_tv_y_accesos(self):
        html = tv.pagina_tv(grupos=tv.cargar_canales(), ruta_raiz="../", config_sitio=CONFIG_SITIO, url_base="https://x.test/tv/")
        self.assertIn("TV en vivo", html)
        self.assertIn('data-fuente="https://arcast.com.ar/canal7jujuy/"', html)
        self.assertIn("assets/tv.js", html)
        accesos = plantillas.bloque_accesos([("tv/", "x", "TV en vivo", "d"), ("guia-comercial/", "y", "Guía Comercial", "d")])
        self.assertIn('href="tv/"', accesos)
        self.assertEqual(plantillas.bloque_accesos([]), "")


class TestPadronRadios(unittest.TestCase):
    def test_diez_activas_con_orion_y_zonas_validas(self):
        activas = radios.cargar_radios(incluir_demo=False)
        self.assertEqual(len(activas), 10)
        orion = [r for r in activas if r["id"] == "fm-orion-106-3"]
        self.assertEqual(orion[0]["zona"], "Libertador")
        self.assertTrue(orion[0]["stream_url"].startswith("https://"))
        self.assertEqual(orion[0]["tipo_stream"], "aac")
        for r in activas:
            self.assertIn(r["zona"], radios.SLUG_ZONA)
            self.assertTrue(r["stream_url"] or r["player_url"])

    def test_inactivas_documentan_motivo(self):
        crudo = json.loads((Path(radios.RAIZ) / "config" / "radios.json").read_text(encoding="utf-8-sig"))
        for r in crudo["radios"]:
            if r["activa"] is False:
                self.assertTrue(r.get("motivo_inactiva"), r["id"])


if __name__ == "__main__":
    unittest.main()
