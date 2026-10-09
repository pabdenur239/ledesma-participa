import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../models/noticia.dart';
import '../theme.dart';

/// Imagen de la noticia: la foto real del hecho (ya validada por la regla
/// de imágenes del servidor) o, si no hay una apta, la PLACA EDITORIAL
/// GRÁFICA (carbón + dorado + titular + territorio). Nunca una imagen
/// descontextualizada ni un ícono genérico.
class ImagenNoticia extends StatelessWidget {
  final Noticia noticia;
  final bool compacta;

  const ImagenNoticia({super.key, required this.noticia, this.compacta = false});

  @override
  Widget build(BuildContext context) {
    final placa = PlacaEditorial(noticia: noticia, compacta: compacta);
    if (noticia.imagen == null) return placa;
    return CachedNetworkImage(
      imageUrl: noticia.imagen!,
      fit: BoxFit.cover,
      fadeInDuration: Duration.zero,
      placeholder: (context, url) => Container(color: MarcaColores.marcaFondo),
      errorWidget: (context, url, error) => placa,
    );
  }
}

class PlacaEditorial extends StatelessWidget {
  final Noticia noticia;
  final bool compacta;

  const PlacaEditorial({super.key, required this.noticia, this.compacta = false});

  @override
  Widget build(BuildContext context) {
    final acento = noticia.urgente
        ? MarcaColores.urgente
        : (noticia.esServicio ? MarcaColores.servicio : MarcaColores.marcaOro);
    return Container(
      decoration: BoxDecoration(
        color: MarcaColores.fondo,
        border: Border(left: BorderSide(color: acento, width: compacta ? 4 : 6)),
      ),
      padding: EdgeInsets.all(compacta ? 8 : 16),
      alignment: Alignment.centerLeft,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!compacta && (noticia.territorioEtiqueta ?? '').isNotEmpty)
            Text(
              noticia.territorioEtiqueta!.toUpperCase(),
              style: const TextStyle(color: MarcaColores.marcaOro, fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: 1),
            ),
          if (!compacta) const SizedBox(height: 6),
          Text(
            noticia.tituloPlaca ?? noticia.titulo,
            maxLines: compacta ? 4 : 4,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: compacta ? 10 : 19, height: 1.15),
          ),
          if (!compacta) const SizedBox(height: 8),
          if (!compacta)
            const Text(
              'LEDESMA PARTICIPA',
              style: TextStyle(color: MarcaColores.marcaOro, fontSize: 9, fontWeight: FontWeight.w800, letterSpacing: 1.2),
            ),
        ],
      ),
    );
  }
}
