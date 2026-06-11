-- ============================================================
-- 古代青铜器粉状锈爆发预警与缓蚀剂智能喷涂系统
-- TimescaleDB 数据库初始化脚本
-- ============================================================

-- 创建数据库扩展
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS postgis CASCADE;
CREATE EXTENSION IF NOT EXISTS pg_trgm CASCADE;

-- ============================================================
-- 业务表：青铜器藏品信息
-- ============================================================
CREATE TABLE IF NOT EXISTS bronze_artifacts (
    artifact_id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    dynasty VARCHAR(32) NOT NULL,
    description TEXT,
    location VARCHAR(64),
    showcase_id VARCHAR(32),
    position_3d JSONB,
    model_path VARCHAR(256),
    status SMALLINT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bronze_artifacts_dynasty ON bronze_artifacts(dynasty);
CREATE INDEX IF NOT EXISTS idx_bronze_artifacts_status ON bronze_artifacts(status);
CREATE INDEX IF NOT EXISTS idx_bronze_artifacts_showcase ON bronze_artifacts(showcase_id);

COMMENT ON TABLE bronze_artifacts IS '青铜器藏品基础信息表';
COMMENT ON COLUMN bronze_artifacts.artifact_id IS '藏品唯一编号';
COMMENT ON COLUMN bronze_artifacts.name IS '藏品名称';
COMMENT ON COLUMN bronze_artifacts.dynasty IS '朝代（商、西周、东周等）';
COMMENT ON COLUMN bronze_artifacts.location IS '陈列位置';
COMMENT ON COLUMN bronze_artifacts.showcase_id IS '展柜编号';
COMMENT ON COLUMN bronze_artifacts.position_3d IS '3D模型位置信息 {x, y, z}';
COMMENT ON COLUMN bronze_artifacts.model_path IS '3D模型文件路径';
COMMENT ON COLUMN bronze_artifacts.status IS '状态:1-正常,2-预警,3-爆发锈';

-- ============================================================
-- 业务表：传感器设备信息
-- ============================================================
CREATE TABLE IF NOT EXISTS sensors (
    sensor_id VARCHAR(32) PRIMARY KEY,
    sensor_type VARCHAR(32) NOT NULL,
    artifact_id VARCHAR(32) REFERENCES bronze_artifacts(artifact_id),
    name VARCHAR(128),
    install_position VARCHAR(128),
    position_offset JSONB,
    status SMALLINT DEFAULT 1,
    calibration_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_maintenance TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sensors_type ON sensors(sensor_type);
CREATE INDEX IF NOT EXISTS idx_sensors_artifact ON sensors(artifact_id);
CREATE INDEX IF NOT EXISTS idx_sensors_status ON sensors(status);

COMMENT ON TABLE sensors IS '传感器设备信息表';
COMMENT ON COLUMN sensors.sensor_id IS '传感器唯一编号';
COMMENT ON COLUMN sensors.sensor_type IS '类型:electrochemical,microenv,microscope';
COMMENT ON COLUMN sensors.artifact_id IS '关联的青铜器ID';
COMMENT ON COLUMN sensors.install_position IS '安装位置描述';
COMMENT ON COLUMN sensors.position_offset IS '相对青铜器3D模型的偏移位置';

-- ============================================================
-- 时序超表：电化学噪声传感器数据
-- ============================================================
CREATE TABLE IF NOT EXISTS electrochemical_noise_data (
    time TIMESTAMPTZ NOT NULL,
    sensor_id VARCHAR(32) NOT NULL REFERENCES sensors(sensor_id),
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id),
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
    chunk_time_interval => INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS idx_ecn_sensor_time ON electrochemical_noise_data(sensor_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_ecn_artifact_time ON electrochemical_noise_data(artifact_id, time DESC);

SELECT add_retention_policy('electrochemical_noise_data', INTERVAL '2 years', if_not_exists => TRUE);
SELECT add_compression_policy('electrochemical_noise_data', INTERVAL '1 month', if_not_exists => TRUE);

COMMENT ON TABLE electrochemical_noise_data IS '电化学噪声时序数据表';
COMMENT ON COLUMN electrochemical_noise_data.noise_resistance IS '噪声电阻 Rn (Ω·cm²)，核心预警指标';
COMMENT ON COLUMN electrochemical_noise_data.pitting_index IS '点蚀指数';

-- ============================================================
-- 时序超表：微环境传感器数据
-- ============================================================
CREATE TABLE IF NOT EXISTS microenvironment_data (
    time TIMESTAMPTZ NOT NULL,
    sensor_id VARCHAR(32) NOT NULL REFERENCES sensors(sensor_id),
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id),
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
    chunk_time_interval => INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS idx_menv_sensor_time ON microenvironment_data(sensor_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_menv_artifact_time ON microenvironment_data(artifact_id, time DESC);

SELECT add_retention_policy('microenvironment_data', INTERVAL '3 years', if_not_exists => TRUE);
SELECT add_compression_policy('microenvironment_data', INTERVAL '2 weeks', if_not_exists => TRUE);

COMMENT ON TABLE microenvironment_data IS '微环境监测时序数据表';
COMMENT ON COLUMN microenvironment_data.chloride_concentration IS 'Cl⁻浓度 (μg/m³)';
COMMENT ON COLUMN microenvironment_data.sulfur_dioxide IS 'SO₂浓度 (μg/m³)';

-- ============================================================
-- 时序超表：视频显微镜图像数据
-- ============================================================
CREATE TABLE IF NOT EXISTS microscope_images (
    time TIMESTAMPTZ NOT NULL,
    sensor_id VARCHAR(32) NOT NULL REFERENCES sensors(sensor_id),
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id),
    image_path VARCHAR(512),
    image_hash VARCHAR(64),
    resolution VARCHAR(32),
    magnification DOUBLE PRECISION,
    rust_detection JSONB,
    surface_features JSONB,
    has_rust_eruption BOOLEAN DEFAULT FALSE,
    confidence_score DOUBLE PRECISION
);

SELECT create_hypertable(
    'microscope_images',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 week'
);

CREATE INDEX IF NOT EXISTS idx_micro_sensor_time ON microscope_images(sensor_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_micro_artifact_time ON microscope_images(artifact_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_micro_rust_flag ON microscope_images(has_rust_eruption);

COMMENT ON TABLE microscope_images IS '视频显微镜图像时序表';
COMMENT ON COLUMN microscope_images.rust_detection IS '锈点检测结果JSON，含坐标和严重度';

-- ============================================================
-- 业务表：粉状锈爆发预测结果
-- ============================================================
CREATE TABLE IF NOT EXISTS rust_predictions (
    prediction_id BIGSERIAL PRIMARY KEY,
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id),
    model_version VARCHAR(32),
    prediction_time TIMESTAMPTZ NOT NULL,
    target_window VARCHAR(16),
    eruption_probability DOUBLE PRECISION NOT NULL,
    risk_level SMALLINT NOT NULL,
    risk_zone JSONB,
    feature_contributions JSONB,
    model_input JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pred_artifact_time ON rust_predictions(artifact_id, prediction_time DESC);
CREATE INDEX IF NOT EXISTS idx_pred_risk_level ON rust_predictions(risk_level);

SELECT create_hypertable(
    'rust_predictions',
    'prediction_time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 month'
);

COMMENT ON TABLE rust_predictions IS '粉状锈爆发预测结果表';
COMMENT ON COLUMN rust_predictions.risk_level IS '风险等级:1-低,2-中,3-高,4-极高';
COMMENT ON COLUMN rust_predictions.risk_zone IS '风险区域在3D模型上的坐标集合';

-- ============================================================
-- 业务表：告警记录
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
    alert_id BIGSERIAL PRIMARY KEY,
    artifact_id VARCHAR(32) REFERENCES bronze_artifacts(artifact_id),
    sensor_id VARCHAR(32) REFERENCES sensors(sensor_id),
    alert_type VARCHAR(32) NOT NULL,
    severity SMALLINT NOT NULL,
    threshold_value DOUBLE PRECISION,
    actual_value DOUBLE PRECISION,
    message TEXT,
    alert_time TIMESTAMPTZ NOT NULL,
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by VARCHAR(64),
    acknowledged_at TIMESTAMPTZ,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMPTZ,
    wecom_sent BOOLEAN DEFAULT FALSE,
    sms_sent BOOLEAN DEFAULT FALSE,
    push_channels JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_artifact_time ON alerts(artifact_id, alert_time DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON alerts(resolved);
CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged ON alerts(acknowledged);

SELECT create_hypertable(
    'alerts',
    'alert_time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 month'
);

COMMENT ON TABLE alerts IS '告警记录表';
COMMENT ON COLUMN alerts.alert_type IS '告警类型:Rn_low,Cl_high,SO2_high,Temp_high,Humidity_high,Rust_prediction,Rust_eruption';
COMMENT ON COLUMN alerts.severity IS '严重级别:1-提示,2-警告,3-严重,4-紧急';

-- ============================================================
-- 业务表：缓蚀剂喷涂任务
-- ============================================================
CREATE TABLE IF NOT EXISTS inhibitor_spray_tasks (
    task_id BIGSERIAL PRIMARY KEY,
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id),
    alert_id BIGINT REFERENCES alerts(alert_id),
    task_type VARCHAR(32),
    inhibitor_type VARCHAR(16) NOT NULL,
    concentration DOUBLE PRECISION,
    total_volume DOUBLE PRECISION,
    target_zones JSONB,
    spray_plan JSONB,
    coverage_estimate DOUBLE PRECISION,
    status SMALLINT DEFAULT 0,
    scheduled_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    actual_volume DOUBLE PRECISION,
    actual_coverage DOUBLE PRECISION,
    operator VARCHAR(64),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_spray_artifact_time ON inhibitor_spray_tasks(artifact_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_spray_status ON inhibitor_spray_tasks(status);

COMMENT ON TABLE inhibitor_spray_tasks IS '缓蚀剂喷涂任务表';
COMMENT ON COLUMN inhibitor_spray_tasks.inhibitor_type IS '缓蚀剂类型:BTA,AMT,MBO';
COMMENT ON COLUMN inhibitor_spray_tasks.status IS '任务状态:0-待执行,1-执行中,2-已完成,3-已取消';

-- ============================================================
-- 时序超表：喷涂执行日志
-- ============================================================
CREATE TABLE IF NOT EXISTS spray_execution_logs (
    time TIMESTAMPTZ NOT NULL,
    task_id BIGINT NOT NULL REFERENCES inhibitor_spray_tasks(task_id),
    nozzle_position JSONB,
    spray_pressure DOUBLE PRECISION,
    flow_rate DOUBLE PRECISION,
    current_zone VARCHAR(32),
    droplet_size DOUBLE PRECISION,
    coverage_progress DOUBLE PRECISION
);

SELECT create_hypertable(
    'spray_execution_logs',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS idx_spray_log_task_time ON spray_execution_logs(task_id, time DESC);

-- ============================================================
-- 视图：青铜器实时状态汇总
-- ============================================================
CREATE OR REPLACE VIEW v_artifact_realtime_status AS
SELECT
    a.artifact_id,
    a.name,
    a.dynasty,
    a.status,
    a.showcase_id,
    latest_ecn.time AS ecn_update_time,
    latest_ecn.noise_resistance,
    latest_menv.time AS menv_update_time,
    latest_menv.temperature,
    latest_menv.humidity,
    latest_menv.chloride_concentration,
    latest_menv.sulfur_dioxide,
    latest_pred.eruption_probability,
    latest_pred.risk_level
FROM bronze_artifacts a
LEFT JOIN LATERAL (
    SELECT time, noise_resistance
    FROM electrochemical_noise_data e
    WHERE e.artifact_id = a.artifact_id
    ORDER BY time DESC
    LIMIT 1
) latest_ecn ON TRUE
LEFT JOIN LATERAL (
    SELECT time, temperature, humidity, chloride_concentration, sulfur_dioxide
    FROM microenvironment_data m
    WHERE m.artifact_id = a.artifact_id
    ORDER BY time DESC
    LIMIT 1
) latest_menv ON TRUE
LEFT JOIN LATERAL (
    SELECT eruption_probability, risk_level
    FROM rust_predictions p
    WHERE p.artifact_id = a.artifact_id
    ORDER BY prediction_time DESC
    LIMIT 1
) latest_pred ON TRUE;

-- ============================================================
-- 物化视图：24小时统计聚合（每小时）
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hourly_ecn_stats
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

SELECT add_continuous_aggregate_policy('mv_hourly_ecn_stats',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hourly_menv_stats
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
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

-- ============================================================
-- 初始化模拟数据：青铜器藏品（200件商周青铜器）
-- ============================================================
INSERT INTO bronze_artifacts (artifact_id, name, dynasty, description, location, showcase_id, position_3d, status) VALUES
('BRZ00001', '司母戊鼎复制品', '商', '商代晚期青铜重器，祭祀用鼎', '一号展厅A区', 'SC-A01', '{"x": 0, "y": 0, "z": 0}', 1),
('BRZ00002', '四羊方尊', '商', '商代青铜方尊，四羊饰', '一号展厅A区', 'SC-A01', '{"x": 2.5, "y": 0, "z": 0}', 1),
('BRZ00003', '饕餮纹方鼎', '商', '商代早期方鼎', '一号展厅A区', 'SC-A02', '{"x": 5, "y": 0, "z": 0}', 1),
('BRZ00004', '连珠纹斝', '商', '商代早期酒器', '一号展厅B区', 'SC-B01', '{"x": 0, "y": 0, "z": 3}', 1),
('BRZ00005', '兽面纹爵', '商', '商代中期酒器', '一号展厅B区', 'SC-B01', '{"x": 2, "y": 0, "z": 3}', 1),
('BRZ00006', '大克鼎', '西周', '西周晚期重器', '二号展厅A区', 'SC-C01', '{"x": 0, "y": 0, "z": -3}', 1),
('BRZ00007', '毛公鼎', '西周', '西周晚期铭文重器', '二号展厅A区', 'SC-C01', '{"x": 2.5, "y": 0, "z": -3}', 1),
('BRZ00008', '散氏盘', '西周', '西周夨人盘', '二号展厅B区', 'SC-C02', '{"x": 5, "y": 0, "z": -3}', 1),
('BRZ00009', '虢季子白盘', '西周', '西周宣王时期青铜器', '二号展厅B区', 'SC-D01', '{"x": 0, "y": 0, "z": -6}', 1),
('BRZ00010', '何尊', '西周', '西周早期成王时期', '二号展厅C区', 'SC-D02', '{"x": 3, "y": 0, "z": -6}', 1)
ON CONFLICT DO NOTHING;

-- 批量插入剩余190件青铜器
DO $$
DECLARE
    i INT;
    dyn VARCHAR[] := ARRAY['商', '西周', '东周', '春秋', '战国'];
    type_prefix VARCHAR[] := ARRAY['鼎', '尊', '爵', '斝', '觚', '觯', '卣', '壶', '盘', '匜', '钟', '镈', '戈', '剑', '钺'];
    showcase VARCHAR;
BEGIN
    FOR i IN 11..200 LOOP
        showcase := 'SC-' || CHAR(65 + (i % 8)) || LPAD(((i % 20) + 1)::TEXT, 2, '0');
        INSERT INTO bronze_artifacts (artifact_id, name, dynasty, description, location, showcase_id, position_3d, status)
        VALUES (
            'BRZ' || LPAD(i::TEXT, 5, '0'),
            type_prefix[(i % 15) + 1] || LPAD(i::TEXT, 3, '0'),
            dyn[(i % 5) + 1],
            dyn[(i % 5) + 1] || '时期青铜器' || i,
            CASE WHEN i % 4 = 0 THEN '一号展厅' WHEN i % 4 = 1 THEN '二号展厅' WHEN i % 4 = 2 THEN '三号展厅' ELSE '四号展厅' END,
            showcase,
            jsonb_build_object('x', (i % 10) * 1.5, 'y', 0, 'z', FLOOR(i / 10) * 2 - 6),
            1
        ) ON CONFLICT DO NOTHING;
    END LOOP;
END $$;

-- ============================================================
-- 初始化：30台电化学噪声传感器
-- ============================================================
INSERT INTO sensors (sensor_id, sensor_type, artifact_id, name, install_position, position_offset)
SELECT
    'ECN' || LPAD(i::TEXT, 3, '0'),
    'electrochemical',
    'BRZ' || LPAD(CASE WHEN i <= 10 THEN i ELSE ((i * 7) % 200) + 1 END::TEXT, 5, '0'),
    '电化学噪声传感器#' || i,
    '器身表面探头',
    jsonb_build_object('dx', (i % 5 - 2) * 0.1, 'dy', (i % 3 - 1) * 0.05, 'dz', 0.02)
FROM generate_series(1, 30) i
ON CONFLICT DO NOTHING;

-- ============================================================
-- 初始化：50台微环境传感器（温湿度、Cl⁻、SO₂）
-- ============================================================
INSERT INTO sensors (sensor_id, sensor_type, artifact_id, name, install_position, position_offset)
SELECT
    'ENV' || LPAD(i::TEXT, 3, '0'),
    'microenv',
    'BRZ' || LPAD(((i * 4) % 200) + 1::TEXT, 5, '0'),
    '微环境传感器#' || i,
    CASE WHEN i % 3 = 0 THEN '展柜顶部' WHEN i % 3 = 1 THEN '展柜中部' ELSE '展柜底部' END,
    jsonb_build_object('dx', 0.3, 'dy', CASE WHEN i % 3 = 0 THEN 0.5 WHEN i % 3 = 1 THEN 0 WHEN i % 3 = 2 THEN -0.4 END, 'dz', 0.1)
FROM generate_series(1, 50) i
ON CONFLICT DO NOTHING;

-- ============================================================
-- 初始化：20台视频显微镜
-- ============================================================
INSERT INTO sensors (sensor_id, sensor_type, artifact_id, name, install_position, position_offset)
SELECT
    'MIC' || LPAD(i::TEXT, 3, '0'),
    'microscope',
    'BRZ' || LPAD(((i * 10) % 200) + 1::TEXT, 5, '0'),
    '视频显微镜#' || i,
    '可移动观测位#' || i,
    jsonb_build_object('dx', (i % 4 - 2) * 0.15, 'dy', 0.2, 'dz', 0.3)
FROM generate_series(1, 20) i
ON CONFLICT DO NOTHING;

-- ============================================================
-- 新增模块：拉曼光谱识别
-- ============================================================
CREATE TABLE IF NOT EXISTS raman_spectra (
    spectrum_id SERIAL PRIMARY KEY,
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id) ON DELETE CASCADE,
    sensor_id VARCHAR(32) REFERENCES sensors(sensor_id),
    wavenumbers REAL[] NOT NULL,
    intensities REAL[] NOT NULL,
    sampling_points INTEGER NOT NULL,
    exposure_time_ms INTEGER,
    laser_wavelength_nm REAL DEFAULT 532.0,
    measurement_time TIMESTAMPTZ NOT NULL,
    position_3d JSONB,
    raw_metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
SELECT create_hypertable('raman_spectra', 'measurement_time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS raman_identification_results (
    result_id SERIAL PRIMARY KEY,
    spectrum_id INTEGER REFERENCES raman_spectra(spectrum_id) ON DELETE CASCADE,
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id) ON DELETE CASCADE,
    product_type VARCHAR(32) NOT NULL,
    product_name VARCHAR(64),
    confidence REAL NOT NULL,
    probabilities JSONB,
    peak_positions REAL[],
    display_color VARCHAR(16),
    position_3d JSONB,
    identification_time TIMESTAMPTZ NOT NULL,
    model_info JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
SELECT create_hypertable('raman_identification_results', 'identification_time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_raman_result_artifact ON raman_identification_results(artifact_id);

-- ============================================================
-- 新增模块：缓蚀剂残留寿命预测
-- ============================================================
CREATE TABLE IF NOT EXISTS inhibitor_spray_records (
    record_id SERIAL PRIMARY KEY,
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id) ON DELETE CASCADE,
    inhibitor_type VARCHAR(16) NOT NULL DEFAULT 'BTA',
    spray_date TIMESTAMPTZ NOT NULL,
    technician VARCHAR(64),
    initial_coverage REAL DEFAULT 0.95,
    total_volume_ml REAL,
    method VARCHAR(32) DEFAULT '雾化喷涂',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_spray_record_artifact ON inhibitor_spray_records(artifact_id, spray_date DESC);

CREATE TABLE IF NOT EXISTS inhibitor_lifetime_predictions (
    prediction_id SERIAL PRIMARY KEY,
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id) ON DELETE CASCADE,
    inhibitor_type VARCHAR(16) NOT NULL DEFAULT 'BTA',
    remaining_days REAL NOT NULL,
    effectiveness REAL NOT NULL,
    degradation_rate REAL,
    status VARCHAR(32) NOT NULL,
    warning_level INTEGER DEFAULT 0,
    need_respray BOOLEAN DEFAULT FALSE,
    average_temp_7d REAL,
    average_rh_7d REAL,
    last_spray_date TIMESTAMPTZ,
    prediction_time TIMESTAMPTZ NOT NULL,
    detail JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
SELECT create_hypertable('inhibitor_lifetime_predictions', 'prediction_time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_life_pred_artifact ON inhibitor_lifetime_predictions(artifact_id, prediction_time DESC);

-- ============================================================
-- 新增模块：文物脆弱性综合评分
-- ============================================================
CREATE TABLE IF NOT EXISTS vulnerability_scores (
    score_id SERIAL PRIMARY KEY,
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id) ON DELETE CASCADE,
    total_score REAL NOT NULL,
    level VARCHAR(32) NOT NULL,
    level_color VARCHAR(16),
    sub_scores JSONB,
    criterion_contributions JSONB,
    consistency_ratio REAL,
    hall_x REAL,
    hall_y REAL,
    recommendations TEXT[],
    calculation_time TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
SELECT create_hypertable('vulnerability_scores', 'calculation_time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_vuln_score_artifact ON vulnerability_scores(artifact_id, calculation_time DESC);

CREATE TABLE IF NOT EXISTS artifact_ct_structure_data (
    ct_id SERIAL PRIMARY KEY,
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id) ON DELETE CASCADE,
    wall_thickness_uniformity REAL,
    crack_index REAL,
    deformation_degree REAL,
    wall_thickness_distribution REAL[],
    scan_date TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS artifact_repair_history (
    repair_id SERIAL PRIMARY KEY,
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id) ON DELETE CASCADE,
    repair_date TIMESTAMPTZ NOT NULL,
    repair_type VARCHAR(64),
    materials_used TEXT[],
    technician VARCHAR(64),
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_repair_hist_artifact ON artifact_repair_history(artifact_id, repair_date DESC);

-- ============================================================
-- 新增模块：智能喷涂路径动态规划
-- ============================================================
CREATE TABLE IF NOT EXISTS spray_rust_hotspots (
    hotspot_id SERIAL PRIMARY KEY,
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id) ON DELETE CASCADE,
    hotspot_code VARCHAR(64) NOT NULL,
    position_3d JSONB NOT NULL,
    surface_normal JSONB,
    severity REAL NOT NULL,
    area_cm2 REAL,
    required_coverage REAL DEFAULT 0.95,
    detected_time TIMESTAMPTZ NOT NULL,
    source VARCHAR(32),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
SELECT create_hypertable('spray_rust_hotspots', 'detected_time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS ga_spray_plans (
    plan_id SERIAL PRIMARY KEY,
    artifact_id VARCHAR(32) NOT NULL REFERENCES bronze_artifacts(artifact_id) ON DELETE CASCADE,
    waypoints JSONB NOT NULL,
    total_distance_m REAL,
    total_time_s REAL,
    estimated_weighted_coverage REAL,
    uniformity_index REAL,
    total_volume_ml REAL,
    hotspot_coverage JSONB,
    generation INTEGER,
    best_fitness REAL,
    planning_time_ms INTEGER,
    robot_config JSONB,
    plan_time TIMESTAMPTZ NOT NULL,
    status VARCHAR(32) DEFAULT 'planned',
    executed_time TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
SELECT create_hypertable('ga_spray_plans', 'plan_time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_ga_plan_artifact ON ga_spray_plans(artifact_id, plan_time DESC);

-- ============================================================
-- 新增视图：文物综合状态
-- ============================================================
CREATE OR REPLACE VIEW v_artifact_comprehensive_status AS
SELECT
    a.artifact_id,
    a.name,
    a.dynasty,
    a.status,
    COALESCE(rp.eruption_probability, 0) AS rust_probability,
    COALESCE(rp.risk_level, 1) AS rust_risk_level,
    COALESCE(vs.total_score, 0) AS vulnerability_score,
    COALESCE(vs.level, 'excellent') AS vulnerability_level,
    COALESCE(lp.remaining_days, 999) AS inhibitor_remaining_days,
    COALESCE(lp.status, 'excellent') AS inhibitor_status,
    COALESCE(lp.need_respray, FALSE) AS need_respray,
    ri.product_type AS latest_rust_product,
    ri.display_color AS rust_product_color
FROM bronze_artifacts a
LEFT JOIN (
    SELECT DISTINCT ON (artifact_id) artifact_id, eruption_probability, risk_level
    FROM rust_predictions
    ORDER BY artifact_id, prediction_time DESC
) rp ON a.artifact_id = rp.artifact_id
LEFT JOIN (
    SELECT DISTINCT ON (artifact_id) artifact_id, total_score, level
    FROM vulnerability_scores
    ORDER BY artifact_id, calculation_time DESC
) vs ON a.artifact_id = vs.artifact_id
LEFT JOIN (
    SELECT DISTINCT ON (artifact_id) artifact_id, remaining_days, status, need_respray
    FROM inhibitor_lifetime_predictions
    ORDER BY artifact_id, prediction_time DESC
) lp ON a.artifact_id = lp.artifact_id
LEFT JOIN (
    SELECT DISTINCT ON (artifact_id) artifact_id, product_type, display_color
    FROM raman_identification_results
    ORDER BY artifact_id, identification_time DESC
) ri ON a.artifact_id = ri.artifact_id;

-- ============================================================
-- 初始化：拉曼光谱传感器
-- ============================================================
INSERT INTO sensors (sensor_id, sensor_type, artifact_id, name, install_position, position_offset)
SELECT
    'RAM' || LPAD(i::TEXT, 3, '0'),
    'raman',
    'BRZ' || LPAD(((i * 13) % 200) + 1::TEXT, 5, '0'),
    '拉曼光谱仪#' || i,
    '显微观测位#' || i,
    jsonb_build_object('dx', (i % 3 - 1) * 0.1, 'dy', 0.1, 'dz', 0.4)
FROM generate_series(1, 15) i
ON CONFLICT DO NOTHING;
