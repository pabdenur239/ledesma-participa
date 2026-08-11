import unittest

from motor_noticias.meta.contenido import ContenidoFacebook
from motor_noticias.meta.preparacion import ErrorPreparacionFacebook, preparar_publicacion


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
    )
    base.update(overrides)
    return base


class TestPrepararPublicacion(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
