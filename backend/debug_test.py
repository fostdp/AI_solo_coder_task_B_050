import sys
import os
sys.path.insert(0, os.path.dirname(__file__) + "/..")

print("Step 1: Import config...")
from app.config import get_settings
settings = get_settings()
print(f"  OK - PCA_COMPONENTS={settings.PCA_COMPONENTS}")

print("Step 2: Import wavelet_features...")
from app.algorithms.wavelet_features import WaveletPacketFeatureExtractor
print("  OK")

print("Step 3: Import pca_transformer...")
from app.algorithms.pca_transformer import PCATransformer
print("  OK")

print("Step 4: Import FeatureExtractorService...")
from app.services.feature_extractor import FeatureExtractorService
print("  OK")

print("Step 5: Create service...")
service = FeatureExtractorService(stream_manager=None)
print("  OK")

print("Step 6: Init components...")
service._init_components()
print("  OK")

print("Step 7: Import numpy...")
import numpy as np
np.random.seed(42)
print("  OK")

print("Step 8: Generate test signals...")
n = 512
volt = np.random.normal(0, 0.01, n)
curr = np.random.normal(0, 1e-6, n)
print(f"  OK - shape={volt.shape}")

print("Step 9: Run extract_sync...")
try:
    result = service.extract_sync(volt, curr, artifact_id="test_001")
    print(f"  OK - result.artifact_id={result.artifact_id}")
    print(f"     pca_dimensions={result.pca_dimensions}")
    print(f"     raw_feature_count={result.raw_feature_count}")
    print(f"     noise_resistance={result.noise_resistance}")
except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print("\nDone!")
