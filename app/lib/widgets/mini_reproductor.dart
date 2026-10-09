import 'package:flutter/material.dart';

import '../services/reproductor_radio.dart';
import '../theme.dart';

/// Barra del reproductor de radio, fija abajo en todas las pantallas
/// (MaterialApp.builder): nombre + dial, estado, Play/Pausa y cerrar.
class MiniReproductor extends StatelessWidget {
  final ReproductorRadio reproductor;

  MiniReproductor({super.key, ReproductorRadio? reproductor})
      : reproductor = reproductor ?? ReproductorRadio.instancia;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: reproductor,
      builder: (context, _) {
        final radio = reproductor.radio;
        if (radio == null) return const SizedBox.shrink();
        final sonando = reproductor.sonando;
        final conectando = reproductor.estado == EstadoReproductor.conectando;
        return Material(
          color: MarcaColores.fondo,
          child: SafeArea(
            top: false,
            child: Container(
              decoration: const BoxDecoration(border: Border(top: BorderSide(color: MarcaColores.marcaOro, width: 2))),
              padding: const EdgeInsets.fromLTRB(8, 6, 4, 6),
              child: Row(
                children: [
                  Semantics(
                    button: true,
                    label: sonando ? 'Pausar ${radio.nombre}' : 'Reproducir ${radio.nombre}',
                    excludeSemantics: true,
                    child: FilledButton.icon(
                      key: const Key('mini-play'),
                      onPressed: conectando ? null : reproductor.alternar,
                      style: FilledButton.styleFrom(
                        backgroundColor: MarcaColores.marcaOro,
                        foregroundColor: MarcaColores.fondo,
                        minimumSize: const Size(48, 48),
                      ),
                      icon: conectando
                          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                          : Icon(sonando ? Icons.pause : Icons.play_arrow),
                      label: Text(sonando ? 'Pausa' : 'Play'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          [radio.nombre, if (radio.dial != null) radio.dial!].join(' · '),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontWeight: FontWeight.w800, color: Colors.white),
                        ),
                        Semantics(
                          liveRegion: true,
                          child: Text(reproductor.mensaje,
                              style: const TextStyle(fontSize: 12, color: MarcaColores.textoSuave)),
                        ),
                      ],
                    ),
                  ),
                  // Sin tooltip: la barra vive fuera del Navigator (no hay
                  // Overlay); la etiqueta accesible va por Semantics.
                  Semantics(
                    button: true,
                    label: 'Cerrar reproductor',
                    excludeSemantics: true,
                    child: IconButton(
                      key: const Key('mini-cerrar'),
                      constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
                      icon: const Icon(Icons.close, color: Colors.white),
                      onPressed: reproductor.cerrar,
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}
