# Scrapper inmobiliario

Scraper multi-sitio (Remax por ahora, luego ZonaProp / Argenprop / MercadoLibre / inmobiliarias)
que normaliza todo a un único esquema y lo guarda en una base SQLite local (`data/properties.db`),
lista para que la usen tus otras aplicaciones.

## Actualizar todo (ej. en octubre)

```bash
python update_all.py
```

Corre `cli.py run <fuente> --operation all` para cada scraper registrado, uno por uno (evita
sobrecargar SQLite con escrituras concurrentes). Como el upsert es por `(source, source_id)`, no
duplica nada — sólo actualiza lo que cambió y agrega lo nuevo. Deja afuera ZonaProp y Argenprop
(hay que correrlos aparte, con cuidado — ver sección de cada uno) y MercadoLibre (es ingesta
manual, no un scraper automático). Para actualizar solo algunas: `python update_all.py remax carfi`.

## Arquitectura

- `scrapers/base.py` — contrato común: `PropertyItem` (esquema normalizado) y `BaseScraper`.
  Cada sitio nuevo es una clase que implementa `fetch_listings()` y devuelve `PropertyItem`s,
  sin importar cómo esté armado el sitio origen (API JSON, HTML, lo que sea).
- `scrapers/remax.py` — primer adapter. Remax usa Angular con SSR y expone una API JSON pública
  (`api-ar.redremax.com`) que se puede consultar directo con `requests`, sin navegador headless.
- `scrapers/zonaprop.py` — segundo adapter. A diferencia de Remax, ZonaProp está detrás de
  Cloudflare (bloquea requests simples con un challenge) y su `robots.txt` prohíbe explícitamente
  su API interna (`/avisos-api/`) y la paginación profunda de resultados de búsqueda. La estrategia
  acá es otra: descubrir URLs vía sus sitemaps públicos (`sitemap_prop_https_*.xml.gz`, están
  pensados para ser crawleados) y scrapear cada ficha con Playwright (Chromium headless, que sí
  pasa el challenge de Cloudflare), leyendo los datos del `dataLayer` de Google Tag Manager y de un
  bloque JSON-LD embebidos en la página.
- `scrapers/argenprop.py` — tercer adapter. Acá la ficha es HTML server-rendered clásico (nada de
  SPA), así que no hace falta navegador: `requests` + BeautifulSoup alcanza, y todo lo que
  necesitamos (precio, m², ambientes, descripción completa, lat/lon, agencia) está directo en el
  HTML con selectores estables (`.titlebar__price`, `ul.property-features`, `[data-location-map]`,
  etc.) o en los `setTargeting(...)` de Google Ad Manager que están inline en la página. El problema
  es otro: está detrás de AWS WAF Bot Control, y las fichas individuales pueden escalar a un
  captcha interactivo ("Human Verification") bajo suficiente volumen desde una misma IP — a
  diferencia del challenge de Cloudflare en ZonaProp, un captcha no lo resuelve solo ni un
  navegador headless, así que este adapter no reintenta ni insiste: si lo ve, corta la corrida ahí
  mismo (`WafBlockedError`) en vez de seguir insistiendo contra una pared que no se mueve.
- `scrapers/mercadolibre_manual.py` — MercadoLibre Inmuebles **no se scrapea**: su `robots.txt`
  nombra explícitamente a `ClaudeBot`/`Claude-User` con `Disallow: /` en todo el dominio (y
  subdominios como `inmuebles.mercadolibre.com.ar`), y `api.mercadolibre.com` disallowea todo bot
  en su robots.txt y encima ahora exige una app autenticada para leer items. En vez de eso, este
  módulo solo _parsea_ texto que vos ya bajaste con tu propio navegador (pegás el contenido de una
  página de resultados en un archivo, `python cli.py ingest-ml archivo.txt`) — no hace ningún
  request a mercadolibre.com.ar ni a su API. Solo toma los avisos "Destacado" (orgánicos, con URL
  estable); los "Ad" (patrocinados) se descartan porque su link es un redirect de tracking sin ID.
- `scrapers/argencasas.py` + `scrapers/ferrero.py` — inmobiliarias locales (ver
  `inmobiliarias_zona_oeste.md`). Ferrero (Ituzaingó) corre sobre una plataforma blanca compartida
  ("ArgenCasas") sin ninguna protección anti-bot: sitio server-rendered plano y, mejor todavía, cada
  ficha trae un `<pre style='display:none'>` con un `var_dump()` de PHP con el registro completo
  (lat/lon, m², ambientes, fotos sin resize) — un leftover de debug del desarrollador, pero muy útil
  para nosotros. `ArgenCasasScraper` toma `base_url` como parámetro, así que sumar otra inmobiliaria
  que corra la misma plataforma es una subclase de 3 líneas.
- `pipeline/upsert.py` — inserta o actualiza propiedades por `(source, source_id)`, y guarda
  historial de precios cuando cambia el precio.
- `db/models.py` — esquema: `properties`, `property_photos`, `price_history`, `scrape_runs`.
- `cli.py` — orquestador (`python cli.py run <fuente> ...`).

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

