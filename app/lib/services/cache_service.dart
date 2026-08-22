import 'package:shared_preferences/shared_preferences.dart';

/// Guarda temporalmente la última respuesta cruda (JSON) de cada endpoint
/// para mejorar la experiencia con mala conexión: si una petición falla,
/// se muestra la última copia conocida en vez de una pantalla vacía. Nunca
/// se usa para nada que no sea contenido ya público.
class CacheService {
  static const _prefijo = 'cache_api_';

  Future<void> guardar(String clave, String contenido) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('$_prefijo$clave', contenido);
  }

  Future<String?> leer(String clave) async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('$_prefijo$clave');
  }
}
