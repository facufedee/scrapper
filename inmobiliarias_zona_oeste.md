# Inmobiliarias — Zona Oeste (Ituzaingó, Morón, Merlo, Haedo, San Antonio de Padua) + Tres de Febrero

Registro de trabajo para ir sumando adapters de inmobiliarias locales al scraper. La lista inicial
(a mano, por patrón de nombre) resultó tener una tasa altísima de dominios inexistentes u
homónimos en otra ciudad — la lista buena, la que realmente sirvió, salió de procesar el HTML
crudo de una búsqueda de Google Maps ("inmobiliarias ituzaingo"), que trae URLs reales puestas por
cada negocio en su propia ficha. Si se quiere cubrir Morón/Merlo/Haedo/Padua con la misma calidad,
conviene repetir eso: buscar "inmobiliarias <localidad>" en Google Maps, guardar el HTML de la
página de resultados en un `.txt`, y pedir que se procese igual que este.

## Plataformas reutilizables encontradas

Cada vez que una inmobiliaria nueva corre sobre una de estas, sumarla es una subclase de ~3 líneas
en vez de investigar de cero:

- **ArgenCasas** (`scrapers/argencasas.py` template nuevo, `scrapers/argencasas_legacy.py`
  template viejo) — plataforma blanca para inmobiliarias chicas. Se nota por fotos en
  `api.argencasas.com`/`cdn.argencasas.com`, o un `<pre style='display:none'>` con un `var_dump()`
  de PHP en la ficha (template nuevo), o un JSON-LD `RealEstateListing` limpio + `código en
  robots.txt` disallowing `/motor/` (template viejo). Template viejo confirmado en 2 agencias más de
  Tres de Febrero: La Rocca Properties (Villa Bosch — ojo, `laroccapropiedades.com`, sin `.ar`, es
  un homónimo sin relación en Colegiales) e Inmobiliaria D'Eramo (Ciudadela).
- **Navent "ficha"** (`scrapers/navent_ficha.py`, clase base `NaventFichaScraper`) — plantilla
  licenciada de Navent (iconos `icon-g-logo-zonaprop`/`icon-g-logo-adondevivir`, asset version
  string "RPFICv4.1.2-RC1"), encontrada vía Ledesma Propiedades y generalizada esta vuelta al
  confirmar 2 tenants más con el mismo backend (`busca_prop.php`/`detalle-item.php`, fotos en
  `inmomap.com.ar`): Inmobiliaria Cabrera (Villa Bosch, Tres de Febrero) y Franco Property
  Organization (Santos Lugares, Tres de Febrero). El query param `co={tenant}` en el listado
  parece un código por tenant pero no lo es — cualquier instalación acepta el código de Ledesma
  (`co=PD`) y devuelve igual su propio inventario (la separación es por dominio, `co` es texto
  de plantilla sin parametrizar); se dejó como argumento del constructor por las dudas, no porque
  haga falta variarlo. Los 3 tenants confirmados **no** comparten frontend: Ledesma usa `<h3>` para
  título/precio/dirección/operación y `div.largo` con formato "valor etiqueta" para
  dormitorios/m²; Cabrera/Franco usan `<h2>` para lo primero y un bloque de texto suelto
  ("Dormitorios: 2 Baños: 1...") bajo el heading "Información del inmueble" para lo segundo — el
  parser prueba ambos formatos en orden.
- **Houzez** (`scrapers/houzez.py`) — theme de WordPress, muy popular en general, no solo acá. Se
  nota por clases `houzez-*` y un objeto JS `houzez_single_property_map = {...}` inline en la
  ficha. Discovery por sitemap de Yoast si existe, si no por paginación de `/propiedad/page/N/`.
- **Tokko Broker** (`scrapers/tokko.py`) — SaaS inmobiliario muy usado en toda Argentina/LatAm. Se
  nota por `static.tokkobroker.com` en las fotos. Listado en `/Propiedades?...&p=N` (necesita el
  querystring completo de filtros, un `/Propiedades` pelado sirve el form vacío). Ojo: no todos los
  tenants corren el mismo theme — Colonna (Sáenz Peña) reveló una variante más nueva con selectores
  totalmente distintos (`.prop-detail-op-tag`/`.prop-detail-price-list .price-number` en vez de
  `.operation-type-div`/`.operation-val`, fotos en `a.pswp-elem[href]` en vez de
  `img.slider-thumb[data-big]`, descripción en `.full-description` u `og:description` en vez de
  `#prop-desc`) — `_normalize` ahora prueba ambos, en ese orden, así que un tenant nuevo con un
  theme aún distinto igual conviene chequearlo antes de asumir que "ya andaría".
- **"adprop"** (`scrapers/adprop.py`, nombre nuestro, no sé el nombre real de la plataforma) — se
  nota por URLs de ficha `/ad/{slug}`. Limitación real: ninguna de las que encontramos tiene
  página de listado/sitemap, así que solo se scrapean las "destacadas" de la home. Confirmada
  también en Ricciardelli Propiedades (Caseros, Tres de Febrero).
