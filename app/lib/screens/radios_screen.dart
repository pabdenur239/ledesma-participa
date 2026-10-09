import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/radio.dart';
import '../services/api_service.dart';
import '../services/favoritos_radios.dart';
import '../services/reproductor_radio.dart';
import '../theme.dart';
import 'categoria_screen.dart';

/// RADIOS EN VIVO (Etapa 2): listado con filtro por zona y favoritas,
/// ficha de emisora y reproductor (mini reproductor global, main.dart).
/// Solo se reproduce la URL oficial de cada radio; sin stream oficial no
/// hay botón Escuchar.
class RadiosScreen extends StatefulWidget {
  final ApiService? api;
  final ReproductorRadio? reproductor;
  final FavoritosRadios? favoritos;

  const RadiosScreen({super.key, this.api, this.reproductor, this.favoritos});

  @override
  State<RadiosScreen> createState() => _RadiosScreenState();
}

class _RadiosScreenState extends State<RadiosScreen> {
  late final ApiService _api = widget.api ?? ApiService();
  late final FavoritosRadios _favoritos = widget.favoritos ?? FavoritosRadios();
  late Future<List<Emisora>> _radios;
  Set<String> _favoritas = {};

  /// '' = todas, 'favoritas', o el slug de una zona.
  String _filtro = '';

  @override
  void initState() {
    super.initState();
    _radios = _api.obtenerRadios();
    _favoritos.leer().then((f) {
      if (mounted) setState(() => _favoritas = f);
    });
  }

  Future<void> _refrescar() async {
    setState(() => _radios = _api.obtenerRadios());
    await _radios;
  }

  Future<void> _alternarFavorita(String id) async {
    final f = await _favoritos.alternar(id);
    if (mounted) setState(() => _favoritas = f);
  }

  List<Emisora> _filtrar(List<Emisora> radios) {
    if (_filtro.isEmpty) return radios;
    if (_filtro == 'favoritas') return radios.where((r) => _favoritas.contains(r.id)).toList();
    return radios.where((r) => r.zonaSlug == _filtro).toList();
  }

