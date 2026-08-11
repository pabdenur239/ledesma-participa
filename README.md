# Ledesma Participa

Medio digital hiperlocal con foco en Libertador General San Martín y el Departamento Ledesma (Jujuy, Argentina).

Estado actual: **Fase 2** (panel mínimo de revisión humana).

## Instalación

Requiere Python 3. No hay dependencias externas (solo biblioteca estándar).

```bash
git clone https://github.com/pabdenur239/ledesma-participa.git
cd ledesma-participa
```

## Ejecución

Ejecuta el pipeline completo (recolección → normalización → relevancia local →
deduplicación → redacción → almacenamiento) usando las noticias de prueba
incluidas en `data/fixtures/noticias_prueba.json`. La base SQLite se crea
automáticamente en `data/ledesma_participa.db` si no existe.

```bash
python3 run.py
```

## Pruebas

```bash
python3 -m unittest discover -s tests
```

## Recolección real: RSS de Prensa Jujuy

Existe un collector real para el RSS oficial de Prensa Jujuy
(configurado en `config/fuentes.json`). Requiere acceso normal a
internet desde el entorno donde se ejecute:

```bash
python3 run.py --fuente rss-prensa-jujuy
```

Las pruebas automáticas no acceden a este feed: usan un fixture XML
local (`data/fixtures/prensa_jujuy_rss_prueba.xml`).

## Recolección real: Municipio Libertador (HTML)

Existe un collector real para la página de actividades del intendente
de la Municipalidad de Libertador General San Martín (configurado en
`config/fuentes.json`). Requiere acceso normal a internet desde el
entorno donde se ejecute:

```bash
python3 run.py --fuente municipio-libertador
```

Las pruebas automáticas no acceden al sitio real: usan un fixture HTML
local (`data/fixtures/municipio_libertador_html_prueba.html`).

## Redacción real: Ollama local

Por defecto el pipeline redacta con `RedactorMock` (sin IA). Existe
además `RedactorOllama`, que usa un modelo local servido por
[Ollama](https://ollama.com) (configurado en `config/redaccion.json`,
endpoint `http://localhost:11434/api/chat`, modelo `qwen3:1.7b`). No
requiere instalar ningún paquete Python adicional ni claves de API;
solo requiere tener Ollama corriendo localmente con el modelo
descargado:

```bash
python3 run.py --fuente municipio-libertador --redactor ollama
```

Si Ollama no está disponible, el pipeline informa el error y se
detiene (no cambia automáticamente a otro proveedor). Las pruebas
automáticas no se conectan a Ollama: simulan sus respuestas.

## Panel de revisión humana

Panel web local y mínimo (solo biblioteca estándar) para revisar a mano
las noticias en estado `preparada` antes de cualquier publicación
futura. Nunca publica nada automáticamente: aprobar o rechazar solo
cambia `revision_estado` (`pendiente` / `aprobada` / `rechazada`) sobre
la misma base SQLite.

```bash
python3 run_panel.py
```

Queda disponible **únicamente** en `http://127.0.0.1:8000` (el servidor
se enlaza siempre a `127.0.0.1`, nunca a `0.0.0.0`). Permite filtrar
noticias preparadas por estado de revisión, ver el contenido original y
preparado, editar un título/texto revisado, y aprobar o rechazar. No
implementa autenticación: está pensado para uso exclusivamente local.

## Control de riesgo editorial político/institucional

Toda noticia se evalúa automáticamente (por reglas simples y
configurables en `config/riesgo_editorial.json`, sin IA) para detectar
contenido sobre la Municipalidad, el intendente, concejales, el Concejo
Deliberante, funcionarios, partidos políticos, candidatos/elecciones o
Pablo Abdenur (sin darle ningún tratamiento distinto al resto). Ese
contenido queda marcado con `requiere_revision_especial = true` y el
panel muestra una advertencia visible ("REVISIÓN POLÍTICA/INSTITUCIONAL
OBLIGATORIA") con la categoría y el motivo detectado. Esto no bloquea
la aprobación humana: solo impide que ese contenido pueda considerarse
publicable automáticamente en una futura etapa
(`motor_noticias.publicacion.puede_publicarse_automaticamente`, todavía
no conectada a ningún mecanismo de publicación).

## Preparación de publicación en Facebook (sin publicar)

Prepara, para noticias **aprobadas**, el contenido que en una futura
etapa podría publicarse en la página de Facebook "Ledesma Participa"
(`motor_noticias/meta/`): un post principal (título + reseña breve +
"Información completa en el primer comentario.") y un primer comentario
(texto completo, fuente, hashtags deterministas según localidad — sin
IA). Usa siempre `titulo_revisado`/`texto_revisado` cuando existen, con
fallback a `titulo_preparado`/`texto_preparado`; nunca vuelve a
pedirle contenido a una IA.

Desde el panel, las noticias aprobadas tienen un enlace "Preparar
publicación Facebook (modo prueba)" que muestra una vista previa
exacta marcada como **"MODO PRUEBA — NO SE PUBLICARÁ NADA"**. El modo
DRY RUN es el único implementado en esta fase: `ClienteMetaGraphAPI`
no contiene ningún camino de código que envíe una petición real a
Meta, y una noticia con `requiere_revision_especial = true` solo
admite DRY RUN, nunca publicación real, incluso estando aprobada.

Credenciales por variables de entorno (ver `.env.example`, nunca
versionadas): `META_PAGE_ID` (dato público, con un valor por defecto
ya confirmado) y `META_PAGE_ACCESS_TOKEN` (sin valor por defecto,
nunca hardcodeado ni mostrado en salidas o logs). `.env` está
ignorado por Git.

### Placa generada automáticamente cuando no hay imagen

Ninguno de los collectors actuales extrae todavía una imagen de la
fuente, así que hoy toda noticia usa este mecanismo; el modelo de datos
ya está preparado para cuando alguno la extraiga (`tiene_imagen_original`).
Si la noticia no tiene imagen original, al preparar la publicación de
Facebook se genera automáticamente una placa 1200×1200 en **SVG**
(`motor_noticias/meta/imagen.py`) con el branding "Ledesma Participa",
el título, una bajada breve, la fuente y la localidad — usando
exclusivamente `titulo_revisado`/`texto_revisado` (o su fallback
preparado), nunca IA. Se eligió SVG generado por código en vez de
Pillow porque Pillow no está disponible en este entorno y agregarla
sería una dependencia nueva para una tarea que el proyecto puede
resolver con biblioteca estándar (`textwrap` para el recorte
determinístico de líneas largas). Nota para una etapa futura: Facebook
no acepta SVG para publicar fotos, así que antes de publicar de verdad
esa placa deberá convertirse a PNG/JPEG.

Las placas se guardan en `data/placas/` (generado localmente, ignorado
por Git), con un nombre de archivo derivado del contenido exacto
(título + bajada + fuente + localidad): el mismo contenido siempre
reutiliza el mismo archivo, sin regenerarlo. La ruta usada para
publicación y si fue generada automáticamente quedan persistidas en la
noticia (`imagen_publicacion_ruta`, `imagen_generada_automaticamente`),
migración SQLite no destructiva. La vista previa de Facebook del panel
(`/facebook?id=...`) muestra esa imagen embebida junto con una
indicación clara de si es "imagen original" o "placa generada
automáticamente" — la placa se genera incluso para noticias con riesgo
político/institucional, ya que solo habilita la previsualización en
DRY RUN, nunca publicación real, y nunca reemplaza la revisión humana.
