import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/noticia.dart';
import '../services/api_service.dart';
import '../theme.dart';
import '../widgets/noticia_card.dart';
import 'busqueda_screen.dart';
import 'categoria_screen.dart';
import 'guia_screen.dart';
import 'radios_screen.dart';
import 'videos_screen.dart';

/// Accesos de Inicio (Etapa 1). Territorio y categoría son listados
/// distintos; Videos, Guía Comercial y Multimedia tienen pantalla propia.
/// Radios en vivo: Etapa 2.
const accesosInicio = <(String, String)>[
  ('ultimas', 'Últimas'),
  ('libertador', 'Libertador'),
  ('ledesma', 'Departamento Ledesma'),
  ('jujuy', 'Jujuy'),
  ('policiales', 'Policiales'),
  ('salud', 'Salud'),
  ('deportes', 'Deportes'),
  ('servicios', 'Servicios'),
  ('videos', 'Videos'),
  ('radios', 'Radios en vivo'),
  ('guia', 'Guía Comercial'),
  ('multimedia', 'Multimedia'),
];

void abrirAcceso(BuildContext context, String slug, String etiqueta) {
  final Widget pantalla;
  switch (slug) {
    case 'videos':
      pantalla = const VideosScreen();
    case 'guia':
      pantalla = const GuiaScreen();
    case 'multimedia':
      pantalla = const MultimediaScreen();
    case 'radios':
      pantalla = const RadiosScreen();
    default:
      pantalla = CategoriaScreen(slug: slug, titulo: etiqueta);
  }
  Navigator.of(context).push(MaterialPageRoute(builder: (_) => pantalla));
}

class HomeScreen extends StatefulWidget {
  final ApiService? api;

  const HomeScreen({super.key, this.api});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late final ApiService _api = widget.api ?? ApiService();
  late Future<Portada> _portada;

  @override
  void initState() {
    super.initState();
    _portada = _api.obtenerPortada();
  }

  Future<void> _refrescar() async {
    setState(() => _portada = _api.obtenerPortada());
    await _portada;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Row(
          children: [
            Text('LEDESMA ', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900, color: Colors.white)),
            Text('PARTICIPA', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900, color: MarcaColores.marcaOro)),
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
            onPressed: () => launchUrl(Uri.parse(ApiService.baseSitio), mode: LaunchMode.externalApplication),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(46),
          child: SizedBox(
            height: 46,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              children: accesosInicio
                  .map((a) => Padding(
                        padding: const EdgeInsets.only(right: 6),
                        child: ActionChip(
                          label: Text(a.$2),
                          labelStyle: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
                          backgroundColor: MarcaColores.marcaFondo,
                          side: const BorderSide(color: Color(0xFF34322C)),
                          onPressed: () => abrirAcceso(context, a.$1, a.$2),
                        ),
                      ))
                  .toList(),
            ),
          ),
        ),
      ),
      body: RefreshIndicator(
        onRefresh: _refrescar,
        child: FutureBuilder<Portada>(
          future: _portada,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError || snapshot.data == null) {
              return ErrorConReintentar(onReintentar: _refrescar);
            }
            return _Portada(portada: snapshot.data!);
          },
        ),
      ),
    );
  }
}

class _Portada extends StatelessWidget {
  final Portada portada;

  const _Portada({required this.portada});

  @override
  Widget build(BuildContext context) {
    final hijos = <Widget>[
      if (portada.urgentes.isNotEmpty) _BloqueUrgentes(urgentes: portada.urgentes),
      if (portada.climaDolar != null) _BloqueClimaDolar(datos: portada.climaDolar!),
      if (portada.principal != null)
        NoticiaDestacada(noticia: portada.principal!, onTap: () => abrirNoticia(context, portada.principal!)),
      for (final seccion in portada.secciones) ...[
        _TituloSeccion(
          etiqueta: seccion.etiqueta,
          onVerMas: () => abrirAcceso(context, seccion.slug, seccion.etiqueta),
        ),
        ...seccion.noticias.map((n) => NoticiaCard(noticia: n, onTap: () => abrirNoticia(context, n))),
      ],
      if (portada.videos.isNotEmpty) ...[
        _TituloSeccion(etiqueta: 'Videos', onVerMas: () => abrirAcceso(context, 'videos', 'Videos')),
        SizedBox(
          height: 230,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 6),
            children: portada.videos.map((v) => TarjetaVideo(video: v, ancho: 260)).toList(),
          ),
        ),
      ],
      const _AccesoRadios(),
      if (portada.guiaComercial.isNotEmpty) ...[
        _TituloSeccion(etiqueta: 'Guía Comercial', onVerMas: () => abrirAcceso(context, 'guia', 'Guía Comercial')),
        const Padding(
          padding: EdgeInsets.symmetric(horizontal: 16),
          child: Text('Espacio comercial: no es contenido periodístico.',
              style: TextStyle(fontSize: 11, color: MarcaColores.textoSuave)),
        ),
        SizedBox(
          height: 270,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 6),
            children: portada.guiaComercial.map((c) => TarjetaComercio(comercio: c, ancho: 250)).toList(),
          ),
        ),
      ],
      Padding(
        padding: const EdgeInsets.all(16),
        child: OutlinedButton(
          onPressed: () => abrirAcceso(context, 'ultimas', 'Últimas'),
          child: const Text('Todas las últimas noticias'),
        ),
      ),
    ];
    if (hijos.length == 1) {
      hijos.insert(0, const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('No hay noticias todavía.'))));
    }
    return ListView(padding: const EdgeInsets.only(top: 6, bottom: 16), children: hijos);
  }
}

