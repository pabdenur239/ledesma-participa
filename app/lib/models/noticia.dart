/// Modelos de la API de solo lectura del sistema existente (docs/api/*.json,
/// generada por motor_noticias/sitio/generador.py — ver ese archivo para el
/// esquema real). Nunca se inventa ningún campo acá: si la API no lo manda,
/// queda null.
///
/// Etapa 1: cada noticia trae su clasificación separada en TERRITORIO,
/// CATEGORÍA y URGENTE (urgente nunca es una categoría).
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
  // Clasificación (Etapa 1).
  final String? territorio;
  final String? territorioEtiqueta;
  final String? categoriaTema;
  final String? categoriaTemaEtiqueta;
  final String? tituloPlaca;
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
    this.territorio,
    this.territorioEtiqueta,
    this.categoriaTema,
    this.categoriaTemaEtiqueta,
    this.tituloPlaca,
    this.textoParrafos,
    this.fuenteNombre,
    this.fuenteUrl,
  });

  bool get esServicio => categoriaTema == 'servicios';

  factory Noticia.fromJson(Map<String, dynamic> json) {
    final clasificacion = json['clasificacion'] as Map<String, dynamic>?;
    final territorio = clasificacion?['territorio'] as Map<String, dynamic>?;
    return Noticia(
      id: json['id'] as int,
      titulo: (json['titulo'] as String?) ?? '',
      bajada: (json['bajada'] as String?) ?? '',
      imagen: json['imagen'] as String?,
      fecha: json['fecha_iso'] != null ? DateTime.tryParse(json['fecha_iso'] as String) : null,
      fechaLegible: (json['fecha_legible'] as String?) ?? '',
      categoriaSlug: (json['categoria_slug'] as String?) ?? '',
      categoriaEtiqueta: (json['categoria_etiqueta'] as String?) ?? '',
      localidad: json['localidad'] as String?,
      urgente: (json['urgente'] as bool?) ?? false,
      url: (json['url'] as String?) ?? '',
      territorio: territorio?['valor'] as String?,
      territorioEtiqueta: json['territorio_etiqueta'] as String?,
      categoriaTema: json['categoria_tema'] as String?,
      categoriaTemaEtiqueta: json['categoria_tema_etiqueta'] as String?,
      tituloPlaca: json['titulo_placa'] as String?,
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

class DolarCotizacion {
  final double compra;
  final double venta;

  DolarCotizacion({required this.compra, required this.venta});

  static DolarCotizacion? fromJson(Map<String, dynamic>? json) {
    if (json == null) return null;
    return DolarCotizacion(compra: (json['compra'] as num).toDouble(), venta: (json['venta'] as num).toDouble());
  }
}

/// Clima + Dólar del informe de la mañana. Lo que la fuente no entregó
/// llega como null y se muestra "No disponible" (nunca un valor inventado).
class ClimaDolar {
  final String fechaLegible;
  final String actualizado;
  final String fuentes;
  final double? temperaturaActual;
  final double? temperaturaMinima;
  final double? temperaturaMaxima;
  final double? probabilidadLluvia;
  final String? descripcion;
  final DolarCotizacion? oficial;
  final DolarCotizacion? blue;

  ClimaDolar({
    required this.fechaLegible,
    required this.actualizado,
    required this.fuentes,
    this.temperaturaActual,
    this.temperaturaMinima,
    this.temperaturaMaxima,
    this.probabilidadLluvia,
    this.descripcion,
    this.oficial,
    this.blue,
  });

  bool get hayClima => temperaturaActual != null;

  static ClimaDolar? fromJson(Map<String, dynamic>? json) {
    if (json == null) return null;
    final clima = json['clima'] as Map<String, dynamic>?;
    double? numero(String clave) => (clima?[clave] as num?)?.toDouble();
    return ClimaDolar(
      fechaLegible: (json['fecha_legible'] as String?) ?? '',
      actualizado: (json['actualizado'] as String?) ?? '',
      fuentes: (json['fuentes'] as String?) ?? '',
      temperaturaActual: numero('temperatura_actual'),
      temperaturaMinima: numero('temperatura_minima'),
      temperaturaMaxima: numero('temperatura_maxima'),
      probabilidadLluvia: numero('probabilidad_lluvia'),
      descripcion: clima?['descripcion'] as String?,
      oficial: DolarCotizacion.fromJson(json['oficial'] as Map<String, dynamic>?),
      blue: DolarCotizacion.fromJson(json['blue'] as Map<String, dynamic>?),
    );
  }
}

/// GUÍA COMERCIAL LEDESMA PARTICIPA: contenido comercial, separado de las
/// noticias. Campos faltantes = null (no se muestran).
class Comercio {
  final String slug;
  final String nombre;
  final String? rubro;
  final String? descripcion;
  final List<String> imagenes;
  final String? direccion;
  final String? whatsapp;
  final String? telefono;
  final String? instagram;
  final String? facebook;
  final String? horarios;
  final List<String> promociones;
  final String? contactoEtiqueta;
  final String? contactoUrl;
  final String url;

  Comercio({
    required this.slug,
    required this.nombre,
    required this.imagenes,
    required this.promociones,
    required this.url,
    this.rubro,
    this.descripcion,
    this.direccion,
    this.whatsapp,
    this.telefono,
    this.instagram,
    this.facebook,
    this.horarios,
    this.contactoEtiqueta,
    this.contactoUrl,
  });

  factory Comercio.fromJson(Map<String, dynamic> json) {
    final contacto = json['contacto'] as Map<String, dynamic>?;
    return Comercio(
      slug: json['slug'] as String,
      nombre: json['nombre'] as String,
      rubro: json['rubro'] as String?,
      descripcion: json['descripcion'] as String?,
      imagenes: ((json['imagenes'] as List?) ?? []).map((e) => e.toString()).toList(),
      direccion: json['direccion'] as String?,
      whatsapp: json['whatsapp'] as String?,
      telefono: json['telefono'] as String?,
      instagram: json['instagram'] as String?,
      facebook: json['facebook'] as String?,
      horarios: json['horarios'] as String?,
      promociones: ((json['promociones'] as List?) ?? []).map((e) => e.toString()).toList(),
      contactoEtiqueta: contacto?['etiqueta'] as String?,
      contactoUrl: contacto?['url'] as String?,
      url: (json['url'] as String?) ?? '',
    );
  }
}

/// Video de YouTube (reproductor oficial embebido en la página del video
/// en ledesmaparticipa.com.ar). Nunca se descarga.
class Video {
  final String id;
  final String titulo;
  final String? fuente;
  final String miniatura;
  final String url;

  Video({required this.id, required this.titulo, required this.miniatura, required this.url, this.fuente});

  factory Video.fromJson(Map<String, dynamic> json) {
    return Video(
      id: json['id'] as String,
      titulo: json['titulo'] as String,
      fuente: json['fuente'] as String?,
      miniatura: json['miniatura'] as String,
      url: json['url'] as String,
    );
  }
}

class SeccionPortada {
  final String slug;
  final String etiqueta;
  final List<Noticia> noticias;

  SeccionPortada({required this.slug, required this.etiqueta, required this.noticias});
}

/// Portada (api/portada.json): misma estructura y criterio que la web.
class Portada {
  final List<Noticia> urgentes;
  final ClimaDolar? climaDolar;
  final Noticia? principal;
  final List<SeccionPortada> secciones;
  final List<Video> videos;
  final List<Comercio> guiaComercial;

  Portada({
    required this.urgentes,
    required this.climaDolar,
    required this.principal,
    required this.secciones,
    required this.videos,
    required this.guiaComercial,
  });

  factory Portada.fromJson(Map<String, dynamic> json) {
    List<Noticia> noticias(dynamic lista) =>
        ((lista as List?) ?? []).map((e) => Noticia.fromJson(e as Map<String, dynamic>)).toList();
    return Portada(
      urgentes: noticias(json['urgentes']),
      climaDolar: ClimaDolar.fromJson(json['clima_dolar'] as Map<String, dynamic>?),
      principal: json['principal'] != null ? Noticia.fromJson(json['principal'] as Map<String, dynamic>) : null,
      secciones: ((json['secciones'] as List?) ?? [])
          .map((e) => e as Map<String, dynamic>)
          .map((s) => SeccionPortada(
                slug: s['slug'] as String,
                etiqueta: s['etiqueta'] as String,
                noticias: noticias(s['noticias']),
              ))
          .where((s) => s.noticias.isNotEmpty)
          .toList(),
      videos: ((json['videos'] as List?) ?? []).map((e) => Video.fromJson(e as Map<String, dynamic>)).toList(),
      guiaComercial:
          ((json['guia_comercial'] as List?) ?? []).map((e) => Comercio.fromJson(e as Map<String, dynamic>)).toList(),
    );
  }
}
