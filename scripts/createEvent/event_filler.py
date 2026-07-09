"""
event_filler.py

Toda la lógica de automatización de Playwright para el formulario de
creación de eventos de IEEE vTools. Este módulo NO tiene interfaz propia:
lo consume gui_app.py.

Puntos clave de diseño:
- Nunca se hardcodean credenciales aquí; siempre se reciben como parámetros.
- Todas las funciones "de negocio" (fill_*) aceptan un callback `log(str)`
  opcional para reportar progreso a la GUI sin acoplarse a tkinter.
- Los campos de fecha/hora se consideran "sensibles" porque el datepicker
  de vTools es frágil: un formato incorrecto lo deja en blanco o con la
  fecha equivocada sin lanzar ningún error visible. Por eso se valida el
  formato ANTES de escribir nada en la página.
"""

from __future__ import annotations

import re
import socket
import subprocess
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError

CREATE_EVENT_URL = "https://events.vtools.ieee.org/tego_/event/create"
DEBUG_PORT = 9222

# Formato exacto que exige el datetimepicker de vTools, ej: "09 Jul 2026 02:03 PM"
DATETIME_FORMAT = "%d %b %Y %I:%M %p"

# Abreviaturas de mes en inglés, tal como las espera vTools. Se usan de forma
# explícita (en vez de strftime/strptime con "%b") porque esas funciones
# dependen del locale del sistema operativo: en un Windows configurado en
# español, "%b" produce "jul." en vez de "Jul" y rompe el formulario.
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_MONTHS_EN_LOOKUP = {m.lower(): i + 1 for i, m in enumerate(MONTHS_EN)}

_DATETIME_RE = re.compile(
    r"^(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3})\s+(?P<year>\d{4})\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>[AaPp][Mm])$"
)


def _noop(_msg: str) -> None:
    pass


# ---------------------------------------------------------------------------
# Validación de campos sensibles (fechas)
# ---------------------------------------------------------------------------
def validate_datetime_str(value: str) -> datetime:
    """
    Valida que `value` cumpla el formato "DD MMM YYYY hh:mm AM/PM" (con
    abreviatura de mes en inglés). Lanza ValueError con un mensaje claro si
    no es válido. El parseo es manual (no usa strptime con "%b") para no
    depender del idioma configurado en el sistema operativo.
    """
    raw = value.strip()
    match = _DATETIME_RE.match(raw)
    if not match:
        raise ValueError(
            f"Fecha/hora inválida: '{raw}'. "
            f"Formato esperado: 'DD Mon YYYY hh:mm AM/PM', ej: '09 Jul 2026 02:03 PM'."
        )

    month_key = match.group("month").lower()
    if month_key not in _MONTHS_EN_LOOKUP:
        raise ValueError(
            f"Mes no reconocido en '{raw}'. Usa abreviaturas en inglés: "
            + ", ".join(MONTHS_EN)
        )

    day = int(match.group("day"))
    month = _MONTHS_EN_LOOKUP[month_key]
    year = int(match.group("year"))
    hour12 = int(match.group("hour"))
    minute = int(match.group("minute"))
    ampm = match.group("ampm").upper()

    if not (1 <= hour12 <= 12) or not (0 <= minute <= 59):
        raise ValueError(f"Hora inválida en '{raw}'.")

    hour24 = (hour12 % 12) + (12 if ampm == "PM" else 0)
    try:
        return datetime(year, month, day, hour24, minute)
    except ValueError as exc:
        raise ValueError(f"Fecha inválida: '{raw}' ({exc})") from exc


def format_vtools_datetime(dt: datetime) -> str:
    """Inverso de validate_datetime_str: datetime -> texto en el formato de vTools."""
    hour12 = dt.hour % 12
    hour12 = 12 if hour12 == 0 else hour12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{dt.day:02d} {MONTHS_EN[dt.month - 1]} {dt.year} {hour12:02d}:{dt.minute:02d} {ampm}"


def validate_event_dates(event: dict) -> None:
    """Valida start_time/end_time y que end > start. Lanza ValueError si algo falla."""
    start_dt = validate_datetime_str(event["start_time"])
    end_dt = validate_datetime_str(event["end_time"])
    if end_dt <= start_dt:
        raise ValueError(
            f"La fecha de fin ({event['end_time']}) debe ser posterior "
            f"a la fecha de inicio ({event['start_time']})."
        )


