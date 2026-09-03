// La sección Contacto es accesible desde la portada y muestra el correo y
// los enlaces del medio (requisito Google Play "News and Magazines").
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ledesma_participa_app/main.dart';
import 'package:ledesma_participa_app/screens/contacto_screen.dart';

void main() {
  testWidgets('Contacto se abre desde la portada y muestra los datos del medio', (tester) async {
    await tester.pumpWidget(LedesmaParticipaApp(navigatorKey: GlobalKey<NavigatorState>()));
    await tester.pump();

    await tester.tap(find.byTooltip('Contacto'));
    await tester.pumpAndSettle();

    expect(find.byType(ContactoScreen), findsOneWidget);
    expect(find.text('ledesmaparticipa@gmail.com'), findsOneWidget);
    expect(find.text('https://ledesmaparticipa.com.ar/'), findsOneWidget);
    expect(find.text('https://ledesmaparticipa.com.ar/contacto/'), findsOneWidget);
  });
}
