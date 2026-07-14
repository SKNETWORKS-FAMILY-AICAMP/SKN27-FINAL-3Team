CREATE TABLE IF NOT EXISTS road_meta.source_sync_logs (
    sync_id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_type TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'started',
    received_count INTEGER NOT NULL DEFAULT 0,
    staging_count INTEGER NOT NULL DEFAULT 0,
    production_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    source_reference_date DATE,
    snapshot_path TEXT,
    pipeline_version TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS road_meta.source_quality_reports (
    report_id BIGSERIAL PRIMARY KEY,
    sync_id BIGINT REFERENCES road_meta.source_sync_logs(sync_id),
    check_name TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    status TEXT NOT NULL,
    metric_value TEXT,
    threshold_value TEXT,
    message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
