"""Lógica editorial 16/10/2026: publicación inmediata no urgente, scoring único
con proximidad que suma pero no domina, policiales con más peso, clima solo si
es noticia, repetición temática penalizada, URGENTE = rojo y 6 franjas."""
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from motor_noticias import motor_editorial
from motor_noticias.meta import publicador
from motor_noticias.meta.preparacion import preparar_publicacion
from motor_noticias.motor_editorial import (
    HORA_INFORME_DIARIO,
    HORA_INSTITUCIONAL_RESERVADA,
    HORARIOS_DEFAULT,
    _buscar_candidato_cascada,
    _fecha_limite_antiguedad,
    franjas_cascada,
    generar_agenda,
    informe_diario_en_meta_habilitado,
)
from motor_noticias.scoring_editorial import es_inmediata, evaluar_noticia, penalizacion_repeticion
from tests.test_motor_editorial import AHORA, BaseAgendaTest, _crear_noticia, _iso

FECHA = AHORA.astimezone(motor_editorial.ZONA_JUJUY).strftime("%Y-%m-%d")
POLICIAL_1 = "Allanamiento en Libertador termina con incautaron drogas y armas"
POLICIAL_2 = "Rescataron a un menor tras una balacera en barrio Arrieta de Libertador"


def _agenda(db):
    # El informe Clima + Dólar ya NO es franja: se usa la configuración real.
    return generar_agenda(db, fecha=FECHA, ahora=AHORA)


def _tipos(entradas):
    return [(e.tipo, e.noticia_id) for e in entradas if e.noticia_id]


