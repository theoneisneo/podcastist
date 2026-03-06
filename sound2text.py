import argparse
import platform
import time
from pathlib import Path


def format_timestamp(seconds: float):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msecs = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{msecs:03d}"


def transcribe_audio(mp3_path: str, model_type: str = "large-v3"):
    # 判斷是否為 Mac (Apple Silicon)
    is_mac = platform.system() == "Darwin" and platform.machine() == "arm64"

    # Check for CUDA without importing full torch if we know we are on a Mac
    has_cuda = False
    if not is_mac:
        try:
            import torch

            has_cuda = torch.cuda.is_available()
        except ImportError:
            pass

    if has_cuda:
        # --- RTX 3090 (Windows/Linux) 邏輯 ---
        print(f"Loading faster-whisper '{model_type}' on CUDA (float16)...")
        from faster_whisper import WhisperModel

        model = WhisperModel(model_type, device="cuda", compute_type="float16")
        segments_generator, info = model.transcribe(
            str(mp3_path),
            language="zh",
            initial_prompt="以下是正體中文的逐字稿，包含標點符號。",
            condition_on_previous_text=False,
        )
        print(
            f"Detected language '{info.language}' with probability {info.language_probability:.2f}"
        )

        # 將 Generator 轉換為統一格式的 List[Dict]
        unified_segments = []
        for s in segments_generator:
            unified_segments.append(
                {"start": s.start, "end": s.end, "text": s.text.strip()}
            )

    elif is_mac:
        # --- MacBook M4 邏輯 ---
        print(f"Loading MLX-whisper '{model_type}' on Apple Silicon (float16)...")
        import mlx_whisper

        # MLX 模型通常需要從 Hugging Face 指定 mlx-community 的版本
        mlx_repo = f"mlx-community/whisper-{model_type}-mlx"

        print(f"Transcribing '{mp3_path}' with {mlx_repo}...")
        result = mlx_whisper.transcribe(
            str(mp3_path),
            path_or_hf_repo=mlx_repo,
            language="zh",
            initial_prompt="以下是正體中文的逐字稿，包含標點符號。",
            condition_on_previous_text=False,
        )

        # result["segments"] 本身就是 List[Dict] 的格式，包含 start, end, text
        unified_segments = []
        for s in result["segments"]:
            unified_segments.append(
                {
                    "start": float(s["start"]),
                    "end": float(s["end"]),
                    "text": s["text"].strip(),
                }
            )

    else:
        # --- CPU 降級備用邏輯 ---
        print("No GPU/MPS detected. Falling back to CPU with int8...")
        from faster_whisper import WhisperModel

        model = WhisperModel(model_type, device="cpu", compute_type="int8")
        segments_generator, info = model.transcribe(
            str(mp3_path),
            language="zh",
            initial_prompt="以下是正體中文的逐字稿，包含標點符號。",
            condition_on_previous_text=False,
        )
        print(
            f"Detected language '{info.language}' with probability {info.language_probability:.2f}"
        )

        unified_segments = []
        for s in segments_generator:
            unified_segments.append(
                {"start": s.start, "end": s.end, "text": s.text.strip()}
            )

    return unified_segments


def main(target_dir_str: str, model_type: str):
    target_dir = Path(target_dir_str).resolve()
    if not target_dir.is_dir():
        print(f"Error: '{target_dir}' is not a valid directory.")
        return

    print(f"Target directory: {target_dir}")

    # Find all mp3 files in the target directory
    mp3_files = sorted(target_dir.glob("*.mp3"), reverse=True)

    if not mp3_files:
        print("No MP3 files found in the target directory.")
        return

    # Initialize OpenCC for Simplified to Traditional conversion
    try:
        import opencc

        converter = opencc.OpenCC(
            "s2twp"
        )  # Simplified to Traditional (Taiwan standard), .json is auto-appended
    except ImportError:
        print("Warning: 'opencc' library not found. Falling back to original text.")
        print("To install: uv add opencc-python-reimplemented")
        converter = None

    for mp3_path in mp3_files:
        # Each episode gets its own folder with the same name as the mp3 file (without extension)
        output_dir = target_dir / mp3_path.stem

        # Check if output directory already exists (implies it's already processed)
        if output_dir.exists() and output_dir.is_dir():
            print(f"Skipping '{mp3_path.name}': Output directory already exists.")
            continue

        print(f"\nProcessing '{mp3_path.name}'...")
        t1 = time.time()

        # Create the output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Transcribe audio using dual-platform logic
        segments = transcribe_audio(str(mp3_path), model_type)

        txt_path = output_dir / f"{mp3_path.stem}.txt"
        srt_path = output_dir / f"{mp3_path.stem}.srt"

        with (
            open(txt_path, "w", encoding="utf-8") as f_txt,
            open(srt_path, "w", encoding="utf-8") as f_srt,
        ):
            for i, segment in enumerate(segments, start=1):
                text = segment["text"]

                # Convert to Traditional Chinese if converter is available
                if converter:
                    text = converter.convert(text)

                # Write to .txt (pure text)
                f_txt.write(text + "\n")

                # Write to .srt (subtitle format)
                start_time = format_timestamp(segment["start"])
                end_time = format_timestamp(segment["end"])
                f_srt.write(f"{i}\n")
                f_srt.write(f"{start_time} --> {end_time}\n")
                f_srt.write(f"{text}\n\n")

                # Print progress to console
                print(f"[{start_time} -> {end_time}] {text}")

        t2 = time.time()
        print(f"Finished '{mp3_path.name}' in {t2 - t1:.2f} seconds.")
        # break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Use faster-whisper and mlx-whisper to transcribe MP3 files."
    )
    parser.add_argument(
        "target_dir",
        type=str,
        nargs="?",
        default="",
        help="Target directory containing mp3 files",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="large-v3",
        help="whisper model type (default: large-v3)",
    )
    args = parser.parse_args()

    # args.target_dir = "Gooaye"
    main(args.target_dir, args.model)