- **RealHomes** (`scrapers/realhomes.py`) — otro theme de WordPress, tan común como Houzez. La
  mejor de todas para scrapear: no hace falta tocar el HTML en absoluto, expone un custom post
  type `property` en la API REST pública de WordPress (`/wp-json/wp/v2/<rest_base>`, el slug varía
  por instalación — hay que resolverlo vía `/wp-json/wp/v2/types`) con precio/m²/dormitorios/
  baños/lat-lon/dirección/fotos ya en un campo `property_meta` con claves `REAL_HOMES_property_*`,
  y `?_embed=wp:term` resuelve tipo/ciudad/estado de una. Se nota por
  `wp-content/plugins/realhomes-elementor-addon` o `easy-real-estate` en el HTML. Ojo: otros temas
  de WP para inmobiliarias (WpResidence/`estate_property`, Estatik) tienen su propio custom post
  type pero **no** siempre exponen los metadatos de precio/m² vía REST — hay que confirmarlo caso
  por caso antes de asumir que funciona igual que RealHomes. Confirmado en Montes de Oca (Gral. San
  Martín, linda con Tres de Febrero) que el plugin **JetEngine** es otro caso de "custom post type
  sin metadatos en REST": `/wp-json/wp/v2/propiedades` da id/título/link/fecha y dos listas de ids
  de taxonomía (`estado`=operación, `tipo`=tipo de propiedad, resolubles con una sola llamada extra
  a `/wp-json/wp/v2/estado` y `/wp-json/wp/v2/tipo`, cacheable) pero nunca precio/m²/ambientes — hay
  que rasparlos del HTML de la ficha, donde JetEngine los renderiza todos con la misma clase
  (`.jet-listing-dynamic-field`) sin forma de distinguirlos salvo por orden/prefijo de texto
  ("Dormitorios: 2", "USD85,000"). Ver `scrapers/montesdeoca.py`. Ojo con la paginación: la REST
  API de WordPress devuelve **400** (no una lista vacía) cuando `page` supera el total de páginas —
  hay que tratar el 400 como "se acabó", igual que un 404, o el scraper corta con una excepción sin
  terminar de guardar nada.
- **Wasi** (`scrapers/wasi.py`) — SaaS inmobiliario LatAm (Colombia/varios países, poco visto en
  Argentina hasta ahora). Se nota por fotos en `images.wasi.co`. Listado en `/s/ventas?page=N` y
  `/s/alquileres?page=N` por separado (no mezcla operaciones). Ficha con JSON-LD + bloque
  `ul.list-li li strong` de campos etiquetados. Ojo: usa formato numérico americano (coma =
  miles, punto = decimal) en el precio, al revés que el resto de las plataformas de acá — el
  parser detecta el separador correcto mirando el largo del grupo final, sea cual sea el
  caracter. No expone lat/lon en el HTML estático.
- **Carlucci/Piccione** (`scrapers/carlucci.py`, clase base `CarlucciPlatformScraper`) — otra
  plataforma multi-tenant blanca, confirmada en 2 agencias de Ituzaingó. Se nota por CDN
  `d1v2p1s05qqabi.cloudfront.net/sites/{id}` (un id por tenant) y ficha en
  `/propiedad/{slug}--{id}` con `ul.details li.{campo}` (la clase del `<li>` ya es la key).
  Listado mixto venta+alquiler en `/propiedades?page=N`.
- **Mapaprop** (`scrapers/mapaprop.py`, clase base `MapapropScraper`) — otra plataforma
  multi-tenant, confirmada en 2 agencias de Ituzaingó/Morón. Se nota por `<meta name="copyright"
  content="Mapaprop ...">`/`images.mapaprop.app` y ficha en `/propiedad/{slug}-{siteId}-{propId}`
  (el slug empieza con `venta-de-` o `alquiler-de-`, de ahí sale la operación). Ojo: la ficha tiene
  un `<h1>` señuelo oculto ("Buscador de propiedades") fuera del bloque real — hay que scopear
  todo dentro de `div.page.page-property`. Tabla de detalles clásica `td.bold`/`td.body`. Listado
  en `/buscar/?type=&operation=&page=N` mixto venta+alquiler, pero la paginación no es un offset
  limpio (páginas consecutivas se solapan mucho) y clampea a un set repetido al pasarse del final
  — el discovery corta cuando 2 páginas seguidas no aportan nada nuevo, igual lógica que Carlucci.
- **Xintel** (`scrapers/xintel.py`, clase base `XintelScraper`) — CRM/SaaS inmobiliario, encontrada
  vía Grupo Vaccaro. A diferencia de las demás, el frontend de la agencia es una SPA de Angular (curl
  siempre devuelve el mismo shell vacío), pero el JS del propio sitio llama directo a una API JSON
  (`https://xintelapi.com.ar/?json=resultados.fichas&inm={tenant}&apiK={key}&page=N`) con una key
  embebida en el HTML de la página (la misma que le llega a cualquier visitante) — no hace falta
  renderizar JS ni pedir cada ficha por separado: una sola llamada trae los datos completos de 10
  propiedades a la vez (precio, moneda, m², dormitorios, coordenadas, fotos, descripción). Cada
  agencia nueva sobre esta plataforma necesita su propio `inm`/`apiK`, que salen de buscar
  `xintelapi.com.ar` en el HTML del sitio. Ojo: el objeto `ficha` completo de la API trae ~300
  campos internos del CRM, incluyendo PII del vendedor (DNI, mail personal) — el scraper solo
  persiste un subconjunto curado en `raw`, nunca el objeto completo.
