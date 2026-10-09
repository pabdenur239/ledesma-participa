import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:just_audio/just_audio.dart';

import '../models/radio.dart';

/// Motor de audio mínimo (permite probar el reproductor con un mock, sin red
/// ni radios reales).
abstract class MotorAudio {
  Future<void> cargar(String url);
  Future<void> reproducir();
  Future<void> pausar();
  Future<void> detener();
  Future<void> volumen(double valor);
}

/// just_audio (ExoPlayer en Android): reproduce directamente la URL oficial
/// de la emisora; no graba ni descarga.
class MotorJustAudio implements MotorAudio {
  final AudioPlayer _player = AudioPlayer();

  @override
  Future<void> cargar(String url) async {
    await _player.setUrl(url);
  }

  @override
  Future<void> reproducir() async {
    // play() completa recién al pausar: no se espera para no bloquear la UI.
    unawaited(_player.play());
  }

  @override
  Future<void> pausar() => _player.pause();

  @override
  Future<void> detener() => _player.stop();

  @override
  Future<void> volumen(double valor) => _player.setVolume(valor);
}

enum EstadoReproductor { detenido, conectando, sonando, pausado, error }

/// Reproductor único de la app: vive por encima del Navigator (ver
/// main.dart), así que el audio sigue sonando al cambiar de pantalla.
class ReproductorRadio extends ChangeNotifier {
  ReproductorRadio({MotorAudio? motor}) : _motorInyectado = motor;

  static final ReproductorRadio instancia = ReproductorRadio();

  final MotorAudio? _motorInyectado;
  MotorAudio? _motorPerezoso;
  MotorAudio get _motor => _motorInyectado ?? (_motorPerezoso ??= MotorJustAudio());

  Emisora? _radio;
  EstadoReproductor _estado = EstadoReproductor.detenido;

  Emisora? get radio => _radio;
  EstadoReproductor get estado => _estado;
  bool get sonando => _estado == EstadoReproductor.sonando;
  bool get visible => _radio != null;

  String get mensaje {
    switch (_estado) {
      case EstadoReproductor.conectando:
        return 'Conectando…';
      case EstadoReproductor.sonando:
        return 'En vivo';
      case EstadoReproductor.pausado:
        return 'En pausa';
      case EstadoReproductor.error:
        return 'Transmisión no disponible temporalmente';
      case EstadoReproductor.detenido:
        return '';
    }
  }

  void _cambiar(EstadoReproductor e) {
    _estado = e;
    notifyListeners();
  }

  Future<void> reproducir(Emisora radio) async {
    if (!radio.tieneStream) return;
    if (_radio?.id == radio.id && sonando) return;
    _radio = radio;
    _cambiar(EstadoReproductor.conectando);
    try {
      await _motor.cargar(radio.streamUrl!);
      await _motor.reproducir();
      if (_radio?.id == radio.id) _cambiar(EstadoReproductor.sonando);
    } catch (_) {
      if (_radio?.id == radio.id) _cambiar(EstadoReproductor.error);
    }
  }

  Future<void> pausar() async {
    if (_radio == null) return;
    await _motor.pausar();
    _cambiar(EstadoReproductor.pausado);
  }

  /// Play/Pausa. Al reanudar se reconecta: es una transmisión en vivo.
  Future<void> alternar() async {
    final actual = _radio;
    if (actual == null) return;
    if (sonando) return pausar();
    _radio = null;
    await reproducir(actual);
  }

  Future<void> volumen(double valor) => _motor.volumen(valor.clamp(0.0, 1.0));

  Future<void> cerrar() async {
    _radio = null;
    _cambiar(EstadoReproductor.detenido);
    try {
      await _motor.detener();
    } catch (_) {}
  }
}
