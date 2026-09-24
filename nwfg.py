#!/usr/bin/env python
# coding: utf-8

"""
Project Name     : Native World File Generator
Version          : 2.0.0
Dependencies     : osgeo (GDAL), arcpy (optional, math fallback), standard lib.
About            : Generates .jgw/.pgw/.tfw and .prj sidecars for untouched 
                   drone images using the row-down convention.
"""

import math
import os
import glob
import sys
import xml.etree.ElementTree as ET

try:
    from osgeo import gdal, osr
except ImportError:
    sys.exit("GDAL Python bindings (osgeo) not found. Run this inside the ArcGIS Pro Python environment.")

try:
    import arcpy
    HAVE_ARCPY = True
except ImportError:
    HAVE_ARCPY = False

# Change based on your Drone Specs
SENSOR_WIDTH_MM = 17.3
FOCAL_LENGTH_MM = 14.45

WORLD_EXT = {
    '.jpg': '.jgw', '.jpeg': '.jgw',
    '.png': '.pgw',
    '.tif': '.tfw', '.tiff': '.tfw',
}

  # Change this to match your specific location
WKT_PRJ = (
    'PROJCS["WGS_1984_UTM_Zone_18N",GEOGCS["GCS_WGS_1984",'
    'DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],PARAMETER["False_Easting",500000.0],'
    'PARAMETER["False_Northing",0.0],PARAMETER["Central_Meridian",-75.0],'
    'PARAMETER["Scale_Factor",0.9996],PARAMETER["Latitude_Of_Origin",0.0],'
    'UNIT["Meter",1.0],AUTHORITY["EPSG",32618]],VERTCS["EGM96_height",'
    'VDATUM["EGM96_Geoid"],PARAMETER["Vertical_Shift",0.0],'
    'PARAMETER["Direction",1.0],UNIT["Meter",1.0],AUTHORITY["EPSG",5773]]'
)

# ----------------------------------------------------------------------
# Projection: arcpy first, Snyder transverse Mercator as fallback
# ----------------------------------------------------------------------

if HAVE_ARCPY:
    _SR_WGS = arcpy.SpatialReference(4326)
    _SR_UTM = {}

