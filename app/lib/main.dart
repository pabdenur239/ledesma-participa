import 'package:flutter/material.dart';

import 'screens/home_screen.dart';
import 'services/notification_service.dart';
import 'theme.dart';
import 'widgets/mini_reproductor.dart';
import 'services/telemetria.dart';

final navigatorKey = GlobalKey<NavigatorState>();

void main() {
  Telemetria.instancia.evento('app_open');
  runApp(LedesmaParticipaApp(navigatorKey: navigatorKey));
  // No bloquea el arranque de la app: si Firebase no está configurado
  // todavía (ver README, sección "Notificaciones push"), esto no hace
  // nada y no rompe nada. navigatorKey le permite abrir la noticia
  // correcta al tocar una notificación sin depender del árbol de widgets.
  NotificationService(navigatorKey).inicializar();
}

class LedesmaParticipaApp extends StatelessWidget {
  final GlobalKey<NavigatorState> navigatorKey;

  const LedesmaParticipaApp({super.key, required this.navigatorKey});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: navigatorKey,
      title: 'Ledesma Participa',
      debugShowCheckedModeBanner: false,
      theme: construirTema(),
      home: const HomeScreen(),
      // Radios en vivo (Etapa 2): el mini reproductor vive por encima del
      // Navigator, así el audio sigue mientras se navega por la app.
      builder: (context, child) => Column(
        children: [
          Expanded(child: child ?? const SizedBox.shrink()),
          MiniReproductor(),
        ],
      ),
    );
  }
}
