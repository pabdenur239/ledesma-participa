import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ledesma_participa_app/services/telemetria.dart';

void main() {
  test('envía solo eventos agregados con clave de contenido, sin datos personales', () async {
    final enviados = <Map<String, dynamic>>[];
    final cliente = MockClient((pedido) async {
      enviados.add(jsonDecode(pedido.body) as Map<String, dynamic>);
      return http.Response('', 204);
    });
    final t = Telemetria.instancia..configurarParaPruebas(cliente, endpoint: 'https://m.test/e');
    t.evento('article_open', 123);
    t.evento('radio_play', 'radio-city-ledesma');
    t.evento('share_click', 'Juan Pérez 3884123456');
    await t.enviar();

    expect(enviados, hasLength(1));
    expect(enviados.first['o'], 'app');
    final eventos = (enviados.first['eventos'] as List).cast<Map<String, dynamic>>();
    expect(eventos.map((e) => e['k']), ['123', 'radio-city-ledesma', '']);
    for (final e in eventos) {
      expect(e.keys.toSet(), {'e', 'k'});
    }
  });

  test('sin endpoint no envía nada y nunca lanza', () async {
    var llamadas = 0;
    final cliente = MockClient((_) async {
      llamadas++;
      throw Exception('sin red');
    });
    final t = Telemetria.instancia..configurarParaPruebas(cliente);
    t.evento('app_open');
    await t.enviar();
    expect(llamadas, 0);

    t.configurarParaPruebas(cliente, endpoint: 'https://m.test/e');
    t.evento('app_open');
    await t.enviar(); // la falla de red se ignora
    expect(t.pendientes, isEmpty);
  });
}
