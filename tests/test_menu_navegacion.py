import re
import unittest

from motor_noticias.sitio import plantillas

EXTRAS = [
    ("videos", "Videos", "videos/"),
    ("radios", "Radios en vivo", "radios/"),
    ("tv", "TV en vivo", "tv/"),
    ("multimedia", "Multimedia", "multimedia/"),
    ("guia-comercial", "Guía Comercial", "guia-comercial/"),
]


def _menu(seccion_activa=None, nav=None, extras=None):
    html = plantillas.encabezado_html(
        ruta_raiz="../", seccion_activa=seccion_activa,
        nav=plantillas.SECCIONES_NAV if nav is None else nav, extras=EXTRAS if extras is None else extras,
    )
    return html[html.index('<div class="nav-pista">'):html.index("</nav>")]


class TestMenuNavegacion(unittest.TestCase):
    def test_visibles_en_escritorio_y_agrupacion(self):
        menu = _menu()
        sueltos = re.sub(r"<details.*?</details>", "", menu, flags=re.S)
        self.assertEqual(
            re.findall(r">([^<]+)</a>", sueltos), ["Últimas", "Libertador", "Ledesma", "Jujuy", "Policiales"]
        )
        grupos = {m.group(1): m.group(0) for m in re.finditer(r"<summary[^>]*>([^<]+)</summary>.*?</details>", menu, re.S)}
        self.assertEqual(list(grupos), ["En vivo", "Servicios", "Más"])
        for etiqueta in ("Radios en vivo", "TV en vivo", "Multimedia"):
            self.assertIn(etiqueta, grupos["En vivo"])
        for etiqueta in ("Salud", "Deportes", "Guía Comercial"):
            self.assertIn(etiqueta, grupos["Servicios"])
        for etiqueta in ("Nacional", "Internacional", "Espectáculos", "Gastronomía"):
            self.assertIn(etiqueta, grupos["Más"])

    def test_mobile_solo_cinco_visibles_y_el_resto_dentro_de_mas(self):
        menu = _menu()
        # Visibles en celular = sin la clase solo-escritorio y fuera de los menús.
        sueltos = re.sub(r"<details.*?</details>", "", menu, flags=re.S)
        visibles = [t for h, c, t in re.findall(r'<a href="([^"]+)"(?: class="([^"]*)")?>([^<]+)</a>', sueltos) if "solo-escritorio" not in (c or "")]
        self.assertEqual(visibles, ["Últimas", "Libertador", "Policiales"])
        self.assertNotIn("solo-escritorio", re.search(r"<details class=\"nav-grupo\"><summary[^>]*>En vivo", menu).group(0))
        self.assertIn('<details class="nav-grupo solo-escritorio"><summary', menu)  # Servicios: oculto en celular
        mas = re.search(r'<details class="nav-grupo nav-mas">.*?</details>', menu, re.S).group(0)
        movil = re.findall(r'class="solo-movil[^"]*"[^>]*>([^<]+)<', mas)
        for etiqueta in ("Ledesma", "Jujuy", "Salud", "Deportes", "Servicios", "Guía Comercial"):
            self.assertIn(etiqueta, movil)

    def test_ninguna_categoria_ni_seccion_queda_inaccesible(self):
        menu = _menu()
        hrefs = set(re.findall(r'<a href="([^"]+)"', menu))
        for slug, _ in plantillas.SECCIONES_NAV:
            self.assertIn(f"../categoria/{slug}/", hrefs, slug)
        for _, _, ruta in EXTRAS:
            self.assertIn(f"../{ruta}", hrefs, ruta)

    def test_rutas_actuales_sin_cambios_y_secciones_vacias_no_aparecen(self):
        menu = _menu(nav=[("ultimas", "Últimas"), ("libertador", "Libertador")], extras=[("multimedia", "Multimedia", "multimedia/")])
        self.assertIn('href="../categoria/libertador/"', menu)
        self.assertNotIn("Servicios", menu)  # sin salud/deportes/guía no hay grupo vacío
        self.assertIn("En vivo", menu)

    def test_seccion_activa_resalta_su_grupo(self):
        self.assertRegex(_menu("tv"), r'<summary class="activa">En vivo')
        self.assertRegex(_menu("salud"), r'<summary class="activa">Servicios')
        self.assertRegex(_menu("nacionales"), r'<summary class="activa">Más')

    def test_un_solo_nivel_de_submenu(self):
        menu = _menu()
        self.assertNotIn("<details", re.search(r'<div class="nav-menu">.*?</div>', menu, re.S).group(0))


if __name__ == "__main__":
    unittest.main()
