import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import '../screens/detalle_screen.dart';

/// Infraestructura de notificaciones push, preparada pero NO activa hasta
/// que exista un proyecto real de Firebase (requiere acceso a la consola
/// de Firebase del dueño del proyecto — ver README.md, sección
/// "Notificaciones push"). Sin `google-services.json` real,
/// `Firebase.initializeApp()` falla — se captura el error y la app sigue
/// funcionando normalmente sin push, en vez de romperse.
///
/// Diseño deliberadamente simple, sin backend nuevo de registro de
/// tokens: la app se suscribe a UN solo tópico de FCM
/// ([_topicoNotificaciones]) en vez de que el VPS tenga que guardar y
/// mantener una base de tokens por dispositivo. El VPS (una vez exista el
/// proyecto de Firebase y su credencial de servidor — Admin SDK) publica
/// al tópico solo cuando corresponde: nunca por cada publicación, solo
/// urgentes reales o locales/departamentales de alta importancia (regla
/// editorial, se aplica del lado del servidor, no acá).
///
/// El payload de cada mensaje debe incluir `data: {"noticia_id": "<id>"}`
/// para poder abrir la noticia correcta al tocar la notificación — con
/// la app en primer plano, en segundo plano o cerrada, los tres casos
/// están cubiertos acá.
class NotificationService {
  static const _topicoNotificaciones = 'ledesma_participa_importantes';
  static const _canalId = 'ledesma_participa_importantes';
  static const _canalNombre = 'Noticias importantes';
  static const _canalDescripcion =
      'Urgentes reales y noticias locales/departamentales de alta importancia — nunca una por cada publicación.';

  final GlobalKey<NavigatorState> navigatorKey;
  final FlutterLocalNotificationsPlugin _notificacionesLocales = FlutterLocalNotificationsPlugin();

  // Dedup: getInitialMessage() y onMessageOpenedApp pueden entregar el
  // mismo mensaje (mismo arranque en frío tocando la notificación) — sin
  // esto, se navegaría dos veces a la misma noticia.
  String? _ultimoMessageIdAbierto;

  NotificationService(this.navigatorKey);

  Future<bool> inicializar() async {
    try {
      await Firebase.initializeApp();

      // Bug real corregido: estos tres registros (apertura por toque) se
      // hacían al FINAL de esta función, después de varios `await` lentos
      // (permiso de notificaciones, suscripción al tópico, token FCM). Con
      // la app recién resumida desde segundo plano y el dispositivo
      // aplicando su propia gestión agresiva de batería (Motorola
      // "moto_freezer"), esa cadena podía no terminar de correr todavía
      // cuando llegaba el toque de la notificación — el evento de
      // `onMessageOpenedApp` se perdía en silencio porque nadie estaba
      // escuchando. Van primero, inmediatamente después de initializeApp,
      // sin nada más por delante.
      FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);
      FirebaseMessaging.onMessageOpenedApp.listen(_manejarAperturaPorNotificacion);
      final mensajeInicial = await FirebaseMessaging.instance.getInitialMessage();
      if (mensajeInicial != null) {
        _manejarAperturaPorNotificacion(mensajeInicial);
      }

      await _notificacionesLocales.initialize(
        const InitializationSettings(
          android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        ),
        onDidReceiveNotificationResponse: (respuesta) {
          final noticiaId = respuesta.payload;
          if (noticiaId != null) _abrirNoticiaCuandoElNavigatorEsteListo(noticiaId);
        },
      );
      await _notificacionesLocales
          .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
          ?.createNotificationChannel(const AndroidNotificationChannel(
            _canalId, _canalNombre,
            description: _canalDescripcion,
            importance: Importance.high,
          ));

      final messaging = FirebaseMessaging.instance;
      await messaging.requestPermission();
      await messaging.subscribeToTopic(_topicoNotificaciones);

      final token = await messaging.getToken();
      if (kDebugMode) {
        debugPrint('FCM token (solo para pruebas manuales): $token');
      }

      // Primer plano: FCM no muestra nada solo — se arma la notificación
      // del sistema a mano, reutilizando el mismo canal.
      FirebaseMessaging.onMessage.listen(_mostrarNotificacionEnPrimerPlano);

      return true;
    } catch (error) {
      // Esperable hasta que se configure un proyecto real de Firebase.
      if (kDebugMode) {
        debugPrint('Notificaciones push no configuradas todavía: $error');
      }
      return false;
    }
  }

  void _manejarAperturaPorNotificacion(RemoteMessage mensaje) {
    final noticiaId = mensaje.data['noticia_id'];
    if (noticiaId == null) return;
    final idMensaje = mensaje.messageId;
    if (idMensaje != null && idMensaje == _ultimoMessageIdAbierto) {
      return; // ya se navegó por este mismo mensaje (getInitialMessage + onMessageOpenedApp)
    }
    _ultimoMessageIdAbierto = idMensaje;
    _abrirNoticiaCuandoElNavigatorEsteListo(noticiaId);
  }

  Future<void> _mostrarNotificacionEnPrimerPlano(RemoteMessage mensaje) async {
    final notif = mensaje.notification;
    if (notif == null) return;
    await _notificacionesLocales.show(
      mensaje.hashCode,
      notif.title,
      notif.body,
      const NotificationDetails(
        android: AndroidNotificationDetails(
          _canalId, _canalNombre,
          channelDescription: _canalDescripcion,
          importance: Importance.high,
          priority: Priority.high,
        ),
      ),
      payload: mensaje.data['noticia_id'],
    );
  }

  /// Bug real corregido: antes usaba `navigatorKey.currentState?.push(...)`
  /// directo — si el Navigator todavía no estaba montado (primer frame sin
  /// dibujar todavía), el `?.` descartaba la apertura en silencio, sin
  /// reintento ni error. Ahora espera al próximo frame construido antes de
  /// navegar, las veces que haga falta.
  void _abrirNoticiaCuandoElNavigatorEsteListo(String noticiaId) {
    final id = int.tryParse(noticiaId);
    if (id == null) return;

    void intentar() {
      final estado = navigatorKey.currentState;
      if (estado == null) {
        WidgetsBinding.instance.addPostFrameCallback((_) => intentar());
        return;
      }
      estado.push(MaterialPageRoute(builder: (_) => DetalleScreen(noticiaId: id)));
    }

    intentar();
  }
}

/// Debe ser una función de nivel superior (no un método): FCM la ejecuta
/// en un isolate aparte cuando llega un mensaje con la app completamente
/// cerrada. No navega ni toca UI — con la app cerrada, Android ya muestra
/// la notificación solo (canal por defecto, ver AndroidManifest.xml); acá
/// solo hace falta inicializar Firebase para que el propio sistema pueda
/// procesar el mensaje.
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage mensaje) async {
  await Firebase.initializeApp();
}
