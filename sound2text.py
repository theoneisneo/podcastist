import argparse
import platform
import time
import uuid
import yaml
import gc
import sys
from pathlib import Path
from typing import List, Dict, Optional

if sys.version_info >= (3, 7):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# 第三方庫統一放在最上方
try:
    import torch
except ImportError:
    torch = None

try:
    import stable_whisper
except ImportError:
    stable_whisper = None

try:
    import mlx_whisper
except ImportError:
    mlx_whisper = None

# 引入自定義模組
from translate_srt import load_config, translate_segments, save_translated_srt


def format_timestamp(seconds: float):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msecs = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{msecs:03d}"


def load_whisper_model(model_type: str):
    """根據平台與硬體載入一次模型"""
    is_mac = platform.system() == "Darwin" and platform.machine() == "arm64"
    has_cuda = torch.cuda.is_available() if torch else False

    if has_cuda:
        print(f"Loading stable-ts (faster-whisper) '{model_type}' on CUDA...")
        return stable_whisper.load_faster_whisper(model_type, device="cuda", compute_type="float16")
    elif is_mac:
        print(f"Using MLX-whisper '{model_type}' (Just-in-time loading)")
        return "mlx" # MLX 庫的設計通常是調用時加載
    else:
        print(f"Loading stable-ts '{model_type}' on CPU...")
        return stable_whisper.load_faster_whisper(model_type, device="cpu", compute_type="int8")


def transcribe_audio(model, mp3_path: Path, language: str, initial_prompt: Optional[str]):
    """使用傳入的模型實體進行轉錄"""
    if model == "mlx":
        mlx_repo = f"mlx-community/whisper-{args.model}-mlx"
        result = mlx_whisper.transcribe(
            str(mp3_path),
            path_or_hf_repo=mlx_repo,
            language=language,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
        )
        segments = result["segments"]
    else:
        result = model.transcribe_stable(
            str(mp3_path),
            language=language,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
            vad=True,
        )
        segments = result.segments

    unified_segments = []
    converter = None
    if language == "zh":
        try:
            import opencc
            converter = opencc.OpenCC("s2twp")
        except ImportError:
            pass

    for s in segments:
        start = float(s.get('start', 0) if isinstance(s, dict) else s.start)
        end = float(s.get('end', 0) if isinstance(s, dict) else s.end)
        text = s.get('text', "").strip() if isinstance(s, dict) else s.text.strip()
        
        if converter:
            text = converter.convert(text)
            
        timestamp = f"[{format_timestamp(start)} -> {format_timestamp(end)}]"
        print(f"{timestamp} {text}")
        unified_segments.append({"start": start, "end": end, "text": text})
    
    return unified_segments


def save_to_files(segments: List[Dict], output_path_base: Path, converter=None):
    txt_path = output_path_base.parent / (output_path_base.name + ".txt")
    srt_path = output_path_base.parent / (output_path_base.name + ".srt")

    with (
        open(txt_path, "w", encoding="utf-8") as f_txt,
        open(srt_path, "w", encoding="utf-8") as f_srt,
    ):
        for i, segment in enumerate(segments, start=1):
            text = segment["text"]
            if converter:
                text = converter.convert(text)

            f_txt.write(text + "\n")
            f_srt.write(f"{i}\n")
            f_srt.write(f"{format_timestamp(segment['start'])} --> {format_timestamp(segment['end'])}\n")
            f_srt.write(f"{text}\n\n")


