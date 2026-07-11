"""
Script para automatizar el llenado del formulario de creación de eventos
en IEEE vTools usando Playwright.

Instalación:
    pip install playwright python-dotenv
    playwright install chromium

Uso:

google-chrome-stable --user-data-dir=/tmp/chrome-playwright --remote-debugging-port=9222
https://events.vtools.ieee.org/tego_/event/create

2. Ejecuta: python fill_event.py
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from EventsVtools import events

event = events[0]

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

USERNAME = os.getenv("IEEE_USER")
PASSWORD = os.getenv("IEEE_PASS")

CREATE_EVENT_URL = "https://events.vtools.ieee.org/tego_/event/create"
STORAGE_STATE_FILE = "auth_state.json"  # guarda la sesión para no loguear cada vez


def login(page):
    page.goto(CREATE_EVENT_URL)
    page.wait_for_selector("#username", timeout=15000)
    page.fill("#username", USERNAME)
    page.fill("#password", PASSWORD)
    page.click("#modalWindowRegisterSignInBtn")
    page.wait_for_load_state("networkidle")


# ---------------------------------------------------------------------------
# Helper genérico para todos los campos TinyMCE
# ---------------------------------------------------------------------------
def fill_tinymce(page, textarea_id: str, html_content: str):
    """
    Todos los editores TinyMCE de este formulario siguen el patrón de id
    <textarea id="meeting_description" ...> -> <iframe id="meeting_description_ifr">

    Confirmado para: meeting_contact_display, meeting_description,
    meeting_header, meeting_footer, meeting_agenda, meeting_virtual_info,
    speakers_speaker{N}_topic_description, speakers_speaker{N}_biography, etc.
    """
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
def fill_host_organizational_unit(page, org_name: str, spoid: str = None, index: int = 0):
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


def fill_contact_email(page, email: str, index: int = 0):
    page.fill(f"#meeting_meeting_host_{index}_contact_email", email)


def fill_extra_contact_info(page, html_content: str):
    fill_tinymce(page, "meeting_contact_display", html_content)


# ---------------------------------------------------------------------------
# Sección: Details
# ---------------------------------------------------------------------------
def fill_title(page, title: str):
    page.fill("#meeting_title", title)


def select_category(page, category_label: str):
    """
    category_label debe ser uno de: Professional, Technical, Nontechnical,
    Administrative, Humanitarian, Pre-U STEM Program
    """
    page.select_option("#meeting_category_id", label=category_label)
    # dispara el onchange que carga las subcategorías vía AJAX
    page.wait_for_timeout(800)


def select_subcategory(page, subcategory_label: str):
    """
    Solo funciona después de select_category(), ya que las opciones
    se cargan dinámicamente vía AJAX en #_select_subcategory.
    """
    page.select_option("#meeting_subcategory_id", label=subcategory_label)


def set_wie_event(page, checked: bool = True):
    checkbox = page.locator("#meeting_wie_event")
    if checkbox.is_checked() != checked:
        checkbox.click()


def fill_start_end_time(page, start_text: str, end_text: str):
    """
    Los campos usan bootstrap-datetimepicker con formato "DD MMM YYYY hh:mm A"
    ej: "09 Jul 2026 02:03 PM"
    Se llenan como texto plano y se dispara 'change' para que el picker
    sincronice su estado interno.
    """
    for selector, value in [("#start_time_in_zone", start_text), ("#end_time_in_zone", end_text)]:
        page.fill(selector, value)
        page.eval_on_selector(
            selector,
            "el => el.dispatchEvent(new Event('change', { bubbles: true }))",
        )


def select_timezone(page, timezone_value: str):
    """
    timezone_value debe ser el value real del <option>, ej:
    "America/Mexico_City", "America/Los_Angeles", "Etc/UTC"
    """
    page.select_option("#meeting_tm_zone_info", value=timezone_value)


def fill_description(page, html_content: str):
    fill_tinymce(page, "meeting_description", html_content)


def fill_header(page, html_content: str):
    fill_tinymce(page, "meeting_header", html_content)


def fill_footer(page, html_content: str):
    fill_tinymce(page, "meeting_footer", html_content)


def fill_agenda(page, html_content: str):
    fill_tinymce(page, "meeting_agenda", html_content)


def fill_keywords(page, keywords: str):
    """Campo de texto plano (no TinyMCE)."""
    page.fill("#meeting_keywords", keywords)


def fill_survey_url(page, url: str):
    page.fill("#meeting_survey_url", url)


# ---------------------------------------------------------------------------
# Sección: Location
# ---------------------------------------------------------------------------
def open_location_section(page):
    page.get_by_text("Location", exact=True).click()
    page.wait_for_timeout(500)


def select_location_type(page, location_type: str):
    """
    location_type debe ser uno de: 'virtual', 'hybrid', 'physical'
    (radio buttons name="meeting[location_type]"; 'physical' viene
    marcado por defecto en el HTML).
    """
    page.check(f"input[name='meeting[location_type]'][value='{location_type}']")
    page.wait_for_timeout(300)  # deja que el JS muestre/oculte los paneles Virtual/In-Person


def fill_virtual_info(page, html_content: str):
    """Solo aplica si location_type es 'virtual' o 'hybrid'."""
    fill_tinymce(page, "meeting_virtual_info", html_content)


def fill_physical_address(
    page,
    address1: str = None,
    address2: str = None,
    city: str = None,
    postal_code: str = None,
    building: str = None,
    room_number: str = None,
    map_url: str = None,
):
    """Solo aplica si location_type es 'physical' o 'hybrid'."""
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


def select_country(page, country_label: str):
    """
    country_label es el texto visible del <option>, ej: "Mexico", "United States"
    Dispara un onchange que carga los estados/provincias vía AJAX en
    #meetingstateselect -> #meeting_state_id.
    """
    page.select_option("#meeting_country_id", label=country_label)
    # Espera a que el spinner de carga termine y el nuevo <select> aparezca
    page.wait_for_timeout(1000)


def select_state(page, state_label: str):
    """Solo funciona después de select_country(), ya que se carga vía AJAX."""
    page.select_option("#meeting_state_id", label=state_label)


def set_override_lat_lng(page, latitude: str, longitude: str):
    page.fill("#meeting_user_override_latitude", latitude)
    page.fill("#meeting_user_override_longitude", longitude)


def fill_location(page, location: dict):
    """Aplica todo el dict 'location' de un evento en un solo llamado."""
    loc_type = location.get("type", "physical")
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
def open_speakers_section(page):
    page.get_by_text("Speakers", exact=True).click()
    page.wait_for_timeout(500)


def add_speaker(page):
    """
    Por defecto el formulario trae 2 speakers (1 y 2). Si necesitas más,
    usa este botón, que agrega el siguiente vía AJAX (contador interno
    'nextSpeakerCounter' en la página).
    """
    page.get_by_role("link", name="Add speaker").click()
    page.wait_for_timeout(800)  # espera a que el AJAX inserte el nuevo bloque


def expand_speaker_panel(page, index: int = 1):
    """
    Cada speaker está en un panel colapsable (Bootstrap accordion).
    Hay que expandirlo antes de interactuar con sus campos internos,
    ya que empiezan colapsados (class="collapse", sin "in").
    """
    page.click(f"#_event_speaker{index}_heading a")
    page.wait_for_timeout(400)


def fill_speaker(
    page,
    index: int = 1,
    topic: str = None,
    dlp_speaker: bool = None,
    topic_description_html: str = None,
    prefix: str = None,
    first_name: str = None,
    middle_name: str = None,
    last_name: str = None,
    suffix: str = None,
    display_name: str = None,
    speaker_url: str = None,
    address1: str = None,
    address2: str = None,
    city: str = None,
    country_label: str = None,
    state_label: str = None,
    postal_code: str = None,
    email: str = None,
    biography_html: str = None,
    organization: str = None,
):
    """
    index es el número de speaker (1, 2, 3...), correspondiente a los ids
    reales del HTML: speakers_speaker{index}_{campo}

    Nota: country/state usan doble guion bajo en el id real:
    speakers_speaker{index}__country_id / __state_id
    """
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
        page.wait_for_timeout(1000)  # carga de estados vía AJAX

    if state_label is not None:
        page.select_option(f"#{prefix_id}__state_id", label=state_label)


def fill_speakers(page, speakers: list):
    """
    Recorre una lista de dicts de speakers (como event["speakers"]) y
    llena cada uno. El formulario ya trae 2 paneles (index 1 y 2); si hay
    más de 2 speakers en la lista, se agregan automáticamente con
    add_speaker() antes de llenarlos.
    """
    for i, speaker_data in enumerate(speakers, start=1):
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
def save_as_draft(page):
    page.get_by_role("link", name="Save as Draft").click()
    page.wait_for_load_state("networkidle")


def open_details_section(page):
    page.get_by_text("Details", exact=True).click()
    page.wait_for_timeout(500)


# ---------------------------------------------------------------------------
def main():
    if not USERNAME or not PASSWORD:
        raise SystemExit("Faltan IEEE_USER / IEEE_PASS en el archivo .env")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")

        context = browser.contexts[0]

        # Busca entre las pestañas abiertas la que ya esté en el formulario de creación
        page = None
        for p_candidate in context.pages:
            if "event/create" in p_candidate.url:
                page = p_candidate
                break

        if page is None:
            # Ninguna pestaña abierta tiene el formulario cargado: usa la primera y navega
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(CREATE_EVENT_URL)

        page.wait_for_selector("#_event_host_spoid_0", timeout=15000)

        # --- Host ---
        fill_host_organizational_unit(
            page,
            org_name="Universidad Autonoma de Aguascalientes",
            spoid="STB60021134",
        )
        fill_contact_email(page, "ieeeagsuaa@gmail.com")
        # fill_extra_contact_info(page, "<p>Información adicional aquí</p>")

        open_details_section(page)

        # --- Details ---
        fill_title(page, event["title"])
        select_category(page, event["category"])
        if event.get("subcategory"):
            select_subcategory(page, event["subcategory"])

        fill_start_end_time(page, event["start_time"], event["end_time"])
        select_timezone(page, event["timezone"])
        fill_description(page, event["description"])
        fill_header(page, event["header"])
        fill_footer(page, event["footer"])
        fill_agenda(page, event["agenda"])
        fill_keywords(page, event["keywords"])
        fill_survey_url(page, event["survey_url"])

        open_location_section(page)

        # --- Location ---
        fill_location(page, event["location"])

        open_speakers_section(page)

        # --- Speakers ---
        if event.get("speakers"):
            fill_speakers(page, event["speakers"])

        input("Revisa el formulario en el navegador y presiona Enter para continuar...")
        save_as_draft(page)

        browser.close()


if __name__ == "__main__":
    main()