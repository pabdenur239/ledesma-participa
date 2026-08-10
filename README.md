# Ledesma Participa

Medio digital hiperlocal con foco en Libertador General San Martín y el Departamento Ledesma (Jujuy, Argentina).

Estado actual: **Fase 1** (núcleo del motor de noticias).

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
