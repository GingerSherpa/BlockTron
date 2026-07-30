#!/usr/bin/env python3
"""Serve a local, read-only preview of the BlockTron LED display."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "Source"
CODE_PATH = SOURCE_ROOT / "code.py"
WEB_ROOT = PROJECT_ROOT / "emulator" / "web"

STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/blocktron-logo.svg": "blocktron-logo.svg",
    "/styles.css": "styles.css",
}

ASCII_CODEPOINTS = frozenset(range(32, 127)) | {0}
REQUIRED_BTC_LAYERS = {
    "price",
    "blockheight",
    "moscow",
    "status_pixel",
    "ticker",
    "time",
}


class ConfigError(RuntimeError):
    """Raised when display configuration cannot be read from the source."""


def load_static_files(
    web_root: Path = WEB_ROOT,
) -> dict[str, tuple[bytes, str]]:
    """Load the browser UI once so it survives checkout branch changes."""
    assets = {}
    for filename in sorted(set(STATIC_FILES.values())):
        path = web_root / filename
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ConfigError(f"Unable to load emulator asset {path}: {exc}") from exc
        content_type, _ = mimetypes.guess_type(path.name)
        assets[filename] = (content, content_type or "application/octet-stream")
    return assets


def dim_color(color: int, level: int) -> int:
    """Match Source/code.py's integer RGB brightness scaling."""
    level = max(1, min(level, 10))
    if level == 10:
        return color

    fraction = level / 10.0
    channels = []
    for shift in (16, 8, 0):
        value = ((color >> shift) & 0xFF) * fraction
        channels.append(max(int(value), 1) if value > 0 else 0)
    return (channels[0] << 16) | (channels[1] << 8) | channels[2]


