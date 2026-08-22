import 'package:flutter/material.dart';

import 'screens/home_screen.dart';
import 'services/notification_service.dart';
import 'theme.dart';

void main() {
  runApp(const LedesmaParticipaApp());
  // No bloquea el arranque de la app: si Firebase no está configurado
  // todavía (ver README, sección "Notificaciones push"), esto no hace
  // nada y no rompe nada.
  NotificationService().inicializar();
}

class LedesmaParticipaApp extends StatelessWidget {
  const LedesmaParticipaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Ledesma Participa',
      debugShowCheckedModeBanner: false,
      theme: construirTema(),
      home: const HomeScreen(),
    );
  }
}
