"""
微服务模块
通过 Redis Stream 解耦的 5 个微服务:
  1. mqtt_ingest    - MQTT 数据接入
  2. feature_extractor - 小波包特征提取 + PCA 降维
  3. predictor      - XGBoost + RF 融合预测
  4. optimizer      - CFD 喷涂优化
  5. alert_ws       - 告警推送 + WebSocket
"""

from .mqtt_ingest import MQTTIngestService
from .feature_extractor import FeatureExtractorService
from .predictor import PredictorService
from .optimizer import SprayOptimizerService
from .alert_ws import AlertWSService, WebSocketManager, AlertDispatcher

__all__ = [
    "MQTTIngestService",
    "FeatureExtractorService",
    "PredictorService",
    "SprayOptimizerService",
    "AlertWSService",
    "WebSocketManager",
    "AlertDispatcher",
]
