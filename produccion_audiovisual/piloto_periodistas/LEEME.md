# Piloto periodistas digitales
Repetir: `.venv\Scripts\python.exe produccion_audiovisual\piloto_periodistas\generar_piloto.py [--sin-vigencia] [--presentador valentina|mateo]`
Assets requeridos (aprobados, NO generados): `assets/presentadores/valentina_vega.png`, `mateo_ferrer.png` (retrato cuadrado, rostro centrado).
Lip-sync opcional: `herramientas/lipsync.cmd <foto> <wav> <salida.mp4>` (LivePortrait/SadTalker); si no existe usa retrato con zoom lento.
Voces Piper: `modelos_voz/` (es_AR-daniela-high = Valentina, es_MX-claude-high = Mateo). Salida: `salidas/<fecha>/`.

## Modo sin conductor (vigente)
`.venv\Scripts\python.exe produccion_audiovisual\piloto_periodistas\generar_resumen_visual.py [--ids ID1 ID2] [--horas 36]`
Lee la portada publica (https://ledesmaparticipa.com.ar/api/portada.json, solo lectura), re-aplica scoring y riesgo, excluye personas buscadas/menores. No publica.
