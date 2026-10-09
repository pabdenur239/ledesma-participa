import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/noticia.dart';
import '../services/api_service.dart';
import '../theme.dart';
import '../widgets/noticia_card.dart';
import 'busqueda_screen.dart';
import 'detalle_screen.dart';

/// Pantalla principal: feed cronológico con prioridad editorial (Inicio,
/// ya viene ordenado así desde la API — ver PRIORIDAD_SECCION en
/// motor_noticias/sitio/generador.py) más una pestaña por categoría real.
/// "Policiales" y "Deportes" están en la lista mínima pedida pero hoy no
/// tienen clasificación real en el sistema (ver README): la pestaña existe
/// y muestra "sin noticias todavía" en vez de inventar contenido ahí.
const _categoriasFijas = [
  ('inicio', 'Inicio'),
  ('locales', 'Locales'),
  ('provinciales', 'Provinciales'),
  ('nacionales', 'Nacionales'),
  ('internacionales', 'Internacionales'),
  ('policiales', 'Policiales'),
  ('espectaculos', 'Espectáculos'),
  ('salud', 'Salud'),
  ('gastronomia', 'Gastronomía'),
  ('deportes', 'Deportes'),
];

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with SingleTickerProviderStateMixin {
  late final TabController _tabController;
  final _api = ApiService();

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: _categoriasFijas.length, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            Container(
              width: 28,
              height: 28,
              alignment: Alignment.center,
              decoration: BoxDecoration(color: MarcaColores.marcaFondo, borderRadius: BorderRadius.circular(6)),
              child: const Text('LP', style: TextStyle(color: MarcaColores.marcaOro, fontWeight: FontWeight.w800, fontSize: 12)),
            ),
            const SizedBox(width: 8),
            const Text('Ledesma Participa', style: TextStyle(fontSize: 17)),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.search),
            tooltip: 'Buscar',
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const BusquedaScreen())),
          ),
          IconButton(
            icon: const Icon(Icons.public),
            tooltip: 'Abrir ledesmaparticipa.com.ar',
            onPressed: () => launchUrl(
              Uri.parse('https://ledesmaparticipa.com.ar'),
              mode: LaunchMode.externalApplication,
            ),
          ),
        ],
        bottom: TabBar(
          controller: _tabController,
          isScrollable: true,
          indicatorColor: MarcaColores.marcaNaranja,
          labelColor: Colors.white,
          unselectedLabelColor: MarcaColores.textoSuave,
          tabs: _categoriasFijas.map((c) => Tab(text: c.$2)).toList(),
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: _categoriasFijas.map((c) {
          if (c.$1 == 'inicio') {
            return _FeedInicio(api: _api);
          }
          return _FeedCategoria(api: _api, slug: c.$1);
        }).toList(),
      ),
    );
  }
}

class _FeedInicio extends StatefulWidget {
  final ApiService api;
  const _FeedInicio({required this.api});

  @override
  State<_FeedInicio> createState() => _FeedInicioState();
}

class _FeedInicioState extends State<_FeedInicio> {
  late Future<List<Noticia>> _feed;
  late Future<List<Noticia>> _urgentes;

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  void _cargar() {
    _feed = widget.api.obtenerFeed();
    _urgentes = widget.api.obtenerUrgentes();
  }

  Future<void> _refrescar() async {
    setState(_cargar);
    await Future.wait([_feed, _urgentes]);
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refrescar,
      child: FutureBuilder<List<Noticia>>(
        future: _feed,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return _ErrorConReintentar(onReintentar: _refrescar);
          }
          final feed = snapshot.data ?? [];
          return ListView(
            children: [
              FutureBuilder<List<Noticia>>(
                future: _urgentes,
                builder: (context, snapUrg) {
                  final urgentes = snapUrg.data ?? [];
                  if (urgentes.isEmpty) return const SizedBox.shrink();
                  return _BannerUrgentes(urgentes: urgentes);
                },
              ),
              if (feed.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(24),
                  child: Center(child: Text('No hay noticias todavía.')),
                ),
              ...feed.map(
                (n) => NoticiaCard(
                  noticia: n,
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => DetalleScreen(noticiaId: n.id, resumenPrevio: n)),
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _FeedCategoria extends StatefulWidget {
  final ApiService api;
  final String slug;
  const _FeedCategoria({required this.api, required this.slug});

  @override
  State<_FeedCategoria> createState() => _FeedCategoriaState();
}

class _FeedCategoriaState extends State<_FeedCategoria> {
  late Future<List<Noticia>> _items;

  @override
  void initState() {
    super.initState();
    _items = widget.api.obtenerCategoria(widget.slug);
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async {
        setState(() => _items = widget.api.obtenerCategoria(widget.slug));
        await _items;
      },
      child: FutureBuilder<List<Noticia>>(
        future: _items,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return _ErrorConReintentar(
              onReintentar: () async {
                setState(() => _items = widget.api.obtenerCategoria(widget.slug));
                await _items;
              },
            );
          }
          final items = snapshot.data ?? [];
          if (items.isEmpty) {
            return ListView(
              children: const [
                Padding(
                  padding: EdgeInsets.all(24),
                  child: Center(child: Text('Sin noticias en esta categoría todavía.')),
                ),
              ],
            );
          }
          return ListView.builder(
            itemCount: items.length,
            itemBuilder: (context, i) => NoticiaCard(
              noticia: items[i],
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => DetalleScreen(noticiaId: items[i].id, resumenPrevio: items[i])),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _BannerUrgentes extends StatelessWidget {
  final List<Noticia> urgentes;
  const _BannerUrgentes({required this.urgentes});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 4),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: MarcaColores.marcaNaranja.withValues(alpha: 0.12),
        border: Border.all(color: MarcaColores.marcaNaranja),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('🔴 URGENTE', style: TextStyle(color: MarcaColores.marcaNaranja, fontWeight: FontWeight.bold, fontSize: 13)),
          const SizedBox(height: 6),
          ...urgentes.take(3).map(
                (n) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: InkWell(
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => DetalleScreen(noticiaId: n.id, resumenPrevio: n)),
                    ),
                    child: Text(n.titulo, maxLines: 2, overflow: TextOverflow.ellipsis),
                  ),
                ),
              ),
        ],
      ),
    );
  }
}

class _ErrorConReintentar extends StatelessWidget {
  final Future<void> Function() onReintentar;
  const _ErrorConReintentar({required this.onReintentar});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('No se pudo cargar. Revisá tu conexión.'),
          const SizedBox(height: 8),
          OutlinedButton(onPressed: onReintentar, child: const Text('Reintentar')),
        ],
      ),
    );
  }
}
