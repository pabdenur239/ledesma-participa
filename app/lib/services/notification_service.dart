import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

/// Infraestructura de notificaciones push, preparada pero NO activa hasta
/// que exista un proyecto real de Firebase (requiere acceso a la consola
/// de Firebase del dueño del proyecto — ver README.md, sección
/// "Notificaciones push"). Sin `firebase_options.dart` real generado por
/// `flutterfire configure`, `Firebase.initializeApp()` falla — se captura
/// el error y la app sigue funcionando normalmente sin push, en vez de
/// romperse.
///
/// Uso previsto una vez configurado: el backend (VPS) dispararía un envío
/// SOLO para dos casos — noticias urgentes y noticias locales importantes
/// — nunca una notificación por cada publicación (regla explícita del
/// proyecto). Ese disparo del lado del servidor todavía no está
/// implementado: queda fuera de este MVP, es un paso posterior una vez
/// exista el proyecto de Firebase real.
class NotificationService {
  Future<bool> inicializar() async {
    try {
      await Firebase.initializeApp();
      final messaging = FirebaseMessaging.instance;
      await messaging.requestPermission();
      final token = await messaging.getToken();
      if (kDebugMode) {
        debugPrint('FCM token (solo para pruebas manuales): $token');
      }
      return true;
    } catch (error) {
      // Esperable hasta que se configure un proyecto real de Firebase.
      if (kDebugMode) {
        debugPrint('Notificaciones push no configuradas todavía: $error');
      }
      return false;
    }
  }
}
