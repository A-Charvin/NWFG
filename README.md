# Native World File Generator

Writes world file (.jgw, .pgw, .tfw) and projection (.prj) sidecars for untouched
drone photographs so ArcGIS Pro and QGIS place every frame at its true ground
position, scale and heading on load. No pixel resampling, no feature matching,
no rewritten rasters.

## What it does

For each image the tool:

1. Reads EXIF GPS latitude and longitude from GDAL metadata.
2. Reads XMP flight telemetry (RelativeAltitude, FlightYawDegree) from the
   embedded XMP packet, falling back to EXIF altitude when XMP is absent.
3. Computes ground sample distance from altitude and camera constants.
4. Projects the camera position to UTM with arcpy, or with a built-in
   transverse Mercator implementation when arcpy is unavailable.
5. Builds the six world file coefficients for a rotated, north-referenced
   placement.
6. Writes a world file and a .prj named to match the raster extension.

Drop the sidecars beside the originals and the images load georeferenced.
The pixels are never touched.

## Why sidecars instead of rewritten rasters

- Source JPEGs stay byte identical, so nothing is lost to recompression.
- No resampling means no interpolation blur and no black border wedges
  from rotation.
- Files stay tiny: a world file is six lines of text.
- Placement remains editable. Open the Georeferencing tool in ArcGIS and
  nudge; your edits layer on top of the telemetry placement.

## Requirements

Runs inside the Python environment that ships with ArcGIS Pro. Uses only:

- osgeo (GDAL), bundled with Pro, for raster dimensions and metadata
- arcpy, optional, for coordinate projection (pure Python fallback included)
- Python standard library

No pip installs.

## Usage

1. Copy the script anywhere.
2. Edit `raw_img_dir` and `save_dir` at the bottom of `main()`.
3. Run it with the ArcGIS Pro Python interpreter:

   ```
   "C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" nwfg.py
   ```

4. Keep the sidecars in the same folder as the rasters, same base names.
5. Add the rasters to a map. They land in place.

## Camera constants

Defaults target the DJI Mavic 4 Pro Hasselblad camera:

- `SENSOR_WIDTH_MM = 17.3` (4/3 CMOS active width)
- `FOCAL_LENGTH_MM = 14.45` (matches EXIF FocalLength, 28 mm equivalent)

For other cameras, edit these two constants at the top of the script using
your EXIF FocalLength and the sensor specification.

## The math

Ground sample distance in metres per pixel:

```
gsd = (relative_altitude * SENSOR_WIDTH_MM) / (FOCAL_LENGTH_MM * image_width_px)
```

World file affine in row-down convention, with alpha as the azimuth of the
image top edge taken from FlightYawDegree:

```
X = A*col + B*row + C
Y = D*col + E*row + F

A =  gsd * cos(alpha)
B = -gsd * sin(alpha)
D = -gsd * sin(alpha)
E = -gsd * cos(alpha)

C = E0 - (width/2 * A + height/2 * B)
F = N0 - (width/2 * D + height/2 * E)
```

where E0, N0 are the UTM coordinates of the camera position. The determinant
`A*E - B*D` must be negative for every valid world file. The script asserts
this so a sign error can never ship a mirrored raster.

Validation: coefficients were checked against a hand-digitized ArcGIS
georeferencing of the same frames. Scale agreed to 0.03 percent and rotation
matched FlightYawDegree directly.

## Output naming

| Raster     | World file | Projection |
|------------|------------|------------|
| .jpg/.jpeg | .jgw       | .prj       |
| .png       | .pgw       | .prj       |
| .tif/.tiff | .tfw       | .prj       |

## Accuracy and limitations

- Placement accuracy is bounded by consumer GNSS, typically one to three
  metres horizontal. Expect to nudge frames in GIS for survey-grade work.
- The transform is affine. Pitch and roll tilt leave a small trapezoidal
  residual, about one to two percent across a frame at typical attitudes,
  which an affine world file cannot express.
- Scale uses relative altitude above takeoff and assumes terrain near
  takeoff elevation.
- The bundled .prj WKT is WGS 84 UTM zone 18N with an EGM96 vertical datum.
  Replace `WKT_PRJ` when flying outside that zone.

## Companion tool

AeroMosaic Ground Mosaic Builder warps the same telemetry placements into a
single feathered GeoTIFF mosaic. Same math and same constants, so the mosaic
and the sidecars agree pixel for pixel.

## Provenance

XMP telemetry handling concepts from cheny124800/Drone-Image-Stitching. 
Coefficient conventions were reverse engineered from and verified against ArcGIS Pro 3.6 georeferencing output.
