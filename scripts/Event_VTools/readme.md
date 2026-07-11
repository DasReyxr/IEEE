# vTools Event Filler

Script de automatización con [Playwright](https://playwright.dev/python/) para llenar el formulario de creación de eventos de **IEEE vTools Events** (`https://events.vtools.ieee.org/tego_/event/create`), a partir de datos definidos en un archivo Python (`EventsVtools.py`).

En vez de intentar automatizar el login (que pasa por PingFederate/PingOne SSO), el script se conecta a una ventana de **Chrome ya abierta y logueada manualmente** mediante el protocolo de depuración remota de Chrome (CDP). Esto evita pelear con SSO/2FA y hace que el flujo sea más confiable.

## Cómo funciona

1. Se lanza (o abres tú manualmente) una instancia de Chrome con el puerto de depuración remota habilitado.
2. Te logueas **tú mismo** en esa ventana con tu cuenta IEEE, de forma normal.
3. El script se conecta a esa ventana ya autenticada vía Playwright (`connect_over_cdp`) y llena el formulario automáticamente con los datos definidos en `EventsVtools.py`.
4. Antes de guardar, el script pausa (`input(...)`) para que revises visualmente el formulario.
5. Al confirmar, guarda el evento como **borrador** (Save as Draft).

## Requisitos

- Python 3.9+
- Google Chrome instalado
- Las siguientes dependencias:

```bash
pip install playwright python-dotenv
playwright install chromium
```

## Estructura del proyecto

```
vtools_bot/
├── fill_event.py       # Script principal: funciones de llenado + main()
├── EventsVtools.py      # Datos de los eventos a crear (lista `events`)
├── .env                 # Credenciales (NO subir a git)
└── auth_state.json      # (no usado actualmente con CDP; ver nota abajo)
```


## Uso

### 1. Abre Chrome con el puerto de depuración remota

**Opción A — Automático (recomendado):**
El script incluye `launch_chrome_with_debugging()`, que detecta tu sistema operativo (Windows / macOS / Linux) y lanza Chrome con la configuración correcta usando un perfil temporal separado de tu Chrome normal.

**Opción B — Manual**, si prefieres controlarlo tú:

**Windows** (PowerShell o CMD):
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="%TEMP%\chrome-playwright" --remote-debugging-port=9222 https://events.vtools.ieee.org/tego_/event/create
```

**macOS:**
```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --user-data-dir=/tmp/chrome-playwright --remote-debugging-port=9222 https://events.vtools.ieee.org/tego_/event/create
```

**Linux:**
```bash
google-chrome-stable --user-data-dir=/tmp/chrome-playwright --remote-debugging-port=9222 https://events.vtools.ieee.org/tego_/event/create
```

> El `--user-data-dir` apunta a un perfil temporal (nunca tu perfil normal de Chrome), así que la primera vez tendrás que loguearte de nuevo con tu cuenta IEEE en esa ventana.

### 2. Logueate manualmente

En la ventana de Chrome que se abrió, inicia sesión con tu cuenta IEEE normalmente (usuario/contraseña, y cualquier 2FA si aplica). Asegúrate de terminar en la página `.../tego_/event/create`.

### 3. Define tus eventos en `EventsVtools.py`

```python
events = [
    {
        "title": "Título del evento",
        "category": "Technical",          # Professional | Technical | Nontechnical
                                            # | Administrative | Humanitarian
                                            # | Pre-U STEM Program
        # "subcategory": "Continuing Education",
        "start_time": "23 Jun 2026 11:00 AM",   # formato: DD MMM YYYY hh:mm A
        "end_time":   "23 Jun 2026 02:05 PM",
        "timezone": "America/Mexico_City",       # value real del <option>
        "description": "<p>HTML de la descripción</p>",
        "header": "<p>HTML del encabezado</p>",
        "footer": "<p>HTML del pie de página</p>",
        "agenda": "<p>HTML de la agenda</p>",
        "keywords": "#IEEE, #evento, #tecnologia",
        "survey_url": "https://ejemplo.com/encuesta",

        "location": {
            "type": "physical",  # physical | virtual | hybrid
            "address1": "Av. Universidad 940",
            "city": "Aguascalientes",
            "postal_code": "20131",
            "building": "Centro de Ciencias Básicas",
            "country": "Mexico",       # texto EXACTO del <option> (en inglés)
            # "state": "Aguascalientes",
            # "virtual_info_html": "<p>Link de Zoom</p>",  # si type es virtual/hybrid
        },

        "speakers": [
            {
                "topic": "Tema de la charla",
                "prefix": "Dra.",
                "first_name": "María",
                "last_name": "Pérez",
                "display_name": "Dra. María Pérez",
                "organization": "Universidad X",
                "email": "maria@ejemplo.com",
                "topic_description_html": "<p>Descripción del tema</p>",
                "biography_html": "<p>Biografía</p>",
            },
        ],
    },
]
```

Solo necesitas incluir las claves que te interesen — todas las funciones de llenado aceptan valores opcionales y se saltan los campos no especificados. `EventsVtools.py` puede tener tantos eventos como quieras en la lista; el script (`event = events[0]`) actualmente solo procesa el **primero**.

### 4. Ejecuta el script

```bash
python fill_event.py
```

El script:
1. Se conecta al Chrome ya abierto en el puerto `9222`.
2. Busca la pestaña con el formulario cargado (o navega ahí si no la encuentra).
3. Llena **Host**, **Details**, **Location** y **Speakers** con los datos de `events[0]`.
4. Se detiene con un `input(...)` para que revises todo visualmente en el navegador.
5. Al presionar Enter, guarda el evento como borrador (**Save as Draft**).

## Secciones soportadas

| Sección | Función principal | Notas |
|---|---|---|
| Host | `fill_host_organizational_unit`, `fill_contact_email`, `fill_extra_contact_info` | El SPOID (código de la unidad organizacional) se setea directo vía JS si ya lo conoces |
| Details | `fill_title`, `select_category`, `select_subcategory`, `fill_start_end_time`, `select_timezone`, `fill_description`, `fill_header`, `fill_footer`, `fill_agenda`, `fill_keywords`, `fill_survey_url` | Sub-category se carga vía AJAX después de elegir Category |
| Location | `fill_location` (envuelve `select_location_type`, `fill_physical_address`, `select_country`, `select_state`, `fill_virtual_info`) | Country/State usan AJAX para cargar el `<select>` de estados |
| Speakers | `fill_speakers` (envuelve `expand_speaker_panel`, `fill_speaker`, `add_speaker`) | El formulario trae 2 paneles de speaker por defecto; se agregan más automáticamente si la lista los necesita |

**No implementado aún:** Registration & Payment, Report/Attendance, Co-Hosts, Cosponsor.

## Notas técnicas importantes

- **TinyMCE:** todos los editores de texto enriquecido siguen el patrón `<textarea id="X">` → `<iframe id="X_ifr">`. La función genérica `fill_tinymce(page, textarea_id, html)` funciona para cualquiera de ellos (Description, Header, Footer, Agenda, Extra Contact Info, Virtual Info, biografías/descripciones de speakers).
- **Selects con carga AJAX** (Sub-category, Country → State): se usan `page.wait_for_timeout(...)` como aproximación simple. Si fallan por lentitud de red, hay que reemplazarlos por un `page.wait_for_function(...)` que espere a que el `<select>` tenga más de una opción.
- **Fecha/hora:** los campos de inicio/fin usan `bootstrap-datetimepicker` con formato `"DD MMM YYYY hh:mm A"` (ej. `"23 Jun 2026 11:00 AM"`). Se llenan como texto plano + evento `change`.
- **Paneles de Speaker** empiezan colapsados; hay que expandirlos (`expand_speaker_panel`) antes de llenar sus campos internos.
- **`select_country`/`select_state`** de Speaker usan doble guion bajo en el id real (`speakers_speaker{N}__country_id`), a diferencia de otros campos.

## Troubleshooting

**`Failed to find element matching selector "#_event_host_spoid_0"`**
La pestaña conectada no tenía el formulario cargado. Verifica que:
- Chrome esté corriendo con `--remote-debugging-port=9222`.
- Estés logueado y en la URL `.../tego_/event/create`.
- El puerto 9222 no esté siendo usado por otra instancia de Chrome.

**El script se conecta pero no hace nada visible**
Revisa que no haya múltiples pestañas abiertas confundiendo la detección automática (`context.pages`); el script busca la que contenga `"event/create"` en su URL.

**Falla `select_subcategory` o `select_state`**
Aumenta el `wait_for_timeout` correspondiente, o reemplázalo por `wait_for_function` esperando a que el `<select>` tenga opciones cargadas.

