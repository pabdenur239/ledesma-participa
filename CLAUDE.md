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

- **Cascada de selección de contenido**, en este orden, sin dejar una franja
  vacía si existe una candidata apta en algún nivel:
  1. Libertador General San Martín.
  2. Departamento Ledesma.
  3. Provincia de Jujuy.
  4. Noticias nacionales argentinas.
  5. Como último recurso, entretenimiento/espectáculos/curiosidades/tendencia
     viral verificable (`motor_noticias/entretenimiento.py` +
     `config/entretenimiento.json`).
  El 70% Libertador / 20% Ledesma / 10% Jujuy es una prioridad editorial
  acumulativa (la implementa el propio orden de la cascada), no una cuota
  rígida diaria ni un bloqueo — no condicionar la selección a un cálculo de
  porcentaje por día.
- **Nunca rellenar con contenido de riesgo obligatorio** aunque una franja
  quede vacía: política, judicial, policial, fiscal-institucional,
  institucional sensible, fallecimientos, salud sensible, violencia,
  menores identificables. Categorías y palabras clave en
  `config/riesgo_editorial.json`; ampliarlo ahí cuando aparezca un caso real
  no cubierto (no resolver casos puntuales sin dejar la regla registrada).
- No publicar rumores, acusaciones sin confirmar, datos privados, contenido
  difamatorio, ni noticias sobre menores o tragedias usadas como
  entretenimiento.
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
