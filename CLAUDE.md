# Reglas del proyecto — Ledesma Participa

- Claude Code es el ejecutor técnico del proyecto.
- ChatGPT define arquitectura, alcance, prioridades y decisiones estratégicas.
- No modificar otros repositorios; trabajar exclusivamente en `pabdenur239/ledesma-participa`.
- Minimizar investigaciones y consumo de tokens.
- No ampliar el alcance de las tareas asignadas.
- Reportar únicamente bloqueos, errores o riesgos reales.
- Cerrar cada tarea cuando cumple su objetivo, sin trabajo adicional.

## Línea editorial y publicación automática en Meta (vigente desde 15/8/2026)

Autorizada la publicación automática en Facebook e Instagram sin aprobación
individual por publicación, mientras esta notebook funcione como servidor
provisional (hasta migrar a un servidor real). Estas reglas son la
referencia estable — no reinterpretar por criterio propio en cada tarea:

- **Prueba editorial 30/9/2026 al 6/10/2026 (vigente, sin otros cambios
  durante el período)**: feed normal de 6 publicaciones/día (informe 07:30
  + 4 franjas de cascada + institucional 20:30) y cascada cortada en
  provincial (`"solo_territorios_prioritarios": true` en
  `config/agenda.json`: sin nacional ni entretenimiento de relleno).
  Urgentes y Stories sin cambios. Al terminar, decidir si se revierte.
- **Objetivo de 12 a 15 publicaciones diarias** (informe diario de
  clima/dólar a las 07:30 + una franja por hora de 09:00 a 22:00 por
  cascada, `HORARIOS_DEFAULT` en `motor_noticias/motor_editorial.py`).
- **Cascada de selección de contenido**, en este orden, sin dejar una franja
  vacía si existe una candidata apta en algún nivel:
  1. Libertador General San Martín.
  2. Departamento Ledesma.
  3. Provincia de Jujuy.
  4. Noticias nacionales argentinas.
  5. Como último recurso, entretenimiento/espectáculos/curiosidades/tendencia
     viral verificable (`motor_noticias/entretenimiento.py` +
     `config/entretenimiento.json`), apuntando a 1-2 publicaciones diarias
     de este tipo cuando haya contenido verificado disponible.
  El 70% Libertador / 20% Ledesma / 10% Jujuy es una prioridad editorial
  acumulativa (la implementa el propio orden de la cascada), no una cuota
  rígida diaria ni un bloqueo — no condicionar la selección a un cálculo de
  porcentaje por día.
- **Padrón de fuentes locales prioritarias** (26 fuentes, aprobado
  17/8/2026): `config/fuentes_locales.json` — Libertador, Fraile Pintado,
  Calilegua, Caimancito y Yuto. Clasificación editorial: A = oficial/primaria,
  B = medio o periodista confiable (exige corroboración adicional en
  hechos policiales/judiciales/fallecimientos/acusaciones/riesgo), C =
  alerta/comunitaria (incluye La Guía Fraile Pintado — nunca es la única
  base de una publicación, exige corroborar con A o B). 13 fuentes marcadas
  `monitoreo_inmediato: true` son las de mayor prioridad para detectar
  noticia local urgente. La gran mayoría son páginas de Facebook: no hay
  forma técnica de sondearlas automáticamente sin acceso oficial de esa
  página (token de admin que no tenemos) ni scraping que evada las
  restricciones de Meta — ninguna de las dos cosas se implementa. Se
  monitorean humanamente y se cargan vía el panel ("Cargar noticia",
  `motor_noticias/ingreso_manual.py`), que aplica el mismo circuito
  editorial que un collector automático, incluida la nueva regla de
  publicación local inmediata. Las únicas fuentes del padrón con collector
  automático real son la Municipalidad de Libertador (`municipio_libertador`,
  ya existente, sobre su sitio oficial), Jujuy al día (`jujuyaldia`, RSS
  real sobre jujuyaldia.com.ar/feed/) y Canal 6 Libertador (`canal6-libertador`,
  RSS real sobre canalseis.com.ar/feed/, agregado 17/8/2026 — su feed
  existe pero suele traer poco contenido propio, porque publican la mayor
  parte en Facebook) — ninguna de las tres es Facebook. Automatizar el
  resto por Graph API (Page Public Content Access) requiere Business
  Verification y App Review de Meta, todavía no iniciados.
- **Policiales y accidentes**: permitidos dentro de la cascada normal (no
  son un nivel aparte) solo con información verificable de fuente
  confiable, sin especular ni acusar, respetando la presunción de
  inocencia. El mero hecho policial o accidente (choque, incendio,
  intervención policial) no activa revisión humana obligatoria; sí la
  activa cualquier contenido de proceso penal contra una persona
  identificada (imputado, detenido, denunciado, causa judicial, condena,
  etc. — ver categoría `judicial` abajo), que sigue bloqueado para
  publicación automática.
