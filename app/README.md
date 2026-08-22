# Ledesma Participa — app móvil

App móvil oficial de Ledesma Participa (Android/iOS). Es un **canal de
distribución nuevo del sistema existente**: no tiene motor de noticias
propio, no duplica la base de datos y no toca la operación actual de
Facebook/Instagram/Stories/web. Consume la misma información que ya
publica el sitio web (`ledesmaparticipa.com.ar`), servida como JSON
estático desde el mismo hosting (GitHub Pages) — no hay ningún servidor
nuevo.

## Arquitectura

```
motor_noticias/sitio/generador.py   (YA EXISTÍA, generador del sitio web)
        │  se le agregó: además del HTML, ahora también escribe
        │  docs/api/*.json con los mismos datos
        ▼
GitHub Pages (ledesmaparticipa.com.ar)  ← mismo hosting, mismo dominio
        │
        │  GET https://ledesmaparticipa.com.ar/api/feed.json
        │  GET https://ledesmaparticipa.com.ar/api/urgentes.json
        │  GET https://ledesmaparticipa.com.ar/api/categoria/{slug}.json
        │  GET https://ledesmaparticipa.com.ar/api/noticia/{id}.json
        │  GET https://ledesmaparticipa.com.ar/assets/search-index.json (ya existía)
        ▼
   app/  (este proyecto Flutter — Android + iOS desde un solo código)
```

La API se regenera cada vez que se regenera el sitio (mismo timer que ya
corre en el VPS cada 15 min, `ledesma-sitio-web.timer` — no se tocó su
frecuencia). Es de **solo lectura**: nunca expone credenciales de Meta ni
del VPS, ni campos de trabajo interno (revisión, observaciones).

## Categorías

Las categorías de la app usan la clasificación real que ya existe en el
sistema (territorio + `categoria_tematica`):

| Categoría (app) | Fuente real | Estado |
|---|---|---|
| Locales | `territorio` local + departamental | ✅ con datos |
| Provinciales | `territorio` provincial | ✅ con datos |
| Nacionales | `territorio` nacional | ✅ con datos (puede estar vacía si no se publicó nada nacional recientemente) |
| Internacionales | `categoria_tematica = internacional` | ✅ con datos |
| Espectáculos | `categoria_tematica = espectaculos` | ✅ con datos |
| Salud | `categoria_tematica = salud` | ✅ con datos |
| Gastronomía | `categoria_tematica = gastronomia` | ✅ con datos |
| **Policiales** | — | ⚠️ **sin clasificación real hoy** — la pestaña existe y queda vacía a propósito, en vez de inventar un clasificador nuevo fuera del Motor Editorial |
| **Deportes** | — | ⚠️ **sin clasificación real hoy**, mismo motivo |

Si más adelante se decide clasificar policiales/deportes en el backend
(nueva `categoria_tematica` o similar), la app ya tiene la pestaña lista:
solo hace falta que `api/categoria/policiales.json` y
`api/categoria/deportes.json` empiecen a traer datos.

## Requisitos para compilar

- Flutter SDK (canal stable) — https://docs.flutter.dev/get-started/install
- Android: Android SDK + `flutter doctor --android-licenses` aceptadas.
- iOS: **requiere macOS + Xcode** (no se puede compilar iOS desde Windows/Linux).

## Ejecutar / compilar

```bash
cd app
flutter pub get

# Ver la app en un emulador/dispositivo conectado:
flutter run

# Compilar APK de Android:
flutter build apk --debug     # o --release

# Compilar para iOS (solo en macOS con Xcode):
flutter build ios
```

## Notificaciones push (preparado, no activo)

El paquete (`firebase_core` + `firebase_messaging`) y el código
(`lib/services/notification_service.dart`) ya están en el proyecto. **No
están activos** porque falta un proyecto real de Firebase — eso requiere
acceso a una cuenta/consola de Firebase que no es algo que se pueda crear
sin intervención humana. Pasos manuales pendientes (bloqueo a resolver
por el dueño del proyecto):

1. Crear un proyecto en https://console.firebase.google.com
2. Agregar una app Android con el `applicationId` real del build (ver
   `android/app/build.gradle`) y descargar `google-services.json` →
   colocarlo en `app/android/app/google-services.json`.
3. Agregar una app iOS con el Bundle ID real y descargar
   `GoogleService-Info.plist` → colocarlo en `app/ios/Runner/`.
4. Para iOS además: generar una **APNs Authentication Key** en
   https://developer.apple.com/account (Certificates, Identifiers & Profiles
   → Keys) y subirla en la consola de Firebase (Configuración del
   proyecto → Cloud Messaging).
5. Correr `flutterfire configure` (o crear `lib/firebase_options.dart` a
   mano) para generar la configuración de Dart.
6. En `android/app/build.gradle` y `android/build.gradle`, descomentar el
   plugin de Google Services (buscar el comentario `// Firebase:` — se
   deja indicado dónde).

Una vez hecho eso, la infraestructura ya registra el token del
dispositivo (ver `NotificationService`). El **envío real** de
notificaciones (disparado desde el VPS solo para urgentes/locales
importantes, nunca por cada publicación) es un paso posterior, fuera de
este MVP — no está implementado todavía del lado del servidor.

## Identidad visual

Reutiliza exactamente la paleta de marca ya usada en el sitio web y en las
placas de Meta (`motor_noticias/meta/imagen.py`, `docs/assets/site.css`):
fondo `#141414`, marca `#1F1A10`, oro `#D4AF37`, naranja `#E8631C`. Sin
rediseño de marca.

## Qué NO incluye este MVP

Registro de usuarios, comentarios, chats, pagos, publicidad, panel
administrativo, perfiles, contenido generado por usuarios — igual que
especifica el alcance del proyecto.
