/// Representa una noticia tal como la expone la API de solo lectura del
/// sistema existente (docs/api/*.json, generada por
/// motor_noticias/sitio/generador.py — ver ese archivo para el esquema
/// real). Nunca se inventa ningún campo acá: si la API no lo manda, queda
/// null.
class Noticia {
  final int id;
  final String titulo;
  final String bajada;
  final String? imagen;
  final DateTime? fecha;
  final String fechaLegible;
  final String categoriaSlug;
  final String categoriaEtiqueta;
  final String? localidad;
  final bool urgente;
  final String url;
  // Solo presentes en el detalle (api/noticia/{id}.json).
  final List<String>? textoParrafos;
  final String? fuenteNombre;
  final String? fuenteUrl;

  Noticia({
    required this.id,
    required this.titulo,
    required this.bajada,
    required this.imagen,
    required this.fecha,
    required this.fechaLegible,
    required this.categoriaSlug,
    required this.categoriaEtiqueta,
    required this.localidad,
    required this.urgente,
    required this.url,
    this.textoParrafos,
    this.fuenteNombre,
    this.fuenteUrl,
  });

  factory Noticia.fromJson(Map<String, dynamic> json) {
    return Noticia(
      id: json['id'] as int,
      titulo: (json['titulo'] as String?) ?? '',
      bajada: (json['bajada'] as String?) ?? '',
      imagen: json['imagen'] as String?,
      fecha: json['fecha_iso'] != null
          ? DateTime.tryParse(json['fecha_iso'] as String)
          : null,
      fechaLegible: (json['fecha_legible'] as String?) ?? '',
      categoriaSlug: (json['categoria_slug'] as String?) ?? '',
      categoriaEtiqueta: (json['categoria_etiqueta'] as String?) ?? '',
      localidad: json['localidad'] as String?,
      urgente: (json['urgente'] as bool?) ?? false,
      url: (json['url'] as String?) ?? '',
      textoParrafos: (json['texto_parrafos'] as List?)?.map((e) => e.toString()).toList(),
      fuenteNombre: json['fuente_nombre'] as String?,
      fuenteUrl: json['fuente_url'] as String?,
    );
  }
}

class Categoria {
  final String slug;
  final String etiqueta;
  final int cantidad;

  Categoria({required this.slug, required this.etiqueta, required this.cantidad});

  factory Categoria.fromJson(Map<String, dynamic> json) {
    return Categoria(
      slug: json['slug'] as String,
      etiqueta: json['etiqueta'] as String,
      cantidad: (json['cantidad'] as int?) ?? 0,
    );
  }
}
