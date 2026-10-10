"""HEIC Explorer: browse HEIC files by metadata and send them to an iPhone over Wi-Fi."""

import datetime as dt
import hashlib
import io
import ipaddress
import os
import secrets
import socket
import threading
import webbrowser
from pathlib import Path

import pillow_heif
import qrcode
import qrcode.image.svg
from flask import Flask, abort, jsonify, request, send_file
from PIL import Image
from werkzeug.serving import make_server

pillow_heif.register_heif_opener()

ROOT = Path(__file__).parent
CACHE_DIR = ROOT / ".cache"
CERT_DIR = ROOT / ".cert"
PC_PORT = 8765
PHONE_PORT = 8766
HEIC_EXT = {".heic", ".heif"}

# Exif tags
EXIF_IFD, GPS_IFD = 0x8769, 0x8825
DATETIME_ORIGINAL, OFFSET_TIME_ORIGINAL, DATETIME = 0x9003, 0x9011, 0x0132
MAKE, MODEL, LENS_MODEL = 0x010F, 0x0110, 0xA434

files_by_id: dict[str, dict] = {}  # id -> metadata (includes absolute path)
transfers: dict[str, list[str]] = {}  # token -> list of file ids


# ---------------------------------------------------------------- metadata

def _gps_to_decimal(values, ref):
    d, m, s = (float(v) for v in values)
    dec = d + m / 60 + s / 3600
    return -dec if ref in ("S", "W") else dec


def read_metadata(path: Path) -> dict:
    stat = path.stat()
    meta = {
        "id": hashlib.sha1(str(path).encode()).hexdigest()[:16],
        "name": path.name,
        "path": str(path),
        "size": stat.st_size,
        "modified": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "taken": None, "offset": None, "lat": None, "lon": None, "alt": None,
        "make": None, "model": None, "lens": None, "width": None, "height": None,
    }
    try:
        heif = pillow_heif.open_heif(path)
        meta["width"], meta["height"] = heif.size
        exif_bytes = heif.info.get("exif")
        if not exif_bytes:
            return meta
        exif = Image.Exif()
        exif.load(exif_bytes)
        ifd = exif.get_ifd(EXIF_IFD)
        raw_date = ifd.get(DATETIME_ORIGINAL) or exif.get(DATETIME)
        if raw_date:
            meta["taken"] = dt.datetime.strptime(raw_date.strip("\x00 "), "%Y:%m:%d %H:%M:%S").isoformat()
        meta["offset"] = ifd.get(OFFSET_TIME_ORIGINAL)
        meta["make"] = (exif.get(MAKE) or "").strip("\x00 ") or None
        meta["model"] = (exif.get(MODEL) or "").strip("\x00 ") or None
        meta["lens"] = (ifd.get(LENS_MODEL) or "").strip("\x00 ") or None
        gps = exif.get_ifd(GPS_IFD)
        if 2 in gps and 4 in gps:
            meta["lat"] = round(_gps_to_decimal(gps[2], gps.get(1, "N")), 6)
            meta["lon"] = round(_gps_to_decimal(gps[4], gps.get(3, "E")), 6)
        if 6 in gps:
            meta["alt"] = round(float(gps[6]) * (-1 if gps.get(5) in (1, b"\x01") else 1), 1)
    except Exception as e:  # unreadable / corrupt file: still list it
        meta["error"] = str(e)
    return meta


def thumbnail_path(meta: dict) -> Path:
    key = hashlib.sha1(f"{meta['path']}|{meta['size']}|{meta['modified']}".encode()).hexdigest()
    return CACHE_DIR / f"{key}.jpg"


# ---------------------------------------------------------------- networking helpers

