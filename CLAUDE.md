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
- **Toda noticia local (Libertador) o departamental (Ledesma) relevante y
  verificada se publica de inmediato, sin esperar la siguiente franja
  fija** — regla vigente desde 17/8/2026. `pipeline.procesar_noticia` marca
  `urgente = True` automáticamente en cuanto la noticia llega a "preparada"
  con `territorio` en `local`/`departamental` (`TERRITORIOS_SIEMPRE_ELEGIBLES`
  en `motor_noticias/pipeline.py`), sea cual sea su origen (collector
  automático o carga manual vía panel). No hace falta tildar "Urgente" a
  mano para que se dispare: el tildado manual sigue existiendo solo para
  casos donde un humano quiera marcar como urgente algo que la
  clasificación territorial no detectó. A partir de ahí se reutiliza el
  circuito ya existente sin cambios: `candidatos_urgentes` la propone (ya
  excluye por su cuenta cualquier noticia con riesgo editorial obligatorio
  o rechazada) y `publicar_urgentes` (`publicar_urgentes_meta.py`, corrida
  cada 15 minutos) la publica sola en cuanto es apta — mismas reglas de
  riesgo editorial y elegibilidad automática que cualquier franja fija.
  Departamental/provincial/nacional en franja fija siguen exactamente con
  el esquema programado existente; esta regla no los toca.
- Deduplicación, vigencia (`ANTIGUEDAD_MAXIMA_HORAS`), fuente verificable y
  filtros de riesgo siempre activos — no se eliminan ni se relajan.
- Cada publicación real: imagen, texto autocontenido con "Fuente y nota
  completa:" + URL original al final. Nunca usar ni prometer un primer
  comentario.
- Verificar cada publicación con GET antes de marcarla como publicada. Si
  una red falla, no duplicar la publicación en la otra ni reiniciar el
  proceso completo.
- No publicar anticipadamente una franja futura; no recuperar retroactivamente
  una franja ya pasada.
- Variables `META_*` de usuario ya configuradas: usarlas sin mostrarlas ni
  registrarlas nunca.
