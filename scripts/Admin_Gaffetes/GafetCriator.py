import csv
import os
import base64
import subprocess
import xml.etree.ElementTree as ET
import barcode
from barcode.writer import ImageWriter
import io

import glob


namespaces = {
    'svg': 'http://www.w3.org/2000/svg',
    'xlink': 'http://www.w3.org/1999/xlink'
}
for prefix, uri in namespaces.items():
    ET.register_namespace(prefix, uri)

NS_SVG = '{http://www.w3.org/2000/svg}'
NS_XLINK = '{http://www.w3.org/1999/xlink}'
ABS_PATH = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(ABS_PATH, "output")  # Carpeta de salida para los PDFs generados



EXTENSIONES_IMAGEN = ('.png', '.jpg', '.jpeg', '.webp')


def buscar_imagen_por_id(carpeta, identificador, extensiones=EXTENSIONES_IMAGEN):
    """
    Busca en 'carpeta' un archivo cuyo nombre (sin extensión) coincida
    exactamente con 'identificador'. Ej: fotos/123.jpg para number='123'.
    Regresa la ruta encontrada o None si no existe.
    """
    identificador = str(identificador).strip()
    for ext in extensiones:
        candidato  = os.path.join(ABS_PATH, carpeta, f"{identificador}{ext}")
        if os.path.exists(candidato):
            return candidato
    return None


