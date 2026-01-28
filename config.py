"""
廣東話語音轉文字應用程式 - 配置檔案
"""

import os

# 基本路徑設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'outputs')
TEMP_FOLDER = os.path.join(BASE_DIR, 'temp')

# 允許的音檔格式
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'mp4', 'm4a', 'ogg', 'flac', 'webm'}

# 檔案限制
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 最大 500MB
MAX_BATCH_FILES = 10  # 批量上傳最多 10 個檔案

# 分段設定
SEGMENT_DURATION = 5 * 60  # 每段 5 分鐘
MIN_DURATION_FOR_SPLIT = 10 * 60  # 超過 10 分鐘才分段

# Whisper 設定
# 使用 MLX 優化模型 (Apple Silicon)
# 可選模型:
# - mlx-community/whisper-large-v3-turbo (推薦: 速度快且準確)
# - mlx-community/whisper-large-v3 (準確度最高但較慢)
# - mlx-community/whisper-base (極快但準確度較低)
WHISPER_MODEL = 'mlx-community/whisper-large-v3-turbo'
WHISPER_LANGUAGE = 'zh'  # 廣東話用 zh 即可，Whisper 會自動識別或由 prompt 引導

# 伺服器設定
HOST = '0.0.0.0'
PORT = 5001
DEBUG = True
