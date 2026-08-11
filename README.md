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
