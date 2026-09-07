"""
gui_app.py

Interfaz gráfica (Tkinter) para llenar el formulario de creación de
eventos de IEEE vTools.

- Botón "Ejecutar": llena el formulario en el evento seleccionado.
- Switch "Iniciar Chrome automáticamente":
    ON  -> lanza Chrome con --remote-debugging-port y hace login solo
           usando las credenciales indicadas.
    OFF -> asume que ya tienes Chrome abierto manualmente en modo
           depuración (puerto 9222) y solo se conecta a él.
- Los campos de fecha/hora (inicio y fin) se seleccionan con un calendario
  (tkcalendar.DateEntry) + listas desplegables de hora/minuto/AM-PM, para
  que sea imposible escribir un formato inválido a mano.
- Incluye todos los campos del evento: título, descripción, encabezado,
  pie de página, agenda, keywords, URL de encuesta y ubicación completa
  (física / virtual / híbrida).

Empaquetar como .exe (Windows) o binario (Linux): ver README.md.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, scrolledtext

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv es opcional; sin él simplemente no se autocargan credenciales
    load_dotenv = None

try:
    from tkcalendar import DateEntry
except ImportError:
    DateEntry = None

import event_filler
from EventsVtools import events

APP_TITLE = "IEEE vTools - Llenado automático de eventos"

DEFAULT_HOST_ORG_NAME = "Universidad Autonoma de Aguascalientes"
DEFAULT_HOST_SPOID = "STB60021134"
DEFAULT_HOST_CONTACT_EMAIL = "ieeeagsuaa@gmail.com"

COMMON_TIMEZONES = [
    "America/Mexico_City",
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "America/Bogota",
    "Etc/UTC",
]

LOCATION_TYPES = [("physical", "Física"), ("virtual", "Virtual"), ("hybrid", "Híbrida")]


def _env_file_path() -> Path:
    """
    Ubicación del .env: junto al ejecutable cuando corre empaquetado
    (PyInstaller), o junto al script cuando corre como .py normal.
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent
    return base / ".env"


def _wrap_html(text: str) -> str:
    """Convierte texto plano en un <p>...</p> (si el usuario ya escribió HTML, lo respeta)."""
    text = text.strip()
    if not text:
        return "<p></p>"
    if text.startswith("<"):
        return text
    return f"<p>{text}</p>"


def _unwrap_html(html: str) -> str:
    """Inverso simple de _wrap_html, para mostrar contenido editable sin etiquetas de sobra."""
    text = (html or "").strip()
    if text.startswith("<p>") and text.endswith("</p>"):
        return text[3:-4]
    return text