# ---------------------------------------------------------------------------
# Detección de Chrome multiplataforma
# ---------------------------------------------------------------------------
def find_chrome_executable() -> str | None:
    """Busca un ejecutable de Chrome/Chromium en Windows, Linux o macOS."""
    candidates: list[str] = []

    if sys.platform.startswith("win"):
        import os as _os
        program_files = [
            _os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            _os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            _os.environ.get("LOCALAPPDATA", ""),
        ]
        for pf in program_files:
            if pf:
                candidates.append(str(Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe"))
        candidates += ["chrome.exe", "chrome"]
    elif sys.platform == "darwin":
        candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        candidates += ["google-chrome", "chromium"]
    else:  # Linux y similares
        candidates += [
            "google-chrome-stable",
            "google-chrome",
            "chromium-browser",
            "chromium",
        ]

    for cand in candidates:
        # Ruta absoluta que ya existe
        if Path(cand).is_file():
            return cand
        # Buscar en PATH
        found = shutil.which(cand)
        if found:
            return found

    return None


def _port_is_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def launch_chrome_with_debugging(
    chrome_path: str,
    url: str = CREATE_EVENT_URL,
    port: int = DEBUG_PORT,
    wait_seconds: float = 15.0,
    log=_noop,
) -> subprocess.Popen:
    """
    Lanza Chrome con --remote-debugging-port en un perfil temporal dedicado
    (para no interferir con la sesión normal del usuario) y espera hasta
    que el puerto de depuración responda.
    """
    user_data_dir = tempfile.mkdtemp(prefix="ieee_vtools_chrome_")
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        url,
    ]
    log(f"Iniciando Chrome: {chrome_path}")
    proc = subprocess.Popen(args)

    waited = 0.0
    step = 0.5
    while waited < wait_seconds:
        if _port_is_open(port):
            log("Puerto de depuración de Chrome listo.")
            return proc
        time.sleep(step)
        waited += step

    raise RuntimeError(
        f"Chrome no respondió en el puerto {port} tras {wait_seconds}s. "
        "Revisa que no haya otra instancia de Chrome bloqueando el puerto."
    )


# ---------------------------------------------------------------------------
# Login (solo se ejecuta si detectamos el formulario de login en pantalla)
# ---------------------------------------------------------------------------
def login_if_needed(page: Page, username: str, password: str, log=_noop, timeout: int = 4000) -> bool:
    """
    Revisa si el formulario de login está presente y, si es así, lo llena
    y lo envía. Devuelve True si hizo login, False si ya había sesión iniciada.
    """
    try:
        page.wait_for_selector("#username", timeout=timeout)
    except PlaywrightTimeoutError:
        log("Sesión ya iniciada (no se detectó formulario de login).")
        return False

    if not username or not password:
        raise RuntimeError(
            "Se detectó el formulario de login pero no hay credenciales "
            "(IEEE_USER / IEEE_PASS). Complétalas en la interfaz o en el .env"
        )

    log("Formulario de login detectado, ingresando credenciales...")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#modalWindowRegisterSignInBtn")
    page.wait_for_load_state("networkidle")
    log("Login completado.")
    return True


# ---------------------------------------------------------------------------
# Helper genérico para todos los campos TinyMCE
# ---------------------------------------------------------------------------
def fill_tinymce(page: Page, textarea_id: str, html_content: str):
    iframe_id = f"{textarea_id}_ifr"
    frame = page.frame_locator(f"#{iframe_id}")
    body = frame.locator("body#tinymce")
    body.click()
    body.evaluate(
        """(el, html) => {
            el.innerHTML = html;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        html_content,
    )


# ---------------------------------------------------------------------------
# Sección: Host
# ---------------------------------------------------------------------------
def fill_host_organizational_unit(page: Page, org_name: str, spoid: str | None = None, index: int = 0):
    field_id = f"_event_host_spoid_{index}"
    if spoid:
        page.eval_on_selector(
            f"#{field_id}",
            """(el, spoid) => {
                el.value = spoid;
                el.setAttribute('data-spoid', spoid);
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }""",
            spoid,
        )
    else:
        page.fill(f"#_event_host_search_{index}", org_name)
        page.wait_for_selector(f"text={org_name}", timeout=10000)
        page.click(f"text={org_name}")


def fill_contact_email(page: Page, email: str, index: int = 0):
    page.fill(f"#meeting_meeting_host_{index}_contact_email", email)


def fill_extra_contact_info(page: Page, html_content: str):
    fill_tinymce(page, "meeting_contact_display", html_content)


# ---------------------------------------------------------------------------
# Sección: Details
# ---------------------------------------------------------------------------
def fill_title(page: Page, title: str):
    page.fill("#meeting_title", title)


def select_category(page: Page, category_label: str):
    page.select_option("#meeting_category_id", label=category_label)
    page.wait_for_timeout(800)


def select_subcategory(page: Page, subcategory_label: str):
    page.select_option("#meeting_subcategory_id", label=subcategory_label)


def set_wie_event(page: Page, checked: bool = True):
    checkbox = page.locator("#meeting_wie_event")
    if checkbox.is_checked() != checked:
        checkbox.click()


def fill_start_end_time(page: Page, start_text: str, end_text: str):
    """
    CAMPO SENSIBLE: valida el formato antes de tocar la página. El picker
    de vTools no avisa si el texto no calza con "DD MMM YYYY hh:mm A".
    """
    validate_datetime_str(start_text)
    validate_datetime_str(end_text)

    for selector, value in [("#start_time_in_zone", start_text), ("#end_time_in_zone", end_text)]:
        page.fill(selector, value)
        page.eval_on_selector(
            selector,
            "el => el.dispatchEvent(new Event('change', { bubbles: true }))",
        )


def select_timezone(page: Page, timezone_value: str):
    page.select_option("#meeting_tm_zone_info", value=timezone_value)


def fill_description(page: Page, html_content: str):
    fill_tinymce(page, "meeting_description", html_content)


def fill_header(page: Page, html_content: str):
    fill_tinymce(page, "meeting_header", html_content)


def fill_footer(page: Page, html_content: str):
    fill_tinymce(page, "meeting_footer", html_content)


def fill_agenda(page: Page, html_content: str):
    fill_tinymce(page, "meeting_agenda", html_content)


def fill_keywords(page: Page, keywords: str):
    page.fill("#meeting_keywords", keywords)


def fill_survey_url(page: Page, url: str):
    page.fill("#meeting_survey_url", url)


# ---------------------------------------------------------------------------
# Sección: Location
# ---------------------------------------------------------------------------
def open_location_section(page: Page):
    page.get_by_text("Location", exact=True).click()
    page.wait_for_timeout(500)


def select_location_type(page: Page, location_type: str):
    page.check(f"input[name='meeting[location_type]'][value='{location_type}']")
    page.wait_for_timeout(300)


def fill_virtual_info(page: Page, html_content: str):
    fill_tinymce(page, "meeting_virtual_info", html_content)


def fill_physical_address(
    page: Page,
    address1: str | None = None,
    address2: str | None = None,
    city: str | None = None,
    postal_code: str | None = None,
    building: str | None = None,
    room_number: str | None = None,
    map_url: str | None = None,
):
    field_map = {
        "#meeting_address1": address1,
        "#meeting_address2": address2,
        "#meeting_city": city,
        "#meeting_postal_code": postal_code,
        "#meeting_building": building,
        "#meeting_room_number": room_number,
        "#meeting_map_url": map_url,
    }
    for selector, value in field_map.items():
        if value is not None:
            page.fill(selector, value)


def select_country(page: Page, country_label: str):
    page.select_option("#meeting_country_id", label=country_label)
    page.wait_for_timeout(1000)


def select_state(page: Page, state_label: str):
    page.select_option("#meeting_state_id", label=state_label)


def set_override_lat_lng(page: Page, latitude: str, longitude: str):
    page.fill("#meeting_user_override_latitude", latitude)
    page.fill("#meeting_user_override_longitude", longitude)


def fill_location(page: Page, location: dict, log=_noop):
    loc_type = location.get("type", "physical")
    log(f"Configurando ubicación tipo '{loc_type}'...")
    select_location_type(page, loc_type)

    if loc_type in ("physical", "hybrid"):
        fill_physical_address(
            page,
            address1=location.get("address1"),
            address2=location.get("address2"),
            city=location.get("city"),
            postal_code=location.get("postal_code"),
            building=location.get("building"),
            room_number=location.get("room_number"),
            map_url=location.get("map_url"),
        )
        if location.get("country"):
            select_country(page, location["country"])
        if location.get("state"):
            select_state(page, location["state"])

    if loc_type in ("virtual", "hybrid") and location.get("virtual_info_html"):
        fill_virtual_info(page, location["virtual_info_html"])


# ---------------------------------------------------------------------------
# Sección: Speakers
# ---------------------------------------------------------------------------
def open_speakers_section(page: Page):
    page.get_by_text("Speakers", exact=True).click()
    page.wait_for_timeout(500)


def add_speaker(page: Page):
    page.get_by_role("link", name="Add speaker").click()
    page.wait_for_timeout(800)


def expand_speaker_panel(page: Page, index: int = 1):
    page.click(f"#_event_speaker{index}_heading a")
    page.wait_for_timeout(400)


def fill_speaker(
    page: Page,
    index: int = 1,
    topic: str | None = None,
    dlp_speaker: bool | None = None,
    topic_description_html: str | None = None,
    prefix: str | None = None,
    first_name: str | None = None,
    middle_name: str | None = None,
    last_name: str | None = None,
    suffix: str | None = None,
    display_name: str | None = None,
    speaker_url: str | None = None,
    address1: str | None = None,
    address2: str | None = None,
    city: str | None = None,
    country_label: str | None = None,
    state_label: str | None = None,
    postal_code: str | None = None,
    email: str | None = None,
    biography_html: str | None = None,
    organization: str | None = None,
):
    prefix_id = f"speakers_speaker{index}"

    simple_fields = {
        f"#{prefix_id}_topic": topic,
        f"#{prefix_id}_prefix": prefix,
        f"#{prefix_id}_first_name": first_name,
        f"#{prefix_id}_middle_name": middle_name,
        f"#{prefix_id}_last_name": last_name,
        f"#{prefix_id}_suffix": suffix,
        f"#{prefix_id}_display_name": display_name,
        f"#{prefix_id}_speaker_url": speaker_url,
        f"#{prefix_id}_address1": address1,
        f"#{prefix_id}_address2": address2,
        f"#{prefix_id}_city": city,
        f"#{prefix_id}_postal_code": postal_code,
        f"#{prefix_id}_email": email,
        f"#{prefix_id}_organization": organization,
    }
    for selector, value in simple_fields.items():
        if value is not None:
            page.fill(selector, value)

    if dlp_speaker is not None:
        checkbox = page.locator(f"#{prefix_id}_dlp_speaker")
        if checkbox.is_checked() != dlp_speaker:
            checkbox.click()

    if topic_description_html is not None:
        fill_tinymce(page, f"{prefix_id}_topic_description", topic_description_html)

    if biography_html is not None:
        fill_tinymce(page, f"{prefix_id}_biography", biography_html)

    if country_label is not None:
        page.select_option(f"#{prefix_id}__country_id", label=country_label)
        page.wait_for_timeout(1000)

    if state_label is not None:
        page.select_option(f"#{prefix_id}__state_id", label=state_label)


def fill_speakers(page: Page, speakers: list, log=_noop):
    for i, speaker_data in enumerate(speakers, start=1):
        log(f"Llenando speaker #{i}: {speaker_data.get('display_name', '(sin nombre)')}")
        if i > 2:
            add_speaker(page)
        expand_speaker_panel(page, index=i)
        fill_speaker(
            page,
            index=i,
            topic=speaker_data.get("topic"),
            dlp_speaker=speaker_data.get("dlp_speaker"),
            topic_description_html=speaker_data.get("topic_description_html"),
            prefix=speaker_data.get("prefix"),
            first_name=speaker_data.get("first_name"),
            middle_name=speaker_data.get("middle_name"),
            last_name=speaker_data.get("last_name"),
            suffix=speaker_data.get("suffix"),
            display_name=speaker_data.get("display_name"),
            speaker_url=speaker_data.get("speaker_url"),
            address1=speaker_data.get("address1"),
            address2=speaker_data.get("address2"),
            city=speaker_data.get("city"),
            country_label=speaker_data.get("country"),
            state_label=speaker_data.get("state"),
            postal_code=speaker_data.get("postal_code"),
            email=speaker_data.get("email"),
            biography_html=speaker_data.get("biography_html"),
            organization=speaker_data.get("organization"),
        )


# ---------------------------------------------------------------------------
# Botones / navegación
# ---------------------------------------------------------------------------
def open_details_section(page: Page):
    page.get_by_text("Details", exact=True).click()
    page.wait_for_timeout(500)


def save_as_draft(page: Page, log=_noop):
    log("Guardando como borrador...")
    page.get_by_role("link", name="Save as Draft").click()
    page.wait_for_load_state("networkidle")
    log("Guardado como borrador.")


# ---------------------------------------------------------------------------
# Orquestación de alto nivel (usada por la GUI)
# ---------------------------------------------------------------------------
def fill_event_form(
    page: Page,
    event: dict,
    host_org_name: str,
    host_spoid: str,
    host_contact_email: str,
    log=_noop,
) -> None:
    """
    Ejecuta el llenado completo del formulario para un evento, en el mismo
    orden que el script original. Lanza ValueError si las fechas no son válidas.
    """
    # Validación temprana de campos sensibles antes de tocar el DOM
    validate_event_dates(event)

    log("Esperando formulario de creación de evento...")
    page.wait_for_selector("#_event_host_spoid_0", timeout=15000)

    log("Llenando datos del host...")
    fill_host_organizational_unit(page, org_name=host_org_name, spoid=host_spoid)
    fill_contact_email(page, host_contact_email)

    open_details_section(page)

    log(f"Llenando detalles del evento: {event['title']}")
    fill_title(page, event["title"])
    select_category(page, event["category"])
    if event.get("subcategory"):
        select_subcategory(page, event["subcategory"])

    log(f"Fecha/hora inicio: {event['start_time']} | fin: {event['end_time']} ({event['timezone']})")
    fill_start_end_time(page, event["start_time"], event["end_time"])
    select_timezone(page, event["timezone"])
    fill_description(page, event["description"])
    fill_header(page, event["header"])
    fill_footer(page, event["footer"])
    fill_agenda(page, event["agenda"])
    fill_keywords(page, event["keywords"])
    fill_survey_url(page, event.get("survey_url", ""))

    open_location_section(page)
    fill_location(page, event["location"], log=log)

    if event.get("speakers"):
        open_speakers_section(page)
        fill_speakers(page, event["speakers"], log=log)

    log("Formulario llenado. Revísalo en el navegador antes de guardar.")


# ---------------------------------------------------------------------------
# Controlador de sesión: mantiene vivo el browser/page entre clics de la GUI
# ---------------------------------------------------------------------------
class AutomationController:
    """
    Envuelve el ciclo de vida de Playwright + Chrome para que la GUI pueda:
      1) Conectar (lanzando Chrome o reusando uno ya abierto)
      2) Llenar el formulario
      3) Guardar como borrador
      4) Cerrar todo
    manteniendo el mismo `page` vivo entre pasos.
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._chrome_process: subprocess.Popen | None = None
        self.page: Page | None = None

    def connect(
        self,
        launch_chrome: bool,
        username: str,
        password: str,
        log=_noop,
    ) -> Page:
        self._playwright = sync_playwright().start()

        if launch_chrome:
            chrome_path = find_chrome_executable()
            if not chrome_path:
                raise RuntimeError(
                    "No se encontró Chrome instalado en este sistema. "
                    "Instálalo o desactiva la opción 'Iniciar Chrome automáticamente' "
                    "y ábrelo manualmente con --remote-debugging-port=9222."
                )
            self._chrome_process = launch_chrome_with_debugging(chrome_path, log=log)
            # Da tiempo a que la pestaña inicial cargue la URL
            time.sleep(1.5)
        else:
            if not _port_is_open(DEBUG_PORT):
                raise RuntimeError(
                    f"No hay ninguna instancia de Chrome escuchando en el puerto {DEBUG_PORT}. "
                    "Actívalo manualmente con:\n"
                    "  google-chrome-stable --user-data-dir=/tmp/chrome-playwright "
                    f"--remote-debugging-port={DEBUG_PORT}\n"
                    "o activa la opción 'Iniciar Chrome automáticamente'."
                )

        log("Conectando a Chrome vía CDP...")
        self._browser = self._playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{DEBUG_PORT}")
        context = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()

        page = None
        for candidate in context.pages:
            if "event/create" in candidate.url:
                page = candidate
                break
        if page is None:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(CREATE_EVENT_URL)

        login_if_needed(page, username, password, log=log)

        self.page = page
        return page

    def fill(self, event: dict, host_org_name: str, host_spoid: str, host_contact_email: str, log=_noop):
        if self.page is None:
            raise RuntimeError("No hay conexión activa. Ejecuta connect() primero.")
        fill_event_form(self.page, event, host_org_name, host_spoid, host_contact_email, log=log)

    def save_draft(self, log=_noop):
        if self.page is None:
            raise RuntimeError("No hay conexión activa.")
        save_as_draft(self.page, log=log)

    def close(self, log=_noop):
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        if self._chrome_process:
            try:
                self._chrome_process.terminate()
            except Exception:
                pass
        log("Sesión cerrada.")
        self.page = None