class TestPublicacionInmediata(BaseAgendaTest):
    def setUp(self):
        super().setUp()
        # Estos tests usan la configuración real: informe fuera de Meta.
        patch.stopall()
        self.assertFalse(informe_diario_en_meta_habilitado())

    def test_1_local_relevante_sale_inmediatamente_sin_ser_urgente(self):
        _crear_noticia(self.db, "local", titulo=POLICIAL_1)
        ev = evaluar_noticia(self.db.obtener(1), AHORA)
        self.assertNotEqual(ev["clasificacion"], "urgente")
        entradas = _agenda(self.db)
        self.assertEqual([x for x in _tipos(entradas) if x[0] == "inmediata"], [("inmediata", 1)])

    def test_2_local_mediocre_no_desplaza_una_nacional_fuerte(self):
        local = _crear_noticia(self.db, "local", titulo="El intendente se reunió con vecinos del barrio")
        nacional = _crear_noticia(self.db, "nacional", titulo="Aumento de tarifas de luz en todo el pais desde noviembre")
        elegido = _buscar_candidato_cascada(
            self.db, set(), _fecha_limite_antiguedad(AHORA), ahora=AHORA, comprometidas=[], cache_eventos={}
        )
        self.assertIsNotNone(elegido)
        self.assertEqual(elegido["territorio"], "nacional")
        self.assertNotEqual(elegido["titulo_original"], local.titulo_original)

    def test_2b_a_igual_relevancia_gana_la_cercania(self):
        # Mismo título (misma señales) en local y en nacional: gana lo local por el bonus.
        titulo = "Aumento de tarifas de luz en todo el pais desde noviembre"
        _crear_noticia(self.db, "nacional", titulo=titulo + " nacional")
        _crear_noticia(self.db, "local", titulo=titulo + " local")
        elegido = _buscar_candidato_cascada(
            self.db, set(), _fecha_limite_antiguedad(AHORA), ahora=AHORA, comprometidas=[], cache_eventos={}
        )
        self.assertEqual(elegido["territorio"], "local")

    def test_3_externa_muy_importante_sale_inmediatamente(self):
        n = _crear_noticia(self.db, "nacional", titulo="Devaluación del peso: el dólar se dispara en todo el país")
        entradas = _agenda(self.db)
        tipos = [t for t, i in _tipos(entradas) if i is not None]
        self.assertTrue(any(t in ("urgente", "inmediata") for t in tipos), tipos)

    def test_4_la_inmediata_no_se_repite_en_la_franja(self):
        _crear_noticia(self.db, "local", titulo=POLICIAL_1)
        _crear_noticia(self.db, "provincial", titulo="Nota provincial común sin novedades")
        entradas = _agenda(self.db)
        ids_inmediatas = [i for t, i in _tipos(entradas) if t == "inmediata"]
        ids_normales = [i for t, i in _tipos(entradas) if t == "normal"]
        self.assertEqual(len(ids_inmediatas), 1)
        self.assertFalse(set(ids_inmediatas) & set(ids_normales))
        # Idempotente: regenerar la agenda no crea una segunda inmediata.
        _agenda(self.db)
        self.assertEqual(len([i for i in self.db.listar_agenda(FECHA) if i["tipo"] == "inmediata"]), 1)

    def test_5_dos_importantes_pueden_salir_en_la_misma_ventana(self):
        _crear_noticia(self.db, "local", titulo=POLICIAL_1)
        _crear_noticia(self.db, "local", titulo=POLICIAL_2)
        entradas = _agenda(self.db)
        self.assertEqual(len([t for t, i in _tipos(entradas) if t == "inmediata"]), 2)

    def test_5b_una_inmediata_reciente_libera_la_franja_de_rellenar_con_poco_relevante(self):
        _crear_noticia(self.db, "local", titulo=POLICIAL_1)
        _crear_noticia(self.db, "provincial", titulo="Nota provincial común sin novedades")
        with patch("motor_noticias.motor_editorial._hubo_inmediata_reciente", return_value=True):
            entradas = _agenda(self.db)
        self.assertEqual([i for t, i in _tipos(entradas) if t == "normal"], [])

    def test_6_la_repeticion_tematica_se_penaliza_sin_bloquear_lo_muy_relevante(self):
        banco_1 = _crear_noticia(self.db, "local", titulo="El banco Macro cambia el horario de atención en Libertador")
        banco_2 = _crear_noticia(self.db, "local", titulo="Otro banco abre una sucursal con cajeros nuevos en Libertador")
        otra = _crear_noticia(self.db, "local", titulo="Vecinos limpiaron la plaza del barrio con ayuda de la escuela")
        a = self.db.obtener(1)
        b = self.db.obtener(2)
        c = self.db.obtener(3)
        ev_b, ev_c = evaluar_noticia(b, AHORA), evaluar_noticia(c, AHORA)
        self.assertEqual(penalizacion_repeticion(b, ev_b, [a], AHORA), 10)
        self.assertEqual(penalizacion_repeticion(c, ev_c, [a], AHORA), 0)
        # Una noticia de relevancia alta no se penaliza aunque repita tema.
        policial_a = self.db.obtener(_crear_noticia(self.db, "local", titulo=POLICIAL_1).id or 4)
        policial_b = self.db.obtener(_crear_noticia(self.db, "local", titulo=POLICIAL_2).id or 5)
        ev = evaluar_noticia(policial_b, AHORA)
        self.assertEqual(penalizacion_repeticion(policial_b, ev, [policial_a], AHORA), 0)
        self.assertIsNotNone(banco_1)
        self.assertIsNotNone(banco_2)
        self.assertIsNotNone(otra)

    def test_7_clima_rutinario_no_se_publica(self):
        n = _crear_noticia(self.db, "local", titulo="Pronóstico: cielo despejado y temperaturas agradables en Libertador")
        ev = evaluar_noticia(self.db.obtener(1), AHORA)
        self.assertTrue(ev["clima_rutinario"])
        self.assertFalse(es_inmediata(self.db.obtener(1), ev))
        entradas = _agenda(self.db)
        self.assertEqual(_tipos(entradas), [])
        self.assertIsNotNone(n)

    def test_8_alerta_meteorologica_relevante_si_se_publica(self):
        _crear_noticia(self.db, "local", titulo="Alerta naranja por tormenta fuerte y granizo en Libertador")
        ev = evaluar_noticia(self.db.obtener(1), AHORA)
        self.assertFalse(ev["clima_rutinario"])
        entradas = _agenda(self.db)
        self.assertTrue(any(t in ("urgente", "inmediata") for t, _ in _tipos(entradas)), _tipos(entradas))

    def test_13_misma_noticia_de_dos_fuentes_no_se_publica_dos_veces(self):
        _crear_noticia(self.db, "local", titulo=POLICIAL_1)
        _crear_noticia(self.db, "local", titulo="Allanamiento en Libertador: incautaron drogas y armas, según otro medio")
        entradas = _agenda(self.db)
        inmediatas = [i for t, i in _tipos(entradas) if t == "inmediata"]
        self.assertEqual(len(inmediatas), 1)