class DateTimePicker(ttk.Frame):
    """
    Selector compuesto: calendario (DateEntry) + hora/minuto/AM-PM en
    listas desplegables de solo lectura. Nunca produce texto libre, así
    que el formato que exige vTools queda garantizado por construcción.
    """

    def __init__(self, parent):
        super().__init__(parent)

        if DateEntry is None:
            raise RuntimeError(
                "Falta la dependencia 'tkcalendar'. Instálala con: pip install tkcalendar"
            )

        self.date_entry = DateEntry(
            self, date_pattern="dd/mm/yyyy", width=11, background="darkblue",
            foreground="white", borderwidth=2, locale="en_US",
        )
        self.date_entry.grid(row=0, column=0, padx=(0, 6))

        self.hour_var = tk.StringVar(value="12")
        ttk.Combobox(
            self, textvariable=self.hour_var, values=[f"{h:02d}" for h in range(1, 13)],
            width=3, state="readonly",
        ).grid(row=0, column=1)

        ttk.Label(self, text=":").grid(row=0, column=2, padx=2)

        self.minute_var = tk.StringVar(value="00")
        ttk.Combobox(
            self, textvariable=self.minute_var, values=[f"{m:02d}" for m in range(0, 60)],
            width=3, state="readonly",
        ).grid(row=0, column=3)

        self.ampm_var = tk.StringVar(value="PM")
        ttk.Combobox(
            self, textvariable=self.ampm_var, values=["AM", "PM"], width=4, state="readonly",
        ).grid(row=0, column=4, padx=(6, 0))

    def get_vtools_string(self) -> str:
        d = self.date_entry.get_date()
        month_str = event_filler.MONTHS_EN[d.month - 1]
        return f"{d.day:02d} {month_str} {d.year} {self.hour_var.get()}:{self.minute_var.get()} {self.ampm_var.get()}"

    def set_from_string(self, value: str) -> None:
        try:
            dt = event_filler.validate_datetime_str(value)
        except ValueError:
            return
        self.date_entry.set_date(dt.date())
        hour12 = dt.hour % 12
        hour12 = 12 if hour12 == 0 else hour12
        self.hour_var.set(f"{hour12:02d}")
        self.minute_var.set(f"{dt.minute:02d}")
        self.ampm_var.set("AM" if dt.hour < 12 else "PM")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("820x780")
        self.minsize(760, 680)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.controller = event_filler.AutomationController()
        self.worker_thread: threading.Thread | None = None

        if load_dotenv is not None:
            load_dotenv(_env_file_path())

        self._build_ui()
        self._poll_log_queue()

    # ------------------------------------------------------------------
    # Construcción de la interfaz
    # ------------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Evento base:").pack(side="left")
        self.event_titles = [e["title"] for e in events]
        self.event_combo = ttk.Combobox(top, values=self.event_titles, state="readonly", width=55)
        self.event_combo.pack(side="left", padx=8)
        self.event_combo.current(0)
        self.event_combo.bind("<<ComboboxSelected>>", self._on_event_selected)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, **pad)

        self.tab_general = ttk.Frame(notebook)
        self.tab_fecha = ttk.Frame(notebook)
        self.tab_ubicacion = ttk.Frame(notebook)
        self.tab_chrome = ttk.Frame(notebook)
        self.tab_cohosts = ttk.Frame(notebook)

        notebook.add(self.tab_chrome, text="Host / Chrome")
        notebook.add(self.tab_cohosts, text="Co-hosts")
        notebook.add(self.tab_ubicacion, text="Ubicación")
        notebook.add(self.tab_fecha, text="Fecha y hora")
        notebook.add(self.tab_general, text="Contenido")
        
        self._build_tab_chrome(self.tab_chrome)
        self._build_tab_cohosts(self.tab_cohosts)
        self._build_tab_ubicacion(self.tab_ubicacion)
        self._build_tab_general(self.tab_general)
        self._build_tab_fecha(self.tab_fecha)

        # --- Botones de acción (siempre visibles) ---
        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", **pad)

        self.run_btn = ttk.Button(action_frame, text="Ejecutar automatización", command=self._on_run_clicked)
        self.run_btn.pack(side="left", padx=4)

        self.save_btn = ttk.Button(action_frame, text="Guardar como borrador", command=self._on_save_clicked, state="disabled")
        self.save_btn.pack(side="left", padx=4)

        self.close_btn = ttk.Button(action_frame, text="Cerrar navegador", command=self._on_close_clicked, state="disabled")
        self.close_btn.pack(side="left", padx=4)

        # --- Log (siempre visible) ---
        log_frame = ttk.LabelFrame(self, text="Registro")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_widget = scrolledtext.ScrolledText(log_frame, height=10, state="disabled", wrap="word")
        self.log_widget.pack(fill="both", expand=True, padx=4, pady=4)

        self._on_event_selected()
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

    def _build_tab_general(self, parent):
        pad = {"padx": 8, "pady": 4}

        ttk.Label(parent, text="Título del evento:").grid(row=0, column=0, sticky="nw", **pad)
        self.title_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.title_var, width=60).grid(row=0, column=1, sticky="we", **pad)

        ttk.Label(parent, text="Descripción:").grid(row=1, column=0, sticky="nw", **pad)
        self.description_text = tk.Text(parent, height=4, width=60, wrap="word")
        self.description_text.grid(row=1, column=1, sticky="we", **pad)

        ttk.Label(parent, text="Encabezado (header):").grid(row=2, column=0, sticky="nw", **pad)
        self.header_text = tk.Text(parent, height=3, width=60, wrap="word")
        self.header_text.grid(row=2, column=1, sticky="we", **pad)

        ttk.Label(parent, text="Pie de página (footer):").grid(row=3, column=0, sticky="nw", **pad)
        self.footer_text = tk.Text(parent, height=3, width=60, wrap="word")
        self.footer_text.grid(row=3, column=1, sticky="we", **pad)

        ttk.Label(parent, text="Agenda:").grid(row=4, column=0, sticky="nw", **pad)
        self.agenda_text = tk.Text(parent, height=3, width=60, wrap="word")
        self.agenda_text.grid(row=4, column=1, sticky="we", **pad)

        ttk.Label(parent, text="Keywords:").grid(row=5, column=0, sticky="w", **pad)
        self.keywords_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.keywords_var, width=60).grid(row=5, column=1, sticky="we", **pad)

        ttk.Label(parent, text="URL de encuesta (survey_url):").grid(row=6, column=0, sticky="w", **pad)
        self.survey_url_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.survey_url_var, width=60).grid(row=6, column=1, sticky="we", **pad)

        ttk.Label(
            parent,
            text="Los campos de texto aceptan HTML (ej. <p>...</p>) o texto plano;\n"
                 "si escribes texto plano, se envuelve automáticamente en <p>.",
            foreground="#555555",
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 0))

        parent.columnconfigure(1, weight=1)

    def _build_tab_fecha(self, parent):
        pad = {"padx": 8, "pady": 8}

        ttk.Label(
            parent,
            text="Selecciona la fecha con el calendario y la hora con las listas desplegables.\n"
                 "Esto evita errores de formato: vTools requiere exactamente 'DD Mon YYYY hh:mm AM/PM'.",
            foreground="#555555",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(parent, text="Inicio:").grid(row=1, column=0, sticky="w", **pad)
        self.start_picker = DateTimePicker(parent)
        self.start_picker.grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(parent, text="Fin:").grid(row=2, column=0, sticky="w", **pad)
        self.end_picker = DateTimePicker(parent)
        self.end_picker.grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(parent, text="Zona horaria:").grid(row=3, column=0, sticky="w", **pad)
        self.timezone_var = tk.StringVar()
        ttk.Combobox(parent, textvariable=self.timezone_var, values=COMMON_TIMEZONES, width=30).grid(
            row=3, column=1, sticky="w", **pad
        )

    def _build_tab_ubicacion(self, parent):
        pad = {"padx": 8, "pady": 4}

        ttk.Label(parent, text="Tipo de ubicación:").grid(row=0, column=0, sticky="w", **pad)
        self.location_type_var = tk.StringVar(value="physical")
        type_frame = ttk.Frame(parent)
        type_frame.grid(row=0, column=1, sticky="w", **pad)
        for value, label in LOCATION_TYPES:
            ttk.Radiobutton(
                type_frame, text=label, value=value, variable=self.location_type_var,
                command=self._update_location_visibility,
            ).pack(side="left", padx=4)

        # --- Campos físicos ---
        self.physical_frame = ttk.LabelFrame(parent, text="Dirección física")
        self.physical_frame.grid(row=1, column=0, columnspan=2, sticky="we", padx=8, pady=6)

        self.address1_var = tk.StringVar()
        self.address2_var = tk.StringVar()
        self.city_var = tk.StringVar()
        self.postal_code_var = tk.StringVar()
        self.building_var = tk.StringVar()
        self.country_var = tk.StringVar()
        self.state_var = tk.StringVar()

        rows = [
            ("Dirección 1:", self.address1_var),
            ("Dirección 2:", self.address2_var),
            ("Ciudad:", self.city_var),
            ("Código postal:", self.postal_code_var),
            ("Edificio:", self.building_var),
            ("País:", self.country_var),
            ("Estado:", self.state_var),
        ]
        self.physical_entries: list[ttk.Entry] = []
        for i, (label, var) in enumerate(rows):
            ttk.Label(self.physical_frame, text=label).grid(row=i, column=0, sticky="w", **pad)
            entry = ttk.Entry(self.physical_frame, textvariable=var, width=45)
            entry.grid(row=i, column=1, sticky="we", **pad)
            self.physical_entries.append(entry)
        self.physical_frame.columnconfigure(1, weight=1)

        # --- Campo virtual ---
        self.virtual_frame = ttk.LabelFrame(parent, text="Información virtual (link, instrucciones, etc.)")
        self.virtual_frame.grid(row=2, column=0, columnspan=2, sticky="we", padx=8, pady=6)
        self.virtual_info_text = tk.Text(self.virtual_frame, height=4, width=60, wrap="word")
        self.virtual_info_text.pack(fill="x", padx=8, pady=8)

        parent.columnconfigure(1, weight=1)
        self._update_location_visibility()

    def _build_tab_chrome(self, parent):
        pad = {"padx": 8, "pady": 4}

        host_frame = ttk.LabelFrame(parent, text="Organización anfitriona")
        host_frame.pack(fill="x", padx=8, pady=8)

        ttk.Label(host_frame, text="Nombre:").grid(row=0, column=0, sticky="w", **pad)
        self.host_org_var = tk.StringVar(value=DEFAULT_HOST_ORG_NAME)
        ttk.Entry(host_frame, textvariable=self.host_org_var, width=40).grid(row=0, column=1, sticky="we", **pad)

        ttk.Label(host_frame, text="SPOID:").grid(row=0, column=2, sticky="w", **pad)
        self.host_spoid_var = tk.StringVar(value=DEFAULT_HOST_SPOID)
        ttk.Entry(host_frame, textvariable=self.host_spoid_var, width=15).grid(row=0, column=3, sticky="w", **pad)

        ttk.Label(host_frame, text="Email de contacto:").grid(row=1, column=0, sticky="w", **pad)
        self.host_email_var = tk.StringVar(value=DEFAULT_HOST_CONTACT_EMAIL)
        ttk.Entry(host_frame, textvariable=self.host_email_var, width=40).grid(row=1, column=1, columnspan=3, sticky="we", **pad)
        host_frame.columnconfigure(1, weight=1)

        chrome_frame = ttk.LabelFrame(parent, text="Navegador y credenciales")
        chrome_frame.pack(fill="x", padx=8, pady=8)

        self.launch_chrome_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            chrome_frame,
            text="Iniciar Chrome automáticamente (perfil temporal + login automático)",
            variable=self.launch_chrome_var,
            command=self._on_switch_toggle,
        ).grid(row=0, column=0, columnspan=2, sticky="w", **pad)

        self.switch_help = ttk.Label(chrome_frame, text="", foreground="#555555", wraplength=680, justify="left")
        self.switch_help.grid(row=1, column=0, columnspan=2, sticky="w", padx=8)

        ttk.Label(chrome_frame, text="Usuario IEEE:").grid(row=2, column=0, sticky="w", **pad)
        self.username_var = tk.StringVar(value=os.getenv("IEEE_USER", ""))
        ttk.Entry(chrome_frame, textvariable=self.username_var, width=35).grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(chrome_frame, text="Contraseña IEEE:").grid(row=3, column=0, sticky="w", **pad)
        self.password_var = tk.StringVar(value=os.getenv("IEEE_PASS", ""))
        ttk.Entry(chrome_frame, textvariable=self.password_var, width=35, show="*").grid(row=3, column=1, sticky="w", **pad)

        self._on_switch_toggle()

    def _build_tab_cohosts(self, parent):
        pad = {"padx": 8, "pady": 4}

        self.cohost_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text="Habilitar Add cohost en la automatización",
            variable=self.cohost_enabled_var,
            command=self._update_cohost_visibility,
        ).grid(row=0, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(
            parent,
            text="Activa esta casilla para que la automatización marque 'Add cohost' y luego complete cada bloque.",
            foreground="#555555",
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        self.cohost_rows_frame = ttk.Frame(parent)
        self.cohost_rows_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=4)
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(2, weight=1)

        self.add_cohost_row_btn = ttk.Button(parent, text="Agregar otro cohost", command=self._add_cohost_row)
        self.add_cohost_row_btn.grid(row=3, column=0, sticky="w", padx=8, pady=(8, 4))

        self.cohost_rows: list[dict] = []
        self._add_cohost_row()

        self._update_cohost_visibility()

    def _add_cohost_row(self, initial_data: dict | None = None):
        initial_data = initial_data or {}
        row_number = len(self.cohost_rows) + 1

        row_frame = ttk.LabelFrame(self.cohost_rows_frame, text=f"Cohost #{row_number}")
        row_frame.pack(fill="x", expand=True, pady=4)

        org_var = tk.StringVar(value=initial_data.get("organization", ""))
        spoid_var = tk.StringVar(value=initial_data.get("spoid", ""))
        email_var = tk.StringVar(value=initial_data.get("email", ""))

        ttk.Label(row_frame, text="Organización:").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        org_entry = ttk.Entry(row_frame, textvariable=org_var, width=40)
        org_entry.grid(row=0, column=1, sticky="we", padx=8, pady=4)

        ttk.Label(row_frame, text="SPOID:").grid(row=0, column=2, sticky="w", padx=8, pady=4)
        spoid_entry = ttk.Entry(row_frame, textvariable=spoid_var, width=15)
        spoid_entry.grid(row=0, column=3, sticky="w", padx=8, pady=4)

        ttk.Label(row_frame, text="Email de contacto:").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        email_entry = ttk.Entry(row_frame, textvariable=email_var, width=40)
        email_entry.grid(row=1, column=1, columnspan=3, sticky="we", padx=8, pady=4)

        row_frame.columnconfigure(1, weight=1)

        self.cohost_rows.append(
            {
                "frame": row_frame,
                "org_var": org_var,
                "spoid_var": spoid_var,
                "email_var": email_var,
                "org_entry": org_entry,
                "spoid_entry": spoid_entry,
                "email_entry": email_entry,
            }
        )
        self._update_cohost_visibility()

    def _update_cohost_visibility(self):
        enabled = self.cohost_enabled_var.get()

        for row in self.cohost_rows:
            state = "normal" if enabled else "disabled"
            row["org_entry"].config(state=state)
            row["spoid_entry"].config(state=state)
            row["email_entry"].config(state=state)

        if hasattr(self, "add_cohost_row_btn"):
            self.add_cohost_row_btn.config(state="normal" if enabled else "disabled")

    def _load_cohosts(self, cohosts: list[dict]):
        while len(self.cohost_rows) < max(1, len(cohosts)):
            self._add_cohost_row()

        for idx, row in enumerate(self.cohost_rows):
            data = cohosts[idx] if idx < len(cohosts) else {}
            row["org_var"].set(data.get("organization", ""))
            row["spoid_var"].set(data.get("spoid", ""))
            row["email_var"].set(data.get("email", ""))

        self.cohost_enabled_var.set(bool(cohosts))
        self._update_cohost_visibility()

    def _on_switch_toggle(self):
        if self.launch_chrome_var.get():
            self.switch_help.config(
                text="Se abrirá Chrome con un perfil temporal y se iniciará sesión automáticamente con las "
                     "credenciales de abajo."
            )
        else:
            self.switch_help.config(
                text="Se usará una instancia de Chrome que TÚ debes tener abierta con:\n"
                     "google-chrome-stable --user-data-dir=/tmp/chrome-playwright --remote-debugging-port=9222\n"
                     "(en Windows: chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\chrome-playwright)"
            )

    def _update_location_visibility(self):
        loc_type = self.location_type_var.get()
        physical_enabled = loc_type in ("physical", "hybrid")
        virtual_enabled = loc_type in ("virtual", "hybrid")

        for entry in self.physical_entries:
            entry.config(state="normal" if physical_enabled else "disabled")

        self.virtual_info_text.config(state="normal" if virtual_enabled else "disabled")

    # ------------------------------------------------------------------
    # Eventos de UI
    # ------------------------------------------------------------------
    def _set_text(self, widget: tk.Text, value: str):
        prev_state = widget.cget("state")
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", _unwrap_html(value))
        widget.config(state=prev_state)

    def _on_event_selected(self, _evt=None):
        idx = self.event_combo.current()
        if idx < 0:
            return
        event = events[idx]

        self.title_var.set(event["title"])
        self.start_picker.set_from_string(event["start_time"])
        self.end_picker.set_from_string(event["end_time"])
        self.timezone_var.set(event.get("timezone", "America/Mexico_City"))

        self._set_text(self.description_text, event.get("description", ""))
        self._set_text(self.header_text, event.get("header", ""))
        self._set_text(self.footer_text, event.get("footer", ""))
        self._set_text(self.agenda_text, event.get("agenda", ""))
        self.keywords_var.set(event.get("keywords", ""))
        self.survey_url_var.set(event.get("survey_url", ""))

        loc = event.get("location", {})
        self.location_type_var.set(loc.get("type", "physical"))
        self.address1_var.set(loc.get("address1", ""))
        self.address2_var.set(loc.get("address2", ""))
        self.city_var.set(loc.get("city", ""))
        self.postal_code_var.set(loc.get("postal_code", ""))
        self.building_var.set(loc.get("building", ""))
        self.country_var.set(loc.get("country", ""))
        self.state_var.set(loc.get("state", ""))
        self._update_location_visibility()
        self._set_text(self.virtual_info_text, loc.get("virtual_info_html", ""))
        self._update_location_visibility()

        self._load_cohosts(event.get("cohosts", []))

    def _log(self, msg: str):
        # Seguro para llamarse desde el worker thread: solo encola.
        self.log_queue.put(msg)

    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_widget.configure(state="normal")
                self.log_widget.insert("end", msg + "\n")
                self.log_widget.see("end")
                self.log_widget.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(150, self._poll_log_queue)

    def _current_event(self) -> dict:
        idx = self.event_combo.current()
        base = dict(events[idx])

        base["title"] = self.title_var.get().strip()
        base["start_time"] = self.start_picker.get_vtools_string()
        base["end_time"] = self.end_picker.get_vtools_string()
        base["timezone"] = self.timezone_var.get().strip()

        base["description"] = _wrap_html(self.description_text.get("1.0", "end-1c"))
        base["header"] = _wrap_html(self.header_text.get("1.0", "end-1c"))
        base["footer"] = _wrap_html(self.footer_text.get("1.0", "end-1c"))
        base["agenda"] = _wrap_html(self.agenda_text.get("1.0", "end-1c"))
        base["keywords"] = self.keywords_var.get().strip()
        base["survey_url"] = self.survey_url_var.get().strip()

        base["location"] = {
            "type": self.location_type_var.get(),
            "address1": self.address1_var.get().strip(),
            "address2": self.address2_var.get().strip(),
            "city": self.city_var.get().strip(),
            "postal_code": self.postal_code_var.get().strip(),
            "building": self.building_var.get().strip(),
            "country": self.country_var.get().strip(),
            "state": self.state_var.get().strip(),
            "virtual_info_html": _wrap_html(self.virtual_info_text.get("1.0", "end-1c")),
        }
        base["cohosts"] = [
            {
                "organization": row["org_var"].get().strip(),
                "spoid": row["spoid_var"].get().strip(),
                "email": row["email_var"].get().strip(),
            }
            for row in self.cohost_rows
            if any(
                (
                    row["org_var"].get().strip(),
                    row["spoid_var"].get().strip(),
                    row["email_var"].get().strip(),
                )
            )
        ]
        return base

    def _set_running_state(self, running: bool):
        self.run_btn.config(state="disabled" if running else "normal")

    def _on_run_clicked(self):
        event = self._current_event()

        try:
            event_filler.validate_event_dates(event)
        except ValueError as exc:
            messagebox.showerror("Fecha inválida", str(exc))
            return

        launch_chrome = self.launch_chrome_var.get()
        username = self.username_var.get().strip()
        password = self.password_var.get()

        if launch_chrome and (not username or not password):
            if not messagebox.askyesno(
                "Sin credenciales",
                "No indicaste usuario/contraseña. Si Chrome pide login, la automatización "
                "se detendrá. ¿Deseas continuar de todas formas?",
            ):
                return

        self._set_running_state(True)
        self.worker_thread = threading.Thread(
            target=self._run_worker,
            args=(event, launch_chrome, username, password),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_worker(self, event: dict, launch_chrome: bool, username: str, password: str):
        try:
            self._log("=== Iniciando automatización ===")
            self.controller.connect(launch_chrome, username, password, log=self._log)
            self.controller.fill(
                event,
                host_org_name=self.host_org_var.get().strip(),
                host_spoid=self.host_spoid_var.get().strip(),
                host_contact_email=self.host_email_var.get().strip(),
                log=self._log,
            )
            self._log("=== Listo. Revisa el formulario en el navegador. ===")
            self.save_btn.config(state="normal")
            self.close_btn.config(state="normal")
        except Exception as exc:  # noqa: BLE001 - queremos capturar y mostrar cualquier error
            self._log(f"ERROR: {exc}")
            self.after(0, lambda: messagebox.showerror("Error durante la automatización", str(exc)))
        finally:
            self.after(0, lambda: self._set_running_state(False))

    def _on_save_clicked(self):
        def worker():
            try:
                self.controller.save_draft(log=self._log)
            except Exception as exc:  # noqa: BLE001
                self._log(f"ERROR al guardar: {exc}")
                self.after(0, lambda: messagebox.showerror("Error al guardar", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_close_clicked(self):
        def worker():
            self.controller.close(log=self._log)
            self.after(0, lambda: self.save_btn.config(state="disabled"))
            self.after(0, lambda: self.close_btn.config(state="disabled"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_window_close(self):
        try:
            self.controller.close(log=lambda _m: None)
        except Exception:
            pass
        self.destroy()


def main():
    if DateEntry is None:
        # Fallamos con un mensaje claro en vez de un traceback críptico.
        import tkinter.messagebox as mb
        root = tk.Tk()
        root.withdraw()
        mb.showerror(
            "Falta una dependencia",
            "Falta instalar 'tkcalendar' (usado para el selector de fecha).\n\n"
            "Ejecuta: pip install tkcalendar",
        )
        return
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