- **Amaira/Xintel vía proxy propio** (`scrapers/fparadela.py`, por ahora sin generalizar) — variante
  del mismo backend Xintel (las fotos se sirven en `cdn-images.xintelweb.com`, igual que Grupo
  Vaccaro/Gabriel Paris), pero con marca "Amaira" (`ficha.amaira.com.ar`) y accedida a través de un
  proxy propio del sitio (`{base_url}/api/proxy.php?page=N&per_page=20`) en vez de llamar
  `xintelapi.com.ar` directo con una key visible en el JS — más prolijo, pero también más
  específico de este sitio (no confirmé aún otra agencia con el mismo `api/proxy.php`). JSON limpio
  con paginación estándar (`data`/`total`/`last_page`), no hace falta ni tocar HTML.
- **ArgenCasas, plantilla custom compartida** (`scrapers/danielinmobiliaria.py`, clase base
  `ArgenCasasCustomScraper`) — confirmada en 2 agencias (Daniel Inmobiliaria, Zopatti), mismo
  desarrollador probablemente. Se nota por `api.argencasas.com` en las fotos + `class="props-list"`
  en el listado + fichas en `/ficha/{id}`. Ojo: el listado usa `href='...'` con comillas simples en
  vez de dobles — un grep con comillas dobles no encuentra nada y hace parecer que el sitio no tiene
  catálogo.
- **Xintel, tenant con API expuesta directo** (`scrapers/moreleloir.py`, sin generalizar) — mismo
  backend que Grupo Vaccaro/Gabriel Paris (fotos en `cdn-images.xintelweb.com`, `inm`/`apiK`
  visibles en el JS), pero el listado es HTML server-rendered propio (no hace falta ni el API para
  discovery) y la ficha usa la acción `json=fichas.propiedades&id=N` (una propiedad por llamada) en
  vez de la paginada `resultados.fichas` de `scrapers/xintel.py` — el detalle sí carga por JS
  (placeholder "-" en el precio del HTML estático), así que la API es imprescindible ahí. Ojo con
  los campos numéricos: `in_sto`/`in_cub`/`in_coo` vienen en formato decimal plano de la API (punto
  siempre decimal), a diferencia del texto de `precio` que sí viene con formato argentino
  (punto=miles) — mezclar los dos parsers de números da superficies 100x más grandes de lo real.
- **Century21 Argentina (portal nacional)** (`scrapers/century21.py`, clase base
  `Century21Scraper`, parametrizada por oficina) — no es una agencia individual sino el portal
  nacional de la franquicia (111 oficinas en Argentina); cada sitio propio de una oficina C21
  (como `c21lamoisselorre.com.ar`) solo redirige a una página dentro de `century21.com.ar`. Se
  descubrió mirando las llamadas de red con Playwright: **cualquier página del portal tiene una
  variante `?json=true`** que devuelve los datos ya armados (no está documentado en ningún lado).
  Listado en `/v/resultados/[pagina_N/]oficina_{slug}_local?json=true` (100/página), ficha en
  `{urlCorrectaPropiedad}?json=true`. El `robots.txt` prohíbe `/busqueda`, `/ft/`, `/ds/`, `/pdf/`
  — ninguno de estos, así que no hay problema. El slug de oficina para la URL de resultados es más
  corto que el de su página `/v/oficina/...` (ej. `94-lamoisse-lorre` vs
  `94-century-21-lamoisse-lorre-ituzaingo-gba-oeste-argentina`) y no hay forma documentada de
  derivarlo — hay que confirmarlo a mano por oficina. El directorio completo de oficinas está en
  `century21.com.ar/v/oficinas?json=true`, de ahí salieron las 3 de zona oeste: Lamoisse Lorré e
  Ituzaingó (Portela Sabrina) en Ituzaingó, Freda en Morón/Castelar.

## Fuentes activas

