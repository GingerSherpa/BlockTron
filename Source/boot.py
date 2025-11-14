# boot.py — OTA-aware + original QR welcome 2.3.A

import microcontroller, storage
if microcontroller.nvm[0] in (1, 3):  # 1=download, 3=swap
    storage.disable_usb_drive()

import os, time, json, microcontroller, storage

# ----- OTA constants -----
_STAGE_FILE = "/ota_stage.json"
_CONFIRM_FILE = "/ota_confirmed"
_MAX_VERIFY_BOOTS = 3

def _exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False

def _load_stage_list():
    try:
        with open(_stage_file := _STAGE_FILE, "r") as f:
            data = json.load(f)
        files = data.get("files", [])
        if files:
            return files
    except Exception:
        pass
    # default if stage file missing or corrupt
    return ["code.py", "boot.py", "version_history.txt"]

def _swap_in_new_files(files):
    # disable USB mass storage and remount RW to safely modify files
    storage.disable_usb_drive()
    storage.remount("/", False)
    try:
        for fn in files:
            newf = fn + ".new"
            bakf = fn + ".bak"
            if not _exists(newf):
                continue  # nothing to swap for this file
            try:
                if _exists(bakf):
                    os.remove(bakf)
            except OSError:
                pass
            if _exists(fn):
                os.rename(fn, bakf)
            os.rename(newf, fn)
    finally:
        storage.remount("/", True)

def _restore_from_backup(files):
    storage.disable_usb_drive()
    storage.remount("/", False)
    try:
        for fn in files:
            bakf = fn + ".bak"
            if _exists(bakf):
                try:
                    if _exists(fn):
                        os.remove(fn)
                except OSError:
                    pass
                os.rename(bakf, fn)
        # clean stage markers
        try:
            if _exists(_STAGE_FILE):
                os.remove(_STAGE_FILE)
        except OSError:
            pass
        try:
            if _exists(_CONFIRM_FILE):
                os.remove(_CONFIRM_FILE)
        except OSError:
            pass
    finally:
        storage.remount("/", True)

# ----- OTA state machine using NVM bytes -----
# nvm[0]: 0=normal, 1=active download (code.py), 2=pending verify, 3=swap pending (boot.py)
# nvm[1]: verify boot counter
nvm = microcontroller.nvm
flag = nvm[0]

# Quick path: handle swaps/rollback before doing any display setup
if flag == 3:
    files = _load_stage_list()
    _swap_in_new_files(files)
    # Stage complete; mark pending verification
    nvm[0] = 2
    nvm[1] = 0
elif flag == 2:
    # If not yet confirmed, count boots and rollback if threshold reached
    if not _exists(_CONFIRM_FILE):
        cnt = int(nvm[1]) + 1
        nvm[1] = cnt if cnt < 255 else 255
        if cnt >= _MAX_VERIFY_BOOTS:
            files = _load_stage_list()
            _restore_from_backup(files)
            nvm[0] = 0
            nvm[1] = 0

# ---------- Original welcome QR screen (shown only in normal mode) ----------
if nvm[0] == 0:  # normal
    import displayio
    from adafruit_matrixportal.matrixportal import MatrixPortal
    import adafruit_miniqr

    DEVICE_KEYS_FILE = "/device_keys.json"
    BASE_SETTINGS_URL = "https://set.blocktron.io?dev_id="
    device_id = "UNKNOWN_DEVICE"

    matrixportal = MatrixPortal(width=64, height=32, color_order="RGB", debug=False)

    matrixportal.add_text(text_position=(3, 4),  text_color=0xFF4500, text_font="/fonts/4x6-lean.bdf", text="WELCOME")
    matrixportal.add_text(text_position=(3, 12), text_color=0xFF4500, text_font="/fonts/4x6-lean.bdf", text="SCAN TO")
    matrixportal.add_text(text_position=(3, 18), text_color=0xFF4500, text_font="/fonts/4x6-lean.bdf", text="REPLACE")
    matrixportal.add_text(text_position=(3, 25), text_color=0xFF4500, text_font="/fonts/4x6-lean.bdf", text="PRESETS")

    try:
        with open(DEVICE_KEYS_FILE, "r") as f:
            device_id = (json.load(f)).get("deviceId", device_id)
    except Exception:
        pass

    url = f"{BASE_SETTINGS_URL}{device_id}"

    import displayio
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