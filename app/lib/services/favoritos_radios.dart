import 'package:shared_preferences/shared_preferences.dart';

/// Favoritos de radios: solo en el dispositivo (SharedPreferences, ya usado
/// por la caché). Sin cuentas ni backend de usuarios.
class FavoritosRadios {
  static const _clave = 'radios_favoritas';

  Future<Set<String>> leer() async {
    final prefs = await SharedPreferences.getInstance();
    return (prefs.getStringList(_clave) ?? const []).toSet();
  }

  Future<Set<String>> alternar(String id) async {
    final prefs = await SharedPreferences.getInstance();
    final actuales = (prefs.getStringList(_clave) ?? const []).toSet();
    if (!actuales.remove(id)) actuales.add(id);
    await prefs.setStringList(_clave, actuales.toList()..sort());
    return actuales;
  }
}
