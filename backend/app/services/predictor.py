"""
Predictor Service (微服务3)
职责：
  1. 从 Redis Stream:features 消费 PCA 降维后的特征
  2. XGBoost + RandomForest 融合模型推理
  3. 风险等级评估、风险区域识别
  4. 发布预测结果到 Redis Stream:predictions

数据流：Redis Stream:features -> RF+XGBoost融合 -> Redis Stream:predictions
"""

import asyncio
import json
import logging
import numpy as np
import os
import joblib
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass, field

from ..config import get_settings
from ..streams import RedisStreamManager, parse_stream_message

logger = logging.getLogger("predictor")
settings = get_settings()

try:
    from xgboost import XGBClassifier
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


@dataclass
class PredictionResult:
    artifact_id: str
    prediction_time: datetime
    target_window: str
    eruption_probability: float
    risk_level: int
    risk_zones: List[Dict]
    feature_contributions: Dict[str, float]
    model_version: str


class PredictorService:
    """粉状锈预测微服务"""

    def __init__(self, stream_manager: Optional[RedisStreamManager] = None):
        self.stream_mgr = stream_manager
        self._feature_stream = settings.REDIS_STREAM_FEATURES
        self._prediction_stream = settings.REDIS_STREAM_PREDICTIONS
        self._alert_stream = settings.REDIS_STREAM_ALERTS
        self._group = settings.REDIS_GROUP_PREDICTOR
        self._consumer_name = f"predictor_{id(self)}"

        self.rf_model = None
        self.xgb_model = None
        self.scaler = None
        self._model_version = "v2.0.0-pca-xgb"
        self._running = False

        self.artifact_last_prediction: Dict[str, float] = {}
        self._prediction_cooldown = 3600

        self._stats = {
            "processed": 0,
            "alerts_generated": 0,
            "failed": 0,
            "last_ts": None
        }

    def _load_models(self):
        model_dir = settings.MODEL_DIR
        os.makedirs(model_dir, exist_ok=True)

        rf_path = os.path.join(model_dir, "rust_rf_model.pkl")
        xgb_path = os.path.join(model_dir, "rust_xgb_model.pkl")
        scaler_path = os.path.join(model_dir, "rust_scaler.pkl")
        meta_path = os.path.join(model_dir, "rust_model_meta.pkl")

        try:
            if os.path.exists(rf_path):
                self.rf_model = joblib.load(rf_path)
                logger.info(f"Loaded RF model from {rf_path}")

            if os.path.exists(scaler_path):
                self.scaler = joblib.load(scaler_path)
                logger.info(f"Loaded scaler from {scaler_path}")

            if os.path.exists(meta_path):
                meta = joblib.load(meta_path)
                self._model_version = meta.get("version", self._model_version)

            if XGBOOST_AVAILABLE and os.path.exists(xgb_path):
                self.xgb_model = joblib.load(xgb_path)
                logger.info(f"Loaded XGBoost model from {xgb_path}")

            if not self.rf_model or not self.scaler:
                logger.warning("Model files not found, will init default models")
                self._init_default_models()
                self._synthesize_and_train()

        except Exception as e:
            logger.warning(f"Model load failed, initializing new: {e}")
            self._init_default_models()
            self._synthesize_and_train()

    def _init_default_models(self):
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn is required for predictor service")

        self.rf_model = RandomForestClassifier(
            n_estimators=500,
            max_depth=12,
            min_samples_split=8,
            min_samples_leaf=4,
            max_features="sqrt",
            class_weight="balanced_subsample",
            bootstrap=True,
            oob_score=True,
            random_state=42,
            n_jobs=-1
        )
        self.scaler = StandardScaler()

        if XGBOOST_AVAILABLE:
            self.xgb_model = XGBClassifier(
                n_estimators=300,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=1.0,
                reg_lambda=2.0,
                min_child_weight=5,
                scale_pos_weight=2.67,
                eval_metric='auc',
                random_state=42,
                n_jobs=-1,
                verbosity=0
            )

    def _synthesize_and_train(self):
        logger.info("Synthesizing training data and training models...")
        from ..algorithms.wavelet_features import WaveletPacketFeatureExtractor

        n_normal = 4000
        n_risk = 1500
        n_features = 72

        np.random.seed(42)
        X = np.random.randn(n_normal + n_risk, n_features) * 0.5
        y = np.zeros(n_normal + n_risk, dtype=int)
        y[n_normal:] = 1

        rn_idx = 30
        pi_idx = 31
        cl_idx = 36
        so2_idx = 37
        t_idx = 32
        h_idx = 33

        X[:n_normal, rn_idx] = np.random.uniform(2.3, 4.0, n_normal)
        X[:n_normal, pi_idx] = np.random.uniform(0.1, 1.5, n_normal)
        X[:n_normal, cl_idx] = np.random.uniform(0.1, 2.0, n_normal)
        X[:n_normal, so2_idx] = np.random.uniform(1.0, 20.0, n_normal)
        X[:n_normal, t_idx] = np.random.uniform(18.0, 25.0, n_normal)
        X[:n_normal, h_idx] = np.random.uniform(35.0, 55.0, n_normal)

        X[n_normal:, rn_idx] = np.random.uniform(0.5, 2.3, n_risk)
        X[n_normal:, pi_idx] = np.random.uniform(1.0, 5.0, n_risk)
        X[n_normal:, cl_idx] = np.random.uniform(1.5, 10.0, n_risk)
        X[n_normal:, so2_idx] = np.random.uniform(15.0, 80.0, n_risk)
        X[n_normal:, t_idx] = np.random.uniform(22.0, 32.0, n_risk)
        X[n_normal:, h_idx] = np.random.uniform(50.0, 80.0, n_risk)

        for i in range(32):
            if i < 16:
                X[n_normal:, i] += np.random.uniform(0.3, 1.2, n_risk)

        X[n_normal:, 70] = X[n_normal:, t_idx] * X[n_normal:, h_idx] / 100.0
        X[n_normal:, 71] = X[n_normal:, cl_idx] + X[n_normal:, so2_idx] * 0.1

        indices = np.random.permutation(n_normal + n_risk)
        X = X[indices]
        y = y[indices]

        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)

        from ..algorithms.pca_transformer import PCATransformer
        pca = PCATransformer(
            n_components=settings.PCA_COMPONENTS,
            model_dir=settings.MODEL_DIR
        )
        X_pca = pca.fit_transform(X_scaled)

        self.rf_model.fit(X_pca, y)

        if self.xgb_model is not None:
            self.xgb_model.fit(X_pca, y)
            logger.info("XGBoost model trained")

        model_dir = settings.MODEL_DIR
        joblib.dump(self.rf_model, os.path.join(model_dir, "rust_rf_model.pkl"))
        joblib.dump(self.scaler, os.path.join(model_dir, "rust_scaler.pkl"))
        if self.xgb_model:
            joblib.dump(self.xgb_model, os.path.join(model_dir, "rust_xgb_model.pkl"))
        joblib.dump({
            "version": self._model_version,
            "feature_names": [f"f_{i}" for i in range(n_features)],
            "trained_at": datetime.now().isoformat()
        }, os.path.join(model_dir, "rust_model_meta.pkl"))

        logger.info(f"Models trained and saved to {model_dir}")

    async def start(self):
        self._load_models()
        if self.stream_mgr:
            await self.stream_mgr.ensure_stream(self._feature_stream)
            await self.stream_mgr.ensure_stream(self._prediction_stream)
            await self.stream_mgr.ensure_stream(self._alert_stream)
            await self.stream_mgr.ensure_group(self._feature_stream, self._group)
        self._running = True
        logger.info("Predictor service started")

    async def stop(self):
        self._running = False
        logger.info("Predictor service stopped")

    async def run_loop(self):
        await self.start()
        while self._running:
            try:
                if not self.stream_mgr:
                    await asyncio.sleep(1)
                    continue

                messages = await self.stream_mgr.consume_group(
                    self._feature_stream,
                    self._group,
                    self._consumer_name,
                    count=5,
                    block_ms=2000
                )

                for stream_name, stream_msgs in messages:
                    for msg in stream_msgs:
                        try:
                            parsed = parse_stream_message(msg)
                            result = await self._process_message(parsed)
                            await self.stream_mgr.ack(
                                self._feature_stream, self._group, parsed["_id"]
                            )
                            if result:
                                self._stats["processed"] += 1
                                self._stats["last_ts"] = datetime.utcnow()
                        except Exception as e:
                            self._stats["failed"] += 1
                            logger.exception(f"Prediction failed: {e}")

                if not messages:
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.exception(f"Predictor loop error: {e}")
                await asyncio.sleep(1)

    async def _process_message(self, msg: Dict) -> Optional[PredictionResult]:
        artifact_id = msg.get("artifact_id", "")

        now = datetime.utcnow().timestamp()
        last = self.artifact_last_prediction.get(artifact_id, 0)
        if now - last < self._prediction_cooldown:
            logger.debug(
                f"Prediction cooldown for {artifact_id}, "
                f"next in {self._prediction_cooldown - (now - last):.0f}s"
            )
            return None

        self.artifact_last_prediction[artifact_id] = now

        try:
            pca_features_str = msg.get("pca_features")
            if isinstance(pca_features_str, str):
                pca_features = np.array(json.loads(pca_features_str), dtype=np.float64)
            else:
                pca_features = np.array(pca_features_str or [], dtype=np.float64)

            if len(pca_features.shape) == 1:
                pca_features = pca_features.reshape(1, -1)

            result = self._predict_internal(artifact_id, pca_features, msg)

            if result:
                await self._publish_prediction(result)

                if result.risk_level >= 3:
                    await self._publish_alert(result, msg)
                    self._stats["alerts_generated"] += 1

            return result

        except Exception as e:
            logger.exception(f"Prediction processing error for {artifact_id}: {e}")
            return None

    def _predict_internal(
        self, artifact_id: str, X_pca: np.ndarray, msg: Dict
    ) -> Optional[PredictionResult]:

        rf_prob = float(self.rf_model.predict_proba(X_pca)[0, 1])

        if self.xgb_model is not None:
            xgb_prob = float(self.xgb_model.predict_proba(X_pca)[0, 1])
            prob = (
                settings.ENSEMBLE_RF_WEIGHT * rf_prob +
                settings.ENSEMBLE_XGB_WEIGHT * xgb_prob
            )
        else:
            prob = rf_prob

        risk_level = self._calculate_risk_level(prob)
        contributions = self._get_feature_contributions(X_pca)
        risk_zones = self._identify_risk_zones(prob, msg)

        return PredictionResult(
            artifact_id=artifact_id,
            prediction_time=datetime.utcnow(),
            target_window="24h",
            eruption_probability=float(prob),
            risk_level=risk_level,
            risk_zones=risk_zones,
            feature_contributions=contributions,
            model_version=self._model_version
        )

    def _calculate_risk_level(self, probability: float) -> int:
        thresholds = {
            "24h": 0.35, "72h": 0.50, "168h": 0.65
        }
        t = thresholds.get("24h", 0.35)
        if probability < t * 0.5:
            return 1
        elif probability < t * 0.8:
            return 2
        elif probability < t:
            return 3
        else:
            return 4

    def _get_feature_contributions(self, X_pca: np.ndarray) -> Dict[str, float]:
        rf_imp = self.rf_model.feature_importances_
        if self.xgb_model is not None:
            xgb_imp = self.xgb_model.feature_importances_
            importances = (
                settings.ENSEMBLE_RF_WEIGHT * rf_imp +
                settings.ENSEMBLE_XGB_WEIGHT * xgb_imp
            )
        else:
            importances = rf_imp

        contrib = {}
        for i in range(min(len(importances), 10)):
            contrib[f"PC{i+1}"] = float(importances[i])
        return contrib

    def _identify_risk_zones(self, prob: float, msg: Dict) -> List[Dict]:
        zones = []
        n_zones = 1 if prob < 0.3 else (3 if prob < 0.6 else 6)

        np.random.seed(int(prob * 10000) % 4294967295)
        for i in range(n_zones):
            severity = min(prob + np.random.uniform(-0.1, 0.1), 1.0)
            zones.append({
                "zone_id": f"Z{i+1:02d}",
                "center": {
                    "x": float(np.random.uniform(-0.4, 0.4)),
                    "y": float(np.random.uniform(-0.2, 0.3)),
                    "z": float(np.random.uniform(-0.1, 0.1))
                },
                "radius": float(0.02 + severity * 0.08),
                "severity": float(severity),
                "has_eruption": bool(severity > 0.75)
            })
        return zones

    async def _publish_prediction(self, result: PredictionResult):
        if not self.stream_mgr:
            return

        data = {
            "artifact_id": result.artifact_id,
            "prediction_time": result.prediction_time.isoformat(),
            "target_window": result.target_window,
            "eruption_probability": result.eruption_probability,
            "risk_level": result.risk_level,
            "risk_zones": json.dumps(result.risk_zones),
            "feature_contributions": json.dumps(result.feature_contributions),
            "model_version": result.model_version
        }

        msg_id = await self.stream_mgr.publish(self._prediction_stream, data)
        logger.info(
            f"Prediction for {result.artifact_id}: "
            f"P={result.eruption_probability:.3f}, risk={result.risk_level} ({msg_id})"
        )

    async def _publish_alert(self, result: PredictionResult, msg: Dict):
        if not self.stream_mgr:
            return

        alert_data = {
            "alert_type": "rust_prediction",
            "artifact_id": result.artifact_id,
            "sensor_id": msg.get("sensor_id", ""),
            "severity": "critical" if result.risk_level >= 4 else "warning",
            "threshold_value": 0.35,
            "actual_value": result.eruption_probability,
            "unit": "probability",
            "risk_level": result.risk_level,
            "message": f"粉状锈爆发风险预警: P={result.eruption_probability:.2%}",
            "alert_time": datetime.utcnow().isoformat()
        }

        msg_id = await self.stream_mgr.publish(self._alert_stream, alert_data)
        logger.warning(
            f"ALERT published for {result.artifact_id}: "
            f"risk_level={result.risk_level} ({msg_id})"
        )

    def predict_sync(
        self,
        artifact_id: str,
        wavelet_features: Dict,
        microenv_data: Dict
    ) -> Optional[PredictionResult]:
        """同步预测接口（用于测试）"""
        self._load_models()

        feat_values = []
        statistical = wavelet_features.get("statistical_features", {})
        for k in sorted(statistical.keys()):
            feat_values.append(float(statistical[k]))

        band_ratios = wavelet_features.get("band_energy_ratios", {})
        for k in sorted(band_ratios.keys()):
            feat_values.append(float(band_ratios[k]))

        feat_values.append(float(wavelet_features.get("wavelet_entropy", 0.0)))
        feat_values.append(np.log10(float(wavelet_features.get("noise_resistance", 1.0)) + 1e-6))
        feat_values.append(float(wavelet_features.get("pitting_index", 0.0)))

        for key in ["temperature", "humidity", "chloride_concentration",
                     "sulfur_dioxide", "nitrogen_oxides", "formaldehyde"]:
            feat_values.append(float(microenv_data.get(key, 0.0)))

        feat_values.append(float(microenv_data.get("temperature", 20.0)) *
                           float(microenv_data.get("humidity", 50.0)) / 100.0)
        feat_values.append(float(microenv_data.get("chloride_concentration", 0.0)) +
                           float(microenv_data.get("sulfur_dioxide", 0.0)) * 0.1)

        X = np.array(feat_values, dtype=np.float64).reshape(1, -1)

        if X.shape[1] != len(self.scaler.mean_):
            if X.shape[1] < len(self.scaler.mean_):
                pad = np.zeros((1, len(self.scaler.mean_) - X.shape[1]))
                X = np.hstack([X, pad])
            else:
                X = X[:, :len(self.scaler.mean_)]

        X_scaled = self.scaler.transform(X)

        from ..algorithms.pca_transformer import PCATransformer
        pca = PCATransformer(
            n_components=settings.PCA_COMPONENTS,
            model_dir=settings.MODEL_DIR
        )
        X_pca = pca.transform(X_scaled)

        return self._predict_internal(artifact_id, X_pca, {})

    def get_stats(self) -> Dict:
        return {
            **self._stats,
            "is_running": self._running,
            "model_version": self._model_version,
            "xgboost_available": self.xgb_model is not None,
            "n_pca_components": settings.PCA_COMPONENTS
        }