def project_to_utm(lon, lat):
    if HAVE_ARCPY:
        zone = int((lon + 180) // 6) + 1
        sr = _SR_UTM.get(zone)
        if sr is None:
            sr = arcpy.SpatialReference(32600 + zone)
            _SR_UTM[zone] = sr
        pt = arcpy.PointGeometry(arcpy.Point(lon, lat), _SR_WGS)
        q = pt.projectAs(sr)
        return q.firstPoint.X, q.firstPoint.Y
    return _utm_math(lon, lat)

def _utm_math(lon, lat):
    a = 6378137.0
    f = 1.0 / 298.257223563
    k0 = 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    zone = int((lon + 180) // 6) + 1
    lam0 = math.radians(zone * 6 - 183)
    phi = math.radians(lat)
    lam = math.radians(lon)
    n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = ep2 * math.cos(phi) ** 2
    aa = math.cos(phi) * (lam - lam0)
    m = a * ((1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 ** 3 / 256) * phi
             - (3 * e2 / 8 + 3 * e2 * e2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * e2 * e2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
             - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    east = k0 * n * (aa + (1 - t + c) * aa ** 3 / 6
                     + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * aa ** 5 / 120) + 500000.0
    north = k0 * (m + n * math.tan(phi) * (aa * aa / 2
                  + (5 - t + 9 * c + 4 * c * c) * aa ** 4 / 24
                  + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * aa ** 6 / 720))
    if lat < 0:
        north += 10000000.0
    return east, north

# ----------------------------------------------------------------------
# Metadata extraction via GDAL (replaces exifread, PIL, xmltodict)
# ----------------------------------------------------------------------

def _dms_to_deg(text):
    vals = [float(v) for v in text.replace('(', ' ').replace(')', ' ').split()]
    return vals[0] + vals[1] / 60.0 + vals[2] / 3600.0

def get_metadata_from_gdal(path):
    ds = gdal.Open(path)
    if ds is None:
        return None
        
    meta = ds.GetMetadata()
    width_px = ds.RasterXSize
    height_px = ds.RasterYSize
    
    # 1. Extract GPS
    if 'EXIF_GPSLatitude' not in meta or 'EXIF_GPSLongitude' not in meta:
        return None
        
    lat = _dms_to_deg(meta['EXIF_GPSLatitude'])
    lon = _dms_to_deg(meta['EXIF_GPSLongitude'])
    if meta.get('EXIF_GPSLatitudeRef', 'N') == 'S': lat = -lat
    if meta.get('EXIF_GPSLongitudeRef', 'E') == 'W': lon = -lon

    # 2. Extract XMP Telemetry (Altitude & Yaw)
    rel_alt = None
    yaw = None
    xmp_lines = ds.GetMetadata_List('xml:XMP')
    if xmp_lines:
        try:
            root = ET.fromstring(''.join(xmp_lines))
            for el in root.iter():
                for key, val in el.attrib.items():
                    local = key.rsplit('}', 1)[-1]
                    if local == 'RelativeAltitude':
                        rel_alt = float(val)
                    elif local == 'FlightYawDegree':
                        yaw = float(val)
        except ET.ParseError:
            pass
            
    if rel_alt is None:
        alt_str = meta.get('EXIF_GPSAltitude', '50').strip('()')
        rel_alt = float(alt_str) if alt_str else 50.0
    if yaw is None:
        yaw = 0.0
        
    return width_px, height_px, lat, lon, rel_alt, yaw

# ----------------------------------------------------------------------
# Sidecar Generation
# ----------------------------------------------------------------------

def generate_sidecars(path, save_dir):
    data = get_metadata_from_gdal(path)
    if data is None:
        print(f"  Skipped (no GPS or unreadable): {os.path.basename(path)}")
        return
        
    width_px, height_px, lat, lon, rel_alt, yaw = data
    
    gsd = (rel_alt * SENSOR_WIDTH_MM) / (FOCAL_LENGTH_MM * width_px)
    Ec, Nc = project_to_utm(lon, lat)

    alpha = math.radians(yaw % 360.0)

    A =  gsd * math.cos(alpha)
    B = -gsd * math.sin(alpha)
    D = -gsd * math.sin(alpha)
    E = -gsd * math.cos(alpha)

    det = A * E - B * D
    assert det < 0, "coefficient signs are wrong, raster would mirror"

    C = Ec - (width_px / 2.0 * A + height_px / 2.0 * B)
    F = Nc - (width_px / 2.0 * D + height_px / 2.0 * E)

    base_name = os.path.splitext(os.path.basename(path))[0]
    world_ext = WORLD_EXT.get(os.path.splitext(path)[1].lower(), '.jgw')

    with open(os.path.join(save_dir, base_name + world_ext), 'w') as f:
        f.write(f"{A:.16f}\n{D:.16f}\n{B:.16f}\n{E:.16f}\n{C:.10f}\n{F:.10f}\n")

    with open(os.path.join(save_dir, base_name + '.prj'), 'w') as f:
        f.write(WKT_PRJ)

    print(f"Wrote {base_name}{world_ext} | GSD {gsd:.6f} | heading {yaw % 360.0:.1f}")

def main():
    raw_img_dir = r'C:\FolderLocation\*.jpg' # Change the path and file type
    save_dir = r'C:/FolderLocation/'
    os.makedirs(save_dir, exist_ok=True)
    gdal.UseExceptions()

    print(f"Generating sidecars (native ArcGIS tools) in: {save_dir}")
    for path in sorted(glob.glob(raw_img_dir)):
        generate_sidecars(path, save_dir)

    print("\nDone. Move the .jgw/.pgw and .prj files next to your rasters.")

if __name__ == '__main__':
    main()
