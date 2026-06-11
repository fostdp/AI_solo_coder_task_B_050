-- ============================================================
-- TimescaleDB v2 迁移脚本
-- 修复: 连续聚合查询慢, 因未设置时间分区
-- 方案:
--   1. 超表按周分区(chunk_time_interval = 1 week)
--   2. 时间-设备复合索引(覆盖高频查询模式)
--   3. 连续聚合刷新策略优化
-- ============================================================

-- Step 1: 重建电化学噪声超表(按周分区)
-- 需先删旧聚合, 迁移数据, 重建超表
DROP MATERIALIZED VIEW IF EXISTS mv_hourly_ecn_stats CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_hourly_menv_stats CASCADE;

-- 创建临时表保存数据
CREATE TABLE IF NOT EXISTS _ecn_backup AS SELECT * FROM electrochemical_noise_data;
CREATE TABLE IF NOT EXISTS _menv_backup AS SELECT * FROM microenvironment_data;

-- 删旧超表重建
DROP TABLE IF EXISTS electrochemical_noise_data CASCADE;
DROP TABLE IF EXISTS microenvironment_data CASCADE;

-- ============================================================
-- 电化学噪声超表 - 按周分区
-- ============================================================
CREATE TABLE electrochemical_noise_data (
    time TIMESTAMPTZ NOT NULL,
    sensor_id VARCHAR(32) NOT NULL,
    artifact_id VARCHAR(32) NOT NULL,
    voltage_noise DOUBLE PRECISION[],
    current_noise DOUBLE PRECISION[],
    sampling_rate INTEGER,
    noise_resistance DOUBLE PRECISION,
    pitting_index DOUBLE PRECISION,
    std_voltage DOUBLE PRECISION,
    std_current DOUBLE PRECISION,
    skewness_voltage DOUBLE PRECISION,
    kurtosis_voltage DOUBLE PRECISION,
    raw_data BYTEA
);

SELECT create_hypertable(
    'electrochemical_noise_data',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 week',
    partitioning_column => 'sensor_id',
    number_partitions => 4
);

-- 时间-设备复合索引: 覆盖最频繁的查询模式
-- 模式1: 按设备+时间范围查最新数据(仪表盘实时更新)
CREATE INDEX idx_ecn_sensor_time_weekly
    ON electrochemical_noise_data(sensor_id, time DESC);

-- 模式2: 按器物+时间范围查趋势(预测模型输入)
CREATE INDEX idx_ecn_artifact_time_weekly
    ON electrochemical_noise_data(artifact_id, time DESC);

-- 模式3: 按时间范围+Rn阈值筛选告警
CREATE INDEX idx_ecn_time_rn_alert
    ON electrochemical_noise_data(time DESC, noise_resistance)
    WHERE noise_resistance < 100;

-- 恢复数据
INSERT INTO electrochemical_noise_data SELECT * FROM _ecn_backup;
DROP TABLE IF EXISTS _ecn_backup;

-- 保留策略+压缩策略
SELECT add_retention_policy('electrochemical_noise_data', INTERVAL '2 years', if_not_exists => TRUE);
SELECT add_compression_policy('electrochemical_noise_data', INTERVAL '1 month', if_not_exists => TRUE);

-- 压缩段键优化: 按sensor_id分段压缩, 加速分区裁剪
ALTER TABLE electrochemical_noise_data SET (
    timescaledb.compress_segmentby = 'sensor_id,artifact_id',
    timescaledb.compress_orderby = 'time DESC'
);

COMMENT ON TABLE electrochemical_noise_data IS '电化学噪声时序数据表(v2: 按周分区+复合索引)';

-- ============================================================
-- 微环境超表 - 按周分区
-- ============================================================
CREATE TABLE microenvironment_data (
    time TIMESTAMPTZ NOT NULL,
    sensor_id VARCHAR(32) NOT NULL,
    artifact_id VARCHAR(32) NOT NULL,
    temperature DOUBLE PRECISION,
    humidity DOUBLE PRECISION,
    chloride_concentration DOUBLE PRECISION,
    sulfur_dioxide DOUBLE PRECISION,
    nitrogen_oxides DOUBLE PRECISION,
    formaldehyde DOUBLE PRECISION,
    voc_total DOUBLE PRECISION,
    illuminance DOUBLE PRECISION,
    uv_intensity DOUBLE PRECISION
);

SELECT create_hypertable(
    'microenvironment_data',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 week',
    partitioning_column => 'sensor_id',
    number_partitions => 4
);

-- 时间-设备复合索引
CREATE INDEX idx_menv_sensor_time_weekly
    ON microenvironment_data(sensor_id, time DESC);

CREATE INDEX idx_menv_artifact_time_weekly
    ON microenvironment_data(artifact_id, time DESC);

-- Cl⁻>3告警加速索引(部分索引)
CREATE INDEX idx_menv_time_cl_alert
    ON microenvironment_data(time DESC, chloride_concentration)
    WHERE chloride_concentration > 3.0;

