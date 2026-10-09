// Smoke tests: la app arranca con la marca y los accesos de Inicio, y los
// modelos leen la clasificación separada (territorio / categoría /
// urgente), Clima + Dólar con datos faltantes, Guía Comercial y videos,
// sin depender de red.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ledesma_participa_app/main.dart';
import 'package:ledesma_participa_app/models/noticia.dart';
import 'package:ledesma_participa_app/screens/home_screen.dart';

void main() {
  testWidgets('La app arranca y muestra la marca y los accesos', (WidgetTester tester) async {
    await tester.pumpWidget(LedesmaParticipaApp(navigatorKey: GlobalKey<NavigatorState>()));
    await tester.pump();

    expect(find.text('LEDESMA '), findsOneWidget);
    expect(find.text('PARTICIPA'), findsOneWidget);
    expect(find.text('Últimas'), findsOneWidget);
    expect(find.text('Libertador'), findsOneWidget);
  });

  test('Accesos de Inicio pedidos en la Etapa 1', () {
    final etiquetas = accesosInicio.map((a) => a.$2).toList();
    expect(etiquetas, [
      'Últimas', 'Libertador', 'Departamento Ledesma', 'Jujuy', 'Policiales', 'Salud', 'Deportes', 'Servicios',
      'Videos', 'Guía Comercial', 'Multimedia',
    ]);
  });

  test('Noticia lee territorio, categoría y urgente por separado', () {
    final n = Noticia.fromJson({
      'id': 7,
      'titulo': 'Corte de agua en Alberdi',
      'urgente': true,
      'territorio_etiqueta': 'Libertador',
      'categoria_tema': 'servicios',
      'categoria_tema_etiqueta': 'Servicios',
      'clasificacion': {
        'territorio': {'valor': 'libertador', 'etiqueta': 'Libertador General San Martín', 'confianza': 0.96},
        'categoria': {'valor': 'servicios', 'etiqueta': 'Servicios', 'confianza': 0.9},
        'urgente': true,
      },
    });
    expect(n.territorio, 'libertador');
    expect(n.categoriaTemaEtiqueta, 'Servicios');
    expect(n.esServicio, isTrue);
    expect(n.urgente, isTrue);
  });

  test('Clima + Dólar con datos faltantes queda en null (No disponible)', () {
    final d = ClimaDolar.fromJson({
      'fecha_legible': 'Viernes 9 de octubre',
      'actualizado': '07:30',
      'fuentes': 'Open-Meteo / DolarApi',
      'clima': null,
      'oficial': {'compra': 1400, 'venta': 1450},
      'blue': null,
    })!;
    expect(d.hayClima, isFalse);
    expect(d.oficial!.venta, 1450);
    expect(d.blue, isNull);
  });

  test('Portada omite secciones vacías y lee guía y videos', () {
    final p = Portada.fromJson({
      'urgentes': [],
      'clima_dolar': null,
      'principal': null,
      'secciones': [
        {'slug': 'salud', 'etiqueta': 'Salud', 'noticias': []},
        {
          'slug': 'policiales',
          'etiqueta': 'Policiales',
          'noticias': [
            {'id': 1, 'titulo': 'Robo en el centro'}
          ]
        },
      ],
      'videos': [
        {'id': 'dQw4w9WgXcQ', 'titulo': 'Video', 'miniatura': 'https://i.ytimg.com/x.jpg', 'url': 'https://ledesmaparticipa.com.ar/videos/dQw4w9WgXcQ/'}
      ],
      'guia_comercial': [
        {'slug': 'un-clasico', 'nombre': 'Un Clásico', 'rubro': 'Drugstore y librería', 'imagenes': [], 'promociones': [], 'contacto': null}
      ],
    });
    expect(p.secciones.map((s) => s.slug), ['policiales']);
    expect(p.videos.single.id, 'dQw4w9WgXcQ');
    expect(p.guiaComercial.single.whatsapp, isNull);
    expect(p.guiaComercial.single.contactoUrl, isNull);
  });
}