| Fuente (id en `SCRAPERS`) | Inmobiliaria | Localidad | Plataforma | Propiedades |
|---|---|---|---|---|
| `carlucci` | Carlucci Propiedades | Ituzaingó | propia | ~275 |
| `morroni` | Morroni Propiedades | Morón | Houzez | ~54 |
| `palacio` | Palacio Propiedades | Ituzaingó | Houzez | ~51 |
| `rejn` | Inmobiliaria Rejn | Ituzaingó | ArgenCasas (viejo) | 131 |
| `santos` | Santos Propiedades | Haedo | ArgenCasas (viejo) | 0 (sin publicaciones activas) |
| `tavella` | R. Tavella | Ituzaingó | ArgenCasas (viejo) | 47 |
| `taburet` | Taburet Propiedades | Ituzaingó | Tokko | 656 |
| `carfi` | Eduardo J. Carfi Propiedades | Castelar | Tokko | 828 |
| `lacoste` | Pedro Lacoste Estudio Inmobiliario | Castelar | API JSON propia | 12 |
| `juliocarfi` | Julio Carfí Propiedades | Castelar | API REST propia | **6.576** — la más grande de todas |
| `milani` | Carlos Milani | Castelar | Houzez | 133 |
| `allo` | Nerina Allo Propiedades | Castelar | Tokko | 757 |
| `spinelli` | Inmobiliaria Spinelli | Haedo | "adprop" | 9 (solo destacadas) |
| `gabrielbasta` | Gabriel Basta | Merlo | "adprop" | 9 (solo destacadas) |
| `magallanes` | Magallanes Estudio Inmobiliario | Ituzaingó | Tokko | 257 |
| `rebecchi` | Rebecchi Propiedades | Ituzaingó | Tokko | 14 |
| `arenaprop` | Arena Lorena Propiedades | Ituzaingó | Tokko | 89 |
| `gescrina` | Gastón Escriña Propiedades | Ituzaingó | Tokko | 115 |
| `mjcarabelli` | Maria Jose Carabelli Propiedades | Ituzaingó | Tokko | 206 |
| `victorvende` | Inmobiliaria Víctor Vende | Ituzaingó | ArgenCasas (viejo) | 46 |
| `vrpropiedades` | VR Propiedades | Ituzaingó | ArgenCasas (viejo) | 58 |
| `brunoinmuebles` | Bruno Inmuebles | Ituzaingó | ArgenCasas (viejo) | 69 |
| `cartechini` | Cartechini Propiedades | Ituzaingó | "adprop" | 9 (solo destacadas) |
| `delizia` | Delizia Propiedades | Ituzaingó | **RealHomes** (nueva) | 402 |
| `corigliano` | Corigliano Propiedades | Ituzaingó | RealHomes | 213 |
| `dicasoli` | Inmobiliaria Di Casoli | Ituzaingó | Wasi | 496 |
| `gonzalopropiedades` | Gonzalo Propiedades | Ituzaingó | Wasi | 150 |
| `repettoprop` | Repetto Propiedades | Ituzaingó | Wasi | 424 |
| `lasalapropiedades` | Lasala Propiedades | Ituzaingó | Wasi | 122 |
| `piccione` | Piccione Propiedades | Ituzaingó | Carlucci/Piccione (propia) | 136 |
| `msvinmobiliaria` | MSV Inmobiliaria | Ituzaingó | Mapaprop (nueva) | 166 |
| `portelapropiedades` | Portela Propiedades | Ituzaingó | Mapaprop | 263 |
| `garnicainmuebles` | Garnica Inmuebles | Ituzaingó | Mapaprop | 90 |
| `gonzalezabella` | González Abella Propiedades | Ituzaingó | Mapaprop | 55 |
| `grupovaccaro` | Grupo Vaccaro | Ituzaingó/Moreno | Xintel (nueva) | 244 |
| `fabianamtripe` | Fabiana M. Tripe Inmuebles | Castelar | propia | 359 |
| `ledesmaprop` | Ledesma Propiedades | Ituzaingó/CABA | propia (plantilla Navent + fotos en `inmomap.com.ar`) | 44 |
| `gabrielparis` | Gabriel Paris Asesor Inmobiliario | Ituzaingó | Xintel | 412 |
| `fparadela` | Fernando Paradela Inmuebles | Ituzaingó | Amaira/Xintel (nueva) | 312 |
| `danielinmobiliaria` | Daniel Inmobiliaria | Ituzaingó | ArgenCasas (frontend propio) | 515 |
| `matiasszpira` | Matías Szpira Bienes Raíces | Moreno/zona oeste | Xintel (API propia local) | 1.107 |
| `sgonzalez` | Santiago González Inmobiliaria | Castelar/zona oeste | propia | 12 |
| `zopatti` | Zopatti Propiedades | zona oeste | ArgenCasas (frontend propio, igual a Daniel Inmobiliaria) | 111 |
| `moreleloir` | More Propiedades | Parque Leloir, Ituzaingó | Xintel (API directa) | 235 |
| `c21lamoisselorre` | CENTURY 21 Lamoisse Lorré | Ituzaingó | Century21 nacional (nueva) | 290 |
| `c21freda` | CENTURY 21 Freda | Morón/Castelar | Century21 nacional | 64 |
| `c21portela` | CENTURY 21 Portela Sabrina | Ituzaingó | Century21 nacional | 440 |
| `ferrero` | Ferrero Propiedades | Ituzaingó | ArgenCasas (nuevo) | **pendiente** — el sitio volvió pero está inestable (timeouts a los pocos ítems, probado 2 veces limpio); reintentar más adelante |
| `colonna` | N.J. Colonna Properties | Sáenz Peña, Tres de Febrero | Tokko (theme nuevo) | 108 — sin dirección (theme nuevo no la expone, ver Notas técnicas) |
| `pintimalli` | Pintimalli Propiedades (= José Pintimalli Propiedades) | Caseros, Tres de Febrero | Tokko | **421** |
| `larocca` | La Rocca Properties | Villa Bosch, Tres de Febrero | ArgenCasas (viejo) | 44 |
| `cabrera` | Inmobiliaria Cabrera | Villa Bosch, Tres de Febrero | Navent "ficha" (nueva, generalizada) | 193 |
| `franco` | Franco Property Organization | Santos Lugares, Tres de Febrero | Navent "ficha" | 91 |
| `deramo` | Inmobiliaria D'Eramo | Ciudadela, Tres de Febrero | ArgenCasas (viejo) | 22 |
| `ricciardelli` | Ricciardelli Propiedades | Caseros, Tres de Febrero | "adprop" | 9 (solo destacadas, limitación conocida de la plataforma) |
| `montesdeoca` | Montes de Oca | Gral. San Martín, linda con Tres de Febrero | WordPress + JetEngine (nueva) | 40 |
| `defazio` | De Fazio Inmobiliaria | Ciudadela, Tres de Febrero | Next.js + Xintel (nueva variante) | 260 |
| `scarinci` | Scarinci Propiedades | **Sáenz Peña** | WordPress + Realtyna WPL Pro (nueva) | **135** |