def main(target_dir_str: str, model_type: str, src_lang: str, tr_lang: str, service: str, limit: int = 0):
    config = load_config()
    service = service or config.get("translation_service", "local")
    target_dir = Path(target_dir_str).resolve()
    
    mp3_files = []
    for ext in ("*.mp3", "*.mp4", "*.m4a", "*.wav"):
        mp3_files.extend(target_dir.glob(ext))
    
    # 遠端修改為依據檔案時間正序排序（oldest-first）
    mp3_files = sorted(mp3_files, reverse=False)

    if limit > 0:
        mp3_files = mp3_files[:limit]
        print(f"Limiting to {limit} file(s).")

    if not mp3_files:
        print("No media files found.")
        return

    # 1. 篩選出尚未處理的檔案
    pending_files = []
    for mp3_path in mp3_files:
        final_dir = target_dir / mp3_path.stem
        
        # 檢查是否已經完全處理完畢 (包含翻譯，如果有設定的話)
        is_completed = False
        if final_dir.exists() and final_dir.is_dir():
            # 支援檢查帶語言後綴 (例如 _zh.srt) 或無語言後綴 (例如 .srt) 的原始檔
            orig_srt_with_lang = final_dir / f"{mp3_path.stem}_{src_lang}.srt"
            orig_srt_no_lang = final_dir / f"{mp3_path.stem}.srt"
            orig_exists = orig_srt_with_lang.exists() or orig_srt_no_lang.exists()
            
            if tr_lang:
                tr_srt = final_dir / f"{mp3_path.stem}_{tr_lang}.srt"
                is_completed = orig_exists and tr_srt.exists()
            else:
                is_completed = orig_exists

        if is_completed:
            print(f"Skipping '{mp3_path.name}': Output files already exist.")
            continue
        
        pending_files.append(mp3_path)

    if not pending_files:
        print("All files already processed.")
        return

    # 2. 載入一次 Whisper 模型
    model = load_whisper_model(model_type)
    
    # 用於存儲待翻譯的任務
    transcription_results = []

    # 3. 批次辨識
    for mp3_path in pending_files:
        final_dir = target_dir / mp3_path.stem
        print(f"\n>>> Transcribing '{mp3_path.name}'...")
        prompt = "以下是正體中文的逐字稿。" if src_lang == "zh" else None
        segments = transcribe_audio(model, mp3_path, src_lang, prompt)
        
        # 立即建立資料夾並存儲原始語言檔案
        final_dir.mkdir(parents=True, exist_ok=True)
        orig_base = final_dir / f"{mp3_path.stem}_{src_lang}"
        save_to_files(segments, orig_base)
        print(f"Saved transcript for '{mp3_path.name}'")
        
        # 暫存結果以便後續翻譯
        transcription_results.append({
            "mp3_path": mp3_path,
            "segments": segments,
            "final_dir": final_dir
        })

    # 3. 辨識結束，立刻徹底釋放 Whisper 模型與 GPU 資源
    print("\nTranscription batch finished. Releasing Whisper model...")
    del model
    if torch and torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()

    # 4. 批次處理翻譯
    for result in transcription_results:
        mp3_path = result["mp3_path"]
        segments = result["segments"]
        final_dir = result["final_dir"]
        
        # 翻譯
        if tr_lang:
            print(f"\n>>> Translating '{mp3_path.name}' to {tr_lang}...")
            tr_base = final_dir / f"{mp3_path.stem}_{tr_lang}"
            translated = translate_segments(segments, src_lang, tr_lang, service, config)
            save_translated_srt(translated, tr_base, tr_lang)
            print(f"Completed translation for: {mp3_path.name}")
        else:
            print(f"Completed: {mp3_path.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch transcribe and translate media files.")
    parser.add_argument("target_dir", type=str, help="Target directory")
    parser.add_argument("-m", "--model", type=str, default="large-v3", help="Whisper model type")
    parser.add_argument("-s", "--src_lang", type=str, default="zh", help="Source language")
    parser.add_argument("-t", "--tr_lang", type=str, default=None, help="Target language")
    parser.add_argument("-v", "--service", type=str, default=None, help="Translation service")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit the number of files to process (0 = no limit)",
    )
    
    args = parser.parse_args()
    main(args.target_dir, args.model, args.src_lang, args.tr_lang, args.service, args.limit)
