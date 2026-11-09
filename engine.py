"""QGIS-backed conversion engine: any input -> WGS 84 lon/lat -> all output formats."""
import math

from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsProject

from . import core as c

WGS = QgsCoordinateReferenceSystem("EPSG:4326")
_cache = {}

# Batch output groups: (field name, key in all_outputs(), type)
D, S, I = QVariant.Double, QVariant.String, QVariant.Int
GROUPS = {
    "dd": [("WGS84_Longitude", "lon", D), ("WGS84_Latitude", "lat", D)],
    "dms": [("Latitude_DMS", "lat_dms", S), ("Longitude_DMS", "lon_dms", S)],
    "utm": [("UTM_Zone", "utm_zone", I), ("UTM_Band", "utm_band", S), ("UTM_Hemisphere", "utm_hemi", S),
            ("UTM_Easting", "utm_e", D), ("UTM_Northing", "utm_n", D), ("UTM_Garmin", "garmin", S)],
    "tm3": [("TM3_Zone", "tm3_zone", S), ("TM3_EPSG", "tm3_epsg", I),
            ("TM3_Easting", "tm3_e", D), ("TM3_Northing", "tm3_n", D)],
}


def tr(epsg, to_wgs):
    key = (epsg, to_wgs)
    if key not in _cache:
        zc = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
        a, b = (zc, WGS) if to_wgs else (WGS, zc)
        _cache[key] = QgsCoordinateTransform(a, b, QgsProject.instance())
    return _cache[key]


def crs_desc(epsg):
    return QgsCoordinateReferenceSystem(f"EPSG:{epsg}").description()


def angle(v, kind):
    """Attribute value (number, '106,8456' or DMS text) -> degrees, NaN if unreadable."""
    x = c.to_float(v)
    if not math.isfinite(x):
        try:
            x = c.parse_angle(str(v), kind)
        except ValueError:
            return float("nan")
    return x if abs(x) <= (90 if kind == "latitude" else 180) else float("nan")


def from_utm(zone, north, e, n):
    if not 1 <= zone <= 60:
        raise ValueError("UTM zone must be between 1 and 60.")
    p = tr(c.utm_epsg(zone, north), True).transform(QgsPointXY(e, n))
    return p.x(), p.y()


def from_tm3(z, e, n):
    p = tr(z.epsg, True).transform(QgsPointXY(e, n))
    return p.x(), p.y()


def all_outputs(lon, lat, tm3_zone=None):
    """Every representation of one WGS 84 point. tm3_zone=None picks it from longitude."""
    out = {"lon": lon, "lat": lat, "lat_dms": c.to_dms(lat, "N", "S"), "lon_dms": c.to_dms(lon, "E", "W")}
    band = c.utm_band(lat)
    if band:
        zone, north = c.utm_zone(lon), lat >= 0
        p = tr(c.utm_epsg(zone, north), False).transform(QgsPointXY(lon, lat))
        out.update(utm_zone=zone, utm_band=band, utm_hemi="N" if north else "S", utm_e=p.x(),
                   utm_n=p.y(), utm_epsg=c.utm_epsg(zone, north), garmin=c.garmin(zone, band, p.x(), p.y()))
    z = tm3_zone or c.zone_for_lon(lon)
    if z:
        p = tr(z.epsg, False).transform(QgsPointXY(lon, lat))
        out.update(tm3_zone=z.label, tm3_epsg=z.epsg, tm3_e=p.x(), tm3_n=p.y(),
                   tm3_far=not c.in_band(lon, z), tm3_cm=z.cm)
    return out


def describe(o):
    t = (f"WGS 84, decimal degrees\n  Latitude : {o['lat']:.8f}°\n  Longitude: {o['lon']:.8f}°\n\n"
         f"WGS 84, degrees-minutes-seconds\n  Latitude : {o['lat_dms']}\n  Longitude: {o['lon_dms']}\n\n")
    if "utm_e" in o:
        t += (f"UTM (WGS 84), EPSG:{o['utm_epsg']}\n  Zone     : {o['utm_zone']}  band {o['utm_band']}  "
              f"({'northern' if o['utm_hemi'] == 'N' else 'southern'} hemisphere)\n"
              f"  Easting  : {o['utm_e']:.3f} m\n  Northing : {o['utm_n']:.3f} m\n"
              f"  Garmin   : {o['garmin']}\n\n")
    else:
        t += "UTM: not defined for latitudes outside 80°S–84°N.\n\n"
    if "tm3_e" in o:
        t += (f"Indonesia TM-3 (DGN95), EPSG:{o['tm3_epsg']}\n  Zone     : {o['tm3_zone']}  (CM {o['tm3_cm']:g}°E)\n"
              f"  Easting  : {o['tm3_e']:.3f} m\n  Northing : {o['tm3_n']:.3f} m\n")
        if o["tm3_far"]:
            t += "  ⚠ Point is outside this zone's 3° band; distortion is larger.\n"
    else:
        t += "Indonesia TM-3: longitude outside 93°E–141°E.\n"
    return t
