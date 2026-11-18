CREATE TABLE source_files (
    id bigserial PRIMARY KEY,
    filename text NOT NULL,
    sha256 char(64) NOT NULL,
    source_type text NOT NULL CHECK (
        source_type IN ('seismic_events', 'borehole_depths', 'interpolated_depth_grid')
    ),
    source_crs text NOT NULL DEFAULT 'EPSG:5514',
    sheet_name text NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    rows_seen integer NOT NULL DEFAULT 0,
    accepted_rows integer NOT NULL DEFAULT 0,
    skipped_rows integer NOT NULL DEFAULT 0,
    duplicate_events integer NOT NULL DEFAULT 0,
    warnings integer NOT NULL DEFAULT 0,
    report jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (sha256, source_type, source_crs)
);

CREATE TABLE seismic_events (
    id bigserial PRIMARY KEY,
    observed_at timestamp without time zone NOT NULL,
    x_m double precision NOT NULL,
    y_m double precision NOT NULL,
    z_m double precision,
    magnitude double precision,
    energy double precision,
    fingerprint char(64) NOT NULL UNIQUE,
    attributes jsonb NOT NULL,
    geom geometry(Point, 5514) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX seismic_events_geom_gix ON seismic_events USING gist (geom);
CREATE INDEX seismic_events_observed_at_idx ON seismic_events (observed_at);
CREATE INDEX seismic_events_energy_idx ON seismic_events (energy);

CREATE TABLE event_sources (
    event_id bigint NOT NULL REFERENCES seismic_events(id) ON DELETE CASCADE,
    source_file_id bigint NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
    source_row integer NOT NULL,
    attributes jsonb NOT NULL,
    PRIMARY KEY (source_file_id, source_row)
);
CREATE INDEX event_sources_event_idx ON event_sources (event_id);

CREATE TABLE depth_points (
    id bigserial PRIMARY KEY,
    source_file_id bigint NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
    source_row integer NOT NULL,
    point_type text NOT NULL CHECK (point_type IN ('borehole', 'grid')),
    point_identifier text,
    depth_m double precision,
    attributes jsonb NOT NULL,
    geom geometry(Point, 5514) NOT NULL,
    UNIQUE (source_file_id, source_row)
);
CREATE INDEX depth_points_geom_gix ON depth_points USING gist (geom);
CREATE INDEX depth_points_type_idx ON depth_points (point_type);

CREATE TABLE mining_panels (
    id bigserial PRIMARY KEY,
    identifier text NOT NULL,
    seam text,
    mining_start date,
    mining_end date,
    buffer_m double precision NOT NULL DEFAULT 100 CHECK (buffer_m >= 0),
    original_description text NOT NULL,
    vertices jsonb NOT NULL,
    boundary geometry(Polygon, 5514) NOT NULL,
    monitoring_area geometry(MultiPolygon, 5514) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (mining_start IS NULL OR mining_end IS NULL OR mining_start <= mining_end)
);
CREATE INDEX mining_panels_boundary_gix ON mining_panels USING gist (boundary);
CREATE INDEX mining_panels_monitoring_gix ON mining_panels USING gist (monitoring_area);