- **Nunca rellenar con contenido de riesgo obligatorio** aunque una franja
  quede vacía: política, judicial (proceso penal contra una persona
  identificada), fiscal-institucional, institucional sensible,
  fallecimientos, salud sensible, violencia, menores identificables.
  Categorías y palabras clave en `config/riesgo_editorial.json`; ampliarlo
  ahí cuando aparezca un caso real no cubierto (no resolver casos puntuales
  sin dejar la regla registrada).
- No publicar rumores, acusaciones sin confirmar, datos privados, contenido
  difamatorio, ni noticias sobre menores o tragedias usadas como
  entretenimiento.
- **Scoring editorial único (vigente desde 2/10/2026)** —
  `motor_noticias/scoring_editorial.py` + `config/scoring_editorial.json`.
  Una sola clasificación alimenta franjas, circuito inmediato y placa roja.
  Base 0–100 = impacto (25) + urgencia (20) + magnitud (20) + relevancia
  para nuestra audiencia (15) + actualidad (10) + interés (10); bonus
  territorial aparte (Libertador +12, Ledesma +9, Jujuy +5, nacional 0).
  Cada franja de cascada elige la candidata de mayor puntaje total: ser
  local suma pero no garantiza ganar. **Inmediato (URGENTE)**: local/
  departamental con base ≥ 70 (sin bonus) y urgencia real en el título;
  provincial/nacional solo si es extraordinaria (base ≥ 80, urgencia ≥ 16,
  relevancia para la audiencia ≥ 10). Ya NO se publica de inmediato una
  local solo por ser local. El tildado manual "Urgente" del panel (carga
  manual) se sigue respetando. `pipeline.procesar_noticia` marca
  `urgente`, `resolver_urgentes` lo confirma con el mismo scoring y
  `publicar_urgentes` (cada 15 min) publica con la identidad visual roja
  (banda URGENTE sobre la foto, o placa roja sin foto). El rojo queda
  reservado exclusivamente a URGENTES. Riesgo editorial, rechazo,
  deduplicación y vigencia siguen excluyendo de todo circuito automático.
  Ajustar señales/umbrales solo en el JSON, con caso real documentado.
- Deduplicación, vigencia (`ANTIGUEDAD_MAXIMA_HORAS`), fuente verificable y
  filtros de riesgo siempre activos — no se eliminan ni se relajan.
- Cada publicación real: imagen + texto autocontenido con el formato de
  copy de la Etapa 1 (ver abajo): fuente siempre atribuida y enlace a la
  nota propia en ledesmaparticipa.com.ar; si la nota propia todavía no
  está generada, "Nota original:" + URL de la fuente. Nunca usar ni
  prometer un primer comentario.
- Verificar cada publicación con GET antes de marcarla como publicada. Si
  una red falla, no duplicar la publicación en la otra ni reiniciar el
  proceso completo.
- No publicar anticipadamente una franja futura; no recuperar retroactivamente
  una franja ya pasada.
- Variables `META_*` de usuario ya configuradas: usarlas sin mostrarlas ni
  registrarlas nunca.

## Etapa 1 — rediseño funcional, editorial y visual (implementada 9/10/2026)

Producción: VPS Contabo (`/opt/ledesma-participa`, servicios `ledesma-*`).
La notebook no publica. Frecuencia y horarios de Facebook/Instagram sin
cambios: no todo lo que entra a web/app se publica en redes.