Corré `python update_all.py` para reactualizar todas de una (ver README). Para una sola:
`python cli.py run <fuente> --operation all`.

## Encontradas pero no vale la pena scrapear

- **Tintorero Propiedades** (Ituzaingó) — usa assets de Tokko pero no tiene `/Propiedades` (404),
  no encontré la ruta real. Deprioritizada, no vale más tiempo de investigación por ahora.
- **Estudio GALAS** (`estudiogalas.com.ar`) — landing de marketing (Systeme.io), sin catálogo.
  Existe otro dominio, `galas.com.ar`, con 1 mención de Tokko — sin confirmar si es real o casual.
- **M.M. Fuentes** (Haedo) — no tiene catálogo propio, linkea directo a su perfil de Zonaprop.
- **Claudio Godoy** (Morón) — página de contacto sin ningún link a propiedades.
- **LujanProp** — portal multi-inmobiliaria de la ciudad de Luján, no la agencia "Luján
  Propiedades" de Haedo.
- **D'Aria, Damico, Merlo Negocios Inmobiliarios, Filippo Propiedades, Fresco Propiedades, la
  primera "Ferrero .com.ar" que probé** — todas inmobiliarias homónimas reales, pero operan en
  Zona Norte/CABA/Quilmes/San Clemente del Tuyú/Uruguay — no en zona oeste.
- **inmobiliariaarmadans.com** — el dominio fue tomado/hackeado, sirve spam de apuestas/casino en
  vez del sitio de la inmobiliaria. No usar ni volver a chequear salvo que cambie.

## Pendientes de investigar (URLs reales confirmadas por Google Maps, sin plataforma identificada)

Estas no matchean ArgenCasas/Houzez/Tokko/adprop — necesitan investigación individual (encontrar
su estructura de listado + ficha) antes de poder scrapearse, igual que se hizo con Lacoste o Julio
Carfi. Todas son de Ituzaingó (salieron de esa búsqueda puntual en Google Maps).

**Bloqueadas por el proxy corporativo (Zscaler) de esta red al chequear — no confirma que el sitio
esté caído, solo que no lo pudimos ver desde acá. Recheckear desde otra red antes de descartarlas:**

| Inmobiliaria | URL |
|---|---|
| Alvarez Pro | https://alvarezpro.com.ar |
| Giusti Propiedades | https://giustipropiedades.com.ar |
| Albanese | https://albanese.com.ar |
| Ber Propiedades | https://berpropiedades.com.ar |
| García Propiedades | https://garciapropiedades.com |
| Marta Rossi Propiedades | https://martarossipropiedades.com.ar |
| Tortolini Propiedades | https://tortolinipropiedades.com |
| Rasgido Propiedades | https://rasgidopropiedades.com.ar |
| LMK Broker | https://lmkbroker.com.ar (dio 403 — no confirmado si es Zscaler o protección propia del sitio) |

**No responden — de las 8 originales, 4 revivieron esta vuelta** (More Leloir y Zopatti, ver
fuentes activas; Romay Desarrollos, ver más abajo) **y quedan 4 confirmadas muertas:**

| Inmobiliaria | URL | Estado |
|---|---|---|
| Inmobiliaria Simone | https://inmobiliariasimone.com.ar | DNS no resuelve (dominio inexistente/vencido) |
| Adriana Ríos Propiedades | https://adrianariospropiedades.com | DNS no resuelve (dominio inexistente/vencido) |
| Nicora Propiedades | https://nicorapropiedades.com.ar | DNS sí resuelve, pero nada responde en el puerto (probado https y http) |
| Oddone Propiedades | https://oddonepropiedades.com | Igual que Nicora — DNS ok, servidor no responde |

**Romay Desarrollos** (`romaydesarrollos.com.ar`, redirige a `www.`) — revivió, pero es una
**desarrolladora de edificios/countries, no una inmobiliaria de reventa**: solo 8 páginas fijas de
proyectos propios ("Durban I", "Edificio Jochy", etc.), WordPress sin custom post type expuesto en
REST, y ninguna página muestra precio — son landings de marketing para captar consultas. Bajo valor
para este proyecto, no se scrapeó.