def reemplazar_imagen_por_id(root, elem_id, ruta_imagen):
    """
    Busca el elemento <image id="elem_id"> dentro del SVG y reemplaza
    únicamente su xlink:href, dejando intactos x, y, width, height
    y cualquier transform ya definido en la plantilla.
    """
    img_elem = root.find(f'.//{NS_SVG}image[@id="{elem_id}"]')

    if img_elem is None:
        print(f"⚠️  No se encontró <image id=\"{elem_id}\"> en la plantilla; se omite.")
        return False

    if ruta_imagen is None or not os.path.exists(ruta_imagen):
        print(f"⚠️  No se encontró imagen para id=\"{elem_id}\"; se omite.")
        return False

    with open(ruta_imagen, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode("utf-8")

    ext = os.path.splitext(ruta_imagen)[1].lstrip('.').lower()
    mime = 'jpeg' if ext == 'jpg' else ext
    img_elem.set(f'{NS_XLINK}href', f'data:image/{mime};base64,{b64_data}')
    return True


def generar_barcode_base64(codigo):
    """
    Genera un código de barras Code128 en PNG (en memoria) y lo regresa
    codificado en base64, listo para embeber en el SVG.
    """
    writer_options = {
        'write_text': False,  # sin texto debajo de las barras (el número ya se ve en el gafete)
        'quiet_zone': 1.0,
    }
    CODE128 = barcode.get_barcode_class('code128')
    bc = CODE128(str(codigo), writer=ImageWriter())

    buffer = io.BytesIO()
    bc.write(buffer, options=writer_options)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode('utf-8')

def agregar_codigo_barras(root, codigo, x_mm=30, y_mm=25, width_mm=45, height_mm=15,
                           elem_referencia_id="number"):
    if not codigo:
        return

    b64_data = generar_barcode_base64(codigo)

    parent_map = {hijo: padre for padre in root.iter() for hijo in padre}
    referencia = root.find(f'.//*[@id="{elem_referencia_id}"]')

    if referencia is None:
        contenedor = root
        indice = len(list(root))
    else:
        contenedor = parent_map.get(referencia, root)
        indice = list(contenedor).index(referencia)

    img_elem = ET.Element(f'{NS_SVG}image')
    img_elem.set('x', str(x_mm))
    img_elem.set('y', str(y_mm))
    img_elem.set('width', str(width_mm))
    img_elem.set('height', str(height_mm))
    img_elem.set(f'{NS_XLINK}href', f'data:image/png;base64,{b64_data}')

    # insert() en el índice del "number" lo coloca justo ANTES de él en el
    # documento -> se pinta primero -> queda en una capa inferior
    contenedor.insert(indice, img_elem)  


def reemplazar_manteniendo_estilo(elem, nuevo_texto):
    tspans = elem.findall(f'.//{NS_SVG}tspan')

    if tspans:
        target = None
        for ts in tspans:
            if ts.text and ts.text.strip():
                target = ts
                break
        if target is None:
            target = tspans[0]

        target.text = str(nuevo_texto)
        for ts in tspans:
            if ts is not target:
                ts.text = ""
    else:
        elem.text = str(nuevo_texto)


def agregar_imagen_yp(root, x=120, y=150, width=40, height=40, ruta_imagen=f"{ABS_PATH}YP.png"):
    """
    Inserta YP.png embebida en base64 en la posición (x, y) del SVG.
    Ajusta width/height y x/y según las unidades reales de tu Template.svg
    (revisa el viewBox/width/height del <svg> raíz para saber si son px, mm, etc).
    """
    if not os.path.exists(ruta_imagen):
        print(f"⚠️  No se encontró {ruta_imagen}; se omite la imagen.")
        return

    with open(ruta_imagen, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode("utf-8")

    img_elem = ET.SubElement(root, f'{NS_SVG}image')
    img_elem.set('x', str(x))
    img_elem.set('y', str(y))
    img_elem.set('width', str(width))
    img_elem.set('height', str(height))
    img_elem.set(f'{NS_XLINK}href', f'data:image/png;base64,{b64_data}')


def generar_gafete(persona):
    tree = ET.parse(os.path.join(ABS_PATH, "Template.svg"))
    root = tree.getroot()

    campos = {
        'name': persona.get('name', ''),
        'role': persona.get('role', ''),
        'number': persona.get('number', ''),
    }

    for elem in root.iter():
        elem_id = elem.attrib.get('id')
        if elem_id in campos:
            valor_nuevo = campos[elem_id]
            if elem.tag.endswith('tspan'):
                elem.text = str(valor_nuevo)
            else:
                reemplazar_manteniendo_estilo(elem, valor_nuevo)

    # --- Nuevo: agregar YP.png si el rol es Young Professionals ---
    if campos['role'].strip().lower() == 'young professionals':
        agregar_imagen_yp(root, x=30, y=35, width=20, height=20, ruta_imagen=os.path.join(ABS_PATH, "YP.png"))

    # --- Código de barras del ID, debajo del texto "number" ---
    agregar_codigo_barras(
        root,
        codigo=campos['number'],
        x_mm=0, y_mm=23, 
        width_mm=120, height_mm=10, 
        elem_referencia_id= 'rect3'
    )
    # --- Foto de la persona, buscada por su ID (number) en la carpeta 'fotos/' ---
    ruta_foto = buscar_imagen_por_id("fotos", campos['number'])
    reemplazar_imagen_por_id(root, elem_id="pic", ruta_imagen=ruta_foto)



    num_id = str(persona.get('number', 'sin_id')).strip()
    nombre_persona = str(persona.get('name', 'sin_nombre')).strip().replace(' ', '_')

    if not os.path.exists(OUTPUT_PATH):
        os.makedirs(OUTPUT_PATH)

    temp_svg = os.path.join(ABS_PATH, f"temp_{num_id}.svg")
    output_pdf = os.path.join(OUTPUT_PATH, f"gafete_{num_id}_{nombre_persona}.pdf")

    tree.write(temp_svg, encoding="utf-8", xml_declaration=True)

    cmd = [
        "inkscape",
        temp_svg,
        f"--export-filename={output_pdf}",
        "--export-dpi=300",
        "--export-type=pdf"
    ]

    try:
        subprocess.run(cmd, check=True)
        print(f"✅ Gafete generado: {output_pdf}")
    finally:
        if os.path.exists(temp_svg):
            os.remove(temp_svg)


def procesar_csv():
    with open(os.path.join(ABS_PATH, "data.csv"), mode="r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for fila in reader:
            fila_limpia = {str(k).strip(): str(v).strip() for k, v in fila.items() if k}
            generar_gafete(fila_limpia)


if __name__ == "__main__":
    procesar_csv()
