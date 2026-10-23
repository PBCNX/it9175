"""Download pyusb and libusb-package wheels without pip, then extract them.

pip's installer cannot write its temporary metadata files under this sandbox,
so this bootstrap fetches the wheels directly from PyPI and unpacks them.
Run once:  python tools/fetch_deps.py
"""
import io
import json
import os
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VENDOR = os.path.join(ROOT, "vendor")
WHEELS = os.path.join(ROOT, ".tmp", "wheels")


def pypi(project):
    with urllib.request.urlopen(f"https://pypi.org/pypi/{project}/json", timeout=30) as r:
        return json.load(r)


def pick(meta, patterns):
    version = meta["info"]["version"]
    for f in meta["releases"][version]:
        name = f["filename"]
        if name.endswith(".whl") and all(p in name for p in patterns):
            return version, f["url"], name
    raise SystemExit(f"no wheel matching {patterns} in {meta['info']['name']} {version}")


def download(url, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return path
    print("fetch", url)
    with urllib.request.urlopen(url, timeout=120) as r, open(path, "wb") as out:
        out.write(r.read())
    return path


def main():
    os.makedirs(WHEELS, exist_ok=True)

    ver, url, name = pick(pypi("pyusb"), ["py3-none-any"])
    whl = download(url, os.path.join(WHEELS, name))
    dest = os.path.join(VENDOR, "pyusb")
    with zipfile.ZipFile(whl) as z:
        z.extractall(os.path.join(VENDOR, "_pyusb_extract"))
    src = os.path.join(VENDOR, "_pyusb_extract", "usb")
    if os.path.isdir(dest):
        import shutil
        shutil.rmtree(dest)
    os.replace(src, dest)
    print("pyusb", ver, "->", dest)

    ver, url, name = pick(pypi("libusb-package"), ["win_amd64"])
    whl = download(url, os.path.join(WHEELS, name))
    dest = os.path.join(VENDOR, "windows", "x64")
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(whl) as z:
        for info in z.infolist():
            base = os.path.basename(info.filename)
            if base.lower() == "libusb-1.0.dll":
                with z.open(info) as src, open(os.path.join(dest, base), "wb") as out:
                    out.write(src.read())
                print("libusb", ver, "->", os.path.join(dest, base))
            elif base.upper().startswith("LICENSE"):
                with z.open(info) as src, open(os.path.join(dest, base), "wb") as out:
                    out.write(src.read())


if __name__ == "__main__":
    main()
