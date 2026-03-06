import argparse
import os
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests


def main(podcast_id: str, limit: int):
    lookup_url = f"https://itunes.apple.com/lookup?id={podcast_id}&entity=podcast"

    # 1. 取得 Apple 針對此 Podcast 的資料
    print("正在向 Apple 查詢 Podcast 資訊...")
    response = requests.get(lookup_url)
    data = response.json()

    if data["resultCount"] == 0:
        print("找不到該 Podcast，請確認 ID 是否正確。")
        return

    feed_url = data["results"][0]["feedUrl"]
    podcast_name = data["results"][0]["collectionName"]
    print(f"成功取得 [{podcast_name}] 的 RSS Feed URL: {feed_url}")

    # 2. 獲取並解析 RSS XML
    print("正在獲取所有集數列表...")
    # 加入 headers 模擬瀏覽器，部分 Hosting 空間會擋爬蟲
    headers = {"User-Agent": "Mozilla/5.0"}
    rss_response = requests.get(feed_url, headers=headers)
    root = ET.fromstring(rss_response.content)

    episodes = []
    # 在 RSS 結構中，節目內容會放在 <channel> 內的 <item>
    for item in root.findall("./channel/item"):
        title_element = item.find("title")
        enclosure_element = item.find("enclosure")
        pubdate_element = item.find("pubDate")

        # 確保該項目有標題及音檔連結
        if title_element is not None and enclosure_element is not None:
            title = title_element.text
            audio_url = enclosure_element.get("url")

            # 解析發行日期 (pubDate)，並格式化為 YYYYMMDD
            date_prefix = ""
            if pubdate_element is not None and pubdate_element.text:
                try:
                    dt = parsedate_to_datetime(pubdate_element.text)
                    date_prefix = dt.strftime("%Y%m%d_")
                except Exception:
                    pass

            if audio_url:
                episodes.append({"title": date_prefix + title, "url": audio_url})

    total_eps = len(episodes)
    print(f"解析成功！共找到 {total_eps} 集節目。")

    # 3. 準備下載資料夾
    # 過濾掉不可作為資料夾名稱的特殊字元
    folder_name = re.sub(r'[\\/:*?"<>|]', "_", podcast_name)
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    # 4. 開始逐一下載
    print(f"\n準備開始下載 (目前設定為最新 {limit} 集)...")
    for i, ep in enumerate(episodes[:limit]):
        # 過濾掉不可作為檔名的特殊字元
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", ep["title"]).strip()
        filename = os.path.join(folder_name, f"{safe_title}.mp3")

        print(f"[{i + 1}/{total_eps}] 正在下載: {safe_title}")

        # 檢查檔案是否已存在，續傳/重啟時可以跳過
        if os.path.exists(filename):
            print(" -> 檔案已經存在，跳過。")
            continue

        try:
            # stream=True 適用於下載大型檔案，避免記憶體一次吃滿
            with requests.get(ep["url"], stream=True, headers=headers) as r:
                r.raise_for_status()  # 若有 Http error 會丟出例外
                with open(filename, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            print(" -> 下載完成")
        except Exception as e:
            print(f" -> 下載失敗發生錯誤: {e}")

    print("\n所有任務處理完畢。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download podcast episodes from Apple Podcasts."
    )
    parser.add_argument(
        "podcast_id", type=str, nargs="?", default="", help="The Apple Podcast ID."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of episodes to download (default: 10)",
    )
    args = parser.parse_args()

    # args.podcast_id = "1500839292"  # Gooaye's id, for testing
    main(args.podcast_id, args.limit)