  Widget _chip(String valor, String etiqueta) {
    final seleccionado = _filtro == valor;
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: ChoiceChip(
        label: Text(etiqueta),
        selected: seleccionado,
        showCheckmark: true,
        selectedColor: MarcaColores.marcaOro,
        labelStyle: TextStyle(fontWeight: FontWeight.w700, color: seleccionado ? MarcaColores.fondo : Colors.white),
        materialTapTargetSize: MaterialTapTargetSize.padded,
        onSelected: (_) => setState(() => _filtro = valor),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Radios en vivo')),
      body: RefreshIndicator(
        onRefresh: _refrescar,
        child: FutureBuilder<List<Emisora>>(
          future: _radios,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) return ErrorConReintentar(onReintentar: _refrescar);
            final todas = snapshot.data ?? [];
            if (todas.isEmpty) {
              return ListView(children: const [
                Padding(
                  padding: EdgeInsets.all(24),
                  child: Center(
                    child: Text(
                      'Estamos sumando las radios de la zona. Solo incluimos emisoras con transmisión oficial.',
                      textAlign: TextAlign.center,
                    ),
                  ),
                ),
              ]);
            }
            final zonas = zonasRadio.where((z) => todas.any((r) => r.zonaSlug == z.$1));
            final visibles = _filtrar(todas);
            return ListView(
              padding: const EdgeInsets.only(bottom: 16),
              children: [
                SizedBox(
                  height: 56,
                  child: ListView(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    children: [
                      _chip('', 'Todas'),
                      if (_favoritas.isNotEmpty) _chip('favoritas', 'Favoritas'),
                      for (final z in zonas) _chip(z.$1, z.$2),
                    ],
                  ),
                ),
                if (visibles.isEmpty)
                  const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('No hay radios para ese filtro.'))),
                ...visibles.map((r) => TarjetaRadio(
                      radio: r,
                      reproductor: widget.reproductor,
                      favorita: _favoritas.contains(r.id),
                      onFavorita: () => _alternarFavorita(r.id),
                      onTap: () => Navigator.of(context).push(MaterialPageRoute(
                        builder: (_) => RadioDetalleScreen(
                          radio: r,
                          reproductor: widget.reproductor,
                          favorita: _favoritas.contains(r.id),
                          onFavorita: () => _alternarFavorita(r.id),
                        ),
                      )),
                    )),
                const Padding(
                  padding: EdgeInsets.fromLTRB(16, 12, 16, 0),
                  child: Text(
                    'Cada radio se escucha desde su transmisión oficial. Ledesma Participa no graba ni retransmite señales.',
                    style: TextStyle(fontSize: 12, color: MarcaColores.textoSuave),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class LogoRadio extends StatelessWidget {
  final Emisora radio;
  final double tamano;

  const LogoRadio({super.key, required this.radio, this.tamano = 64});

  @override
  Widget build(BuildContext context) {
    final iniciales = radio.nombre.split(' ').where((p) => p.isNotEmpty).take(2).map((p) => p[0]).join().toUpperCase();
    final placa = Container(
      width: tamano,
      height: tamano,
      color: MarcaColores.fondo,
      alignment: Alignment.center,
      child: Text(iniciales,
          style: TextStyle(color: MarcaColores.marcaOro, fontWeight: FontWeight.w900, fontSize: tamano / 3)),
    );
    return ExcludeSemantics(
      child: ClipRRect(
        borderRadius: BorderRadius.circular(10),
        child: radio.logoUrl == null
            ? placa
            : CachedNetworkImage(
                imageUrl: radio.logoUrl!,
                width: tamano,
                height: tamano,
                fit: BoxFit.cover,
                errorWidget: (_, __, ___) => placa,
                placeholder: (_, __) => placa,
              ),
      ),
    );
  }
}

/// Estado con texto (nunca solo color).
class EstadoRadio extends StatelessWidget {
  final Emisora radio;

  const EstadoRadio({super.key, required this.radio});

  @override
  Widget build(BuildContext context) {
    final texto = radio.textoEstado;
    if (texto == null) return const SizedBox.shrink();
    final enVivo = radio.estadoTransmision == 'en_vivo';
    return Container(
      margin: const EdgeInsets.only(top: 6),
      padding: enVivo ? const EdgeInsets.symmetric(horizontal: 6, vertical: 2) : EdgeInsets.zero,
      decoration: enVivo ? BoxDecoration(color: MarcaColores.marcaOro, borderRadius: BorderRadius.circular(4)) : null,
      child: Text(enVivo ? '● $texto' : texto,
          style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w800,
              color: enVivo ? MarcaColores.fondo : MarcaColores.textoSuave)),
    );
  }
}

/// Botón ESCUCHAR EN VIVO: stream oficial → reproductor de la app; solo
/// player oficial → se abre en el navegador integrado; nada → sin botón.
class BotonEscuchar extends StatelessWidget {
  final Emisora radio;
  final ReproductorRadio reproductor;

  BotonEscuchar({super.key, required this.radio, ReproductorRadio? reproductor})
      : reproductor = reproductor ?? ReproductorRadio.instancia;

  @override
  Widget build(BuildContext context) {
    if (radio.soloPlayerOficial) {
      return FilledButton.icon(
        style: _estilo(false),
        onPressed: () => launchUrl(Uri.parse(radio.playerUrl!), mode: LaunchMode.inAppBrowserView),
        icon: const Icon(Icons.open_in_new),
        label: const Text('ESCUCHAR EN VIVO'),
      );
    }
    if (!radio.tieneStream) return const SizedBox.shrink();
    return ListenableBuilder(
      listenable: reproductor,
      builder: (context, _) {
        final esta = reproductor.radio?.id == radio.id && reproductor.sonando;
        return Semantics(
          button: true,
          label: esta ? 'Pausar ${radio.nombre}' : 'Escuchar en vivo ${radio.nombre} ${radio.dial ?? ''}'.trim(),
          excludeSemantics: true,
          child: FilledButton.icon(
            key: Key('escuchar-${radio.id}'),
            style: _estilo(esta),
            onPressed: () => esta ? reproductor.pausar() : reproductor.reproducir(radio),
            icon: Icon(esta ? Icons.pause : Icons.play_arrow),
            label: Text(esta ? 'PAUSA' : 'ESCUCHAR EN VIVO'),
          ),
        );
      },
    );
  }

  ButtonStyle _estilo(bool activo) => FilledButton.styleFrom(
        backgroundColor: activo ? MarcaColores.marcaOro : Colors.white,
        foregroundColor: MarcaColores.fondo,
        minimumSize: const Size(48, 48),
        textStyle: const TextStyle(fontWeight: FontWeight.w900),
      );
}

class TarjetaRadio extends StatelessWidget {
  final Emisora radio;
  final ReproductorRadio? reproductor;
  final bool favorita;
  final VoidCallback onFavorita;
  final VoidCallback onTap;

  const TarjetaRadio({
    super.key,
    required this.radio,
    required this.favorita,
    required this.onFavorita,
    required this.onTap,
    this.reproductor,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              LogoRadio(radio: radio),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(radio.nombre.toUpperCase(),
                        style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 15)),
                    if (radio.dial != null)
                      Text(radio.dial!, style: const TextStyle(fontWeight: FontWeight.w800, color: MarcaColores.marcaOro)),
                    if (radio.localidad != null)
                      Text(radio.localidad!, style: const TextStyle(fontSize: 13, color: MarcaColores.textoSuave)),
                    EstadoRadio(radio: radio),
                    const SizedBox(height: 8),
                    BotonEscuchar(radio: radio, reproductor: reproductor),
                  ],
                ),
              ),
              IconButton(
                tooltip: favorita ? 'Quitar de favoritas' : 'Agregar a favoritas',
                constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
                icon: Icon(favorita ? Icons.star : Icons.star_border, color: MarcaColores.marcaOro),
                onPressed: onFavorita,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class RadioDetalleScreen extends StatefulWidget {
  final Emisora radio;
  final ReproductorRadio? reproductor;
  final bool favorita;
  final Future<void> Function() onFavorita;

  const RadioDetalleScreen({
    super.key,
    required this.radio,
    required this.favorita,
    required this.onFavorita,
    this.reproductor,
  });

  @override
  State<RadioDetalleScreen> createState() => _RadioDetalleScreenState();
}

class _RadioDetalleScreenState extends State<RadioDetalleScreen> {
  late bool _favorita = widget.favorita;

  @override
  Widget build(BuildContext context) {
    final r = widget.radio;
    final enlaces = <(String, String)>[
      if (r.sitioWeb != null) ('Sitio web', r.sitioWeb!),
      if (r.facebook != null) ('Facebook', r.facebook!),
      if (r.instagram != null) ('Instagram', r.instagram!),
    ];
    return Scaffold(
      appBar: AppBar(
        title: Text(r.nombre),
        actions: [
          IconButton(
            tooltip: _favorita ? 'Quitar de favoritas' : 'Agregar a favoritas',
            icon: Icon(_favorita ? Icons.star : Icons.star_border),
            onPressed: () async {
              await widget.onFavorita();
              if (mounted) setState(() => _favorita = !_favorita);
            },
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Center(child: LogoRadio(radio: r, tamano: 120)),
          const SizedBox(height: 16),
          Text(r.nombre.toUpperCase(),
              textAlign: TextAlign.center, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
          if (r.dial != null)
            Text(r.dial!,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: MarcaColores.marcaOro)),
          if (r.localidad != null)
            Text(r.localidad!, textAlign: TextAlign.center, style: const TextStyle(color: MarcaColores.textoSuave)),
          Text(r.zona, textAlign: TextAlign.center, style: const TextStyle(fontSize: 12, color: MarcaColores.textoSuave)),
          Center(child: EstadoRadio(radio: r)),
          const SizedBox(height: 16),
          BotonEscuchar(radio: r, reproductor: widget.reproductor),
          if (enlaces.isNotEmpty) ...[
            const SizedBox(height: 16),
            Wrap(
              alignment: WrapAlignment.center,
              spacing: 8,
              children: enlaces
                  .map((e) => TextButton(
                        onPressed: () => launchUrl(Uri.parse(e.$2), mode: LaunchMode.externalApplication),
                        child: Text(e.$1),
                      ))
                  .toList(),
            ),
          ],
        ],
      ),
    );
  }
}
