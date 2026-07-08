import argparse
import json
import os
import sys
import time
from pathlib import Path
import yaml
from google import genai
from google.genai import types

# 解決 Windows 主控台編碼問題
if sys.version_info >= (3, 7):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

def load_gemini_api_key() -> str:
    # 1. 優先從環境變數讀取
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        return api_key

    # 2. 次之嘗試讀取 config.yaml
    config_path = Path(__file__).parent / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                key = config.get("providers", {}).get("gemini", {}).get("api_key")
                if key and key != "AIza..." and not key.startswith("sk-"):
                    return key
        except Exception as e:
            print(f"【警告】讀取 config.yaml 失敗: {e}")
    return ""

def load_gemini_model(cli_model: str = None) -> str:
    # 1. 優先使用命令列帶入的模型
    if cli_model:
        return cli_model

    # 2. 次之嘗試讀取 config.yaml 中的 model
    config_path = Path(__file__).parent / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                model = config.get("providers", {}).get("gemini", {}).get("model")
                if model:
                    return model
        except Exception as e:
            print(f"【警告】讀取 config.yaml 中的 model 失敗: {e}")
    return "gemini-1.5-flash"

def main(target_dir_str: str, model_name: str, rpm: int, limit: int = 0):
    # 檢查 API Key
    api_key = load_gemini_api_key()
    if not api_key:
        print("【錯誤】未偵測到環境變數 GEMINI_API_KEY，且 config.yaml 中也未設定有效的 gemini.api_key。")
        print("請在 config.yaml 中的 providers.gemini.api_key 設定金鑰，")
        print("或在終端機設定環境變數再執行，例如：")
        print('PowerShell:  $env:GEMINI_API_KEY="您的金鑰"')
        print('CMD:         set GEMINI_API_KEY="您的金鑰"')
        print("您可以到 https://aistudio.google.com/ 免費申請金鑰。")
        sys.exit(1)

    model_name = load_gemini_model(model_name)

    target_dir = Path(target_dir_str).resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"【錯誤】目標路徑 {target_dir} 不存在或不是目錄。")
        sys.exit(1)

    # 取得所有集數資料夾，依時間倒序排序（從新到舊）
    episode_dirs = sorted([d for d in target_dir.iterdir() if d.is_dir()], reverse=True)
    
    # 篩選出含有 _zh.txt 的資料夾
    valid_dirs = []
    for d in episode_dirs:
        txt_files = list(d.glob("*_zh.txt"))
        if txt_files:
            valid_dirs.append((d, txt_files[0]))

    print(f"找到 {len(valid_dirs)} 個已轉錄的集數資料夾。")

    # 篩選出尚未處理的集數
    pending_dirs = []
    for d, txt_path in valid_dirs:
        output_json = d / "summary_from_llm.json"
        if not output_json.exists():
            pending_dirs.append((d, txt_path))

    print(f"已處理: {len(valid_dirs) - len(pending_dirs)} 集")
    print(f"待處理: {len(pending_dirs)} 集")

    if limit > 0:
        pending_dirs = pending_dirs[:limit]
        print(f"套用限制，本次僅處理最新待處理的 {limit} 集。")

    if not pending_dirs:
        print("所有集數均已處理完畢或無符合本次限制的待處理集數！")
        return

    # 初始化 Gemini Client，設置超時時間為 300 秒（5 分鐘），以防免費金鑰因伺服器繁忙而超時
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=300_000)
    )

    # 定義 System Instruction
    system_instruction = """
你是一個專業的財經 Podcast 內容分析師。請仔細閱讀提供的逐字稿，並將其分析後轉化為結構化的 JSON 格式。
請特別注意以下規則：
1. 提取提到的產業與股票時，需區分台股（taiwan）與美股（us），其他地區列入其他（other_regions）。
2. 包含「暗示性」的稱呼（例如「皮衣男/NV」、「蘇媽/AMD」、「發哥/聯發科」、「神山/台積電」），請將其還原成真實的股票名稱/代碼並括號註明（如：台積電(2330)、輝達(NVDA)）。
3. 若有 Q&A 環節，請整理為 1Q1A 形式，以簡明扼要、口語化且好讀的格式呈現。
4. 輸出必須完全符合指定的 JSON Schema 格式，且內容必須使用正體中文（台灣繁體）。
5. 如果有些欄位無提及，請填入空陣列或空值，不要編造。
"""

    # 定義 JSON Schema
    json_schema = {
        "type": "OBJECT",
        "properties": {
            "date": {"type": "STRING", "description": "播出日期 YYYY-MM-DD (若逐字稿中未提及確切日期，請根據情境推估或填寫未知)"},
            "summary": {"type": "STRING", "description": "主節目核心議題的簡明摘要 (約 200-400 字)"},
            "qa": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "q": {"type": "STRING", "description": "聽眾問題簡述"},
                        "a": {"type": "STRING", "description": "主持人的回答與建議簡述"}
                    },
                    "required": ["q", "a"]
                },
                "description": "QA 環節整理，一問一答。若本集沒有 QA，請放空陣列。"
            },
            "market_entities": {
                "type": "OBJECT",
                "properties": {
                    "taiwan": {
                        "type": "OBJECT",
                        "properties": {
                            "industries": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "提及的台股產業 (例如: 半導體設備、散熱、代工)"},
                            "stocks": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "提及或暗示的台股個股名稱/代碼"}
                        },
                        "required": ["industries", "stocks"]
                    },
                    "us": {
                        "type": "OBJECT",
                        "properties": {
                            "industries": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "提及的美股產業"},
                            "stocks": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "提及或暗示的美股個股名稱/代碼"}
                        },
                        "required": ["industries", "stocks"]
                    },
                    "other_regions": {
                        "type": "OBJECT",
                        "properties": {
                            "stocks": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "其他地區的股票"}
                        },
                        "required": ["stocks"]
                    }
                },
                "required": ["taiwan", "us", "other_regions"]
            },
            "important_notes": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "其他值得記錄的重要觀點、操作心態或市場趨勢提醒"
            }
        },
        "required": ["date", "summary", "qa", "market_entities", "important_notes"]
    }

    # 計算每次請求的間隔時間 (例如 12 RPM = 5.0 秒)
    delay = 60.0 / rpm
    
    print(f"\n開始處理，使用模型: {model_name}，每次請求間隔: {delay:.1f} 秒...")

    for idx, (ep_dir, txt_path) in enumerate(pending_dirs, start=1):
        print(f"\n[{idx}/{len(pending_dirs)}] 正在處理: {ep_dir.name}")
        
        # 讀取逐字稿與長度
        print("   -> 正在讀取逐字稿...")
        transcript_text = txt_path.read_text(encoding="utf-8")
        char_count = len(transcript_text)
        print(f"      逐字稿長度: {char_count} 字")

        # 自動重試迴圈，專為免費 Key 的 503 與 429 暫時性錯誤設計
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            try:
                start_time = time.time()
                
                # 2. 調用 API
                if attempt > 1:
                    print(f"   -> [重試 {attempt}/{max_retries}] 正在發送請求至 Gemini API ({model_name})...")
                else:
                    print(f"   -> 正在發送請求至 Gemini API ({model_name}) 進行結構化分析，請稍候...")
                
                api_start_time = time.time()
                response = client.models.generate_content(
                    model=model_name,
                    contents=f"請分析以下股癌 Podcast 逐字稿：\n\n{transcript_text}",
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=json_schema,
                        temperature=0.1,
                    ),
                )
                
                api_elapsed = time.time() - api_start_time
                print(f"      Gemini API 處理完成！(耗時 {api_elapsed:.1f} 秒)")
                
                # 3. 解析與儲存
                print("   -> 正在解析並儲存報告...")
                result_json = json.loads(response.text)
                
                output_json_path = ep_dir / "summary_from_llm.json"
                with open(output_json_path, "w", encoding="utf-8") as f:
                    json.dump(result_json, f, ensure_ascii=False, indent=2)
                
                # 同時寫入一個好讀的 Markdown 檔案方便直接預覽
                output_md_path = ep_dir / "summary_from_llm.md"
                save_as_markdown(result_json, output_md_path, ep_dir.name)
                
                total_elapsed = time.time() - start_time
                print(f"   -> 成功存檔！(JSON & MD) [累計耗時 {total_elapsed:.1f} 秒]")
                
                # 控制頻率以防被 API Rate Limit
                elapsed = time.time() - start_time
                if elapsed < delay:
                    sleep_time = delay - elapsed
                    print(f"   -> 頻率控制：冷卻等待 {sleep_time:.1f} 秒...")
                    time.sleep(sleep_time)
                break # 成功，跳出重試迴圈
                
            except Exception as e:
                print(f"      處理失敗 (嘗試 {attempt}/{max_retries})：{e}")
                if attempt < max_retries:
                    # 遞增等待時間（例如：第 1 次失敗等 20 秒，第 2 次失敗等 40 秒，以此類推）
                    retry_delay = attempt * 20
                    print(f"      將於 {retry_delay} 秒後進行重試...")
                    time.sleep(retry_delay)
                else:
                    print(f"   -> [錯誤] 達到最大重試次數，跳過此集。")