**Investigadas con Playwright en esta vuelta:**

- **Matías Szpira** (`matiasszpira.com.ar`) — **Resuelto**. Es React de verdad (`id="app"`), pero
  levantar la página en un navegador real mostró que llama a sus propios endpoints locales
  (`/api/results.json`, `/api/property.json`) con el mismo esquema de campos `in_*`/`resultado.fichas`
  que `xintelapi.com.ar` — no hizo falta terminar de usar Playwright para el scraping en sí, solo
  para descubrir el endpoint. Además la cuenta real es **~1.167 propiedades**, no las 12 que se
  veían en la home — el número bajo original era solo lo que la portada mostraba como destacadas.
  Ver plataforma Xintel arriba y tabla de fuentes activas.
- **S. González** (`sgonzalez.com.ar`) — **Resuelto, y no hacía falta Playwright**. El `<title>` se
  queda fijo en "Santiago Gonzalez Inmobiliaria" en todas las páginas (por eso parecía SPA), pero el
  contenido real (precio, m², descripción) está en el HTML servido por el propio servidor —
  confirmado con un `curl` derecho. Catálogo chico, sin paginación (`propiedades.php?operacion=Venta`
  trae todo en una sola página). Ver tabla de fuentes activas.
- **Grupo Vaccaro** (`grupovaccaro.com`) — **Resuelto** en una vuelta anterior — el frontend es
  Angular SPA pero la API JSON real detrás (`xintelapi.com.ar`) no necesitó Playwright. Ver
  plataforma Xintel arriba y tabla de fuentes activas.
- **Germán Tavella** (`germantavella.com.ar`) — **Descartado, no por falta de datos sino por
  robots.txt**. Con Playwright confirmamos que el sitio SÍ es server-rendered (mismo patrón que
  S. González — el `<title>` genérico había hecho parecer que era una SPA) y que corre sobre la
  misma familia Xintel (fotos en `watermark.xintelweb.com`, `codemp=TAV`). Pero su `robots.txt`
  prohíbe explícitamente cualquier URL con query string (`Disallow: /*?`) — justo lo que hace falta
  para paginar `propiedades.php?page=N` — y además fija `Crawl-delay: 60` con apenas 3-6 requests
  permitidos por hora. No es compatible con un scraping respetuoso de su política declarada; se
  descarta por decisión de cumplimiento, no por limitación técnica.

**Sin catálogo público / precio (bajo valor, no priorizar):**

| Inmobiliaria | URL | Nota |
|---|---|---|
| Marasco Quiroga Prop | https://marascoquirogaprop.com.ar | Server-rendered, listado real en `/home/search` + fichas en `/home/view/{id}` (193 propiedades), pero **ninguna ficha muestra precio** — es un esquema "consultar valor" en todas las que probé. Bajo valor para el objetivo del proyecto. |
| Ramírez Prop | https://ramirezprop.com.ar | Hecho en Webflow, sin señales de catálogo. |
| Grupo MSZ | https://grupomsz.com.ar | Hecho en Framer, sin señales de catálogo. |

**Descartadas en esta vuelta:**

- **JM Correa Propiedades** (`jmcorreapropiedades.com`) — página default del hosting ("Welcome to the home of..."), el sitio nunca se llegó a publicar.
- **Propulse Central** (`propulse-central.com`) — confirmado: agencia de consultoría/marketing ("Transformamos ambición en resultados..."), no inmobiliaria — homónimo.
- **Torres Bernal** (~~torresbernal.com.ar~~) — es un estudio jurídico ("Estudio Jurídico Torres Bernal"), homónimo, no la inmobiliaria.

**Wix — confirmado, sin catálogo (descartadas):**

- **Kelezuki** (`kelezuki.com`) — sitio institucional (about/contacto/blog "Conociendo el oeste"),
  sin listado de propiedades.
- **Solimei Propiedades** (`solimeipropiedades.wixsite.com/solimeipropiedades`) — página única de
  contacto, sin catálogo.
- **Lo De Felay** (`lodefelay.wixsite.com`) — probado con varias rutas típicas de Wix
  (`/lodefelay`, `/website`, `/my-site`), 404 en todas. El sitio parece haber sido dado de baja.

**Resueltas en esta vuelta** (ya no están pendientes, ver tabla de fuentes activas): `dicasoli.com.ar`,
`gonzalopropiedades.com.ar`, `repettoprop.com.ar`, `lasalapropiedades.com.ar` (las 4, plataforma
Wasi), `piccioneprop.com.ar` (plataforma Carlucci/Piccione), `msvinmobiliaria.com` y
`portelapropiedades.com.ar` (plataforma Mapaprop, encontrada esta vuelta), `garnicainmuebles.com` y
`gonzalezabella.com.ar` (2 agencias más sobre Mapaprop), `grupovaccaro.com` (plataforma Xintel,
encontrada esta vuelta) y `fabianamtripe.com.ar` (scraper propio, plantilla PHP a medida —
tiene un bug de encoding del lado del sitio que corrompe la "ó" en algunas URLs, no afecta precio/m²/
título), `ledesmaprop.com` (scraper propio, plantilla Navent), `gabrielparis.com.ar` (segundo
tenant confirmado de Xintel, junto a Grupo Vaccaro), `fparadela.com.ar` (variante Amaira/Xintel
vía proxy propio del sitio), `danielinmobiliaria.com.ar` (ArgenCasas con frontend 100% a medida —
el bug estaba en mi propio grep, que buscaba `href="..."` con comillas dobles y el sitio usa
comillas simples), `zopatti.com` (mismo template ArgenCasas que Daniel Inmobiliaria),
`more-leloir.com` (tercer tenant confirmado de Xintel, API directa) y `c21lamoisselorre.com.ar`
(plataforma Century21 nacional, nueva — de paso se sumaron 2 oficinas C21 más de zona oeste que no
estaban en la lista original: Freda en Morón y Portela Sabrina en Ituzaingó).