```bash
# prueba rápida: 2 páginas (200 propiedades) en venta
python cli.py run remax --operation sale --max-pages 2

# scrapeo completo de venta (~67.000 propiedades, ~670 requests)
python cli.py run remax --operation sale

# venta + alquiler + temporal
python cli.py run remax --operation all

# prueba rápida de ZonaProp: 5 fichas (todas las operaciones mezcladas, se filtran solas por campo)
python cli.py run zonaprop --operation all --max-pages 5

# scrapeo de ZonaProp: sin --max-pages recorre TODO el sitemap (decenas/cientos de miles de fichas).
# Es lento a propósito (ver nota de Cloudflare abajo) — pensalo como algo para dejar corriendo
# de fondo por horas, no un comando de unos minutos.
python cli.py run zonaprop --operation all

# prueba chica de Argenprop
python cli.py run argenprop --operation all --max-pages 5

# scrapeo de Argenprop: sin --max-pages recorre todos los sitemaps de fichas.
# Si en algún momento aparece el captcha de AWS WAF, la corrida se corta sola y queda
# registrada como 'failed' en scrape_runs — no la reintentes en loop, esperá un buen rato.
python cli.py run argenprop --operation all

# MercadoLibre: navegá inmuebles.mercadolibre.com.ar vos mismo, copiá el contenido de la
# página de resultados a un .txt, y cargalo:
python cli.py ingest-ml ruta/al/archivo.txt
```

Antes de correr Playwright por primera vez hay que descargar el binario de Chromium una vez:

```bash
python -m playwright install chromium
```

Los resultados quedan en `data/properties.db`. Cada corrida queda registrada en la tabla
`scrape_runs` (encontrados, nuevos, actualizados, errores).

Para volver a correrlo periódicamente (cron / tarea programada), simplemente reejecutá el mismo
comando: hace upsert por `source_id`, no duplica, y va guardando el historial de precios.

## Agregar un nuevo sitio

1. Crear `scrapers/<sitio>.py` con una clase que extienda `BaseScraper` e implemente
   `fetch_listings(operation, max_pages) -> Iterator[PropertyItem]`.
2. Investigar primero si el sitio tiene una API JSON interna (como Remax) antes de ir a parsear
   HTML o usar un navegador headless — es mucho más rápido y estable. Si no la tiene, usar
   `requests` + `BeautifulSoup` para HTML estático, o Playwright si el contenido depende de JS.
3. Registrar la clase en `SCRAPERS` en `cli.py`.

## Notas legales / buenas prácticas

- Se respeta `robots.txt` de cada sitio: Remax se scrapea vía su API pública (permitida), ZonaProp
  vía sus sitemaps públicos (nunca su API interna, que está explícitamente disallowed).
- Hay un delay configurable entre requests. Remax usa `SCRAPPER_DELAY` (default 0.6s). ZonaProp usa
  un delay propio bastante más largo (6s por defecto) porque **Cloudflare ahí escala a bloquear
  directamente si detecta demasiados requests seguidos desde la misma IP** — lo confirmamos
  empíricamente durante el desarrollo. Si en algún momento ZonaProp empieza a devolver "Just a
  moment..." de forma persistente (lo vas a ver en los logs como challenges que no se resuelven ni
  reintentando), lo mejor es parar, esperar y volver a correrlo más tarde con delays todavía más
  largos — no vale la pena forzarlo con proxies o resolución de CAPTCHA.
- Argenprop tiene su propio delay conservador igual que ZonaProp (5s por defecto, configurable
  con `ArgenpropScraper(delay=...)`), porque su AWS WAF también escala con volumen — ahí
  directamente a un captcha interactivo, no a un challenge resoluble por un navegador. Si aparece,
  el scraper corta la corrida solo; no lo reintentes en loop ni intentes automatizar la resolución
  del captcha.
- Esto es para uso personal (armar tu propia base de datos de referencia), no para redistribuir
  el contenido ni tirar los sitios con carga masiva concurrente.
- SQLite no soporta bien que dos procesos escriban a la vez por default; la DB usa modo WAL para
  tolerarlo, pero igual es mejor no correr dos scrapers en simultáneo contra el mismo archivo si se
  puede evitar.

## Pendiente / ideas para siguientes fases

- Fotos: Remax sirve las imágenes a través de un resizer (CloudFront + Lambda) que requiere un
  parámetro de tamaño que todavía no reverse-engineerié del todo; por ahora se guarda la URL base
  en `property_photos.url` y el payload crudo completo en `properties.raw_json`, así no se pierde
  nada aunque haya que resolverlo después.
- Descripción completa: el endpoint de listado no trae el texto de descripción; falta encontrar el
  endpoint del detalle (probé varias rutas típicas y ninguna coincidió — la página de detalle no
  trae la data en el SSR inicial, así que probablemente se resuelve client-side).
- ZonaProp: no extrae todavía lat/lon ni teléfono del agente (no encontré un anchor estable para
  eso en la ficha). Tampoco cachea la lista de URLs del sitemap entre corridas, así que cada full
  scrape la vuelve a descargar (liviano, un par de MB comprimidos, pero se podría cachear).
- Argenprop: no extrae teléfono del agente (queda atrás de un botón "Ver teléfono", probablemente
  requiere JS/una llamada aparte — no lo investigué). Tampoco se probó todavía un scrape en volumen
  real de punta a punta (solo el parser contra una ficha guardada) porque la IP de desarrollo quedó
  con el captcha de AWS WAF activo en las fichas — probarlo primero con `--max-pages` chico y delay
  largo antes de ir a un scrape completo.
- Sumar MercadoLibre Inmuebles e inmobiliarias sueltas siguiendo el mismo patrón de adapter.
- Migrar a PostgreSQL si en algún momento varias apps necesitan leer/escribir concurrentemente.
