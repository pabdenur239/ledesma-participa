import 'package:flutter/material.dart';

import 'screens/home_screen.dart';
import 'services/notification_service.dart';
import 'theme.dart';

final navigatorKey = GlobalKey<NavigatorState>();

void main() {
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
    );
  }
}
