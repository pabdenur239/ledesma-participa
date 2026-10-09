// Radios en vivo (Etapa 2): modelo, reproductor (motor de audio simulado,
// nunca radios reales ni red), pantalla con filtro por zona, fallback sin
// stream, favoritos locales y mini reproductor persistente al navegar.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ledesma_participa_app/models/radio.dart';
import 'package:ledesma_participa_app/screens/radios_screen.dart';
import 'package:ledesma_participa_app/services/api_service.dart';
import 'package:ledesma_participa_app/services/reproductor_radio.dart';
import 'package:ledesma_participa_app/widgets/mini_reproductor.dart';

class MotorFalso implements MotorAudio {
  final bool falla;
  final acciones = <String>[];

  MotorFalso({this.falla = false});

  @override
  Future<void> cargar(String url) async {
    acciones.add('cargar $url');
    if (falla) throw Exception('stream inválido');
  }

  @override
  Future<void> reproducir() async => acciones.add('play');

  @override
  Future<void> pausar() async => acciones.add('pausa');

  @override
  Future<void> detener() async => acciones.add('stop');

  @override
  Future<void> volumen(double valor) async => acciones.add('volumen $valor');
}

Map<String, dynamic> _json(String id, String zona, String zonaSlug, {String? stream, String? player, String estado = 'sin_verificar'}) => {
      'id': id,
      'nombre': 'Radio $id',
      'dial': '95.5 FM',
      'localidad': 'Libertador General San Martín',
      'zona': zona,
      'zona_slug': zonaSlug,
      'stream_url': stream,
      'player_url': player,
      'estado_transmision': estado,
    };

final _radiosJson = [
  _json('uno', 'Libertador', 'libertador', stream: 'https://stream.test/uno.mp3', estado: 'en_vivo'),
  _json('dos', 'Jujuy', 'jujuy', stream: 'https://stream.test/dos.mp3', estado: 'no_disponible'),
  _json('tres', 'Argentina', 'argentina', estado: 'sin_transmision'),
];

ApiService _apiFalsa() => ApiService(
      cliente: MockClient((pedido) async {
        if (pedido.url.path.endsWith('/api/radios.json')) {
          return http.Response.bytes(utf8.encode(jsonEncode(_radiosJson)), 200);
        }
        return http.Response('no', 404);
      }),
    );