**Chequeadas y descartadas en esta vuelta** (WordPress con custom post type propio, pero sin los
metadatos de precio/m² expuestos vía REST — necesitarían scraping de HTML, no investigado):
`gomezmartinez.com.ar` (theme WpResidence, CPT `estate_property`), `projectandbrokers.com`
(plugin Estatik, sin CPT propio en REST), `inmobiliariacgramis.com.ar` (REST API no responde).
`tintorero.com.ar` y `mjcarabelli.com` ya estaban resueltas antes (ver tabla de fuentes activas).

## Tres de Febrero (Sáenz Peña, Caseros, Ciudadela, Villa Bosch, Santos Lugares...)

Misma metodología, esta vez arrancando de dos búsquedas de Google Maps ("inmobiliarias" general y
"inmobiliarias tres de febrero") — pero esta vez sin el HTML crudo, solo el texto renderizado de los
resultados (sin `href` reales), así que hubo que ubicar el sitio de cada negocio por nombre +
dirección en vez de sacar la URL directo de la ficha de Maps. ~103 negocios candidatos entre las dos
búsquedas, deduplicados y con dirección/localidad verificada uno por uno contra el propio sitio
(mismo cuidado que ya advertía este archivo: varios "resultaron" ser el mismo nombre pero en otro
partido/CABA — border-street trap distinto del homónimo clásico: la dirección SÍ coincide porque el
negocio está sobre una avenida límite (Beiró, San Martín, Mosconi, Albarellos) pero del lado CABA,
no Tres de Febrero).

**Nuevas fuentes activas esta vuelta** (ver tabla de arriba): `colonna`, `pintimalli`, `larocca`,
`cabrera`, `franco`, `deramo`, `ricciardelli`, `montesdeoca`, `defazio`, `scarinci` — **10 fuentes,
1.351 propiedades**. 6 sobre plataformas ya conocidas (Tokko ×2, ArgenCasas viejo ×2, "adprop" ×1,
Navent "ficha" ×2 — esta última recién generalizada esta vuelta), más 3 plataformas nuevas: JetEngine
(Montes de Oca), un frontend Next.js sobre Xintel (De Fazio) y **Realtyna WPL Pro** (Scarinci,
Sáenz Peña — la fuente más grande de esta tanda, 135 propiedades).

**Resueltas en esta vuelta** (estaban pendientes, ya no lo están):

- **Scarinci Propiedades** (`scarincipropiedades.com.ar`, Sáenz Peña) — **Resuelto sin
  Playwright**, inspeccionando `window` en un navegador real en vez de leyendo el JS minificado a
  ciegas: el plugin expone su estado de paginación en variables globales
  (`wpl_listing_request_str`, `wpl_listing_total_pages`, y la función `wpl_paginate` misma). Con
  `window.wpl_ajax == '0'` en este sitio, paginar es simplemente recargar `/en-venta/` (o
  `/inmuebles-en-alquiler/`) con `?wplview=property_listing&sf_select_listing={9|10}&wplpagination=normal&wplpage={N}`
  — el `/page/N/` nativo de WordPress que se probó antes nunca iba a funcionar, WPL lo ignora
  totalmente. Ojo: pedir una página más allá del final no da vacío, devuelve HTML de navegación que
  por casualidad contiene la palabra "inmueble" en un link no relacionado (`/inmuebles-en-alquiler/`)
  — el discovery tiene que matchear el patrón preciso `inmueble/\d+-...`, no cualquier href con esa
  palabra, o el corte de paginación nunca llega. Fichas con formato limpio
  `Label : <span>Valor</span>`, fácil de parsear. Ver `scrapers/scarinci.py`.
- **De Fazio Inmobiliaria** (`defazioprop.com.ar`, Ciudadela) — **Resuelto**. Frontend Next.js
  propio sobre backend Xintel (fotos en `cdn-images.xintelweb.com`), pero sin la ruta de proxy que
  usa `fparadela.py` (`/api/proxy.php` da 404 acá) y sin `/api/properties` tampoco — no hizo falta:
  `/propiedades` sirve las 260 fichas ya renderizadas en un único HTML (sin paginar). El parseo con
  BeautifulSoup por ancestros (`find_parent`) no encontraba el contenedor de cada tarjeta, así que
  se resolvió con regex sobre el HTML crudo, cortando por cada 2do `href="/propiedades/DEF{id}"`
  (aparece 2 veces por tarjeta). Ver `scrapers/defazio.py`.
