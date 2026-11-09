"""Pure-Python helpers (no QGIS imports): TM-3 zone table, parsing, formatting."""
import re
from collections import namedtuple

Zone = namedtuple("Zone", "label epsg cm")  # cm = central meridian (deg E)
LON_MIN, LON_MAX, HALF_WIDTH = 93.0, 141.0, 1.5


def _build_zones():
    zones = []
    for i in range(16):
        n, sub = (46, 2) if i == 0 else (47 + (i - 1) // 2, 1 + (i - 1) % 2)
        zones.append(Zone(f"{n}.{sub}", 23830 + i, 94.5 + 3 * i))  # EPSG:23830..23845
    return zones


ZONES = _build_zones()
ZONE_BY_LABEL = {z.label: z for z in ZONES}
AUTO = "Auto (from longitude)"
CHOICES = [f"{z.label}  (EPSG:{z.epsg}, CM {z.cm:g}°E)" for z in ZONES]


def label_of(choice):
    """Combo text -> zone label ('48.2'); None means Auto."""
    if choice == AUTO:
        return None
    if not choice:
        raise ValueError("Please select a TM-3 zone.")
    return choice.split()[0]


def zone_for_lon(lon):
    if not (LON_MIN <= lon <= LON_MAX):
        return None
    return ZONES[min(int((lon - LON_MIN) // 3), 15)]


def in_band(lon, zone):
    return abs(lon - zone.cm) <= HALF_WIDTH + 1e-6


def parse_angle(text, kind):
    """Decimal degrees or DMS: 6°12'31.5"S, 106 50 44 E, 6 12 31 LS, 106 50 BT."""
    s = text.strip().upper()
    for a, b in (("LS", "S"), ("LU", "N"), ("BT", "E"), ("BB", "W")):
        s = s.replace(a, b)
    s = s.replace(",", ".")
    if not s:
        raise ValueError(f"Please enter the {kind}.")
    try:
        val = float(s)
    except ValueError:
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
        if not 1 <= len(nums) <= 3:
            raise ValueError(f"Cannot read '{text}' as a {kind}.") from None
        d, m, sec = nums + [0.0] * (3 - len(nums))
        if m >= 60 or sec >= 60:
            raise ValueError(f"Minutes/seconds must be below 60 in '{text}'.") from None
        val = d + m / 60 + sec / 3600
        hemi = re.findall(r"[NSEW]", s)
        if hemi and hemi[-1] not in ("NS" if kind == "latitude" else "EW"):
            raise ValueError(f"'{text}': wrong hemisphere letter for a {kind}.") from None
        if s.startswith("-") or (hemi and hemi[-1] in "SW"):
            val = -val
    limit = 90 if kind == "latitude" else 180
    if abs(val) > limit:
        raise ValueError(f"The {kind} must be between -{limit} and {limit}.")
    return val


def to_float(v):
    """Lenient number reader for attribute values (handles NULL, '106,8456', '1,234.5')."""
    try:
        if isinstance(v, str):
            s = v.strip().replace(" ", "")
            s = s.replace(",", ".") if ("," in s and "." not in s) else s.replace(",", "")
            return float(s)
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def norm_zone(v):
    try:
        return f"{float(str(v).strip().replace(',', '.')):.1f}"
    except ValueError:
        return str(v).strip()


def to_dms(v, pos, neg):
    h = pos if v >= 0 else neg
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = round((v - d - m / 60) * 3600, 4)
    if s >= 60:
        s -= 60
        m += 1
    if m >= 60:
        m -= 60
        d += 1
    return f"{d}°{m:02d}'{s:07.4f}\"{h}"


# ---- UTM helpers (WGS 84) -------------------------------------------------
BANDS = "CDEFGHJKLMNPQRSTUVWX"


def utm_zone(lon):
    return min(int((lon + 180) // 6) + 1, 60)


def utm_band(lat):
    """Latitude band letter C..X; '' outside UTM range (-80..84)."""
    return BANDS[min(int((lat + 80) // 8), 19)] if -80 <= lat <= 84 else ""


def utm_epsg(zone, north):
    return (32600 if north else 32700) + zone


def garmin(zone, band, e, n):
    return f"{zone} {band} {round(e)} {round(n)}"