def _evaluate_node(node: ast.AST, values: dict[str, Any]) -> Any:
    """Evaluate the small literal subset used by display configuration."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise ValueError(f"unknown name: {node.id}")
        return values[node.id]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_evaluate_node(item, values) for item in node.elts]
    if isinstance(node, ast.Dict):
        return {
            _evaluate_node(key, values): _evaluate_node(value, values)
            for key, value in zip(node.keys, node.values)
        }
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_evaluate_node(node.operand, values)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "dim_color"
        and len(node.args) == 2
    ):
        return dim_color(
            int(_evaluate_node(node.args[0], values)),
            int(_evaluate_node(node.args[1], values)),
        )
    raise ValueError(f"unsupported expression: {type(node).__name__}")


def _text_role_names(values: dict[str, Any]) -> dict[int, str]:
    roles = {}
    for name, value in values.items():
        if name.endswith("_TEXT_INDEX") and isinstance(value, int):
            roles[value] = name.removesuffix("_TEXT_INDEX").lower()
        elif name == "STATUS_PIXEL_INDEX" and isinstance(value, int):
            roles[value] = "status_pixel"
    return roles


def _raw_text_color(node: ast.AST, values: dict[str, Any]) -> int:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "dim_color"
        and node.args
    ):
        return int(_evaluate_node(node.args[0], values))
    return int(_evaluate_node(node, values))


def _extract_text_layers(
    tree: ast.Module,
    values: dict[str, Any],
) -> list[dict[str, Any]]:
    roles = _text_role_names(values)
    layers = []

    for statement in tree.body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            continue
        call = statement.value
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "add_text"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "matrixportal"
        ):
            continue

        keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
        index = len(layers)
        try:
            position = _evaluate_node(keywords["text_position"], values)
            font = str(_evaluate_node(keywords["text_font"], values))
            color = _raw_text_color(keywords["text_color"], values)
        except (KeyError, ValueError, TypeError):
            position = [0, 0]
            font = "/fonts/5x8-lean.bdf"
            color = 0xFFFFFF

        try:
            text = str(_evaluate_node(keywords["text"], values))
        except (KeyError, ValueError, TypeError):
            text = ""

        try:
            scale = int(_evaluate_node(keywords["text_scale"], values))
        except (KeyError, ValueError, TypeError):
            scale = 1

        try:
            scrolling = bool(_evaluate_node(keywords["scrolling"], values))
        except (KeyError, ValueError, TypeError):
            scrolling = False

        layers.append(
            {
                "index": index,
                "role": roles.get(index, f"text_{index}"),
                "position": position,
                "font": font,
                "color": color,
                "scale": scale,
                "scrolling": scrolling,
                "initialText": text,
            }
        )

    return layers


def extract_source_config(
    source: str,
    source_path: Path = CODE_PATH,
) -> tuple[dict[str, Any], int, int, list[dict[str, Any]]]:
    """Extract display-only constants without importing hardware-bound code.py."""
    try:
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError as exc:
        raise ConfigError(
            f"{source_path}:{exc.lineno}: {exc.msg}"
        ) from exc

    values: dict[str, Any] = {}
    display_width = 64
    display_height = 32

    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue

        if isinstance(statement, ast.Assign):
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                continue
            name = statement.targets[0].id
            value_node = statement.value
        else:
            if not isinstance(statement.target, ast.Name) or statement.value is None:
                continue
            name = statement.target.id
            value_node = statement.value

        if (
            name == "matrixportal"
            and isinstance(value_node, ast.Call)
            and isinstance(value_node.func, ast.Name)
            and value_node.func.id == "MatrixPortal"
        ):
            for keyword in value_node.keywords:
                if keyword.arg == "width":
                    display_width = int(_evaluate_node(keyword.value, values))
                elif keyword.arg == "height":
                    display_height = int(_evaluate_node(keyword.value, values))
            continue

        try:
            values[name] = _evaluate_node(value_node, values)
        except ValueError:
            continue

    layers = _extract_text_layers(tree, values)
    roles = {layer["role"] for layer in layers}
    missing = sorted(REQUIRED_BTC_LAYERS - roles)
    if missing:
        raise ConfigError(
            "Source/code.py is missing BTC display layers: " + ", ".join(missing)
        )

    return values, display_width, display_height, layers


def parse_bdf(path: Path, codepoints: frozenset[int] = ASCII_CODEPOINTS) -> dict[str, Any]:
    """Parse BDF glyphs into JSON-safe pixel rows and metrics."""
    try:
        lines = path.read_text(encoding="latin-1").splitlines()
    except OSError as exc:
        raise ConfigError(f"Unable to read font {path}: {exc}") from exc

    ascent = 0
    descent = 0
    bounding_box = [0, 0, 0, 0]
    glyphs: dict[str, Any] = {}
    current: dict[str, Any] | None = None
    reading_bitmap = False

    for line in lines:
        if line.startswith("FONT_ASCENT "):
            ascent = int(line.split()[1])
        elif line.startswith("FONT_DESCENT "):
            descent = int(line.split()[1])
        elif line.startswith("FONTBOUNDINGBOX "):
            bounding_box = [int(value) for value in line.split()[1:5]]
        elif line.startswith("STARTCHAR "):
            current = {"bitmap_hex": []}
            reading_bitmap = False
        elif current is not None and line.startswith("ENCODING "):
            current["encoding"] = int(line.split()[1])
        elif current is not None and line.startswith("DWIDTH "):
            width, height = line.split()[1:3]
            current["shift"] = [int(width), int(height)]
        elif current is not None and line.startswith("BBX "):
            current["bounds"] = [int(value) for value in line.split()[1:5]]
        elif current is not None and line == "BITMAP":
            reading_bitmap = True
        elif current is not None and line == "ENDCHAR":
            encoding = current.get("encoding")
            bounds = current.get("bounds")
            shift = current.get("shift", [0, 0])
            if encoding in codepoints and bounds is not None:
                width, height, dx, dy = bounds
                rows = []
                for bitmap_hex in current["bitmap_hex"][:height]:
                    stored_width = len(bitmap_hex) * 4
                    bits = bin(int(bitmap_hex or "0", 16))[2:].zfill(stored_width)
                    rows.append(bits[:width])
                rows.extend(["0" * width] * (height - len(rows)))
                glyphs[str(encoding)] = {
                    "width": width,
                    "height": height,
                    "dx": dx,
                    "dy": dy,
                    "shiftX": shift[0],
                    "rows": rows,
                }
            current = None
            reading_bitmap = False
        elif current is not None and reading_bitmap:
            current["bitmap_hex"].append(line.strip())

    if not glyphs:
        raise ConfigError(f"No previewable glyphs found in {path}")

    return {
        "ascent": ascent,
        "descent": descent,
        "boundingBox": bounding_box,
        "glyphs": glyphs,
    }


def _safe_font_path(source_root: Path, font_name: str) -> Path:
    candidate = (source_root / font_name.lstrip("/")).resolve()
    try:
        candidate.relative_to(source_root.resolve())
    except ValueError as exc:
        raise ConfigError(f"Font path escapes Source: {font_name}") from exc
    return candidate


def watched_files(project_root: Path = PROJECT_ROOT) -> list[Path]:
    source_root = project_root / "Source"
    files = [source_root / "code.py"]
    files.extend(sorted((source_root / "fonts").glob("*.bdf")))
    return files


def source_revision(project_root: Path = PROJECT_ROOT) -> str:
    digest = hashlib.sha256()
    for path in watched_files(project_root):
        digest.update(str(path.relative_to(project_root)).encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()[:12]


def build_display_config(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    source_root = project_root / "Source"
    code_path = source_root / "code.py"
    try:
        source = code_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Unable to read {code_path}: {exc}") from exc

    values, width, height, layers = extract_source_config(source, code_path)
    font_names = {layer["font"] for layer in layers}
    fonts = {
        font_name: parse_bdf(_safe_font_path(source_root, font_name))
        for font_name in sorted(font_names)
    }

    return {
        "revision": source_revision(project_root),
        "display": {"width": width, "height": height},
        "source": {
            "path": "Source/code.py",
            "mode": "btc",
        },
        "brightness": values.get("GLOBAL_DIM_LEVEL", 10),
        "btc": {
            "layers": {layer["role"]: layer for layer in layers},
        },
        "fonts": fonts,
    }


class EmulatorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        project_root: Path,
        web_root: Path = WEB_ROOT,
        verbose: bool = False,
    ) -> None:
        self.project_root = project_root.resolve()
        self.static_files = load_static_files(web_root)
        self.verbose = verbose
        super().__init__(server_address, EmulatorRequestHandler)


class EmulatorRequestHandler(BaseHTTPRequestHandler):
    server: EmulatorHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/api/config":
            self._serve_config()
            return
        if path == "/api/revision":
            self._send_json(
                {"revision": source_revision(self.server.project_root)},
                cache_control="no-store",
            )
            return
        if path == "/api/health":
            self._send_json({"status": "ok"}, cache_control="no-store")
            return
        if path in STATIC_FILES:
            self._serve_static(STATIC_FILES[path])
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _serve_config(self) -> None:
        try:
            config = build_display_config(self.server.project_root)
        except ConfigError as exc:
            self._send_json(
                {
                    "error": str(exc),
                    "revision": source_revision(self.server.project_root),
                },
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
                cache_control="no-store",
            )
            return
        self._send_json(config, cache_control="no-store")

    def _serve_static(self, filename: str) -> None:
        try:
            content, content_type = self.server.static_files[filename]
        except KeyError:
            self.send_error(HTTPStatus.NOT_FOUND, "Static file not found")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.end_headers()
        self.wfile.write(content)

    def _send_json(
        self,
        payload: Any,
        *,
        status: HTTPStatus = HTTPStatus.OK,
        cache_control: str = "no-cache",
    ) -> None:
        content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format_string: str, *args: Any) -> None:
        if self.server.verbose:
            super().log_message(format_string, *args)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview the BlockTron 64x32 display in a browser."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="BlockTron checkout containing the Source directory to watch.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    project_root = args.project_root.expanduser().resolve()
    code_path = project_root / "Source" / "code.py"
    if not code_path.is_file():
        print(f"Unable to find firmware source: {code_path}", file=sys.stderr)
        return 1

    try:
        server = EmulatorHTTPServer(
            (args.host, args.port),
            project_root=project_root,
            verbose=args.verbose,
        )
    except (ConfigError, OSError) as exc:
        print(f"Unable to start emulator: {exc}", file=sys.stderr)
        return 1

    host, port = server.server_address[:2]
    print(f"BlockTron emulator: http://{host}:{port}", flush=True)
    print(f"Watching {code_path} and {code_path.parent / 'fonts' / '*.bdf'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping emulator.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