def save_as_markdown(data: dict, md_path: Path, title: str):
    """將結構化資料輸出成精美的 Markdown 方便預覽"""
    lines = []
    lines.append(f"# {title} - 結構化分析報告\n")
    lines.append(f"**播出日期**：{data.get('date', '未知')}\n")
    
    lines.append("## 節目總結")
    lines.append(f"{data.get('summary', '無')}\n")
    
    # 提及市場標的
    entities = data.get("market_entities", {})
    lines.append("## 提及的市場與標的")
    
    # 台股
    tw = entities.get("taiwan", {})
    lines.append("### 🇹🇼 台股")
    lines.append(f"* **產業別**：{', '.join(tw.get('industries', [])) if tw.get('industries') else '無'}")
    lines.append(f"* **個股/暗示**：{', '.join(tw.get('stocks', [])) if tw.get('stocks') else '無'}\n")
    
    # 美股
    us = entities.get("us", {})
    lines.append("### 🇺🇸 美股")
    lines.append(f"* **產業別**：{', '.join(us.get('industries', [])) if us.get('industries') else '無'}")
    lines.append(f"* **個股/暗示**：{', '.join(us.get('stocks', [])) if us.get('stocks') else '無'}\n")

    # 其他
    other = entities.get("other_regions", {})
    if other and other.get("stocks"):
        lines.append("### 🌐 其他地區")
        lines.append(f"* **個股**：{', '.join(other.get('stocks', []))}\n")

    # QA
    qa_list = data.get("qa", [])
    lines.append("## Q&A 整理")
    if qa_list:
        for i, qa in enumerate(qa_list, start=1):
            lines.append(f"### Q{i}: {qa.get('q')}")
            lines.append(f"**A**: {qa.get('a')}\n")
    else:
        lines.append("本集無 Q&A 環節。\n")

    # 重要觀點
    notes = data.get("important_notes", [])
    lines.append("## 其他重要重點/操作觀點")
    if notes:
        for note in notes:
            lines.append(f"* {note}")
    else:
        lines.append("無")
    
    md_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch generate structured summaries using Gemini API.")
    parser.add_argument("target_dir", type=str, help="Target directory containing transcribed subdirectories")
    parser.add_argument("-m", "--model", type=str, default=None, help="Gemini model (default: read from config.yaml, or gemini-1.5-flash)")
    parser.add_argument("-r", "--rpm", type=int, default=12, help="Max requests per minute (default: 12, free tier limit is 15)")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit the number of files to process (0 = no limit)",
    )
    
    args = parser.parse_args()
    main(args.target_dir, args.model, args.rpm, args.limit)
