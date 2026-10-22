import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "produccion_audiovisual" / "piloto_periodistas"))
import validacion_guion as vg  # noqa: E402

T = "Joven motociclista herida debió ser hospitalizada"


def test_guion_valido():
    ok, m = vg.validar_guion(T, ['Fue trasladada al hospital "Oscar Orías", de Libertador.'])
    assert ok, m


def test_rechaza_pie_del_sitio():
    ok, m = vg.validar_guion(T, ["Facebook Instagram Guía Comercial Contacto Privacidad Eliminación de datos Cada nota indica su fuente original y enlaza a ella."])
    assert not ok and any("contaminacion" in x for x in m)


def test_rechaza_sin_cuerpo_o_incompleto_o_repetido():
    assert not vg.validar_guion(T, [])[0]
    assert not vg.validar_guion(T, ["Se trata de una mujer de la zona sur"])[0]
    assert not vg.validar_guion("Tercera fase del Torneo Regional Amateur: partidos de ida", ["En la tercera fase del Torneo Regional Amateur, partidos de ida."])[0]


def test_cierre_es_plantilla_fija():
    assert vg.cierre_institucional() == "Ampliá la información en Ledesma Participa."