- **Clasificación separada** (`motor_noticias/clasificacion.py`), nunca
  mezclada:
  - TERRITORIO con confianza propia (Libertador General San Martín,
    Departamento Ledesma, Jujuy, Nacional, Internacional) —
    `territorio.clasificar_territorio` (`CONFIANZA` por tipo de evidencia).
    Marcadores nacionales genéricos (Banco Central, inflación, "de la
    Nación"…: `nacional_generico` en `config/localidades.json`) no le
    ganan a un país extranjero en el título; protagonistas jujeños (Sadir)
    y deporte argentino (AFA, Selección, Messi…) ubican la nota.
  - CATEGORÍA por tema principal con confianza (`categorias.clasificar_categoria`,
    reglas en `config/categorias.json`): Policiales, Salud, Deportes,
    Gastronomía, Espectáculos, Política, Servicios, Economía, Educación,
    Cultura. > 0.85 automática; 0.50–0.85 → General / Últimas; < 0.50 sin
    categoría (no aparece en grillas temáticas). Palabras débiles
    ("partido", "hospital", "asado") nunca deciden solas; exclusiones por
    título (banco/jubilados ≠ Gastronomía, hecho policial ≠ Salud).
  - URGENTE (bool): no es categoría; lo decide el scoring editorial único
    (`scoring_editorial.urgente_confirmado`).
- **Volumen web/app** (`motor_noticias/portal.py`, tabla `portal_seleccion`):
  15–25 noticias válidas por día + urgentes = lo publicado en redes + lo
  agendado hoy + las preparadas de mayor puntaje, con topes por territorio
  (Jujuy 10, nacional 8, internacional 2) y por categoría (6). Nunca
  entran: riesgo editorial, rechazadas, descartadas, el mismo hecho de dos
  medios, piezas periódicas de cotización/pronóstico. No se rellena. Web y
  app leen la misma fuente (`sitio/generador.py` → `docs/` + `docs/api/`).
- **Web mobile-first** (`sitio/plantillas.py`, `assets_fuente/site.css`):
  portada Urgente → Clima + Dólar → principal (prioriza Libertador /
  Ledesma / Jujuy) → Libertador → Ledesma → Jujuy → Policiales → Salud →
  Deportes → Servicios → Videos → Guía Comercial → redes. Nunca secciones
  vacías; los informes de clima no compiten como noticia. Histórico en
  `/categoria/<slug>/`. API nueva: `portada.json`, `clima_dolar.json`,
  `guia_comercial.json`, `videos.json`, `categoria/<slug>.json` nuevos;
  los endpoints de la app publicada se mantienen (feed ahora cronológico).
- **App Android** (`app/`, mismo package): Inicio con accesos (Últimas,
  Libertador, Departamento Ledesma, Jujuy, Policiales, Salud, Deportes,
  Servicios, Videos, Guía Comercial, Multimedia), listado, nota completa,
  Guía Comercial. Consume `api/portada.json`.
- **Identidad Versión C** (`meta/identidad_visual.py`, tipografía
  Montserrat OFL en `meta/fuentes/`): carbón + dorado, blanco para leer;
  ROJO solo urgente, VERDE servicios. Feed 1080x1350, titular dominante
  (~10 palabras), territorio visible, logo discreto. Plantillas: noticia
  con foto, placa editorial sin foto, urgente, servicio, institucional,
  clima + dólar; Story 1080x1920; carrusel 3–5 placas; cuadros de Reel
  10–20 s (`meta/video.generar_reel_desde_cuadros`). Carrusel y Reel están
  preparados, NO automatizados. Canva queda como laboratorio manual.
- **Regla de imágenes** (`regla_imagenes.py`, `config/imagenes.json`):
  1) foto real del hecho, 2) oficial, 3) recurso relacionado permitido,
  4) PLACA EDITORIAL GRÁFICA. Stock, archivos genéricos y fotos de archivo
  reutilizadas en varias notas distintas → placa. Nunca párrafos en
  miniatura.
- **Copy** (`meta/contenido.py`): `[TERRITORIO] | TITULAR EN MAYÚSCULAS`,
  párrafos con oraciones completas (máx. 4, nunca truncados), `Fuente:`,
  CTA breve variable (estable por noticia), enlace a la nota propia en
  ledesmaparticipa.com.ar (o "Nota original:" si aún no existe), dos
  hashtags como máximo. Sin URLs externas dentro del cuerpo.
- **Clima + Dólar** (`informe_diario.py`, `informe_diario_datos.py`): una
  sola publicación "CLIMA + DÓLAR | INFORME DE LA MAÑANA" (07:30, sin
  cambio de cantidad). Temperatura actual/mín/máx, condición, lluvia,
  oficial y blue compra/venta, hora y fuentes. Si una fuente falla, esa
  parte dice "No disponible"; sin ningún dato no hay informe.
- **Guía Comercial Ledesma Participa** (nunca "Marketplace";
  `config/guia_comercial.json`, `guia_comercial.py`): listado + ficha,
  separada de las noticias. Solo datos reales; lo que falta va en null y
  no se muestra.
- **Videos** (`config/videos.json`, `videos.py`): YouTube con reproductor
  oficial embebido; sin URL/ID válido no se muestra; sección oculta si no
  hay videos. Estructura Multimedia preparada; entrevistas/podcast no.
- **Push** (`push_notificaciones.py`): solo urgentes confirmados por el
  scoring o cortes/servicios críticos e información pública inmediata en el
  TÍTULO de una noticia local/departamental publicada.
- **Métricas Meta**: la tabla de 10 publicaciones de Gemini está PENDIENTE
  DE VERIFICACIÓN VISUAL; no se usa como verdad operativa ni para cambiar
  reglas.

### Cierre de Etapa 1 (9/10/2026): riesgos aceptados
- 57 tests de la suite ya fallaban antes de la Etapa 1 (tests
  desincronizados con código de producción no commiteado:
  `test_meta_publicador`, `test_motor_editorial`, `test_territorio`…).
  Comparados contra la línea base: ninguno es regresión de la Etapa 1. No
  se corrigieron; cubren menos de lo que parece.
- Enlace propio en el copy: si la página de la nota todavía no existe
  (sitio cada 15 min), el post usa "Nota original:" + URL externa. Afecta
  sobre todo a URGENTES (se publican apenas se confirman). Hacer esperar al
  post cambiaría la inmediatez de urgentes/horarios: queda para decisión
  posterior, sin cambios.
- Videos vacío hasta tener URLs reales de YouTube (no se inventan).
- App: código verificado; release a Google Play pendiente (prueba cerrada
  sin tocar).

### Etapa 2 (siguiente, NO implementada todavía): RADIOS EN VIVO
Libertador, Departamento Ledesma, Jujuy y Argentina; solo streams
oficiales; reproductor persistente que siga sonando mientras se navega;
favoritos si es viable. El acceso "Multimedia" de la app es su lugar
natural.
