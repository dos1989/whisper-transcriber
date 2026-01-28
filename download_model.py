from huggingface_hub import snapshot_download
from config import WHISPER_MODEL

print(f"正在下載模型: {WHISPER_MODEL} ...")
print("這可能需要幾分鐘，取決於您的網路速度。")

try:
    snapshot_download(repo_id=WHISPER_MODEL)
    print("✅ 模型下載完成！")
except Exception as e:
    print(f"❌ 下載失敗: {e}")