def lan_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def ensure_cert(ip: str) -> tuple[str, str]:
    """Self-signed cert so the phone page is a secure context (required by the Web Share API)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    CERT_DIR.mkdir(exist_ok=True)
    cert_file, key_file, ip_file = CERT_DIR / "cert.pem", CERT_DIR / "key.pem", CERT_DIR / "ip.txt"
    if cert_file.exists() and ip_file.exists() and ip_file.read_text() == ip:
        return str(cert_file), str(key_file)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HEIC Explorer")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    ip_file.write_text(ip)
    return str(cert_file), str(key_file)


# ---------------------------------------------------------------- PC app (localhost only)

pc = Flask("pc", static_folder=str(ROOT / "static"), static_url_path="/static")


@pc.get("/")
def index():
    return pc.send_static_file("index.html")


@pc.post("/api/pick-folder")
def pick_folder():
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(title="Choose a folder with HEIC files")
    root.destroy()
    return jsonify(folder=folder or None)


@pc.post("/api/scan")
def scan():
    folder = Path(request.json["folder"])
    recursive = bool(request.json.get("recursive"))
    if not folder.is_dir():
        return jsonify(error=f"Not a folder: {folder}"), 400
    paths = folder.rglob("*") if recursive else folder.iterdir()
    results = []
    for p in paths:
        if p.is_file() and p.suffix.lower() in HEIC_EXT:
            meta = read_metadata(p)
            files_by_id[meta["id"]] = meta
            results.append(meta)
    return jsonify(files=results)


@pc.get("/api/thumb/<fid>")
def thumb(fid):
    meta = files_by_id.get(fid) or abort(404)
    out = thumbnail_path(meta)
    if not out.exists():
        CACHE_DIR.mkdir(exist_ok=True)
        with Image.open(meta["path"]) as im:
            im.thumbnail((400, 400))
            im.convert("RGB").save(out, "JPEG", quality=80)
    return send_file(out, mimetype="image/jpeg", max_age=86400)


@pc.get("/api/preview/<fid>")
def preview(fid):
    meta = files_by_id.get(fid) or abort(404)
    buf = io.BytesIO()
    with Image.open(meta["path"]) as im:
        im.thumbnail((2000, 2000))
        im.convert("RGB").save(buf, "JPEG", quality=88)
    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg")


@pc.post("/api/transfer")
def create_transfer():
    ids = [i for i in request.json["ids"] if i in files_by_id]
    if not ids:
        return jsonify(error="No files selected"), 400
    token = secrets.token_urlsafe(16)
    transfers[token] = ids
    url = f"https://{PHONE_HOST}:{PHONE_PORT}/t/{token}"
    svg = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10).to_string(encoding="unicode")
    return jsonify(url=url, qr=svg, count=len(ids))


# ---------------------------------------------------------------- phone app (LAN, HTTPS, token-gated)

phone = Flask("phone", static_folder=None)


def transfer_or_404(token):
    return transfers.get(token) or abort(404)


@phone.get("/t/<token>")
def phone_page(token):
    transfer_or_404(token)
    return send_file(ROOT / "static" / "phone.html")


@phone.get("/t/<token>/list")
def phone_list(token):
    ids = transfer_or_404(token)
    return jsonify(files=[{"index": i, "name": files_by_id[f]["name"], "size": files_by_id[f]["size"]}
                          for i, f in enumerate(ids)])


@phone.get("/t/<token>/file/<int:index>")
def phone_file(token, index):
    ids = transfer_or_404(token)
    if not 0 <= index < len(ids):
        abort(404)
    # Original bytes, untouched: EXIF date/GPS reach Photos exactly as recorded.
    return send_file(files_by_id[ids[index]]["path"], mimetype="image/heic")


# ---------------------------------------------------------------- main

PHONE_HOST = lan_ip()


def main():
    cert, key = ensure_cert(PHONE_HOST)
    phone_server = make_server("0.0.0.0", PHONE_PORT, phone, threaded=True, ssl_context=(cert, key))
    threading.Thread(target=phone_server.serve_forever, daemon=True).start()
    pc_server = make_server("127.0.0.1", PC_PORT, pc, threaded=True)
    url = f"http://127.0.0.1:{PC_PORT}"
    print(f"HEIC Explorer running at {url}  (iPhone transfers via https://{PHONE_HOST}:{PHONE_PORT})")
    if not os.environ.get("NO_BROWSER"):
        webbrowser.open(url)
    try:
        pc_server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
