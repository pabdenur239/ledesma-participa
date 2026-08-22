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

## Notificaciones push (Android preparado por completo, solo falta el proyecto de Firebase)

El paquete (`firebase_core` + `firebase_messaging` + `flutter_local_notifications`)
y el código (`lib/services/notification_service.dart`) ya están completos:
inicialización, canal de notificación, primer plano, segundo plano, app
cerrada, y abrir la noticia correcta al tocar la notificación (usa
`data: {"noticia_id": "<id>"}` del mensaje). **No está activo** porque
falta un proyecto real de Firebase — eso requiere acceso a una cuenta/
consola de Firebase que no es algo que se pueda crear sin intervención
humana.

Diseño: la app se suscribe a un solo tópico de FCM
(`ledesma_participa_importantes`) en vez de que el VPS tenga que guardar
tokens por dispositivo — sin backend nuevo de registro. El servidor solo
necesita publicar al tópico cuando corresponda.

**Bloqueo — pasos manuales exactos (dueño del proyecto):**

1. Crear un proyecto en https://console.firebase.google.com
2. Agregar una app Android con el `applicationId` exacto
   `com.ledesmaparticipa.ledesma_participa_app` (ver
   `android/app/build.gradle.kts`) y descargar `google-services.json` →
   colocarlo en `app/android/app/google-services.json`.
3. En `app/android/settings.gradle.kts` y `app/android/app/build.gradle.kts`,
   descomentar el plugin de Google Services (buscar el comentario
   `// Firebase:` — ya está indicado dónde, es una sola línea en cada
   archivo).
4. (Para más adelante, cuando se implemente el envío desde el VPS) generar
   una credencial de servidor: Firebase Console → Configuración del
   proyecto → Cuentas de servicio → Generar nueva clave privada. Es un
   archivo JSON **distinto** de `google-services.json` — nunca debe
   quedar en el repo (ver `.gitignore`).

Con eso (pasos 1-3) alcanza para Android: `Firebase.initializeApp()` deja
de fallar, se pide el permiso de notificaciones, se suscribe al tópico y
se genera el token real en el dispositivo — verificable con
`adb logcat | grep "FCM token"`.

**iOS** (fuera de esta ejecución, dejado preparado): además de los pasos
de Firebase para iOS (Bundle ID, `GoogleService-Info.plist` en
`app/ios/Runner/`), requiere una APNs Authentication Key desde
https://developer.apple.com/account (Certificates, Identifiers & Profiles
→ Keys), subida en la consola de Firebase. No se puede compilar ni
probar sin una Mac con Xcode.

**Envío real desde el VPS:** no implementado todavía — depende del paso 4
de arriba (credencial de servidor). Cuando exista, es un script mínimo
nuevo (Firebase Admin SDK) que publica al tópico `ledesma_participa_importantes`
solo para urgentes reales o locales/departamentales de alta importancia,
nunca por cada publicación — sin tocar el pipeline editorial existente.

## Identidad visual

Reutiliza exactamente la paleta de marca ya usada en el sitio web y en las
placas de Meta (`motor_noticias/meta/imagen.py`, `docs/assets/site.css`):
fondo `#141414`, marca `#1F1A10`, oro `#D4AF37`, naranja `#E8631C`. Sin
rediseño de marca.

## Qué NO incluye este MVP

Registro de usuarios, comentarios, chats, pagos, publicidad, panel
administrativo, perfiles, contenido generado por usuarios — igual que
especifica el alcance del proyecto.
