# Piloto periodistas digitales
Repetir: `.venv\Scripts\python.exe produccion_audiovisual\piloto_periodistas\generar_piloto.py [--sin-vigencia] [--presentador valentina|mateo]`
Assets requeridos (aprobados, NO generados): `assets/presentadores/valentina_vega.png`, `mateo_ferrer.png` (retrato cuadrado, rostro centrado).
Lip-sync opcional: `herramientas/lipsync.cmd <foto> <wav> <salida.mp4>` (LivePortrait/SadTalker); si no existe usa retrato con zoom lento.
Voces Piper: `modelos_voz/` (es_AR-daniela-high = Valentina, es_MX-claude-high = Mateo). Salida: `salidas/<fecha>/`.

## Modo sin conductor (vigente)
`.venv\Scripts\python.exe produccion_audiovisual\piloto_periodistas\generar_resumen_visual.py [--ids ID1 ID2] [--horas 36]`
Lee la portada publica (https://ledesmaparticipa.com.ar/api/portada.json, solo lectura), re-aplica scoring y riesgo, excluye personas buscadas/menores. No publica.

## Voz externa (TTS comercial) — pendiente de elegir proveedor
1. `... generar_noticia_presentador.py --solo-guion [--id ID]` -> crea `salidas/<fecha>/guion.json` (texto por segmento) y elige presentador. Sin video.
2. Generar el audio con el TTS externo y pasarlo en una de dos formas:
   - `--audios-dir CARPETA` con `apertura`, `titular`, `desarrollo`, `cierre` (.wav/.mp3): sincronia exacta.
   - `--audio ARCHIVO` con toda la locucion en orden: limites estimados por palabras.
3. Con `--id` (misma noticia) + `--audios-dir`/`--audio` se genera el MP4 final con subtitulos. No publica.

## Flujo vigente: audio externo aprobado + musica por categoria (sin TTS local)
Presentadores: Valentina Vega / Mateo Ferrer (recortes de `assets/presentadores/valentina y mateo.png`). Audio: MP3 externo aprobado en `audio_externo/` (no se versiona).
1. Transcribir (solo para sincronizar subtitulos): `venv_xtts\Scripts\python.exe produccion_audiovisual\piloto_periodistas\transcribir_audio.py AUDIO transcripcion.json`
2. Render: `.venv\Scripts\python.exe produccion_audiovisual\piloto_periodistas\generar_piloto_voz_externa.py --audio AUDIO --transcripcion transcripcion.json --id ID_NOTICIA --presentador valentina|mateo [--musica auto|policial|...|none]`
   Salida 1080x1920, 25 fps, duracion = audio; `salidas/<fecha>/`. No publica.
3. Musica: camas propias en `assets/musica/<categoria>.mp3` (regenerables con `generar_camas_musicales.py`); categoria por palabras clave y nivel/ducking/fades en `config_musica.json` (mezcla en `mezcla_musical.py`).

## Programacion automatica, urgentes y cola de revision (sin publicacion)

- `programador_audiovisual.py tick` hace una pasada: detecta urgentes (video adicional) y, si es la ventana de ~10:00 o ~19:00 (hora Argentina, hasta 3 h de gracia), genera UN video programado. `loop --cada 300` queda corriendo; `simular` solo muestra que haria.
- Ejecucion portable (local o VPS), sin tocar tareas del sistema: `python produccion_audiovisual/piloto_periodistas/programador_audiovisual.py loop` o llamar `tick` cada 5-10 min desde cron/Programador de tareas/systemd timer. `--sin-voz` evita gastar ElevenLabs.
- Estado persistente en `salidas/cola/` (no se versiona, o `$LEDESMA_COLA_DIR`): `registro_videos.json` (noticias usadas, anti-duplicados) y `cola_publicacion.json` (MP4, texto, hashtags, estado).
- Todo MP4 queda `pendiente_revision`. `... cola`, `... aprobar ID`, `... rechazar ID` para revisar.
- `publicador_meta_video.py`: preparado para Facebook/Instagram con el cliente Meta existente, DESACTIVADO (requiere `LEDESMA_VIDEO_PUBLICAR=1`, estado `aprobado` y `dry_run=False`). Instagram necesita URL publica del MP4.
- Pruebas: `python -m unittest tests.test_programacion_audiovisual`.
