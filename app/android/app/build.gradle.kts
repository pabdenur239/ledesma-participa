import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
    // Firebase: activado — google-services.json real ya en android/app/.
    id("com.google.gms.google-services")
}

// Firma de release: keystore y contraseñas guardados fuera del repo
// (C:\Users\benic\ledesma-participa-keystore\), nunca commiteados.
// Si el archivo no existe (ej. build de otra máquina), release cae a la
// firma debug para no romper `flutter build` en ese entorno.
val releaseKeystoreProperties = Properties()
val releaseKeystorePropertiesFile = file("C:/Users/benic/ledesma-participa-keystore/key.properties")
val hasReleaseSigning = releaseKeystorePropertiesFile.exists()
if (hasReleaseSigning) {
    releaseKeystoreProperties.load(releaseKeystorePropertiesFile.inputStream())
}

android {
    namespace = "com.ledesmaparticipa.ledesma_participa_app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
        // Requerido por flutter_local_notifications (notificaciones push
        // en primer plano, ver notification_service.dart).
        isCoreLibraryDesugaringEnabled = true
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.ledesmaparticipa.ledesma_participa_app"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(releaseKeystoreProperties.getProperty("storeFile"))
                storePassword = releaseKeystoreProperties.getProperty("storePassword")
                keyAlias = releaseKeystoreProperties.getProperty("keyAlias")
                keyPassword = releaseKeystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (hasReleaseSigning) {
                signingConfigs.getByName("release")
            } else {
                // Sin keystore de release disponible en esta máquina: cae a
                // debug para no romper `flutter run --release` local.
                signingConfigs.getByName("debug")
            }
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

dependencies {
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.4")
}
