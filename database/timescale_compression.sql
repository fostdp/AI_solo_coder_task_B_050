-- ============================================================
-- TimescaleDB 自动压缩 + 保留策略 + 降采样配置
-- 原始数据保留180天，降采样数据保留5年
-- ============================================================

-- 1. 启用压缩设置（按表逐个配置段列和压缩选项）

ALTER TABLE electrochemical_noise_data SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'artifact_id, sensor_id',
    timescaledb.compress_orderby = 'time DESC'
);

ALTER TABLE microenvironment_data SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'artifact_id, sensor_id',
    timescaledb.compress_orderby = 'time DESC'
);

ALTER TABLE microscope_images SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'artifact_id, sensor_id',
    timescaledb.compress_orderby = 'time DESC'
);

ALTER TABLE rust_predictions SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'artifact_id',
    timescaledb.compress_orderby = 'prediction_time DESC'
);

ALTER TABLE alerts SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'artifact_id',
    timescaledb.compress_orderby = 'alert_time DESC'
);

ALTER TABLE spray_execution_logs SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'task_id',
    timescaledb.compress_orderby = 'time DESC'
);


-- 2. 压缩策略（7天后自动压缩，节省磁盘约 90%）

SELECT add_compression_policy('electrochemical_noise_data', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('microenvironment_data', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('microscope_images', INTERVAL '14 days', if_not_exists => TRUE);
SELECT add_compression_policy('rust_predictions', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('alerts', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('spray_execution_logs', INTERVAL '14 days', if_not_exists => TRUE);


-- 3. 原始数据保留策略（180天后自动删除原始粒度数据）

SELECT remove_retention_policy('electrochemical_noise_data', if_exists => TRUE);
SELECT add_retention_policy('electrochemical_noise_data', INTERVAL '180 days', if_not_exists => TRUE);

SELECT remove_retention_policy('microenvironment_data', if_exists => TRUE);
SELECT add_retention_policy('microenvironment_data', INTERVAL '180 days', if_not_exists => TRUE);

SELECT remove_retention_policy('microscope_images', if_exists => TRUE);
SELECT add_retention_policy('microscope_images', INTERVAL '180 days', if_not_exists => TRUE);

SELECT remove_retention_policy('rust_predictions', if_exists => TRUE);
SELECT add_retention_policy('rust_predictions', INTERVAL '2 years', if_not_exists => TRUE);

SELECT remove_retention_policy('alerts', if_exists => TRUE);
SELECT add_retention_policy('alerts', INTERVAL '3 years', if_not_exists => TRUE);

SELECT remove_retention_policy('spray_execution_logs', if_exists => TRUE);
SELECT add_retention_policy('spray_execution_logs', INTERVAL '180 days', if_not_exists => TRUE);


-- 4. 降采样连续聚合（5年保留期）

-- 4a. 电化学噪声 → 1小时聚合
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_ecn_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    sensor_id,
    artifact_id,
    avg(noise_resistance) AS avg_rn,
    min(noise_resistance) AS min_rn,
    max(noise_resistance) AS max_rn,
    stddev(noise_resistance) AS std_rn,
    avg(pitting_index) AS avg_pi,
    max(pitting_index) AS max_pi,
    avg(std_voltage) AS avg_std_v,
    avg(std_current) AS avg_std_i,
    count(*) AS sample_count
FROM electrochemical_noise_data
GROUP BY bucket, sensor_id, artifact_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('mv_ecn_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

SELECT add_retention_policy('mv_ecn_hourly', INTERVAL '5 years', if_not_exists => TRUE);


-- 4b. 电化学噪声 → 1天聚合
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_ecn_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    sensor_id,
    artifact_id,
    avg(noise_resistance) AS avg_rn,
    min(noise_resistance) AS min_rn,
    max(noise_resistance) AS max_rn,
    percentile_cont(0.05) WITHIN GROUP (ORDER BY noise_resistance) AS p05_rn,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY noise_resistance) AS p95_rn,
    avg(pitting_index) AS avg_pi,
    max(pitting_index) AS max_pi,
    count(*) AS sample_count
FROM electrochemical_noise_data
GROUP BY bucket, sensor_id, artifact_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('mv_ecn_daily',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

SELECT add_retention_policy('mv_ecn_daily', INTERVAL '5 years', if_not_exists => TRUE);


-- 4c. 微环境 → 1小时聚合
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_menv_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    sensor_id,
    artifact_id,
    avg(temperature) AS avg_temp,
    max(temperature) AS max_temp,
    min(temperature) AS min_temp,
    avg(humidity) AS avg_rh,
    max(humidity) AS max_rh,
    avg(chloride_concentration) AS avg_cl,
    max(chloride_concentration) AS max_cl,
    avg(sulfur_dioxide) AS avg_so2,
    max(sulfur_dioxide) AS max_so2,
    avg(nitrogen_oxides) AS avg_nox,
    avg(formaldehyde) AS avg_hcho,
    count(*) AS sample_count
FROM microenvironment_data
GROUP BY bucket, sensor_id, artifact_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('mv_menv_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

SELECT add_retention_policy('mv_menv_hourly', INTERVAL '5 years', if_not_exists => TRUE);


-- 4d. 微环境 → 1天聚合
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_menv_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    sensor_id,
    artifact_id,
    avg(temperature) AS avg_temp,
    max(temperature) AS max_temp,
    min(temperature) AS min_temp,
    avg(humidity) AS avg_rh,
    max(humidity) AS max_rh,
    avg(chloride_concentration) AS avg_cl,
    max(chloride_concentration) AS max_cl,
    avg(sulfur_dioxide) AS avg_so2,
    max(sulfur_dioxide) AS max_so2,
    count(*) AS sample_count
FROM microenvironment_data
GROUP BY bucket, sensor_id, artifact_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('mv_menv_daily',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

SELECT add_retention_policy('mv_menv_daily', INTERVAL '5 years', if_not_exists => TRUE);


-- 5. 确保降采样数据在原始数据删除后仍可用（使用 compress_enable + order by）

ALTER TABLE mv_ecn_hourly SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'artifact_id, sensor_id',
    timescaledb.compress_orderby = 'bucket DESC'
);

ALTER TABLE mv_ecn_daily SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'artifact_id, sensor_id',
    timescaledb.compress_orderby = 'bucket DESC'
);

ALTER TABLE mv_menv_hourly SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'artifact_id, sensor_id',
    timescaledb.compress_orderby = 'bucket DESC'
);

ALTER TABLE mv_menv_daily SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'artifact_id, sensor_id',
    timescaledb.compress_orderby = 'bucket DESC'
);

SELECT add_compression_policy('mv_ecn_hourly', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('mv_ecn_daily', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('mv_menv_hourly', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('mv_menv_daily', INTERVAL '30 days', if_not_exists => TRUE);


-- 6. 索引优化（压缩后仍需查询的列）

CREATE INDEX IF NOT EXISTS idx_ecn_rn_low ON electrochemical_noise_data(noise_resistance)
    WHERE noise_resistance < 1000;

CREATE INDEX IF NOT EXISTS idx_ecn_pi_high ON electrochemical_noise_data(pitting_index)
    WHERE pitting_index > 2.0;

CREATE INDEX IF NOT EXISTS idx_menv_cl_high ON microenvironment_data(chloride_concentration)
    WHERE chloride_concentration > 3.0;


-- 7. 数据保留策略摘要视图
CREATE OR REPLACE VIEW v_retention_policies AS
SELECT
    hypertable_name,
    policy_type,
    schedule_interval,
    config::jsonb->>'drop_after' AS drop_after
FROM timescaledb_information.jobs j
JOIN timescaledb_information.job_stats js ON j.job_id = js.job_id
WHERE j.proc_name IN ('policy_retention', 'policy_compression', 'policy_refresh_continuous_aggregate')
ORDER BY hypertable_name, policy_type;
