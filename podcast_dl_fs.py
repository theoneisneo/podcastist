import argparse
import os
import re
import xml.etree.ElementTree as ET

import requests


def main(channel_id: str, limit: int):
    rss_url = f"https://open.firstory.me/rss/user/{channel_id}"
    print(f"Fetching RSS: {rss_url}")

    try:
        res = requests.get(rss_url)
        res.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching RSS feed: {e}")
        return

    # Parse XML using Python's built-in ElementTree
    try:
        root = ET.fromstring(res.content)
    except ET.ParseError as e:
        print(f"Error parsing RSS XML: {e}")
        return

    # Extract podcast title
    channel_title_element = root.find(".//channel/title")
    podcast_name = (
        channel_title_element.text
        if channel_title_element is not None
        else "Unknown_Podcast"
    )
    print(f"Podcast Name: {podcast_name}")

    # Create directory for the podcast
    folder_name = re.sub(r'[\\/:*?"<>|]', "_", podcast_name).strip()
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    # In RSS, episodes are inside <channel><item> usually, or just <item>
    items = root.findall(".//item")
    print(f"Total episodes found: {len(items)}\n")

    count = 0
    for item in items:
        if count >= limit:
            break

        title_element = item.find("title")
        title = title_element.text if title_element is not None else "Unknown_Title"

        # Sanitize filename
        clean_title = (
            title.replace("|", "=")
            .replace("｜", "-=-")
            .replace(" ", "-")
            .replace("/", "_")
        )

        # Original MP3 url is usually hidden in <enclosure> for podcasts
        enclosure = item.find("enclosure")
        if enclosure is None or not enclosure.get("url"):
            print(f"[{count + 1}] Skipping: {clean_title} (No MP3 enclosure found)")
            continue

        mp3_url = enclosure.get("url")
        filename = f"{clean_title}.mp3"
        output_file = os.path.join(folder_name, filename)

        print(f"[{count + 1}] Downloading: {title}")
        print(f"URL: {mp3_url}")

        # Check if file already exists
        if os.path.exists(output_file):
            print(f"File '{output_file}' already exists. Skipping download.\n")
        else:
            # Use curl to download the file directly
            os.system(f'curl -L "{mp3_url}" --output "{output_file}"')
            print(f"Finished downloading: {output_file}\n")

        count += 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download podcast episodes from a Firstory RSS feed."
    )
    # Default is Brian's podcast ID: ckyjmnkp0166d0830od1kznfj
    parser.add_argument(
        "channel_id",
        type=str,
        nargs="?",
        default="",
        help="Firstory Channel ID (the alphanumeric string in the RSS URL)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of episodes to download (default: 10)",
    )
    args = parser.parse_args()

    # args.channel_id = "ckyjmnkp0166d0830od1kznfj"  # boring's id, for testing
    main(args.channel_id, args.limit)
