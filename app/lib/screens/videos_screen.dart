import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/noticia.dart';
import '../services/api_service.dart';
import '../theme.dart';
import 'categoria_screen.dart';

/// Abre la página del video en ledesmaparticipa.com.ar, que embebe el
/// reproductor oficial de YouTube, dentro de la app (navegador integrado).
/// Nunca se descarga el video.
Future<void> abrirVideo(Video video) =>
    launchUrl(Uri.parse(video.url), mode: LaunchMode.inAppBrowserView);

class VideosScreen extends StatefulWidget {
  const VideosScreen({super.key});

  @override
  State<VideosScreen> createState() => _VideosScreenState();
}

class _VideosScreenState extends State<VideosScreen> {
  final _api = ApiService();
  late Future<List<Video>> _videos;

  @override
  void initState() {
    super.initState();
    _videos = _api.obtenerVideos();
  }

  Future<void> _refrescar() async {
    setState(() => _videos = _api.obtenerVideos());
    await _videos;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Videos')),
      body: RefreshIndicator(
        onRefresh: _refrescar,
        child: FutureBuilder<List<Video>>(
          future: _videos,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) return ErrorConReintentar(onReintentar: _refrescar);
            final videos = snapshot.data ?? [];
            if (videos.isEmpty) {
              return ListView(children: const [
                Padding(padding: EdgeInsets.all(24), child: Center(child: Text('Todavía no hay videos.'))),
              ]);
            }
            return ListView(
              padding: const EdgeInsets.only(bottom: 16),
              children: videos.map((v) => TarjetaVideo(video: v)).toList(),
            );
          },
        ),
      ),
    );
  }
}

class TarjetaVideo extends StatelessWidget {
  final Video video;
  final double? ancho;

  const TarjetaVideo({super.key, required this.video, this.ancho});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: ancho,
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => abrirVideo(video),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AspectRatio(
                aspectRatio: 16 / 9,
                child: Stack(fit: StackFit.expand, children: [
                  CachedNetworkImage(imageUrl: video.miniatura, fit: BoxFit.cover, fadeInDuration: Duration.zero),
                  const Center(child: Icon(Icons.play_circle_fill, size: 56, color: MarcaColores.marcaOro)),
                ]),
              ),
              Padding(
                padding: const EdgeInsets.all(10),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(video.titulo, maxLines: 2, overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w700)),
                  if (video.fuente != null)
                    Text(video.fuente!, style: const TextStyle(fontSize: 12, color: MarcaColores.textoSuave)),
                ]),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Multimedia: punto de entrada para los formatos audiovisuales. Hoy solo
/// Videos (YouTube embebido); entrevistas, podcast y radios en vivo se
/// sumarán acá en etapas siguientes (radios = Etapa 2).
class MultimediaScreen extends StatelessWidget {
  const MultimediaScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Multimedia')),
      body: ListView(
        children: [
          ListTile(
            leading: const Icon(Icons.smart_display_outlined, color: MarcaColores.marcaOro),
            title: const Text('Videos'),
            subtitle: const Text('Videos de YouTube con su reproductor oficial'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const VideosScreen())),
          ),
        ],
      ),
    );
  }
}
