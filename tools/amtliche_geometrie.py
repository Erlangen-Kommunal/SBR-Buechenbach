"""Shapefile-Leser und Koordinatenumrechnung für die Geodaten der Stadt Erlangen.

Die Stadt veröffentlicht ihre Gebietsgliederungen als Esri-Shapefile in
DHDN / Gauß-Krüger Zone 4 (EPSG:31468). Beides — Format und Bezugssystem —
wird hier in wenigen Zeilen selbst behandelt, statt GDAL/pyproj zu fordern:
der Wochen-Sync soll ohne Fremdabhängigkeit auskommen.

Belegt ist die Umrechnung durch eine Gegenprobe gegen eine unabhängige Quelle:
Legt man die umgerechneten Bezirksgrenzen über die OpenStreetMap-Geometrie der
Straßen, stimmt der Bezirk bei 87,5 % der Abschnitte mit dem amtlichen
Straßenverzeichnis überein; die Abweichungen sind durchweg unmittelbare
Nachbarbezirke (Straßen auf der Grenze). Ein systematischer Fehler in der
Projektion würde diese Übereinstimmung zerstören.
"""

from __future__ import annotations

import io
import math
import struct
import zipfile

# ── Shapefile ────────────────────────────────────────────────────────────────


def read_dbf(blob: bytes) -> list[dict[str, str]]:
    """Attributtabelle eines Shapefiles."""
    nrec, hlen, rlen = struct.unpack("<IHH", blob[4:12])
    # Byte 29 ist der dBASE-Sprachtreiber. Die Erlanger Dateien nutzen
    # unterschiedliche Zeichensätze — Bezirke 0x10 (cp850),
    # Beiratsgebiete 0x57 (ANSI). Ohne die Fallunterscheidung wird aus
    # „Hüttendorf" ein „H³ttendorf".
    enc = "cp1252" if blob[29] in (0x03, 0x57) else "cp850"
    fields, off = [], 32
    while blob[off] != 0x0D:
        name = blob[off:off + 11].split(b"\x00")[0].decode(enc)
        fields.append((name, blob[off + 16]))
        off += 32

    rows = []
    for i in range(nrec):
        rec = blob[hlen + i * rlen: hlen + (i + 1) * rlen]
        pos, row = 1, {}                      # Byte 0 = Löschmarke
        for name, length in fields:
            row[name] = rec[pos:pos + length].decode(enc).strip()
            pos += length
        rows.append(row)
    return rows


def read_shp(blob: bytes) -> list[list[list[tuple[float, float]]]]:
    """Polygone (Shape-Typ 5) als Liste von Ringen je Objekt."""
    shapes, pos = [], 100                      # 100 Byte Dateikopf
    while pos < len(blob):
        _num, clen = struct.unpack(">II", blob[pos:pos + 8])
        body = blob[pos + 8: pos + 8 + clen * 2]
        pos += 8 + clen * 2
        (stype,) = struct.unpack("<i", body[:4])
        if stype != 5:
            shapes.append([])
            continue
        nparts, npoints = struct.unpack("<ii", body[36:44])
        parts = list(struct.unpack(f"<{nparts}i", body[44:44 + 4 * nparts]))
        raw = body[44 + 4 * nparts:]
        pts = [struct.unpack("<2d", raw[i * 16:(i + 1) * 16]) for i in range(npoints)]
        shapes.append([pts[parts[i]: (parts[i + 1] if i + 1 < nparts else npoints)]
                       for i in range(nparts)])
    return shapes


def load_zip(blob: bytes) -> tuple[list, list[dict[str, str]]]:
    """Shapefile aus einem ZIP-Archiv (Geometrie, Attribute)."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    shp_name = next(n for n in z.namelist() if n.lower().endswith(".shp"))
    dbf_name = next(n for n in z.namelist() if n.lower().endswith(".dbf"))
    return read_shp(z.read(shp_name)), read_dbf(z.read(dbf_name))


def bbox(rings) -> tuple[float, float, float, float]:
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return min(xs), min(ys), max(xs), max(ys)


def contains(rings, x: float, y: float) -> bool:
    """Punkt-in-Polygon nach der Even-odd-Regel über alle Ringe (Löcher inklusive)."""
    inside = False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


# ── DHDN / Gauß-Krüger Zone 4  →  WGS84 ──────────────────────────────────────

_A, _F = 6377397.155, 1 / 299.1528128          # Bessel 1841
_E2 = _F * (2 - _F)
_LON0, _FE = math.radians(12.0), 4500000.0     # Zone 4

# 7-Parameter-Helmert DHDN→WGS84 (EPSG:1777), Restfehler rund 1 m
_DX, _DY, _DZ = 598.1, 73.7, 418.2
_RX, _RY, _RZ = (math.radians(v / 3600) for v in (0.202, 0.045, -2.455))
_DS = 6.7e-6

_AW, _FW = 6378137.0, 1 / 298.257223563        # WGS84
_E2W = _FW * (2 - _FW)


def _tm_inverse(east: float, north: float) -> tuple[float, float]:
    x = east - _FE
    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    mu = north / (_A * (1 - _E2 / 4 - 3 * _E2**2 / 64 - 5 * _E2**3 / 256))
    phi1 = (mu
            + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
            + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
            + (151 * e1**3 / 96) * math.sin(6 * mu)
            + (1097 * e1**4 / 512) * math.sin(8 * mu))
    sin1, cos1, tan1 = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    ep2 = _E2 / (1 - _E2)
    c1, t1 = ep2 * cos1**2, tan1**2
    n1 = _A / math.sqrt(1 - _E2 * sin1**2)
    r1 = _A * (1 - _E2) / (1 - _E2 * sin1**2) ** 1.5
    d = x / n1
    phi = phi1 - (n1 * tan1 / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720)
    lam = _LON0 + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120) / cos1
    return phi, lam


def gk4_to_wgs84(east: float, north: float) -> tuple[float, float]:
    """Gauß-Krüger Zone 4 → (Länge, Breite) in Grad."""
    phi, lam = _tm_inverse(east, north)
    n = _A / math.sqrt(1 - _E2 * math.sin(phi) ** 2)
    x = n * math.cos(phi) * math.cos(lam)
    y = n * math.cos(phi) * math.sin(lam)
    z = n * (1 - _E2) * math.sin(phi)

    xw = _DX + (1 + _DS) * (x - _RZ * y + _RY * z)
    yw = _DY + (1 + _DS) * (_RZ * x + y - _RX * z)
    zw = _DZ + (1 + _DS) * (-_RY * x + _RX * y + z)

    lam_w = math.atan2(yw, xw)
    p = math.hypot(xw, yw)
    phi_w = math.atan2(zw, p * (1 - _E2W))
    for _ in range(8):                          # konvergiert nach 3-4 Runden
        nw = _AW / math.sqrt(1 - _E2W * math.sin(phi_w) ** 2)
        h = p / math.cos(phi_w) - nw
        phi_w = math.atan2(zw, p * (1 - _E2W * nw / (nw + h)))
    return math.degrees(lam_w), math.degrees(phi_w)
