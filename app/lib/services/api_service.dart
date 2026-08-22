import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/noticia.dart';
import 'cache_service.dart';

/// Cliente de la API pública de solo lectura de Ledesma Participa.
///
/// IMPORTANTE: no es un backend nuevo. Es el mismo sistema existente
/// (el generador del sitio web, motor_noticias/sitio/generador.py) que ya
/// escribe JSON estático junto al HTML del sitio, servido por el mismo
/// hosting (GitHub Pages, mismo dominio que la web). No hay servidor
/// nuevo, no hay credenciales acá: todo lo que se pide es público.
class ApiService {
  static const _baseUrl = 'https://ledesmaparticipa.com.ar/api';
  final http.Client _cliente;
  final CacheService _cache;

  ApiService({http.Client? cliente, CacheService? cache})
      : _cliente = cliente ?? http.Client(),
        _cache = cache ?? CacheService();

  Future<List<Noticia>> _obtenerLista(String ruta, {required String claveCache}) async {
    try {
      final respuesta = await _cliente
          .get(Uri.parse('$_baseUrl/$ruta'))
          .timeout(const Duration(seconds: 12));
      if (respuesta.statusCode != 200) {
        throw Exception('HTTP ${respuesta.statusCode}');
      }
      await _cache.guardar(claveCache, respuesta.body);
      return _parsearLista(respuesta.body);
    } catch (_) {
      // Sin conexión o falla de red: se usa la última copia guardada
      // localmente (si existe) para que la app siga siendo utilizable con
      // mala conexión, en vez de mostrar una pantalla vacía.
      final guardado = await _cache.leer(claveCache);
      if (guardado != null) {
        return _parsearLista(guardado);
      }
      rethrow;
    }
  }

  List<Noticia> _parsearLista(String cuerpo) {
    final datos = jsonDecode(cuerpo) as List;
    return datos.map((e) => Noticia.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<Noticia>> obtenerFeed() => _obtenerLista('feed.json', claveCache: 'feed');

  Future<List<Noticia>> obtenerUrgentes() => _obtenerLista('urgentes.json', claveCache: 'urgentes');

  Future<List<Noticia>> obtenerCategoria(String slug) =>
      _obtenerLista('categoria/$slug.json', claveCache: 'categoria_$slug');

  Future<List<Categoria>> obtenerCategorias() async {
    final respuesta = await _cliente
        .get(Uri.parse('$_baseUrl/categorias.json'))
        .timeout(const Duration(seconds: 12));
    final datos = jsonDecode(respuesta.body) as List;
    return datos.map((e) => Categoria.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Noticia> obtenerDetalle(int id) async {
    final respuesta = await _cliente
        .get(Uri.parse('$_baseUrl/noticia/$id.json'))
        .timeout(const Duration(seconds: 12));
    if (respuesta.statusCode != 200) {
      throw Exception('HTTP ${respuesta.statusCode}');
    }
    return Noticia.fromJson(jsonDecode(respuesta.body) as Map<String, dynamic>);
  }
}
