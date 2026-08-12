# Ledesma Participa

Medio digital hiperlocal con foco en Libertador General San Martín y el Departamento Ledesma (Jujuy, Argentina).

Estado actual: **Fase 2** (panel mínimo de revisión humana).

## Instalación

Requiere Python 3. Una única dependencia externa —
[Pillow](https://pillow.readthedocs.io/), para generar las placas PNG
cuando una noticia no tiene imagen (ver más abajo); el resto del
proyecto sigue usando solo biblioteca estándar.

```bash
git clone https://github.com/pabdenur239/ledesma-participa.git
cd ledesma-participa
pip install -r requirements.txt
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

## Recolección real: InfoYungas (HTML)

Existe un collector real para el listado de noticias de InfoYungas
(configurado en `config/fuentes.json`), medio local que cubre
Libertador General San Martín, Ledesma y las Yungas. A diferencia del
collector municipal, no asigna una localidad fija: la relevancia
geográfica de cada noticia se deriva de su contenido con el
clasificador existente. Requiere acceso normal a internet desde el
entorno donde se ejecute:

```bash
python3 run.py --fuente infoyungas
```

Las pruebas automáticas no acceden al sitio real: usan un fixture HTML
local (`data/fixtures/infoyungas_html_prueba.html`).

## Recolección real: Jujuy al Momento (HTML)

Existe un collector real para el listado de noticias de Jujuy al Momento
(configurado en `config/fuentes.json`), medio provincial. Es una fuente
provincial: no asigna una localidad fija, la relevancia geográfica de
cada noticia se deriva de su contenido con el clasificador existente
(igual que InfoYungas), lo que evita que se cuele contenido genérico de
Jujuy sin relación con Libertador General San Martín o el Departamento
Ledesma. El sitio no expone ninguna fecha estable en el listado, así que
ese campo siempre queda vacío. Requiere acceso normal a internet desde
el entorno donde se ejecute:

```bash
python3 run.py --fuente jujuy-al-momento
```

Las pruebas automáticas no acceden al sitio real: usan un fixture HTML
local (`data/fixtures/jujuyalmomento_html_prueba.html`).

## Recolección real: El Tribuno de Jujuy (HTML)

Existe un collector real para el listado de noticias de El Tribuno de
Jujuy (configurado en `config/fuentes.json`), medio provincial. El sitio
no ofrece RSS/Atom (su página "RSS" en realidad lista redes sociales, no
feeds); el listado se extrae de la portada HTML. Es una fuente
provincial: no asigna una localidad fija, la relevancia geográfica de
cada noticia se deriva de su contenido con el clasificador existente. A
diferencia de InfoYungas y Jujuy al Momento, el sitio sí expone una
fecha explícita y estable: el propio permalink de cada nota incluye la
fecha y hora de publicación (p. ej.
`/seccion/2026-8-12-9-30-0-titulo-slug`), de donde se extrae sin
inferirla. Requiere acceso normal a internet desde el entorno donde se
ejecute:

```bash
python3 run.py --fuente tribuno-jujuy
```

Las pruebas automáticas no acceden al sitio real: usan un fixture HTML
local (`data/fixtures/tribuno_jujuy_html_prueba.html`).

## Recolección real: TodoJujuy (RSS)

Existe un collector real para el canal RSS "Jujuy" de TodoJujuy
(configurado en `config/fuentes.json`), medio provincial. Es una fuente
provincial: no asigna una localidad fija, la relevancia geográfica de
cada noticia se deriva de su contenido con el clasificador existente.
La imagen viene en el `<enclosure url="...">` de cada ítem (no todos los
ítems la incluyen) y la fecha es el `pubDate` del feed tal como lo
expone la fuente. Requiere acceso normal a internet desde el entorno
donde se ejecute:

```bash
python3 run.py --fuente todojujuy
```

Las pruebas automáticas no acceden al feed real: usan un fixture XML
local (`data/fixtures/todojujuy_rss_prueba.xml`).

## Recolección real: Somos Jujuy (RSS)

Existe un collector real para el feed RSS de Somos Jujuy (configurado
en `config/fuentes.json`), medio provincial. Es una fuente provincial:
no asigna una localidad fija, la relevancia geográfica de cada noticia
se deriva de su contenido con el clasificador existente. A diferencia
de TodoJujuy, la imagen no viene en un campo separado: está embebida
como `<img src="...">` al principio del HTML de `<description>`, seguida
de un `<p>` con el resumen; el collector extrae la imagen de ahí y
limpia el resto del HTML para quedarse solo con el texto. El feed
declara codificación `iso-8859-1`, por lo que el collector procesa la
respuesta como bytes crudos (sin decodificarla de antemano) para que
los acentos se interpreten correctamente. Requiere acceso normal a
internet desde el entorno donde se ejecute:

```bash
python3 run.py --fuente somos-jujuy
```

Las pruebas automáticas no acceden al feed real: usan un fixture XML
local (`data/fixtures/somosjujuy_rss_prueba.xml`).

## Recolección real: La Nación e Infobae (RSS nacionales)

Existen collectors reales para los feeds RSS de La Nación e Infobae
(configurados en `config/fuentes.json`), ambos medios nacionales sobre
la plataforma Arc XP y por lo tanto con el mismo dialecto RSS —
comparten un mismo módulo de parseo (`motor_noticias/collectors/rss_arc_nacional.py`).
Ninguna noticia de estas fuentes se marca como "nacional" solo por
venir de ahí: pasa por el mismo clasificador territorial que el resto,
pudiendo resultar local, departamental, provincial, nacional o sin
clasificar según su contenido. El feed real de Infobae es internacional
(sin `<category>`, con el país codificado en la URL), por lo que la
mayoría de sus notas no son de alcance argentino.

El resumen usa `description` cuando trae un texto útil, o si no,
`content:encoded` limpio de HTML/scripts/estilos, nunca la nota
completa. La imagen se toma de `media:content`, luego
`media:thumbnail`, luego un `<img>` embebido válido — ignorando
píxeles, íconos y logos. La fecha es el `pubDate` del feed tal como lo
expone la fuente. Se excluyen determinísticamente (por categoría o
segmento de URL, sin IA) horóscopo, lotería/sorteos y contenido
publicitario/patrocinado; deportes y espectáculos no se bloquean pero
tienen un tope para no dominar el lote. Límite de 25 ítems recientes
por fuente y ciclo. Requieren acceso normal a internet desde el
entorno donde se ejecuten:

```bash
python3 run.py --fuente la-nacion
python3 run.py --fuente infobae
```

Las pruebas automáticas no acceden a los feeds reales: usan fixtures
XML locales (`data/fixtures/lanacion_rss_prueba.xml` y
`data/fixtures/infobae_rss_prueba.xml`).

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

## Motor continuo de noticias

Servicio local (solo biblioteca estándar) que consulta automáticamente,
cada 30 minutos por defecto, las fuentes reales ya incorporadas
(Prensa Jujuy, Municipio Libertador, InfoYungas, Jujuy al Momento, El
Tribuno de Jujuy, TodoJujuy, Somos Jujuy, La Nación e Infobae),
reutilizando el mismo
pipeline y las mismas reglas de relevancia, deduplicación y riesgo
editorial que la ejecución manual — no publica nada, todo sigue
requiriendo revisión humana en el panel.

```bash
python3 run_continuo.py
```

Ejecuta un primer ciclo de inmediato y luego repite cada
`--intervalo` segundos (default `1800`, es decir 30 minutos). Se
detiene de forma limpia con Ctrl+C. Evita dos instancias simultáneas
mediante un archivo de lock (`data/run_continuo.lock`, se libera al
cerrar); si un cierre previo no fue limpio, borrar ese archivo antes de
reintentar. Registra logs entendibles tanto en la consola como en
`data/logs/run_continuo.log`.

Una fuente que falla (error de red, HTTP, parseo, etc.) nunca detiene
el ciclo: se registra el error y se sigue con las demás. Por cada
fuente se guarda en SQLite (tablas nuevas, no destructivas:
`fuente_salud` y `ciclo_ejecucion`) su último resultado (`ok`/`error`),
cantidad de elementos y noticias nuevas obtenidas, fecha de la última
noticia recibida, último mensaje de error y fallos consecutivos.

A partir de ese estado se calculan alertas internas (todavía sin
enviar nada por fuera del sistema: sin WhatsApp, email ni
notificaciones externas) — "fuente con fallas" tras 3 fallos
consecutivos, "fuente inactiva" si una fuente que responde OK lleva 24
horas sin traer ninguna noticia nueva, y "sin información local" si
pasan 6 horas sin ninguna noticia relevante para Libertador o el
Departamento Ledesma. Ninguna alerta asume que una fuente está caída
solo por no publicar contenido nuevo.

## Clasificación territorial y elegibilidad editorial

Cada noticia se clasifica de forma determinística (sin IA, `motor_noticias/territorio.py`)
en `local`, `departamental`, `provincial`, `nacional` o `sin_clasificar`,
reutilizando sin modificar el clasificador de relevancia existente y
agregando un nivel nacional configurable en `config/localidades.json`
("nacional"). `relevancia_local` conserva exactamente el mismo
significado que siempre tuvo (relación directa con Libertador o el
Departamento Ledesma); local y departamental siguen preparándose
siempre. Provincial y nacional ahora también pueden llegar a
`preparada` —sin relevancia_local— si superan un gate mínimo de calidad
editorial sin IA (`motor_noticias/elegibilidad_editorial.py`: descarta
publicidad, navegación, contenido vacío o insuficiente). Sin
clasificación geográfica ni nacional identificable, nunca se prepara
automáticamente.

## Motor Editorial en Cascada y Agenda Editorial

Selecciona automáticamente, para cada espacio de publicación del día,
la mejor noticia ya `preparada` siguiendo la prioridad territorial
obligatoria **local → departamental → provincial → nacional**
(`motor_noticias/motor_editorial.py`): nunca elige un nivel inferior si
existe una noticia apta de un nivel superior. Nunca publica nada: solo
propone candidatos para revisión humana.

```bash
python3 generar_agenda.py
python3 generar_agenda.py --fecha 2026-08-15
```

Objetivo de 6 propuestas diarias en franjas horarias configurables
(`08:00, 10:30, 13:00, 16:00, 19:00, 21:30`, huso `America/Argentina/Jujuy`
fijo en UTC-3, sin depender de la base de datos IANA de zonas horarias).
Excluye automáticamente noticias con más de 48 horas de antigüedad,
rechazadas o ya usadas en una agenda anterior. Si no hay candidato
válido para un espacio, queda registrado como `sin_candidato` — nunca
se inventa contenido ni se baja la exigencia editorial para completar
la cuota. Una vez que un espacio tiene una noticia asignada, regenerar
la agenda no la reemplaza (así una aprobación o un rechazo humano nunca
se pisa automáticamente); los espacios `sin_candidato` sí se
reintentan en cada regeneración.

Soporte estructural para marcar una noticia como **urgente**
(`Database.marcar_urgente`, hoy manual). Una urgente local o
departamental aparece como propuesta aparte, fuera de las seis franjas
fijas, y tampoco se publica sola: sigue requiriendo revisión humana.

Desde el panel, la sección **"Agenda Editorial"**
(`http://127.0.0.1:8000/agenda`, opcionalmente `?fecha=YYYY-MM-DD`)
muestra hora, candidato, territorio, fuente, antigüedad, riesgo
editorial, estado de revisión y si es urgente, con acciones para
aprobar o rechazar (reutiliza el mismo flujo de revisión existente).

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

La sección **"Estado del sistema"** (`http://127.0.0.1:8000/estado`,
enlazada desde la barra de navegación) muestra si el motor continuo
está activo, su última ejecución y la próxima aproximada, las noticias
nuevas del último ciclo, la última noticia local recibida, el estado
de cada fuente (`OK` / `ADVERTENCIA` / `ERROR`) y las alertas internas
activas descritas más arriba.

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
Facebook se genera automáticamente una placa **PNG de 1200×1200**
(`motor_noticias/meta/imagen.py`, dibujada con Pillow) con el branding
"Ledesma Participa", el título, una bajada breve, la fuente y la
localidad — usando exclusivamente `titulo_revisado`/`texto_revisado`
(o su fallback preparado), nunca IA. El recorte de líneas largas mide
el ancho real en píxeles con la propia fuente tipográfica para no
desbordar el lienzo, y nunca corta una palabra al medio.

Se eligió Pillow (única dependencia externa del proyecto) en vez de
seguir generando SVG porque Facebook no acepta SVG para publicar fotos
reales — se necesitaba un PNG válido — y este entorno no tiene ningún
conversor SVG→PNG ya instalado (ni `rsvg-convert`, ni Inkscape, ni
ImageMagick) que además fuera a estar disponible en la máquina del
usuario. Pillow se instala igual en Windows/Mac/Linux vía `pip`, sin
librerías de sistema adicionales, y desde Pillow 10.1 incluye una
fuente tipográfica propia escalable (`ImageFont.load_default(size=…)`),
así que tampoco hace falta empaquetar ningún archivo de fuente. El
generador de SVG (`generar_svg_placa`) se conserva en el mismo módulo
como representación interna simple, aunque ya no es el archivo que se
persiste ni se publica.

Las placas se guardan en `data/placas/` (generado localmente, ignorado
por Git), con un nombre de archivo derivado del contenido exacto
(título + bajada + fuente + localidad): el mismo contenido siempre
reutiliza el mismo archivo `.png`, sin regenerarlo. La ruta usada para
publicación y si fue generada automáticamente quedan persistidas en la
noticia (`imagen_publicacion_ruta`, `imagen_generada_automaticamente`;
no hicieron falta columnas nuevas para este cambio). La vista previa de
Facebook del panel (`/facebook?id=...`) embebe ese PNG (como
`data:image/png;base64,...`) junto con una indicación clara de si es
"imagen original" o "placa generada automáticamente" — la placa se
genera incluso para noticias con riesgo político/institucional, ya que
solo habilita la previsualización en DRY RUN, nunca publicación real,
y nunca reemplaza la revisión humana.