-- 恢复数据
INSERT INTO microenvironment_data SELECT * FROM _menv_backup;
DROP TABLE IF EXISTS _menv_backup;

SELECT add_retention_policy('microenvironment_data', INTERVAL '3 years', if_not_exists => TRUE);
SELECT add_compression_policy('microenvironment_data', INTERVAL '2 weeks', if_not_exists => TRUE);

ALTER TABLE microenvironment_data SET (
    timescaledb.compress_segmentby = 'sensor_id,artifact_id',
    timescaledb.compress_orderby = 'time DESC'
);

COMMENT ON TABLE microenvironment_data IS '微环境监测时序数据表(v2: 按周分区+复合索引)';

-- ============================================================
-- 重建连续聚合 - 优化刷新策略
-- ============================================================
CREATE MATERIALIZED VIEW mv_hourly_ecn_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    sensor_id,
    artifact_id,
    avg(noise_resistance) AS avg_noise_resistance,
    min(noise_resistance) AS min_noise_resistance,
    max(noise_resistance) AS max_noise_resistance,
    avg(std_voltage) AS avg_std_voltage,
    avg(pitting_index) AS avg_pitting_index,
    count(*) AS sample_count
FROM electrochemical_noise_data
GROUP BY bucket, sensor_id, artifact_id
WITH NO DATA;

-- 缩短刷新间隔: 从3小时提前到1小时, 减少首次查询延迟
SELECT add_continuous_aggregate_policy('mv_hourly_ecn_stats',
    start_offset => INTERVAL '2 hours',
    end_offset => INTERVAL '30 minutes',
    schedule_interval => INTERVAL '30 minutes',
    if_not_exists => TRUE
);

CREATE MATERIALIZED VIEW mv_hourly_menv_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    sensor_id,
    artifact_id,
    avg(temperature) AS avg_temperature,
    max(temperature) AS max_temperature,
    min(temperature) AS min_temperature,
    avg(humidity) AS avg_humidity,
    max(humidity) AS max_humidity,
    avg(chloride_concentration) AS avg_chloride,
    max(chloride_concentration) AS max_chloride,
    avg(sulfur_dioxide) AS avg_so2,
    max(sulfur_dioxide) AS max_so2
FROM microenvironment_data
GROUP BY bucket, sensor_id, artifact_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('mv_hourly_menv_stats',
    start_offset => INTERVAL '2 hours',
    end_offset => INTERVAL '30 minutes',
    schedule_interval => INTERVAL '30 minutes',
    if_not_exists => TRUE
);

-- ============================================================
-- 新增: 日级聚合(低频查询场景, 进一步加速)
-- ============================================================
CREATE MATERIALIZED VIEW mv_daily_ecn_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    artifact_id,
    avg(noise_resistance) AS avg_noise_resistance,
    min(noise_resistance) AS min_noise_resistance,
    max(noise_resistance) AS max_noise_resistance,
    stddev(noise_resistance) AS std_noise_resistance,
    avg(pitting_index) AS avg_pitting_index,
    count(*) AS sample_count
FROM electrochemical_noise_data
GROUP BY bucket, artifact_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('mv_daily_ecn_stats',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE MATERIALIZED VIEW mv_daily_menv_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    artifact_id,
    avg(temperature) AS avg_temperature,
    max(temperature) AS max_temperature,
    min(temperature) AS min_temperature,
    avg(humidity) AS avg_humidity,
    max(chloride_concentration) AS max_chloride,
    avg(chloride_concentration) AS avg_chloride,
    max(sulfur_dioxide) AS max_so2,
    avg(sulfur_dioxide) AS avg_so2
FROM microenvironment_data
GROUP BY bucket, artifact_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('mv_daily_menv_stats',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- ============================================================
-- 外键约束恢复(因DROP CASCADE丢失)
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'ecn_sensor_id_fkey'
    ) THEN
        ALTER TABLE electrochemical_noise_data
            ADD CONSTRAINT ecn_sensor_id_fkey
            FOREIGN KEY (sensor_id) REFERENCES sensors(sensor_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'ecn_artifact_id_fkey'
    ) THEN
        ALTER TABLE electrochemical_noise_data
            ADD CONSTRAINT ecn_artifact_id_fkey
            FOREIGN KEY (artifact_id) REFERENCES bronze_artifacts(artifact_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'menv_sensor_id_fkey'
    ) THEN
        ALTER TABLE microenvironment_data
            ADD CONSTRAINT menv_sensor_id_fkey
            FOREIGN KEY (sensor_id) REFERENCES sensors(sensor_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'menv_artifact_id_fkey'
    ) THEN
        ALTER TABLE microenvironment_data
            ADD CONSTRAINT menv_artifact_id_fkey
            FOREIGN KEY (artifact_id) REFERENCES bronze_artifacts(artifact_id);
    END IF;
END $$;

-- 验证迁移
SELECT hypertable_name, num_chunks, chunk_interval
FROM timescaledb_information.hypertables
WHERE hypertable_name IN ('electrochemical_noise_data', 'microenvironment_data');
