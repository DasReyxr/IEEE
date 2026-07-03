"""
Script para automatizar el llenado del formulario de creación de eventos
en IEEE vTools usando Playwright.

Instalación:
    pip install playwright python-dotenv
    playwright install chromium

Uso:
    1. Crea un archivo .env en la misma carpeta con:
        IEEE_USER=tu_usuario
        IEEE_PASS=tu_contraseña
    2. Ejecuta: python fill_event.py
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

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
# Botones / navegación
# ---------------------------------------------------------------------------
def save_as_draft(page):
    page.get_by_role("link", name="Save as Draft").click()
    page.wait_for_load_state("networkidle")


def open_details_section(page):
    page.get_by_text("Details", exact=True).click()
    page.wait_for_timeout(500)


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


# ---------------------------------------------------------------------------
def main():
    if not USERNAME or not PASSWORD:
        raise SystemExit("Faltan IEEE_USER / IEEE_PASS en el archivo .env")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)

        if os.path.exists(STORAGE_STATE_FILE):
            context = browser.new_context(storage_state=STORAGE_STATE_FILE)
        else:
            context = browser.new_context()

        page = context.new_page()

        if not os.path.exists(STORAGE_STATE_FILE):
            login(page)
            context.storage_state(path=STORAGE_STATE_FILE)
        else:
            page.goto(CREATE_EVENT_URL)
            page.wait_for_load_state("networkidle")

        # --- Host ---
        fill_host_organizational_unit(
            page,
            org_name="Universidad Autonoma de Aguascalientes",
            spoid="STB60021134",
        )
        fill_contact_email(page, "correo@ejemplo.com")
        fill_extra_contact_info(page, "<p>Información adicional aquí</p>")

        open_details_section(page)

        # --- Details ---
        fill_title(page, "Título del evento de ejemplo")
        select_category(page, "Technical")
        # select_subcategory(page, "Continuing Education")  # descomenta si aplica
        fill_start_end_time(page, "09 Jul 2026 02:03 PM", "24 Jul 2026 02:05 PM")
        select_timezone(page, "America/Mexico_City")
        fill_description(page, "<p>Descripción del evento aquí.</p>")
        fill_header(page, "<p>Encabezado</p>")
        fill_footer(page, "<p>Pie de página</p>")
        fill_agenda(page, "<p>Agenda</p>")
        fill_keywords(page, "IEEE evento tecnologia")
        fill_survey_url(page, "https://ejemplo.com/encuesta")

        open_location_section(page)

        # --- Location ---
        select_location_type(page, "physical")  # o "virtual" / "hybrid"
        fill_physical_address(
            page,
            address1="Av. Universidad 940",
            city="Aguascalientes",
            postal_code="20131",
            building="Centro de Ciencias Básicas",
        )
        select_country(page, "Mexico")
        # select_state(page, "Aguascalientes")  # descomenta una vez cargado el select
        # fill_virtual_info(page, "<p>Link de Zoom aquí</p>")  # si es virtual/hybrid

        input("Revisa el formulario en el navegador y presiona Enter para continuar...")
        save_as_draft(page)
       
        browser.close()


if __name__ == "__main__":
    main()