# Podcastist 🎙️

[English](#english) | [繁體中文](#繁體中文)

---

<h2 id="english">English</h2>

**Podcastist** is a Python-based utility toolset designed to automate the process of downloading podcast episodes and transcribing them into text and subtitles with high performance. 

It specifically supports seamless cross-platform hardware acceleration, utilizing **CUDA** on Windows/Linux machines and **Apple Metal (MLX)** on macOS M-series chips for fast audio transcription.

### Features
* **Podcast Downloader**: Download episodes from Apple Podcasts or Firstory RSS feeds.
* **Smart Transcription**: Uses `faster-whisper` (CUDA/CPU) or `mlx-whisper` (Apple Silicon) to transcribe audio to text (`.txt`) and subtitles (`.srt`).
* **Cross-Platform AI Acceleration**: Automatically detects your hardware and applies the best backend (fp16 on RTX 3090, fp16 on M4 Mac) for maximum performance without changing the code.
* **Auto-Translation (OpenCC)**: Automatically converts Simplified Chinese transcripts to Traditional Chinese (Taiwan standard) during processing.

### Prerequisites

This project uses [uv](https://github.com/astral-sh/uv) for fast Python package management.

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/theoneisneo/podcastist.git
   cd podcastist
   ```

2. Install dependencies via `uv`:
   ```bash
   uv sync
   ```
   *(Note: The dependencies are specifically configured in `pyproject.toml` to dynamically install `mlx-whisper` only on Apple Silicon Macs, and PyTorch with CUDA only on Windows)*

### Usage

#### 1. Downloading Podcasts
*(Depending on which downloader script you use)*
```bash
# Example: Download episodes using Apple script
uv run podcast_dl_apple.py <podcast_url> --limit 5
```

#### 2. Transcribing Audio
Use `sound2text.py` to target a folder containing `.mp3` files. The script creates subfolders for each episode, generating a `.txt` transcript and an `.srt` subtitle file.
```bash
uv run sound2text.py "path/to/your/mp3/folder" --model large-v3
```

---

<h2 id="繁體中文">繁體中文</h2>

**Podcastist** 是一個基於 Python 的自動化工具集，專為下載 Podcast 單集並將其高效轉錄為逐字稿與字幕所設計。

本作針對跨平台硬體加速做了深度最佳化，能夠自動在 Windows/Linux 機器上使用 **CUDA (faster-whisper)**，並在 Mac M 系列晶片上無縫啟用 **Apple Metal (MLX)**，大幅提升語音辨識速度。

### 核心功能
* **Podcast 下載器**: 透過 RSS Feed 從 Apple Podcasts 或 Firstory 批次下載音檔。
* **智慧語音轉文字**: 將音檔高精度轉譯為純文字逐字稿 (`.txt`) 與時間軸字幕檔 (`.srt`)。
* **跨平台 AI 算力加速**: 腳本會自動偵測硬體環境，PC 端掛載 CUDA 引擎、Mac 端掛載 Apple Silicon MLX 引擎，兩者皆預設使用 fp16 浮點運算，在不同主機上皆能發揮極致效能。
* **內建繁簡轉換**: 整合 `OpenCC`，自動將多語言模型生成的簡體中文轉正為符合台灣習慣的繁體中文 (`s2twp`)。

### 系統需求

本專案使用新一代套件管理器 [uv](https://github.com/astral-sh/uv) 進行依賴管理。

### 安裝步驟

1. 複製專案到本地端：
   ```bash
   git clone https://github.com/theoneisneo/podcastist.git
   cd podcastist
   ```

2. 透過 `uv` 同步並安裝所有相依套件：
   ```bash
   uv sync
   ```
   *（註：`pyproject.toml` 已配置智能依賴，在 Mac 環境會自動安裝 `mlx-whisper`，而在 Windows 環境則對應安裝 CUDA 版本的 PyTorch）*

### 快速開始

#### 1. 下載 Podcast 節目
*(根據您想使用的下載腳本而定)*
```bash
# 範例：使用 Apple 下載腳本，並限制下載最新 5 集
uv run podcast_dl_apple.py <podcast_url> --limit 5
```

#### 2. 音檔轉錄文字
執行 `sound2text.py` 並指定包含 `.mp3` 檔案的目標資料夾。程式會為每一個音檔建立專屬資料夾，並在其中生成對應的 `.txt` 與 `.srt`。
```bash
uv run sound2text.py "指定您的音檔資料夾路徑" --model large-v3
```
