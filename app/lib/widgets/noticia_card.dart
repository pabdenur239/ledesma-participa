import 'package:flutter/material.dart';

import '../models/noticia.dart';
import '../theme.dart';
import 'imagen_noticia.dart';
import 'insignias.dart';

/// Tarjeta de una noticia en una lista: miniatura a la izquierda (o placa
/// editorial si no hay foto apta), insignias (urgente / territorio /
/// categoría), titular y hora/fecha. Compacta para que 15–25 notas no se
/// vean caóticas en el celular.
class NoticiaCard extends StatelessWidget {
  final Noticia noticia;
  final VoidCallback onTap;

  const NoticiaCard({super.key, required this.noticia, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Card(
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: noticia.urgente ? const BorderSide(color: MarcaColores.urgente, width: 1.5) : BorderSide.none,
      ),
      child: InkWell(
        onTap: onTap,
        child: IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(width: 108, child: ImagenNoticia(noticia: noticia, compacta: true)),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.all(10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Insignias(noticia: noticia),
                      const SizedBox(height: 5),
                      Text(
                        noticia.titulo,
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14.5, height: 1.25),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        horaYFecha(noticia),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 11.5, color: MarcaColores.textoSuave),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Tarjeta grande (noticia principal o primera de una sección).
class NoticiaDestacada extends StatelessWidget {
  final Noticia noticia;
  final VoidCallback onTap;

  const NoticiaDestacada({super.key, required this.noticia, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Card(
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: noticia.urgente ? const BorderSide(color: MarcaColores.urgente, width: 2) : BorderSide.none,
      ),
      child: InkWell(
        onTap: onTap,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            AspectRatio(aspectRatio: 16 / 10, child: ImagenNoticia(noticia: noticia)),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Insignias(noticia: noticia),
                  const SizedBox(height: 6),
                  Text(noticia.titulo, style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800, height: 1.2)),
                  if (noticia.bajada.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text(
                      noticia.bajada,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 13.5, color: MarcaColores.textoSuave, height: 1.35),
                    ),
                  ],
                  const SizedBox(height: 6),
                  Text(horaYFecha(noticia), style: const TextStyle(fontSize: 11.5, color: MarcaColores.textoSuave)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// "08:15 · 9/10" — hora y fecha local de la publicación.
String horaYFecha(Noticia noticia) {
  final fecha = noticia.fecha;
  if (fecha == null) return noticia.fechaLegible;
  final local = fecha.toLocal();
  final hh = local.hour.toString().padLeft(2, '0');
  final mm = local.minute.toString().padLeft(2, '0');
  return '$hh:$mm · ${local.day}/${local.month}';
}
