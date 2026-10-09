/// Emisora de RADIOS EN VIVO (Etapa 2) — api/radios.json, generado desde
/// config/radios.json. Solo llegan radios activas con fuente autorizada.
class Emisora {
  final String id;
  final String nombre;
  final String? dial;
  final String? localidad;
  final String zona;
  final String zonaSlug;
  final String? logoUrl;
  final String? streamUrl;
  final String? playerUrl;
  final String? tipoStream;
  final String? sitioWeb;
  final String? facebook;
  final String? instagram;

  /// en_vivo | no_disponible | sin_verificar | sin_transmision
  final String estadoTransmision;
  final String? ultimaVerificacion;

  const Emisora({
    required this.id,
    required this.nombre,
    required this.zona,
    required this.zonaSlug,
    this.dial,
    this.localidad,
    this.logoUrl,
    this.streamUrl,
    this.playerUrl,
    this.tipoStream,
    this.sitioWeb,
    this.facebook,
    this.instagram,
    this.estadoTransmision = 'sin_verificar',
    this.ultimaVerificacion,
  });

  factory Emisora.fromJson(Map<String, dynamic> json) {
    return Emisora(
      id: json['id'] as String,
      nombre: json['nombre'] as String,
      dial: json['dial'] as String?,
      localidad: json['localidad'] as String?,
      zona: json['zona'] as String? ?? '',
      zonaSlug: json['zona_slug'] as String? ?? '',
      logoUrl: json['logo_url'] as String?,
      streamUrl: json['stream_url'] as String?,
      playerUrl: json['player_url'] as String?,
      tipoStream: json['tipo_stream'] as String?,
      sitioWeb: json['sitio_web'] as String?,
      facebook: json['facebook'] as String?,
      instagram: json['instagram'] as String?,
      estadoTransmision: json['estado_transmision'] as String? ?? 'sin_verificar',
      ultimaVerificacion: json['ultima_verificacion'] as String?,
    );
  }

  bool get tieneStream => streamUrl != null && streamUrl!.isNotEmpty;
  bool get soloPlayerOficial => !tieneStream && playerUrl != null && playerUrl!.isNotEmpty;

  /// Texto de estado visible; null cuando no hay nada verificado que decir
  /// (nunca se muestra un EN VIVO sin verificación).
  String? get textoEstado {
    switch (estadoTransmision) {
      case 'en_vivo':
        return 'EN VIVO';
      case 'no_disponible':
        return 'Transmisión no disponible temporalmente';
      case 'sin_transmision':
        return 'Sin transmisión online disponible';
      default:
        return null;
    }
  }
}

/// Zonas base, en el orden en que se muestran (mismo que la web).
const zonasRadio = <(String, String)>[
  ('libertador', 'Libertador'),
  ('ledesma', 'Departamento Ledesma'),
  ('jujuy', 'Jujuy'),
  ('argentina', 'Argentina'),
];
