import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:http/http.dart' as http;

import 'api_service.dart';

/// Medición propia, anónima y agregada de la app (Etapa 3).
///
/// Solo cuenta eventos (app_open, article_open, category_open, radio_play,
/// commercial_open, video_open, share_click…) con una clave de CONTENIDO
/// (id de noticia, slug de categoría, id de radio). Nunca envía datos
/// personales, identificadores de dispositivo ni ubicación, y no usa SDK de
/// terceros ni de publicidad.
///
/// El receptor se lee de `api/medicion.json` (lo escribe el generador del
/// sitio): si no hay endpoint configurado, no se envía nada. Cualquier falla
/// se ignora: la telemetría nunca bloquea ni rompe la app.
class Telemetria {
  Telemetria._();
  static final Telemetria instancia = Telemetria._();

  static final _claveValida = RegExp(r'^[a-z0-9][a-z0-9_\-]{0,79}$');
  static const _maximoLote = 10;

  // En `flutter test` queda apagada (sin red ni timers pendientes) salvo
  // que el test la configure explícitamente.
  bool _habilitada = !Platform.environment.containsKey('FLUTTER_TEST');
  http.Client _cliente = http.Client();
  Future<String?>? _endpoint;
  final List<Map<String, Object>> _pendientes = [];
  Timer? _timer;

  /// Solo para tests.
  void configurarParaPruebas(http.Client cliente, {String? endpoint}) {
    _habilitada = true;
    _cliente = cliente;
    _endpoint = Future.value(endpoint);
    _pendientes.clear();
  }

  List<Map<String, Object>> get pendientes => List.unmodifiable(_pendientes);

  Future<String?> _resolverEndpoint() {
    return _endpoint ??= () async {
      try {
        final r = await _cliente
            .get(Uri.parse('${ApiService.baseSitio}/api/medicion.json'))
            .timeout(const Duration(seconds: 8));
        if (r.statusCode != 200) return null;
        final datos = jsonDecode(utf8.decode(r.bodyBytes));
        final endpoint = datos is Map ? datos['endpoint'] : null;
        return endpoint is String && endpoint.startsWith('https://') ? endpoint : null;
      } catch (_) {
        return null;
      }
    }();
  }

  /// Registra un evento (no bloqueante).
  void evento(String nombre, [Object? clave]) {
    if (!_habilitada) return;
    try {
      var k = (clave ?? '').toString().toLowerCase();
      if (k.isNotEmpty && !_claveValida.hasMatch(k)) k = '';
      _pendientes.add({'e': nombre, 'k': k});
      if (_pendientes.length >= _maximoLote) {
        unawaited(enviar());
      } else {
        _timer ??= Timer(const Duration(seconds: 20), () => unawaited(enviar()));
      }
    } catch (_) {
      // nunca afecta a la app
    }
  }

  Future<void> enviar() async {
    _timer?.cancel();
    _timer = null;
    if (_pendientes.isEmpty) return;
    final lote = List<Map<String, Object>>.from(_pendientes);
    _pendientes.clear();
    try {
      final endpoint = await _resolverEndpoint();
      if (endpoint == null) return;
      await _cliente
          .post(Uri.parse(endpoint), headers: {'Content-Type': 'text/plain'}, body: jsonEncode({'o': 'app', 'eventos': lote}))
          .timeout(const Duration(seconds: 8));
    } catch (_) {
      // sin reintentos: se pierde el lote, nunca se acumula ni bloquea
    }
  }
}
