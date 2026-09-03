import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/noticia.dart';
import '../services/api_service.dart';
import '../theme.dart';

class DetalleScreen extends StatefulWidget {
  final int noticiaId;
  final Noticia? resumenPrevio;

  const DetalleScreen({super.key, required this.noticiaId, this.resumenPrevio});

  @override
  State<DetalleScreen> createState() => _DetalleScreenState();
}

class _DetalleScreenState extends State<DetalleScreen> {
  final _api = ApiService();
  late Future<Noticia> _detalle;

  @override
  void initState() {
    super.initState();
    _detalle = _api.obtenerDetalle(widget.noticiaId);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Noticia')),
      body: FutureBuilder<Noticia>(
        future: _detalle,
        builder: (context, snapshot) {
          if (snapshot.hasError && widget.resumenPrevio == null) {
            return const Center(child: Text('No se pudo cargar la noticia. Revisá tu conexión.'));
          }
          final noticia = snapshot.data ?? widget.resumenPrevio;
          if (noticia == null) {
            return const Center(child: CircularProgressIndicator());
          }
          return _Contenido(noticia: noticia, cargandoCompleto: snapshot.connectionState != ConnectionState.done);
        },
      ),
    );
  }
}

class _Contenido extends StatelessWidget {
  final Noticia noticia;
  final bool cargandoCompleto;

  const _Contenido({required this.noticia, required this.cargandoCompleto});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (noticia.imagen != null)
            CachedNetworkImage(
              imageUrl: noticia.imagen!,
              width: double.infinity,
              height: 220,
              fit: BoxFit.cover,
              fadeInDuration: Duration.zero,
              placeholder: (context, url) => Container(height: 220, color: MarcaColores.marcaFondo),
              errorWidget: (context, url, error) => Container(height: 220, color: MarcaColores.marcaFondo),
            ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (noticia.urgente)
                  const Padding(
                    padding: EdgeInsets.only(bottom: 8),
                    child: Text('URGENTE', style: TextStyle(color: MarcaColores.marcaNaranja, fontWeight: FontWeight.bold)),
                  ),
                Text(noticia.titulo, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                Text(
                  [noticia.categoriaEtiqueta, if (noticia.localidad != null) noticia.localidad!, noticia.fechaLegible]
                      .join(' · '),
                  style: const TextStyle(color: MarcaColores.textoSuave, fontSize: 12.5),
                ),
                const Divider(height: 28),
                if (noticia.textoParrafos != null)
                  ...noticia.textoParrafos!.map(
                    (p) => Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Text(p, style: const TextStyle(fontSize: 15, height: 1.4)),
                    ),
                  )
                else if (cargandoCompleto)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: Center(child: CircularProgressIndicator()),
                  )
                else
                  Text(noticia.bajada, style: const TextStyle(fontSize: 15, height: 1.4)),
                // Fuente siempre visible (requisito Google Play "News and
                // Magazines"). El contenido producido por el propio medio
                // se rotula como tal.
                const SizedBox(height: 12),
                Text(
                  'Fuente: ${(noticia.fuenteNombre != null && noticia.fuenteNombre!.isNotEmpty) ? noticia.fuenteNombre : 'Ledesma Participa'}',
                  style: const TextStyle(fontSize: 12.5, fontStyle: FontStyle.italic),
                ),
                if (noticia.fuenteUrl != null && noticia.fuenteUrl!.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  InkWell(
                    onTap: () => launchUrl(Uri.parse(noticia.fuenteUrl!), mode: LaunchMode.externalApplication),
                    child: const Text(
                      'Ver fuente original',
                      style: TextStyle(fontSize: 13, color: MarcaColores.marcaOro, decoration: TextDecoration.underline),
                    ),
                  ),
                ],
                const SizedBox(height: 20),
                OutlinedButton.icon(
                  onPressed: () => Share.share('${noticia.titulo}\n${noticia.url}'),
                  icon: const Icon(Icons.share_outlined),
                  label: const Text('Compartir'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
