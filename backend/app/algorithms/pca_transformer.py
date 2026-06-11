"""
PCA 降维转换器
针对小波包分解高维特征(64维)远超样本量(500)导致的过拟合问题
通过 PCA 降维至 10 维，保留 95%+ 方差，大幅降低特征空间维度
"""

import numpy as np
import joblib
import os
from typing import Optional, Tuple
from sklearn.decomposition import PCA
import logging

logger = logging.getLogger(__name__)


class PCATransformer:
    def __init__(self, n_components: int = 10, model_dir: str = "app/models"):
        self.n_components = n_components
        self.model_dir = model_dir
        self.pca_path = os.path.join(model_dir, "pca_transformer.pkl")
        self.pca: Optional[PCA] = None
        self._fitted = False
        self._load_or_init()

    def _load_or_init(self):
        if os.path.exists(self.pca_path):
            try:
                self.pca = joblib.load(self.pca_path)
                self.n_components = self.pca.n_components_
                self._fitted = True
                logger.info(
                    f"PCA loaded: {self.pca.n_features_in_} -> {self.n_components} components, "
                    f"explained variance: {sum(self.pca.explained_variance_ratio_):.4f}"
                )
            except Exception as e:
                logger.warning(f"PCA load failed, init fresh: {e}")
                self._init_pca()
        else:
            self._init_pca()

    def _init_pca(self):
        self.pca = PCA(
            n_components=self.n_components,
            svd_solver='full',
            random_state=42
        )
        self._fitted = False

    def fit(self, X: np.ndarray) -> 'PCATransformer':
        if X.shape[0] < self.n_components:
            actual = max(1, X.shape[0] - 1)
            logger.warning(
                f"Sample count {X.shape[0]} < n_components {self.n_components}, "
                f"reducing to {actual}"
            )
            self.pca.n_components = actual

        self.pca.fit(X)
        self._fitted = True

        total_var = sum(self.pca.explained_variance_ratio_)
        self.n_components = self.pca.n_components_
        logger.info(
            f"PCA fitted: {self.pca.n_features_in_} -> {self.n_components}, "
            f"explained variance ratio: {total_var:.4f}"
        )

        os.makedirs(self.model_dir, exist_ok=True)
        joblib.dump(self.pca, self.pca_path)
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if not self._fitted:
            logger.warning("PCA not fitted, returning original features")
            return X[:, :self.n_components] if X.shape[1] > self.n_components else X
        return self.pca.transform(X)

    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        self.fit(X)
        return self.transform(X)

    def get_explained_variance(self) -> float:
        if not self._fitted:
            return 0.0
        return float(sum(self.pca.explained_variance_ratio_))

    def get_component_importance(self, top_k: int = 5) -> dict:
        if not self._fitted:
            return {}
        return {
            f"PC{i+1}": float(self.pca.explained_variance_ratio_[i])
            for i in range(min(top_k, len(self.pca.explained_variance_ratio_)))
        }
