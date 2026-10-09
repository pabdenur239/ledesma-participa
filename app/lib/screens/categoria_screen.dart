import 'package:flutter/material.dart';

import '../models/noticia.dart';
import '../services/api_service.dart';
import '../widgets/noticia_card.dart';
import 'detalle_screen.dart';

void abrirNoticia(BuildContext context, Noticia noticia) {
  Navigator.of(context).push(
    MaterialPageRoute(builder: (_) => DetalleScreen(noticiaId: noticia.id, resumenPrevio: noticia)),
  );
}

/// Listado por categoría o territorio (api/categoria/<slug>.json). "ultimas"
/// usa el feed cronológico.
class CategoriaScreen extends StatefulWidget {
  final String slug;
  final String titulo;
  final ApiService? api;

  const CategoriaScreen({super.key, required this.slug, required this.titulo, this.api});

  @override
  State<CategoriaScreen> createState() => _CategoriaScreenState();
}

class _CategoriaScreenState extends State<CategoriaScreen> {
  late final ApiService _api = widget.api ?? ApiService();
  late Future<List<Noticia>> _items;

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  void _cargar() {
    _items = widget.slug == 'ultimas' ? _api.obtenerFeed() : _api.obtenerCategoria(widget.slug);
  }

  Future<void> _refrescar() async {
    setState(_cargar);
    await _items;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.titulo)),
      body: RefreshIndicator(
        onRefresh: _refrescar,
        child: FutureBuilder<List<Noticia>>(
          future: _items,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return ErrorConReintentar(onReintentar: _refrescar);
            }
            final items = snapshot.data ?? [];
            if (items.isEmpty) {
              return ListView(
                children: const [
                  Padding(
                    padding: EdgeInsets.all(24),
                    child: Center(child: Text('Todavía no hay noticias en esta sección.')),
                  ),
                ],
              );
            }
            return ListView.builder(
              padding: const EdgeInsets.only(bottom: 16),
              itemCount: items.length,
              itemBuilder: (context, i) => i == 0
                  ? NoticiaDestacada(noticia: items[0], onTap: () => abrirNoticia(context, items[0]))
                  : NoticiaCard(noticia: items[i], onTap: () => abrirNoticia(context, items[i])),
            );
          },
        ),
      ),
    );
  }
}

class ErrorConReintentar extends StatelessWidget {
  final Future<void> Function() onReintentar;

  const ErrorConReintentar({super.key, required this.onReintentar});

  @override
  Widget build(BuildContext context) {
    return ListView(
      children: [
        const SizedBox(height: 80),
        const Center(child: Text('No se pudo cargar. Revisá tu conexión.')),
        const SizedBox(height: 8),
        Center(child: OutlinedButton(onPressed: onReintentar, child: const Text('Reintentar'))),
      ],
    );
  }
}
