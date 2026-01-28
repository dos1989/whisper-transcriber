"""
廣東話語音轉文字網頁應用程式
使用 OpenAI Whisper 進行語音識別
支援長錄音自動分段轉錄
使用 SSE 實時進度推送
"""

import os
import uuid
import subprocess
import json
import math
from flask import Flask, render_template, request, jsonify, send_file, Response
import whisper
from opencc import OpenCC

# 簡繁轉換器 (將簡體轉換為繁體)
cc = OpenCC('s2t')

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 最大 500MB

# 設定上傳和輸出目錄
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
OUTPUT_FOLDER = os.path.join(os.path.dirname(__file__), 'outputs')
TEMP_FOLDER = os.path.join(os.path.dirname(__file__), 'temp')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)

# 允許的音檔格式
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'mp4', 'm4a', 'ogg', 'flac', 'webm'}

# 分段設定
SEGMENT_DURATION = 5 * 60  # 每段 5 分鐘
MIN_DURATION_FOR_SPLIT = 10 * 60  # 超過 10 分鐘才分段

# 儲存進度狀態
transcription_progress = {}

# 載入 Whisper 模型 (首次運行會自動下載)
print("正在載入 Whisper 模型...")
model = whisper.load_model("large-v3")
print("模型載入完成！")


def allowed_file(filename):
    """檢查檔案格式是否允許"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_audio_duration(audio_path):
    """使用 ffprobe 獲取音檔時長（秒）"""
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', audio_path
        ], capture_output=True, text=True)
        info = json.loads(result.stdout)
        return float(info['format']['duration'])
    except Exception as e:
        print(f"獲取音檔時長失敗: {e}")
        return 0


def split_audio(audio_path, file_id, progress_callback=None):
    """將長音檔分割成多個片段"""
    duration = get_audio_duration(audio_path)
    
    if duration <= 0:
        print("無法獲取音檔時長，使用原始檔案")
        return [audio_path], False, 1
    
    if duration <= MIN_DURATION_FOR_SPLIT:
        print(f"音檔時長: {duration:.1f} 秒，無需分段")
        return [audio_path], False, 1
    
    segments = []
    segment_count = math.ceil(duration / SEGMENT_DURATION)
    
    print(f"音檔時長: {duration:.1f} 秒（約 {duration/60:.1f} 分鐘），將分割成 {segment_count} 個片段")
    
    if progress_callback:
        progress_callback('splitting', 0, segment_count, f"正在分割音檔為 {segment_count} 個片段...")
    
    for i in range(segment_count):
        start_time = i * SEGMENT_DURATION
        actual_duration = min(SEGMENT_DURATION, duration - start_time)
        
        if actual_duration <= 1:
            continue
            
        segment_path = os.path.join(TEMP_FOLDER, f'{file_id}_segment_{i}.wav')
        
        subprocess.run([
            'ffmpeg', '-y', 
            '-i', audio_path,
            '-ss', str(start_time),
            '-t', str(actual_duration),
            '-acodec', 'pcm_s16le',
            '-ar', '16000',
            '-ac', '1',
            '-f', 'wav',
            segment_path
        ], capture_output=True, text=True)
        
        if os.path.exists(segment_path):
            segment_size = os.path.getsize(segment_path)
            if segment_size > 1000:
                segments.append(segment_path)
                print(f"分割片段 {i+1}/{segment_count}: {start_time}s - {start_time + actual_duration:.0f}s")
                if progress_callback:
                    progress_callback('splitting', i + 1, segment_count, f"已分割 {i+1}/{segment_count} 個片段")
            else:
                os.remove(segment_path)
    
    if not segments:
        return [audio_path], False, 1
    
    return segments, True, segment_count


def cleanup_segments(segments):
    """清理臨時分割檔案"""
    for segment in segments:
        if TEMP_FOLDER in segment and os.path.exists(segment):
            os.remove(segment)


@app.route('/')
def index():
    """首頁"""
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    """處理音檔上傳（第一步）"""
    if 'audio' not in request.files:
        return jsonify({'error': '未找到音檔'}), 400
    
    file = request.files['audio']
    
    if file.filename == '':
        return jsonify({'error': '未選擇檔案'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': f'不支援的檔案格式。支援格式：{", ".join(ALLOWED_EXTENSIONS)}'}), 400
    
    # 生成唯一檔名
    file_id = str(uuid.uuid4())
    original_ext = file.filename.rsplit('.', 1)[1].lower()
    audio_path = os.path.join(UPLOAD_FOLDER, f'{file_id}.{original_ext}')
    
    # 儲存上傳的檔案
    file.save(audio_path)
    
    # 獲取音檔時長
    duration = get_audio_duration(audio_path)
    segment_count = max(1, math.ceil(duration / SEGMENT_DURATION)) if duration > MIN_DURATION_FOR_SPLIT else 1
    
    # 初始化進度狀態
    transcription_progress[file_id] = {
        'status': 'uploaded',
        'audio_path': audio_path,
        'duration': duration,
        'segment_count': segment_count,
        'current_segment': 0,
        'message': '檔案已上傳',
        'transcript': '',
        'error': None
    }
    
    return jsonify({
        'success': True,
        'file_id': file_id,
        'duration': duration,
        'segment_count': segment_count
    })


@app.route('/transcribe/<file_id>')
def transcribe_stream(file_id):
    """SSE 串流轉錄"""
    def generate():
        if file_id not in transcription_progress:
            yield f"data: {json.dumps({'error': '找不到檔案'})}\n\n"
            return
        
        progress = transcription_progress[file_id]
        audio_path = progress['audio_path']
        
        try:
            # 階段 1: 分割
            yield f"data: {json.dumps({'stage': 'splitting', 'progress': 5, 'message': '正在分析音檔...'})}\n\n"
            
            segments, was_split, total_segments = split_audio(audio_path, file_id)
            
            yield f"data: {json.dumps({'stage': 'splitting', 'progress': 15, 'message': f'已分割為 {total_segments} 個片段', 'total_segments': total_segments})}\n\n"
            
            # 階段 2: 轉錄每個片段
            all_transcripts = []
            base_progress = 15
            progress_per_segment = 80 / total_segments
            
            for i, segment_path in enumerate(segments):
                segment_num = i + 1
                segment_progress = base_progress + (i * progress_per_segment)
                
                yield f"data: {json.dumps({'stage': 'transcribing', 'progress': int(segment_progress), 'current_segment': segment_num, 'total_segments': total_segments, 'message': f'正在轉錄第 {segment_num}/{total_segments} 個片段...'})}\n\n"
                
                try:
                    result = model.transcribe(segment_path, language="yue")
                    text = result['text'].strip()
                    if text:
                        all_transcripts.append(text)
                    
                    completed_progress = base_progress + ((i + 1) * progress_per_segment)
                    yield f"data: {json.dumps({'stage': 'transcribing', 'progress': int(completed_progress), 'current_segment': segment_num, 'total_segments': total_segments, 'message': f'第 {segment_num}/{total_segments} 個片段完成！'})}\n\n"
                    
                except Exception as e:
                    print(f"片段 {segment_num} 轉錄失敗: {e}")
                    yield f"data: {json.dumps({'stage': 'transcribing', 'progress': int(segment_progress), 'current_segment': segment_num, 'total_segments': total_segments, 'message': f'片段 {segment_num} 轉錄失敗，繼續下一個...'})}\n\n"
            
            # 階段 3: 合併結果並轉換為繁體中文
            yield f"data: {json.dumps({'stage': 'finalizing', 'progress': 95, 'message': '正在合併結果並轉換為繁體中文...'})}\n\n"
            
            transcript = '\n\n'.join(all_transcripts) if was_split else (all_transcripts[0] if all_transcripts else '')
            
            # 將簡體中文轉換為繁體中文
            transcript = cc.convert(transcript)
            
            # 清理臨時檔案
            if was_split:
                cleanup_segments(segments)
            
            # 儲存結果
            output_path = os.path.join(OUTPUT_FOLDER, f'{file_id}.txt')
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(transcript)
            
            # 清理上傳的音檔
            if os.path.exists(audio_path):
                os.remove(audio_path)
            
            # 完成
            yield f"data: {json.dumps({'stage': 'complete', 'progress': 100, 'message': '轉錄完成！', 'transcript': transcript, 'download_id': file_id})}\n\n"
            
            # 清理進度狀態
            if file_id in transcription_progress:
                del transcription_progress[file_id]
                
        except Exception as e:
            print(f"轉錄錯誤: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no'
    })


@app.route('/download/<file_id>')
def download(file_id):
    """下載轉錄結果"""
    output_path = os.path.join(OUTPUT_FOLDER, f'{file_id}.txt')
    
    if not os.path.exists(output_path):
        return jsonify({'error': '檔案不存在'}), 404
    
    return send_file(
        output_path,
        as_attachment=True,
        download_name='transcript.txt',
        mimetype='text/plain'
    )


if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("廣東話語音轉文字應用程式")
    print("開啟瀏覽器訪問: http://localhost:5001")
    print("=" * 50 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5001, threaded=True)
