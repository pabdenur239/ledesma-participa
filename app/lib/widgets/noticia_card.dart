import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../models/noticia.dart';
import '../theme.dart';

/// Tarjeta de una noticia en una lista (feed, categoría, urgentes).
/// Carga progresiva de imagen (placeholder liviano mientras carga, ícono
/// simple si falla) y sin animaciones de por medio — rápida y legible en
/// celulares económicos.
class NoticiaCard extends StatelessWidget {
  final Noticia noticia;
  final VoidCallback onTap;

  const NoticiaCard({super.key, required this.noticia, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 96,
              height: 96,
              child: noticia.imagen != null
                  ? CachedNetworkImage(
                      imageUrl: noticia.imagen!,
                      fit: BoxFit.cover,
                      fadeInDuration: Duration.zero,
                      placeholder: (context, url) => Container(color: MarcaColores.marcaFondo),
                      errorWidget: (context, url, error) => Container(
                        color: MarcaColores.marcaFondo,
                        child: const Icon(Icons.image_not_supported_outlined, color: MarcaColores.textoSuave),
                      ),
                    )
                  : Container(
                      color: MarcaColores.marcaFondo,
                      child: const Icon(Icons.article_outlined, color: MarcaColores.textoSuave),
                    ),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (noticia.urgente)
                      const Padding(
                        padding: EdgeInsets.only(bottom: 4),
                        child: _EtiquetaUrgente(),
                      ),
                    Text(
                      noticia.titulo,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14.5),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _metaLinea(),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 12, color: MarcaColores.textoSuave),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _metaLinea() {
    final partes = <String>[noticia.categoriaEtiqueta];
    if (noticia.localidad != null && noticia.localidad!.isNotEmpty) {
      partes.add(noticia.localidad!);
    }
    if (noticia.fecha != null) {
      partes.add(_horaCorta(noticia.fecha!));
    }
    return partes.join(' · ');
  }

  String _horaCorta(DateTime fecha) {
    final local = fecha.toLocal();
    final hh = local.hour.toString().padLeft(2, '0');
    final mm = local.minute.toString().padLeft(2, '0');
    return '$hh:$mm';
  }
}

class _EtiquetaUrgente extends StatelessWidget {
  const _EtiquetaUrgente();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: MarcaColores.marcaNaranja,
        borderRadius: BorderRadius.circular(3),
      ),
      child: const Text(
        'URGENTE',
        style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5),
      ),
    );
  }
}
