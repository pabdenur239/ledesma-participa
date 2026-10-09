import 'package:flutter/material.dart';

import '../models/noticia.dart';
import '../theme.dart';

/// Insignias de una noticia: URGENTE (rojo), territorio (dorado) y
/// categoría (carbón; verde si es Servicios). Territorio, categoría y
/// urgente son dimensiones separadas.
class Insignias extends StatelessWidget {
  final Noticia noticia;

  const Insignias({super.key, required this.noticia});

  @override
  Widget build(BuildContext context) {
    final items = <Widget>[
      if (noticia.urgente) const Insignia(texto: 'URGENTE', fondo: MarcaColores.urgente, colorTexto: Colors.white),
      if ((noticia.territorioEtiqueta ?? '').isNotEmpty)
        Insignia(texto: noticia.territorioEtiqueta!, fondo: MarcaColores.marcaOro, colorTexto: Colors.black),
      if ((noticia.categoriaTemaEtiqueta ?? '').isNotEmpty)
        Insignia(
          texto: noticia.categoriaTemaEtiqueta!,
          fondo: noticia.esServicio ? MarcaColores.servicio : const Color(0xFF3A3833),
          colorTexto: Colors.white,
        ),
    ];
    if (items.isEmpty) return const SizedBox.shrink();
    return Wrap(spacing: 5, runSpacing: 4, children: items);
  }
}

class Insignia extends StatelessWidget {
  final String texto;
  final Color fondo;
  final Color colorTexto;

  const Insignia({super.key, required this.texto, required this.fondo, required this.colorTexto});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(20)),
      child: Text(
        texto.toUpperCase(),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w800, color: colorTexto, letterSpacing: 0.4),
      ),
    );
  }
}
