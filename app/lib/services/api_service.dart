import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/noticia.dart';
import '../models/radio.dart';
import 'cache_service.dart';

/// Cliente de la API pública de solo lectura de Ledesma Participa.
///
/// IMPORTANTE: no es un backend nuevo. Es el mismo sistema existente
/// (el generador del sitio web, motor_noticias/sitio/generador.py) que ya
/// escribe JSON estático junto al HTML del sitio, servido por el mismo
/// hosting (GitHub Pages, mismo dominio que la web). Web y app consumen la
/// misma fuente lógica de contenido y clasificación.
class ApiService {
  static const baseSitio = 'https://ledesmaparticipa.com.ar';
  static const _baseUrl = '$baseSitio/api';
  final http.Client _cliente;
  final CacheService _cache;

  ApiService({http.Client? cliente, CacheService? cache})
      : _cliente = cliente ?? http.Client(),
        _cache = cache ?? CacheService();

  /// GET con caché local: sin conexión se usa la última copia guardada,
  /// para que la app siga siendo útil con mala señal.
  Future<String> _obtener(String ruta, {required String claveCache}) async {
    try {
      final respuesta = await _cliente.get(Uri.parse('$_baseUrl/$ruta')).timeout(const Duration(seconds: 12));
      if (respuesta.statusCode != 200) {
        throw Exception('HTTP ${respuesta.statusCode}');
      }
      final cuerpo = utf8.decode(respuesta.bodyBytes);
      await _cache.guardar(claveCache, cuerpo);
      return cuerpo;
    } catch (_) {
      final guardado = await _cache.leer(claveCache);
      if (guardado != null) return guardado;
      rethrow;
    }
  }

  /// Antigüedad máxima del contenido que la app muestra como normal, por
  /// la política de Google Play "News and Magazines" (contenido reciente,
  /// menos de 3 meses). El backend ya excluye lo más viejo de las listas
  /// de la API; este filtro es una segunda barrera en el cliente por si
  /// llega contenido viejo desde la caché local.
  static const _antiguedadMaxima = Duration(days: 90);

  Future<List<Noticia>> _obtenerLista(String ruta, {required String claveCache}) async {
    return _parsearLista(await _obtener(ruta, claveCache: claveCache));
  }

  List<Noticia> _parsearLista(String cuerpo) {
    final datos = jsonDecode(cuerpo) as List;
    final items = datos.map((e) => Noticia.fromJson(e as Map<String, dynamic>)).toList();
    final limite = DateTime.now().subtract(_antiguedadMaxima);
    return items.where((n) => n.fecha != null && n.fecha!.isAfter(limite)).toList();
  }

  Future<Portada> obtenerPortada() async {
    final datos = jsonDecode(await _obtener('portada.json', claveCache: 'portada')) as Map<String, dynamic>;
    return Portada.fromJson(datos);
  }

  /// Últimas (cronológico, lo más nuevo primero).
  Future<List<Noticia>> obtenerFeed() => _obtenerLista('feed.json', claveCache: 'feed');

  Future<List<Noticia>> obtenerUrgentes() => _obtenerLista('urgentes.json', claveCache: 'urgentes');

  Future<List<Noticia>> obtenerCategoria(String slug) =>
      _obtenerLista('categoria/$slug.json', claveCache: 'categoria_$slug');

  Future<List<Categoria>> obtenerCategorias() async {
    final datos = jsonDecode(await _obtener('categorias.json', claveCache: 'categorias')) as List;
    return datos.map((e) => Categoria.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<Comercio>> obtenerGuiaComercial() async {
    final datos = jsonDecode(await _obtener('guia_comercial.json', claveCache: 'guia')) as List;
    return datos.map((e) => Comercio.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<Video>> obtenerVideos() async {
    final datos = jsonDecode(await _obtener('videos.json', claveCache: 'videos')) as List;
    return datos.map((e) => Video.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Radios en vivo (Etapa 2). Sin zona: todas las activas
  /// (api/radios.json); con zona: api/radios/zona/<slug>.json.
  Future<List<Emisora>> obtenerRadios({String? zona}) async {
    final ruta = zona == null ? 'radios.json' : 'radios/zona/$zona.json';
    final datos = jsonDecode(await _obtener(ruta, claveCache: zona == null ? 'radios' : 'radios_$zona')) as List;
    return datos.map((e) => Emisora.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Noticia> obtenerDetalle(int id) async {
    final respuesta = await _cliente.get(Uri.parse('$_baseUrl/noticia/$id.json')).timeout(const Duration(seconds: 12));
    if (respuesta.statusCode != 200) {
      throw Exception('HTTP ${respuesta.statusCode}');
    }
    return Noticia.fromJson(jsonDecode(utf8.decode(respuesta.bodyBytes)) as Map<String, dynamic>);
  }
}
