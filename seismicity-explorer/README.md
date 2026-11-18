# Seismicity Explorer

A small Flask/PostGIS application for filtering seismic events by mining-panel
monitoring areas. Existing notebooks and `seismi` research modules are left
untouched.

## What the repository data showed

- The 2013 workbook has 6,506 event rows. Its `!-Y` values (about -459,000) are
  the project X coordinate and `!-X` values (about -1,103,000) are Y; this is
  the explicit axis swap used by `seismi.xls.read_seismic_events`.
- `seismic_events.xlsx` has 143,125 rows with `Datum`, `hh:mm:ss.sss`, `X`,
  `Y`, `Z`, `Magn`, and `Energie`.
- The measured-depth workbook has `ID`, `x-coord`, `y-coord`, and a named
  seam-depth column; the interpolated grid has `X`, `Y`, and that depth.
- Event, borehole, and grid coordinates align numerically and with the
  EPSG:5514 assumption in the existing loaders; a sample EPSG:5514 point
  transforms to the Karviná area. The DXF extents overlap those coordinates,
  but its `$INSUNITS=4` metadata says millimetres, inconsistent with the
  coordinate magnitudes. It is not imported until its unit metadata is
  confirmed. The shapefiles have no `.prj` or `.dbf` files and their current
  coordinate bounds do not align with the mine data, so they are not imported.

The database retains event and depth records separately. Every imported row's
original workbook attributes are kept as JSONB, and imports are recorded by
file checksum and sheet. Re-uploading the same workbook and type reports its
previous result without duplicating data. Seismic events are deduplicated by
their normalized time, coordinates, depth, magnitude, and energy; all source
rows remain linked for traceability. The per-import duplicate count includes
both repeated rows in a workbook and events already present from earlier
imports.

## Current development database

The persistent development database is initialized with 143,181 unique
seismic events from 149,631 accepted source rows, 14 measured borehole points,
and 5,100 interpolated grid points. The additional 2013 workbook contributes
6,506 source rows; 6,447 match events already in the main catalogue. Its 58
malformed magnitude cells are retained in the original attributes and stored
as null magnitudes. Panel `138 708` is preselected on the dashboard with its
1989-09-01 to 1990-12-01 mining period and 100 m monitoring buffer. A fresh
database volume does not contain these imports until the workbooks are
imported.

## Run locally or deploy

From this directory:

1. Copy `.env.example` to `.env` and set a long, unique `POSTGRES_PASSWORD`.
   Keep `.env` private; it is ignored by git.
2. Start the database and application with `docker compose up --build -d`.
   The database has no published port. The app binds to `127.0.0.1:8000` by
   default for local access; set `APP_PORT` to change it. The app also joins
   the Docker network `seismicity` with the stable alias `seismicity-app`;
   PostgreSQL does not join that network.
3. Create an Nginx Basic Auth file outside this directory, for example:
   `sudo htpasswd -c /etc/nginx/seismicity.htpasswd analyst`.
4. Attach the Nginx container to the same Docker network. In the Nginx
   Compose project, declare the network as external:
   ```yaml
   services:
     nginx:
       networks:
         - default
         - seismicity
   networks:
     seismicity:
       external: true
       name: seismicity
   ```
   Add `seismicity` to the Nginx service's networks, then install
   `nginx/seismicity.conf.template` in the container. Render only
   `${PUBLIC_HOST}` (so Nginx variables such as `$host` remain intact). The
   template resolves `seismicity-app` through Docker DNS and proxies to port
   8000. It uses the corresponding Let's Encrypt certificate paths and
   redirects HTTP to HTTPS. Ensure Nginx can read the Basic Auth file and
   certificate.
5. Obtain/renew the TLS certificate for the configured `PUBLIC_HOST` using the
   host's existing certificate process. The initial `.env.example` hostname is
   `seismicity.dev.garncarz.cz`; changing it does not require an app rebuild.

The database volume is named `seismicity_data`. Back it up using the normal
PostgreSQL backup process. Schema version 1 is applied by the app at startup;
future schema changes should be added as numbered migrations.

## Use

Open the configured HTTPS host. The UI supports:

- importing `.xlsx` event, measured-borehole, or interpolated-grid data;
- entering panel descriptions and ordered coordinate rows, previewing the
  polygon and outward buffer, and creating/editing/deleting panels;
- filtering by panel monitoring area, mining dates, a custom inclusive date
  range, minimum energy, or minimum magnitude;
- inspecting a bounded set of event markers and raw event attributes, with
  whole-result statistics and monthly energy/event charts;
- optional borehole and depth-grid point layers.

The importer defaults to EPSG:5514 and accepts another projected or geographic
source CRS (for example `EPSG:4326`), transforming coordinates into the stored
EPSG:5514 system. The parser accepts Czech dotted dates and defaults an omitted
monitoring buffer to 100 m. Mining dates may be omitted; the mining-period
filter then explains that complete dates are required. Buffer operations are
computed in PostGIS in EPSG:5514. Only map output is transformed to WGS84. The
map uses Leaflet/OpenStreetMap and Chart.js browser assets from public CDNs.

Run the focused checks with `python -m pytest -q`.
