import argparse
import time
import yaml
import re
from pathlib import Path
from typing import List, Dict, Optional

def load_config():
    config_path = Path(__file__).parent / "config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {
        "translation_service": "local",
        "batch_size": 10,
        "providers": {
            "local": {"api_base": "http://localhost:1234/v1", "api_key": "lm-studio", "model": "default"}
        }
    }

def call_llm(prompt: str, service: str, config: Dict) -> str:
    provider_config = config.get("providers", {}).get(service)
    if not provider_config:
        raise ValueError(f"Configuration for service '{service}' not found.")
        
    model = provider_config.get("model", "default")
    api_key = provider_config.get("api_key")

    if service in ["local", "openai"]:
        import openai
        api_base = provider_config.get("api_base")
        client = openai.OpenAI(api_key=api_key, base_url=api_base)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return response.choices[0].message.content.strip()
        
    elif service == "claude":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=0.1,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
        
    elif service == "gemini":
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
        )
        return response.text.strip()

    else:
        raise ValueError(f"Unknown service: {service}")

def translate_segments(
    segments: List[Dict],
    src_lang: str,
    tr_lang: str,
    service: str,
    config: Dict,
) -> List[Dict]:
    if not tr_lang or src_lang == tr_lang:
        return segments

    batch_size = config.get("batch_size", 10)
    print(f"Translating {len(segments)} segments using {service} (Batch size: {batch_size})...")
    translated_segments = []

    for i in range(0, len(segments), batch_size):
        batch = segments[i : i + batch_size]
        print(f"Progress: {i}/{len(segments)} (Batching {len(batch)} segments)...")
        
        batch_text = "\n".join([f"[{j}] {s['text']}" for j, s in enumerate(batch)])
        
        prompt = (
            f"You are a professional translator. Translate the following {src_lang} text to {tr_lang}. \n"
            f"IMPORTANT RULES:\n"
            f"1. Keep the index markers like [0], [1] at the start of each line.\n"
            f"2. Return exactly {len(batch)} translated lines.\n"
            f"3. Do not add any introductory or concluding remarks.\n"
            f"4. Only return the translated lines.\n\n"
            f"{batch_text}"
        )
        
        try:
            result_text = call_llm(prompt, service, config)
            result_lines = result_text.split('\n')
            
            translated_batch_dict = {}
            for line in result_lines:
                line = line.strip()
                match = re.match(r'^\[(\d+)\]\s*(.*)', line)
                if match:
                    idx = int(match.group(1))
                    translated_batch_dict[idx] = match.group(2)
            
            if len(translated_batch_dict) == len(batch):
                for j in range(len(batch)):
                    translated_segments.append({**batch[j], "text": translated_batch_dict[j]})
            else:
                print(f"Batch {i} format mismatch (Got {len(translated_batch_dict)}/{len(batch)}). Falling back to one-by-one...")
                for s in batch:
                    single_prompt = f"Translate this {src_lang} text to {tr_lang}. Only return the translation:\n\n{s['text']}"
                    res = call_llm(single_prompt, service, config)
                    translated_segments.append({**s, "text": res})
        
        except Exception as e:
            print(f"Batch {i} processing failed: {e}. Falling back to one-by-one...")
            for s in batch:
                try:
                    single_prompt = f"Translate this {src_lang} text to {tr_lang}. Only return the translation:\n\n{s['text']}"
                    res = call_llm(single_prompt, service, config)
                    translated_segments.append({**s, "text": res})
                except:
                    translated_segments.append(s)

    return translated_segments

def parse_srt(srt_content: str) -> List[Dict]:
    segments = []
    pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n([\s\S]*?)(?=\n\d+\n|\Z)')
    matches = pattern.finditer(srt_content)
    for match in matches:
        segments.append({
            "index": match.group(1),
            "start_str": match.group(2),
            "end_str": match.group(3),
            "text": match.group(4).strip()
        })
    return segments

def save_translated_srt(segments: List[Dict], output_path: Path, tr_lang: str):
    converter = None
    if "zh-TW" in tr_lang or "zh-Hant" in tr_lang:
        try:
            import opencc
            converter = opencc.OpenCC("s2twp")
        except ImportError:
            pass

    txt_path = output_path.with_suffix(".txt")
    with open(output_path, "w", encoding="utf-8") as f_srt, open(txt_path, "w", encoding="utf-8") as f_txt:
        for s in segments:
            text = s["text"]
            if converter:
                text = converter.convert(text)
            
            f_txt.write(f"{text}\n")
            f_srt.write(f"{s['index']}\n")
            f_srt.write(f"{s['start_str']} --> {s['end_str']}\n")
            f_srt.write(f"{text}\n\n")

def process_single_file(input_path: Path, src_lang: str, tr_lang: str, service: str, config: Dict):
    print(f"\n--- Processing: {input_path.name} ---")
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    segments = parse_srt(content)
    if not segments:
        print(f"Skip: Could not parse SRT format in {input_path}")
        return

    translated_segments = translate_segments(segments, src_lang, tr_lang, service, config)
    
    output_name = input_path.stem
    if output_name.endswith(f"_{src_lang}"):
        output_name = output_name[:-len(src_lang)-1]
    
    output_path = input_path.parent / f"{output_name}_{tr_lang}.srt"
    save_translated_srt(translated_segments, output_path, tr_lang)
    print(f"Saved: {output_path.name} and {output_path.with_suffix('.txt').name}")

def main():
    parser = argparse.ArgumentParser(description="Translate SRT files using LLMs.")
    parser.add_argument("path", type=str, help="Path to an SRT file or a directory")
    parser.add_argument("-s", "--src_lang", type=str, default="ja", help="Source language (default: ja)")
    parser.add_argument("-t", "--tr_lang", type=str, default="zh-TW", help="Target language (default: zh-TW)")
    parser.add_argument("-v", "--service", type=str, default=None, help="Translation service (local, openai, claude, gemini)")
    
    args = parser.parse_args()
    config = load_config()
    service = args.service or config.get("translation_service", "local")
    
    target_path = Path(args.path)
    if not target_path.exists():
        print(f"Error: Path '{args.path}' not found.")
        return

    if target_path.is_file():
        process_single_file(target_path, args.src_lang, args.tr_lang, service, config)
    else:
        print(f"Scanning directory: {target_path}")
        srt_files = list(target_path.glob(f"**/*_{args.src_lang}.srt"))
        all_srts = list(target_path.glob("**/*.srt"))
        
        to_process = []
        for f in all_srts:
            if f.stem.endswith(f"_{args.tr_lang}"):
                continue
            if f.stem.endswith(f"_{args.src_lang}") or not any(f.stem.endswith(f"_{l}") for l in ["en", "zh", "ja", "zh-TW"]):
                to_process.append(f)

        if not to_process:
            print("No matching SRT files found to translate.")
            return

        print(f"Found {len(to_process)} files to translate.")
        for srt_file in sorted(to_process):
            process_single_file(srt_file, args.src_lang, args.tr_lang, service, config)

if __name__ == "__main__":
    main()
