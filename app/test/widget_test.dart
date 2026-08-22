// Smoke test: la app arranca y muestra el nombre de marca y las pestañas
// mínimas de categoría, sin depender de red (no espera a que las
// peticiones HTTP terminen).
import 'package:flutter_test/flutter_test.dart';

import 'package:ledesma_participa_app/main.dart';

void main() {
  testWidgets('La app arranca y muestra la marca y las pestañas', (WidgetTester tester) async {
    await tester.pumpWidget(const LedesmaParticipaApp());
    await tester.pump();

    expect(find.text('Ledesma Participa'), findsOneWidget);
    expect(find.text('Inicio'), findsOneWidget);
    expect(find.text('Locales'), findsOneWidget);
    expect(find.text('Policiales'), findsOneWidget);
    expect(find.text('Deportes'), findsOneWidget);
  });
}
