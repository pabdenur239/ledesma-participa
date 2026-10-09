import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

/// Identidad Versión C (Etapa 1) — la misma que la web y las placas de
/// Meta (motor_noticias/meta/identidad_visual.py, docs/assets/site.css):
/// carbón + dorado como marca, blanco para leer; ROJO solo para urgente y
/// VERDE para servicios.
class MarcaColores {
  static const fondo = Color(0xFF111111);
  static const marcaFondo = Color(0xFF1C1B18);
  static const marcaOro = Color(0xFFD4AF37);
  static const textoSuave = Color(0xFFCFCAC0);
  static const tarjeta = Color(0xFF1C1B18);
  static const urgente = Color(0xFFC8102E);
  static const servicio = Color(0xFF1E8E3E);
  // Nombre anterior, conservado para no romper referencias.
  static const marcaNaranja = urgente;
}

ThemeData construirTema() {
  final base = ThemeData.dark(useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: MarcaColores.fondo,
    colorScheme: base.colorScheme.copyWith(
      primary: MarcaColores.marcaOro,
      secondary: MarcaColores.marcaOro,
      surface: MarcaColores.tarjeta,
      error: MarcaColores.urgente,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: MarcaColores.fondo,
      foregroundColor: MarcaColores.marcaOro,
      elevation: 0,
      centerTitle: false,
    ),
    cardTheme: const CardThemeData(
      color: MarcaColores.tarjeta,
      elevation: 0,
      margin: EdgeInsets.symmetric(horizontal: 12, vertical: 6),
    ),
    // Sin animaciones de transición innecesarias: la app debe sentirse
    // rápida en celulares económicos, no vistosa.
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {
        TargetPlatform.android: FadeUpwardsPageTransitionsBuilder(),
        TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
      },
    ),
    textTheme: base.textTheme.apply(bodyColor: Colors.white, displayColor: Colors.white),
  );
}