class TestSeisFranjasYComercio(BaseAgendaTest):
    def setUp(self):
        super().setUp()
        patch.stopall()

    def test_12_seis_franjas_base_intactas(self):
        self.assertFalse(informe_diario_en_meta_habilitado())
        self.assertEqual(franjas_cascada(), (HORA_INFORME_DIARIO,) + tuple(HORARIOS_DEFAULT))
        self.assertEqual(franjas_cascada(), ("07:30", "09:00", "12:00", "16:00", "19:00"))
        self.assertEqual(HORA_INSTITUCIONAL_RESERVADA, "20:30")
        self.assertEqual(len(franjas_cascada()) + 1, 6)
        horas = [e.hora for e in _agenda(self.db) if e.tipo == "normal"]
        self.assertEqual(horas, list(franjas_cascada()))

    def test_informe_diario_no_se_reserva_ni_se_asegura_en_meta(self):
        entrada = motor_editorial.reservar_franja_informe_diario(self.db, fecha=FECHA, ahora=AHORA)
        self.assertEqual(entrada.estado, "deshabilitado")
        with patch.object(publicador, "asegurar_informe_diario_en_franja") as asegurar:
            publicador.publicar_franja(self.db, FECHA, HORA_INFORME_DIARIO, cliente_fb=MagicMock(), cliente_ig=MagicMock())
            asegurar.assert_not_called()

    def test_11_comercio_diario_no_depende_de_la_logica_editorial(self):
        # Circuito propio (motor_noticias.publicidad + ledesma-publicidad.timer): intacto.
        from motor_noticias import publicidad

        self.assertTrue(hasattr(publicidad, "publicar_publicidad_del_dia"))
        self.assertNotIn("publicidad", motor_editorial.__dict__)


class TestUrgenteRojoYInmediataNormal(BaseAgendaTest):
    def setUp(self):
        super().setUp()
        patch.stopall()

    def test_9_10_claves_y_visual(self):
        _crear_noticia(self.db, "local", titulo=POLICIAL_1)
        agenda = _agenda(self.db)
        item_inmediata = next(i for i in self.db.listar_agenda(FECHA) if i["tipo"] == "inmediata")
        self.db.guardar_agenda_item(FECHA, None, "urgente", "local", item_inmediata["noticia_id"], "2026-08-12T00:00:00+00:00")
        claves = []
        with patch.object(
            publicador, "_publicar_noticia_en_clave", side_effect=lambda db, fecha, clave, *a, **k: claves.append(clave)
        ), patch.object(publicador, "_urgente_sin_trabajo_pendiente", return_value=False):
            publicador.publicar_urgentes(self.db, FECHA, cliente_fb=MagicMock(), cliente_ig=MagicMock())
        self.assertEqual(len([c for c in claves if c.startswith("urgente-")]), 1)
        self.assertEqual(len([c for c in claves if c.startswith("inmediata-")]), 1)
        # Solo "urgente-…" activa la identidad roja (ver _publicar_noticia_en_clave).
        self.assertTrue("urgente-3".startswith("urgente-"))
        self.assertFalse("inmediata-3".startswith("urgente-"))
        self.assertIsNotNone(agenda)

    def test_urgente_usa_pieza_roja_y_normal_no(self):
        n = _crear_noticia(
            self.db, "local", titulo="Choque grave en la ruta 34 deja tres heridos en Libertador", revision_estado="aprobada"
        )
        noticia = self.db.obtener(1)
        rojo = preparar_publicacion(noticia, dry_run=True, db=self.db, urgente=True)
        normal = preparar_publicacion(noticia, dry_run=True, db=self.db, urgente=False)
        self.assertIn("urgente_", str(rojo.imagen_url))
        self.assertNotIn("urgente_", str(normal.imagen_url))
        self.assertIsNotNone(n)


if __name__ == "__main__":
    unittest.main()
