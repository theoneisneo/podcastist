import argparse
import time
from pathlib import Path

from faster_whisper import WhisperModel


def format_timestamp(seconds: float):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msecs = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{msecs:03d}"


def main(target_dir_str: str, model_type: str):
    target_dir = Path(target_dir_str).resolve()
    if not target_dir.is_dir():
        print(f"Error: '{target_dir}' is not a valid directory.")
        return

    print(f"Target directory: {target_dir}")
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"

    if device == "cuda":
        print(f"Loading faster-whisper model '{model_type}' on CUDA (float16)...")
        compute_type = "float16"  # RTX 3090 supports float16 efficiently
    else:
        # Apple Silicon (M1/M2/M3/M4) doesn't fully support faster-whisper's CTranslate2 GPU backend yet,
        # but their CPUs are very fast and support float16 / int8.
        print(f"CUDA not found. Loading faster-whisper model '{model_type}' on CPU...")
        # compute_type = "int8" # float16 might fall back or be slower depending on compile flags; int8 is safest and fast on Mac.
        compute_type = "float16"

    model = WhisperModel(model_type, device=device, compute_type=compute_type)

    # Find all mp3 files in the target directory
    mp3_files = sorted(target_dir.glob("*.mp3"), reverse=True)

    if not mp3_files:
        print("No MP3 files found in the target directory.")
        return

    for mp3_path in mp3_files:
        # Each episode gets its own folder with the same name as the mp3 file (without extension)
        output_dir = target_dir / mp3_path.stem

        # Check if output directory already exists (implies it's already processed)
        if output_dir.exists() and output_dir.is_dir():
            print(f"Skipping '{mp3_path.name}': Output directory already exists.")
            continue

        print(f"\nProcessing '{mp3_path.name}'...")
        t1 = time.time()

        # Transcribe directly from the mp3 path
        segments, info = model.transcribe(
            str(mp3_path),
            language="zh",  # 正體中文
            initial_prompt="以下是正體中文的逐字稿，包含標點符號。",
            condition_on_previous_text=False,
        )

        print(
            f"Detected language '{info.language}' with probability {info.language_probability:.2f}"
        )

        # Create the output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize OpenCC for Simplified to Traditional conversion
        try:
            import opencc

            converter = opencc.OpenCC(
                "s2twp"
            )  # Simplified to Traditional (Taiwan standard), .json is auto-appended
        except ImportError:
            print("Warning: 'opencc' library not found. Falling back to original text.")
            print("To install: pip install opencc-python-reimplemented")
            converter = None

        txt_path = output_dir / f"{mp3_path.stem}.txt"
        srt_path = output_dir / f"{mp3_path.stem}.srt"

        with (
            open(txt_path, "w", encoding="utf-8") as f_txt,
            open(srt_path, "w", encoding="utf-8") as f_srt,
        ):
            for i, segment in enumerate(segments, start=1):
                text = segment.text.strip()

                # Convert to Traditional Chinese if converter is available
                if converter:
                    text = converter.convert(text)

                # Write to .txt (pure text)
                f_txt.write(text + "\n")

                # Write to .srt (subtitle format)
                start_time = format_timestamp(segment.start)
                end_time = format_timestamp(segment.end)
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
        description="Use faster-whisper to transcribe MP3 files."
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
        help="faster-whisper model type (default: large-v3)",
    )
    args = parser.parse_args()

    # args.target_dir = "Gooaye"
    main(args.target_dir, args.model)
