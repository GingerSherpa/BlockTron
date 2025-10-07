import time
import json
import displayio
from adafruit_matrixportal.matrixportal import MatrixPortal
import adafruit_miniqr

DEVICE_KEYS_FILE = "/device_keys.json"
BASE_SETTINGS_URL = "https://set.blocktron.io?dev_id="
device_id = "UNKNOWN_DEVICE"
api_key = "UNKNOWN_KEY"

matrixportal = MatrixPortal(
    width=64,
    height=32,
    color_order="RGB",
    debug=False,
)

matrixportal.add_text(
    text_position=(3, 4),
    text_color=0xFF4500,
    text_font="/fonts/4x6-lean.bdf",
    text="WELCOME",
)

matrixportal.add_text(
    text_position=(3, 12),
    text_color=0xFF4500,
    text_font="/fonts/4x6-lean.bdf",
    text="SCAN TO",
)

matrixportal.add_text(
    text_position=(3, 18),
    text_color=0xFF4500,
    text_font="/fonts/4x6-lean.bdf",
    text="REPLACE",
)

matrixportal.add_text(
    text_position=(3, 25),
    text_color=0xFF4500,
    text_font="/fonts/4x6-lean.bdf",
    text="PRESETS",
)

try:
    with open(DEVICE_KEYS_FILE, "r") as f:
        data = json.load(f)
        device_id = data.get("deviceId", device_id)
        api_key = data.get("apiKey", api_key)
except Exception as e:
    pass

url = f"{BASE_SETTINGS_URL}{device_id}"

palette = displayio.Palette(2)
palette[0] = 0x000000
palette[1] = 0xFFFFFF

bitmap = displayio.Bitmap(32, 32, 2)
tile_grid = displayio.TileGrid(bitmap, pixel_shader=palette, x=34, y=1)
matrixportal.splash.append(tile_grid)

def draw_qr_code(bm, data_url):
    qr = adafruit_miniqr.QRCode()
    qr.add_data(data_url.encode())
    qr.make()
    code_size = min(qr.matrix.width, 32)
    for y in range(code_size):
        for x in range(code_size):
            bm[x, y] = 1 if qr.matrix[x, y] else 0

draw_qr_code(bitmap, url)

time.sleep(10)