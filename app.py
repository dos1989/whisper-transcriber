"""
廣東話語音轉文字網頁應用程式
使用 OpenAI Whisper 進行語音識別
支援長錄音自動分段轉錄 + 批量處理
使用 SSE 實時進度推送
"""

import os
import uuid
import json
import math
import subprocess
import shutil
import zipfile
from flask import Flask, render_template, request, jsonify, Response, send_file
import mlx_whisper
import opencc
from datetime import datetime

# 導入配置
from config import *

# 初始化 OpenCC (簡體 -> 繁體)
cc = opencc.OpenCC('s2t')

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# 確保目錄存在
for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, TEMP_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

print("正在初始化 mlx-whisper...")
# MLX 不需要顯式預加載模型到顯存，它會在首次使用時自動處理
print(f"將使用模型: {WHISPER_MODEL}")


# 儲存進度狀態
transcription_progress = {}
batch_progress = {}


def allowed_file(filename):
    """檢查檔案格式是否允許"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_audio_duration(file_path):
    """獲取音檔時長（秒）"""
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout)
    except Exception as e:
        print(f"獲取時長失敗: {e}")
        return 0


def split_audio(audio_path, file_id):
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


def transcribe_audio(audio_path, file_id, output_format='txt'):
    """轉錄單個音檔，返回生成器"""
    segments = []
    was_split = False
    
    try:
        # 階段 1: 分割
        yield {'stage': 'splitting', 'progress': 5, 'message': '正在分析音檔...'}
        
        segments, was_split, total_segments = split_audio(audio_path, file_id)
        
        yield {'stage': 'splitting', 'progress': 15, 'message': f'已分割為 {total_segments} 個片段', 'total_segments': total_segments}
        
        # 階段 2: 轉錄每個片段
        all_transcripts = []
        base_progress = 15
        progress_per_segment = 80 / total_segments
        
        for i, segment_path in enumerate(segments):
            segment_num = i + 1
            segment_progress = base_progress + (i * progress_per_segment)
            
            yield {'stage': 'transcribing', 'progress': int(segment_progress), 'current_segment': segment_num, 'total_segments': total_segments, 'message': f'正在轉錄第 {segment_num}/{total_segments} 個片段...'}
            
            try:
                # 使用 mlx-whisper 進行轉錄
                result = mlx_whisper.transcribe(
                    segment_path, 
                    path_or_hf_repo=WHISPER_MODEL,
                    language=WHISPER_LANGUAGE,
                    initial_prompt="以下是廣東話的錄音，請用繁體中文轉錄。"
                )
                text = result['text'].strip()
                if text:
                    all_transcripts.append(text)
                
                completed_progress = base_progress + ((i + 1) * progress_per_segment)
                yield {'stage': 'transcribing', 'progress': int(completed_progress), 'current_segment': segment_num, 'total_segments': total_segments, 'message': f'第 {segment_num}/{total_segments} 個片段完成！'}
                
            except Exception as e:
                print(f"片段 {segment_num} 轉錄失敗: {e}")
                yield {'stage': 'transcribing', 'progress': int(segment_progress), 'current_segment': segment_num, 'total_segments': total_segments, 'message': f'片段 {segment_num} 轉錄失敗，繼續下一個...'}
        
        # 階段 3: 合併結果並轉換為繁體中文
        yield {'stage': 'finalizing', 'progress': 95, 'message': '正在合併結果並轉換為繁體中文...'}
        
        # 轉換所有片段為繁體中文
        translated_segments = []
        for text in all_transcripts:
            translated_segments.append(cc.convert(text))
            
        # 生成 TXT 內容 (單換行)
        txt_content = '\n'.join(translated_segments)
        
        # 生成 Markdown 內容 (雙換行分段)
        md_content = '\n\n'.join(translated_segments)
        
        # 儲存 TXT
        txt_path = os.path.join(OUTPUT_FOLDER, f'{file_id}.txt')
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(txt_content)
            
        # 儲存 Markdown
        md_path = os.path.join(OUTPUT_FOLDER, f'{file_id}.md')
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        # 完成 (返回默認內容為 Markdown 以供預覽，但下載 ID 可用於兩種格式)
        yield {'stage': 'complete', 'progress': 100, 'message': '轉錄完成！', 'transcript': md_content, 'download_id': file_id}
            
    except Exception as e:
        print(f"轉錄錯誤: {e}")
        yield {'error': str(e)}
        
    finally:
        # 確保清理臨時檔案
        if was_split and segments:
            cleanup_segments(segments)
            
        # 確保清理上傳的音檔
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
                print(f"已清理原始音檔: {audio_path}")
            except Exception as e:
                print(f"清理原始音檔失敗: {e}")


@app.route('/')
def index():
    """首頁"""
    return render_template('index.html')


# ==================== 單檔處理 ====================

@app.route('/upload', methods=['POST'])
def upload():
    """處理單檔上傳"""
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
        'original_name': file.filename,
        'duration': duration,
        'segment_count': segment_count
    }
    
    return jsonify({
        'success': True,
        'file_id': file_id,
        'duration': duration,
        'segment_count': segment_count
    })


@app.route('/transcribe/<file_id>')
def transcribe_stream(file_id):
    """SSE 串流轉錄（單檔）"""
    output_format = request.args.get('format', 'txt')
    
    def generate():
        if file_id not in transcription_progress:
            yield f"data: {json.dumps({'error': '找不到檔案'})}\n\n"
            return
        
        progress = transcription_progress[file_id]
        audio_path = progress['audio_path']
        
        for update in transcribe_audio(audio_path, file_id, output_format):
            yield f"data: {json.dumps(update)}\n\n"
        
        # 清理進度狀態
        if file_id in transcription_progress:
            del transcription_progress[file_id]
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no'
    })


# ==================== 批量處理 ====================

@app.route('/upload-batch', methods=['POST'])
def upload_batch():
    """處理批量上傳"""
    if 'audio' not in request.files:
        return jsonify({'error': '未找到音檔'}), 400
    
    files = request.files.getlist('audio')
    
    if len(files) == 0:
        return jsonify({'error': '未選擇檔案'}), 400
    
    if len(files) > MAX_BATCH_FILES:
        return jsonify({'error': f'最多只能上傳 {MAX_BATCH_FILES} 個檔案'}), 400
    
    batch_id = str(uuid.uuid4())
    file_infos = []
    
    for file in files:
        if file.filename == '' or not allowed_file(file.filename):
            continue
        
        file_id = str(uuid.uuid4())
        original_ext = file.filename.rsplit('.', 1)[1].lower()
        audio_path = os.path.join(UPLOAD_FOLDER, f'{file_id}.{original_ext}')
        
        file.save(audio_path)
        duration = get_audio_duration(audio_path)
        
        file_infos.append({
            'file_id': file_id,
            'original_name': file.filename,
            'audio_path': audio_path,
            'duration': duration,
            'status': 'pending'
        })
    
    if len(file_infos) == 0:
        return jsonify({'error': '沒有有效的音檔'}), 400
    
    batch_progress[batch_id] = {
        'files': file_infos,
        'total': len(file_infos),
        'completed': 0,
        'status': 'uploaded'
    }
    
    return jsonify({
        'success': True,
        'batch_id': batch_id,
        'files': [{'file_id': f['file_id'], 'name': f['original_name'], 'duration': f['duration']} for f in file_infos],
        'total': len(file_infos)
    })


@app.route('/transcribe-batch/<batch_id>')
def transcribe_batch_stream(batch_id):
    """SSE 串流轉錄（批量）"""
    output_format = request.args.get('format', 'txt')
    
    def generate():
        if batch_id not in batch_progress:
            yield f"data: {json.dumps({'error': '找不到批次'})}\n\n"
            return
        
        batch = batch_progress[batch_id]
        total_files = batch['total']
        
        for file_index, file_info in enumerate(batch['files']):
            file_id = file_info['file_id']
            file_name = file_info['original_name']
            audio_path = file_info['audio_path']
            
            # 發送開始處理訊息
            yield f"data: {json.dumps({'stage': 'file_start', 'file_index': file_index, 'file_name': file_name, 'total_files': total_files, 'message': f'開始處理 {file_name} ({file_index + 1}/{total_files})'})}\n\n"
            
            # 轉錄這個檔案
            for update in transcribe_audio(audio_path, file_id, output_format):
                update['file_index'] = file_index
                update['file_name'] = file_name
                update['total_files'] = total_files
                update['batch_progress'] = int((file_index / total_files) * 100 + (update.get('progress', 0) / total_files))
                yield f"data: {json.dumps(update)}\n\n"
            
            file_info['status'] = 'completed'
            batch['completed'] += 1
            
            # 發送檔案完成訊息
            completed_count = batch['completed']
            complete_msg = f'{file_name} 完成！({completed_count}/{total_files})'
            yield f"data: {json.dumps({'stage': 'file_complete', 'file_index': file_index, 'file_name': file_name, 'total_files': total_files, 'completed': completed_count, 'message': complete_msg})}\n\n"
        
        # 全部完成
        batch_complete_msg = f'批量轉錄完成！共 {total_files} 個檔案'
        yield f"data: {json.dumps({'stage': 'batch_complete', 'batch_id': batch_id, 'total_files': total_files, 'message': batch_complete_msg})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no'
    })
        



@app.route('/download/<file_id>')
def download(file_id):
    """下載單個轉錄結果"""
    # 優先檢查 Markdown，然後檢查 TXT
    md_path = os.path.join(OUTPUT_FOLDER, f'{file_id}.md')
    txt_path = os.path.join(OUTPUT_FOLDER, f'{file_id}.txt')
    
    # 用戶可以指定下載格式（如果存在）
    requested_format = request.args.get('format')
    
    if requested_format == 'md' and os.path.exists(md_path):
        output_path = md_path
        download_name = 'transcript.md'
        mimetype = 'text/markdown'
    elif requested_format == 'txt' and os.path.exists(txt_path):
        output_path = txt_path
        download_name = 'transcript.txt'
        mimetype = 'text/plain'
    # 如果沒指定或指定的不存在，自動選擇
    elif os.path.exists(md_path):
        output_path = md_path
        download_name = 'transcript.md'
        mimetype = 'text/markdown'
    elif os.path.exists(txt_path):
        output_path = txt_path
        download_name = 'transcript.txt'
        mimetype = 'text/plain'
    else:
        return jsonify({'error': '檔案不存在'}), 404
    
    return send_file(
        output_path,
        as_attachment=True,
        download_name=download_name,
        mimetype=mimetype
    )


@app.route('/download-batch/<batch_id>')
def download_batch(batch_id):
    """下載批量轉錄結果（ZIP）"""
    if batch_id not in batch_progress:
        return jsonify({'error': '找不到批次'}), 404
    
    batch = batch_progress[batch_id]
    
    # 創建 ZIP 檔案
    zip_path = os.path.join(OUTPUT_FOLDER, f'{batch_id}.zip')
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_info in batch['files']:
            file_id = file_info['file_id']
            original_name = file_info['original_name']
            base_name = os.path.splitext(original_name)[0]
            
            md_path = os.path.join(OUTPUT_FOLDER, f'{file_id}.md')
            txt_path = os.path.join(OUTPUT_FOLDER, f'{file_id}.txt')
            
            # 添加 Markdown
            if os.path.exists(md_path):
                zipf.write(md_path, f'{base_name}.md')
                
            # 添加 TXT
            if os.path.exists(txt_path):
                zipf.write(txt_path, f'{base_name}.txt')
    
    return send_file(
        zip_path,
        as_attachment=True,
        download_name='transcripts.zip',
        mimetype='application/zip'
    )


@app.route('/auto-save', methods=['POST'])
def auto_save():
    """自動儲存轉錄結果到指定路徑 (複製 .txt 和 .md)"""
    data = request.get_json()
    
    save_path = data.get('save_path', '')
    original_name = data.get('original_name', '')
    file_id = data.get('file_id') # 必須提供 file_id 來查找原始檔案
    
    if not save_path or not original_name or not file_id:
        return jsonify({'error': '缺少必要參數'}), 400
    
    # 驗證路徑是否存在
    if not os.path.isdir(save_path):
        return jsonify({'error': f'路徑不存在: {save_path}'}), 400
    
    saved_files = []
    
    try:
        base_name = os.path.splitext(original_name)[0]
        
        # 複製 TXT
        src_txt = os.path.join(OUTPUT_FOLDER, f'{file_id}.txt')
        dst_txt = os.path.join(save_path, f'{base_name}.txt')
        if os.path.exists(src_txt):
            shutil.copy2(src_txt, dst_txt)
            saved_files.append(f'{base_name}.txt')
            
        # 複製 Markdown
        src_md = os.path.join(OUTPUT_FOLDER, f'{file_id}.md')
        dst_md = os.path.join(save_path, f'{base_name}.md')
        if os.path.exists(src_md):
            shutil.copy2(src_md, dst_md)
            saved_files.append(f'{base_name}.md')
            
        if not saved_files:
             return jsonify({'error': '找不到原始輸出檔案'}), 404
        
        return jsonify({
            'success': True,
            'saved_path': save_path,
            'file_name': ', '.join(saved_files)
        })
    except Exception as e:
        return jsonify({'error': f'儲存失敗: {str(e)}'}), 500


@app.route('/auto-save-batch', methods=['POST'])
def auto_save_batch():
    """批量自動儲存轉錄結果到指定路徑"""
    data = request.get_json()
    
    save_path = data.get('save_path', '')
    files = data.get('files', []) # 包含 file_id 和 name
    
    if not save_path or not files:
        return jsonify({'error': '缺少必要參數'}), 400
    
    if not os.path.isdir(save_path):
        return jsonify({'error': f'路徑不存在: {save_path}'}), 400
    
    saved_count = 0
    errors = []
    
    for file_info in files:
        try:
            original_name = file_info.get('name', '')
            file_id = file_info.get('download_id') # 前端傳來的可能是 download_id
            
            if not original_name or not file_id:
                continue
                
            base_name = os.path.splitext(original_name)[0]
            
            # 複製 TXT
            src_txt = os.path.join(OUTPUT_FOLDER, f'{file_id}.txt')
            dst_txt = os.path.join(save_path, f'{base_name}.txt')
            if os.path.exists(src_txt):
                shutil.copy2(src_txt, dst_txt)
                
            # 複製 Markdown
            src_md = os.path.join(OUTPUT_FOLDER, f'{file_id}.md')
            dst_md = os.path.join(save_path, f'{base_name}.md')
            if os.path.exists(src_md):
                shutil.copy2(src_md, dst_md)
                
            saved_count += 1
            
        except Exception as e:
            errors.append(f"{original_name}: {str(e)}")
    
    return jsonify({
        'success': True,
        'saved_count': saved_count,
        'errors': errors
    })


@app.route('/select-folder', methods=['POST'])
def select_folder():
    """打開系統原生資料夾選擇視窗 (macOS Only)"""
    try:
        # 使用 AppleScript 彈出資料夾選擇視窗
        cmd = """osascript -e 'POSIX path of (choose folder with prompt "請選擇儲存位置")'"""
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            path = result.stdout.strip()
            return jsonify({'success': True, 'path': path})
        else:
            # 用戶取消
            return jsonify({'success': False, 'message': 'User cancelled'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("廣東話語音轉文字應用程式")
    print(f"開啟瀏覽器訪問: http://localhost:{PORT}")
    print("=" * 50 + "\n")
    app.run(debug=DEBUG, host=HOST, port=PORT, threaded=True)