/// Acceso a RADIOS EN VIVO en Inicio (Etapa 2).
class _AccesoRadios extends StatelessWidget {
  const _AccesoRadios();

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.fromLTRB(12, 18, 12, 6),
      child: ListTile(
        minVerticalPadding: 12,
        leading: const Icon(Icons.radio, color: MarcaColores.marcaOro, size: 32),
        title: const Text('RADIOS EN VIVO', style: TextStyle(fontWeight: FontWeight.w900)),
        subtitle: const Text('Libertador, Departamento Ledesma, Jujuy y Argentina'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => abrirAcceso(context, 'radios', 'Radios en vivo'),
      ),
    );
  }
}

class _TituloSeccion extends StatelessWidget {
  final String etiqueta;
  final VoidCallback onVerMas;

  const _TituloSeccion({required this.etiqueta, required this.onVerMas});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 18, 8, 4),
      child: Row(
        children: [
          Container(width: 4, height: 18, color: MarcaColores.marcaOro),
          const SizedBox(width: 8),
          Expanded(
            child: Text(etiqueta.toUpperCase(),
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w900, letterSpacing: 0.6)),
          ),
          TextButton(onPressed: onVerMas, child: const Text('Ver más')),
        ],
      ),
    );
  }
}

class _BloqueUrgentes extends StatelessWidget {
  final List<Noticia> urgentes;

  const _BloqueUrgentes({required this.urgentes});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 6),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: MarcaColores.urgente, borderRadius: BorderRadius.circular(10)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('URGENTE', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: 1.5, fontSize: 13)),
          ...urgentes.take(3).map(
                (n) => InkWell(
                  onTap: () => abrirNoticia(context, n),
                  child: Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      '${(n.territorioEtiqueta ?? '').toUpperCase()}  ${n.titulo}',
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w700, height: 1.25),
                    ),
                  ),
                ),
              ),
        ],
      ),
    );
  }
}

String _pesos(double? valor) {
  if (valor == null) return 'No disponible';
  final entero = valor.round().toString();
  final conPuntos = entero.replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => '.');
  return '\$$conPuntos';
}

class _BloqueClimaDolar extends StatelessWidget {
  final ClimaDolar datos;

  const _BloqueClimaDolar({required this.datos});

  @override
  Widget build(BuildContext context) {
    Widget filaDolar(String etiqueta, DolarCotizacion? d) => Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Row(children: [
            SizedBox(width: 64, child: Text(etiqueta, style: const TextStyle(fontWeight: FontWeight.w700))),
            Expanded(
              child: Text(
                d == null ? 'No disponible' : 'Compra ${_pesos(d.compra)} · Venta ${_pesos(d.venta)}',
                style: TextStyle(color: d == null ? MarcaColores.textoSuave : MarcaColores.marcaOro, fontWeight: FontWeight.w700),
              ),
            ),
          ]),
        );
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 6),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: MarcaColores.marcaFondo, borderRadius: BorderRadius.circular(10)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const Text('CLIMA + DÓLAR',
                style: TextStyle(color: MarcaColores.marcaOro, fontWeight: FontWeight.w900, letterSpacing: 1)),
            const Spacer(),
            Text(datos.fechaLegible, style: const TextStyle(fontSize: 11.5, color: MarcaColores.textoSuave)),
          ]),
          const SizedBox(height: 8),
          if (datos.hayClima)
            Row(children: [
              Text('${datos.temperaturaActual!.round()}°', style: const TextStyle(fontSize: 38, fontWeight: FontWeight.w900)),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(_capitalizar(datos.descripcion ?? ''), style: const TextStyle(fontWeight: FontWeight.w700)),
                  Text(
                    'Mín ${datos.temperaturaMinima?.round() ?? '-'}° · Máx ${datos.temperaturaMaxima?.round() ?? '-'}°'
                    ' · Lluvia ${datos.probabilidadLluvia?.round() ?? '-'}%',
                    style: const TextStyle(fontSize: 12.5, color: MarcaColores.textoSuave),
                  ),
                ]),
              ),
            ])
          else
            const Text('Clima: No disponible', style: TextStyle(color: MarcaColores.textoSuave)),
          const SizedBox(height: 6),
          filaDolar('Oficial', datos.oficial),
          filaDolar('Blue', datos.blue),
          const SizedBox(height: 6),
          Text('Actualizado ${datos.actualizado} · ${datos.fuentes}',
              style: const TextStyle(fontSize: 10.5, color: MarcaColores.textoSuave)),
        ],
      ),
    );
  }
}

String _capitalizar(String texto) => texto.isEmpty ? texto : texto[0].toUpperCase() + texto.substring(1);
