import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

/// Paleta de marca de Ledesma Participa — misma que usa el sitio web
/// (motor_noticias/meta/imagen.py y docs/assets/site.css). No se rediseña
/// nada acá: se reutilizan los mismos colores para que la app se sienta
/// consistente con la web y con las publicaciones de Meta.
class MarcaColores {
  static const fondo = Color(0xFF141414);
  static const marcaFondo = Color(0xFF1F1A10);
  static const marcaOro = Color(0xFFD4AF37);
  static const marcaNaranja = Color(0xFFE8631C);
  static const textoSuave = Color(0xFFDED4BB);
  static const tarjeta = Color(0xFF1F1F1F);
}

ThemeData construirTema() {
  final base = ThemeData.dark(useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: MarcaColores.fondo,
    colorScheme: base.colorScheme.copyWith(
      primary: MarcaColores.marcaOro,
      secondary: MarcaColores.marcaNaranja,
      surface: MarcaColores.tarjeta,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: MarcaColores.marcaFondo,
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
    textTheme: base.textTheme.apply(
      bodyColor: Colors.white,
      displayColor: Colors.white,
    ),
  );
}
