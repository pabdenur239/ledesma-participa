import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/noticia.dart';
import '../services/api_service.dart';
import '../theme.dart';
import 'categoria_screen.dart';

/// GUÍA COMERCIAL LEDESMA PARTICIPA: listado de comercios. Contenido
/// comercial, siempre rotulado como tal y separado de las noticias.
class GuiaScreen extends StatefulWidget {
  const GuiaScreen({super.key});

  @override
  State<GuiaScreen> createState() => _GuiaScreenState();
}

class _GuiaScreenState extends State<GuiaScreen> {
  final _api = ApiService();
  late Future<List<Comercio>> _comercios;

  @override
  void initState() {
    super.initState();
    _comercios = _api.obtenerGuiaComercial();
  }

  Future<void> _refrescar() async {
    setState(() => _comercios = _api.obtenerGuiaComercial());
    await _comercios;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Guía Comercial')),
      body: RefreshIndicator(
        onRefresh: _refrescar,
        child: FutureBuilder<List<Comercio>>(
          future: _comercios,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) return ErrorConReintentar(onReintentar: _refrescar);
            final comercios = snapshot.data ?? [];
            return ListView(
              padding: const EdgeInsets.only(bottom: 16),
              children: [
                const Padding(
                  padding: EdgeInsets.fromLTRB(16, 12, 16, 4),
                  child: Text('ESPACIO COMERCIAL · NO ES CONTENIDO PERIODÍSTICO',
                      style: TextStyle(fontSize: 11, color: MarcaColores.textoSuave, letterSpacing: 0.6)),
                ),
                if (comercios.isEmpty)
                  const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('Todavía no hay comercios.'))),
                ...comercios.map((c) => TarjetaComercio(comercio: c)),
              ],
            );
          },
        ),
      ),
    );
  }
}

class TarjetaComercio extends StatelessWidget {
  final Comercio comercio;
  final double? ancho;

  const TarjetaComercio({super.key, required this.comercio, this.ancho});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: ancho,
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ComercioScreen(comercio: comercio))),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AspectRatio(
                aspectRatio: 3 / 2,
                child: comercio.imagenes.isNotEmpty
                    ? CachedNetworkImage(imageUrl: comercio.imagenes.first, fit: BoxFit.cover, fadeInDuration: Duration.zero)
                    : Container(color: MarcaColores.marcaFondo),
              ),
              Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(comercio.nombre, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
                    if (comercio.rubro != null)
                      Text(comercio.rubro!, style: const TextStyle(color: MarcaColores.textoSuave, fontSize: 13)),
                    if (comercio.promociones.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 4),
                        child: Text(comercio.promociones.first,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(color: MarcaColores.servicio, fontWeight: FontWeight.w700, fontSize: 13)),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Ficha individual. Solo se muestran los datos que existen (nunca uno
/// inventado). Botón de contacto: WhatsApp, teléfono o redes.
class ComercioScreen extends StatelessWidget {
  final Comercio comercio;

  const ComercioScreen({super.key, required this.comercio});

  @override
  Widget build(BuildContext context) {
    final datos = <(String, String)>[
      if (comercio.rubro != null) ('Rubro', comercio.rubro!),
      if (comercio.direccion != null) ('Dirección', comercio.direccion!),
      if (comercio.horarios != null) ('Horarios', comercio.horarios!),
      if (comercio.whatsapp != null) ('WhatsApp', comercio.whatsapp!),
      if (comercio.telefono != null) ('Teléfono', comercio.telefono!),
      if (comercio.instagram != null) ('Instagram', comercio.instagram!),
      if (comercio.facebook != null) ('Facebook', comercio.facebook!),
    ];
    return Scaffold(
      appBar: AppBar(title: const Text('Guía Comercial')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('ESPACIO COMERCIAL', style: TextStyle(fontSize: 11, color: MarcaColores.textoSuave, letterSpacing: 0.6)),
          const SizedBox(height: 4),
          Text(comercio.nombre, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w900)),
          if (comercio.descripcion != null) ...[
            const SizedBox(height: 8),
            Text(comercio.descripcion!, style: const TextStyle(fontSize: 15.5, height: 1.4)),
          ],
          if (comercio.contactoUrl != null) ...[
            const SizedBox(height: 14),
            FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: MarcaColores.servicio, foregroundColor: Colors.white),
              onPressed: () => launchUrl(Uri.parse(comercio.contactoUrl!), mode: LaunchMode.externalApplication),
              icon: const Icon(Icons.chat_outlined),
              label: Text(comercio.contactoEtiqueta ?? 'Contactar'),
            ),
          ],
          if (datos.isNotEmpty) ...[
            const SizedBox(height: 16),
            ...datos.map((d) => Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    SizedBox(width: 92, child: Text(d.$1, style: const TextStyle(fontWeight: FontWeight.w800))),
                    Expanded(child: Text(d.$2)),
                  ]),
                )),
          ],
          if (comercio.promociones.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Text('Promociones', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            const SizedBox(height: 6),
            ...comercio.promociones.map((p) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text('• $p', style: const TextStyle(fontSize: 15)),
                )),
          ],
          const SizedBox(height: 12),
          ...comercio.imagenes.map((url) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: CachedNetworkImage(imageUrl: url, fadeInDuration: Duration.zero),
                ),
              )),
        ],
      ),
    );
  }
}