Widget _app(Widget home, ReproductorRadio reproductor) => MaterialApp(
      home: home,
      builder: (context, child) => Column(children: [Expanded(child: child!), MiniReproductor(reproductor: reproductor)]),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('Emisora lee la API y no inventa estados', () {
    final r = Emisora.fromJson(_radiosJson[0]);
    expect(r.tieneStream, isTrue);
    expect(r.textoEstado, 'EN VIVO');
    final sinVerificar = Emisora.fromJson(_json('x', 'Jujuy', 'jujuy', stream: 'https://s.test/x'));
    expect(sinVerificar.textoEstado, isNull);
    final soloPlayer = Emisora.fromJson(_json('p', 'Jujuy', 'jujuy', player: 'https://radio.test/player'));
    expect(soloPlayer.soloPlayerOficial, isTrue);
    expect(Emisora.fromJson(_radiosJson[2]).textoEstado, 'Sin transmisión online disponible');
  });

  test('Reproductor: play, pausa, reanudar y cerrar', () async {
    final motor = MotorFalso();
    final rep = ReproductorRadio(motor: motor);
    final radio = Emisora.fromJson(_radiosJson[0]);
    await rep.reproducir(radio);
    expect(rep.sonando, isTrue);
    expect(rep.mensaje, 'En vivo');
    await rep.alternar();
    expect(rep.estado, EstadoReproductor.pausado);
    await rep.alternar();
    expect(rep.sonando, isTrue);
    await rep.cerrar();
    expect(rep.visible, isFalse);
    expect(motor.acciones, [
      'cargar https://stream.test/uno.mp3', 'play', 'pausa', 'cargar https://stream.test/uno.mp3', 'play', 'stop',
    ]);
  });

  test('Reproductor: stream inválido muestra no disponible', () async {
    final rep = ReproductorRadio(motor: MotorFalso(falla: true));
    await rep.reproducir(Emisora.fromJson(_radiosJson[0]));
    expect(rep.estado, EstadoReproductor.error);
    expect(rep.mensaje, 'Transmisión no disponible temporalmente');
  });

  test('Reproductor: sin stream no reproduce nada', () async {
    final motor = MotorFalso();
    final rep = ReproductorRadio(motor: motor);
    await rep.reproducir(Emisora.fromJson(_radiosJson[2]));
    expect(rep.visible, isFalse);
    expect(motor.acciones, isEmpty);
  });

  testWidgets('Listado, filtro por zona, fallback y favoritas', (tester) async {
    final rep = ReproductorRadio(motor: MotorFalso());
    await tester.pumpWidget(_app(RadiosScreen(api: _apiFalsa(), reproductor: rep), rep));
    await tester.pumpAndSettle();

    expect(find.text('RADIO UNO'), findsOneWidget);
    expect(find.text('RADIO DOS'), findsOneWidget);
    expect(find.text('● EN VIVO'), findsOneWidget);
    expect(find.text('Transmisión no disponible temporalmente'), findsOneWidget);
    expect(find.text('Sin transmisión online disponible'), findsOneWidget);
    expect(find.byKey(const Key('escuchar-tres')), findsNothing, reason: 'sin stream no hay botón');

    await tester.tap(find.widgetWithText(ChoiceChip, 'Jujuy'));
    await tester.pumpAndSettle();
    expect(find.text('RADIO UNO'), findsNothing);
    expect(find.text('RADIO DOS'), findsOneWidget);

    await tester.tap(find.widgetWithText(ChoiceChip, 'Todas'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Agregar a favoritas').first);
    await tester.pumpAndSettle();
    expect((await SharedPreferences.getInstance()).getStringList('radios_favoritas'), ['uno']);
    await tester.tap(find.widgetWithText(ChoiceChip, 'Favoritas'));
    await tester.pumpAndSettle();
    expect(find.text('RADIO UNO'), findsOneWidget);
    expect(find.text('RADIO DOS'), findsNothing);
  });

  testWidgets('El audio sigue al navegar: mini reproductor persistente', (tester) async {
    final rep = ReproductorRadio(motor: MotorFalso());
    await tester.pumpWidget(_app(RadiosScreen(api: _apiFalsa(), reproductor: rep), rep));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('escuchar-uno')));
    await tester.pumpAndSettle();
    expect(rep.sonando, isTrue);
    expect(find.text('Radio uno · 95.5 FM'), findsOneWidget);
    expect(find.text('PAUSA'), findsOneWidget);

    // Abre la ficha (otra pantalla) y vuelve: el reproductor sigue.
    await tester.tap(find.text('RADIO DOS'));
    await tester.pumpAndSettle();
    expect(find.byType(RadioDetalleScreen), findsOneWidget);
    expect(find.text('Radio uno · 95.5 FM'), findsOneWidget);
    expect(rep.sonando, isTrue);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(rep.sonando, isTrue);

    await tester.tap(find.byKey(const Key('mini-play')));
    await tester.pumpAndSettle();
    expect(rep.estado, EstadoReproductor.pausado);
    expect(find.text('En pausa'), findsOneWidget);
    await tester.tap(find.byKey(const Key('mini-cerrar')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('mini-play')), findsNothing);
  });

  testWidgets('Sin radios cargadas: mensaje, sin datos inventados', (tester) async {
    final api = ApiService(cliente: MockClient((_) async => http.Response('[]', 200)));
    final rep = ReproductorRadio(motor: MotorFalso());
    await tester.pumpWidget(_app(RadiosScreen(api: api, reproductor: rep), rep));
    await tester.pumpAndSettle();
    expect(find.textContaining('Estamos sumando las radios'), findsOneWidget);
  });
}