- **Castellani - Piccoli Property Consultants** (`castellani-piccoli.com.ar`, Sáenz Peña) — sigue
  **sin resolver**: corre sobre **InmoBusqueda.com.ar**, un portal nacional (no software propio de
  la agencia, como Century21). El listado del tenant vive en `inmobusqueda.com/castellanipiccoli`
  (60 fichas en un solo fetch, sin paginar) pero cada ficha individual
  (`inmobusqueda.com.ar/ficha-{id}`) redirige a `/verificar/?...&h={hash}` — un challenge anti-bot,
  mismo patrón que Argenprop/AWS WAF ya documentado en el otro registro de este proyecto. No se
  intentó bypassear (fuera del alcance de un scraper respetuoso).

**Bloqueadas por el proxy corporativo (Zscaler) de esta red — no confirma que el sitio esté caído,
solo que no lo pudimos ver desde acá (mismo patrón que la sección equivalente para zona oeste; hay
que recheckear desde otra red antes de descartarlas):**

Estas comparten infraestructura de hosting entre sí (mismo bloque de IPs
`34.205.114.230`/`184.192.46.241`/`184.192.177.197`, mismo certificado TLS roto para curl en
Windows vía schannel — `SEC_E_WRONG_PRINCIPAL`), lo que probablemente explica por qué Zscaler las
bloquea juntas mientras deja pasar otros sitios de esta misma tanda de investigación:

| Inmobiliaria | URL | Plataforma (confirmada antes del bloqueo) |
|---|---|---|
| Javier Molina - Negocios Inmobiliarios | molinapropiedades.com.ar | Adinco CRM |
| Ciampinelli Propiedades (rebrandeada "MCNELLI") | ciampinelli.com.ar | Adinco CRM |
| Marcos Gruttaroti negocios inmobiliarios | marcosgruttaroti.com.ar | SaaS Next.js sin nombre (`buildId: mYz2-kr4c8D6S4bvav4_i`) |
| Amado Propiedades | amadoprop.com | mismo SaaS Next.js que Gruttaroti |
| Espinola de Tolosa Estudio Inmobiliario | espinoladetolosa.com.ar | mismo SaaS Next.js — fuera de zona igual (Gral. San Martín) |
| Luis Scagliola Real Estate Broker | scagliolabroker.com.ar | "LiderProp" |

Nota sobre el SaaS Next.js: antes del bloqueo se había confirmado que las 3 agencias sirven el
**mismo build exacto** (`/aviso/[slug]`, `/properties`, `/api/properties`, `/company`,
`/tasaciones`) — un `/api/properties` sin parámetros da 400, hace falta encontrar el querystring
correcto una vez se pueda volver a acceder. Vale la pena generalizarlo si se resuelve, son 2
tenants dentro de zona (Gruttaroti, Amado).

**"HAMMER"**: Inmobiliaria D'Eramo en realidad resultó ser ArgenCasas viejo (ver tabla de fuentes
activas), pero su footer también menciona una marca "HAMMER" — puede ser el nombre comercial de
quien les vendió/mantiene el ArgenCasas, no una plataforma aparte; no se investigó más porque
D'Eramo ya quedó resuelto por otra vía.

**Descartadas esta vuelta** (homónimos de otro partido/CABA confirmados, sin catálogo propio, o ya
cubiertas por otra fuente): de las ~103 candidatas originales, ~40 resultaron ser el mismo patrón ya
documentado arriba (border-street trap o homónimo real), ~15 sin sitio propio (solo presencia en
portales/redes), y un puñado de duplicados de fuentes que ya existían (Nerina Allo → `allo`,
Inmobiliaria Spinelli → `spinelli`, Morroni → `morroni`, Ferrero → `ferrero`, Cartechini →
`cartechini`) o cubiertos por el scraper nacional (`Inmobiliaria REMAX Data Work`, franquicia local
de REMAX). No se llevó el detalle fila por fila de estas al archivo — quedó en la investigación de
esta sesión, no vale la pena inflar este `.md` con ~55 líneas de "no, esta tampoco".

## Notas técnicas

- SQLite no banca bien 3+ scrapers escribiendo a la vez incluso con WAL — bajamos `COMMIT_EVERY` a
  20 (antes 200) para que las transacciones sean cortas, pero igual conviene no lanzar más de 2 en
  simultáneo. `update_all.py` ya corre todo secuencial por esto. Confirmado de nuevo esta vuelta:
  con 4 scrapers nuevos corriendo a la vez (`cabrera` entre ellos) saltó un `database is locked` real
  a mitad de corrida — no corrompió nada (las 61 propiedades ya insertadas quedaron bien), pero cortó
  el resto de esa corrida. Bajar a 2 concurrentes y reintentar el que falló resolvió sin drama.
- Esta red tiene cortes de DNS intermitentes (no es de los sitios) — `MAX_RETRIES` subido a 6. Si
  una corrida falla por `NameResolutionError`, el upsert ya guardó lo que llevaba — reintentar el
  mismo comando retoma sin duplicar nada.
