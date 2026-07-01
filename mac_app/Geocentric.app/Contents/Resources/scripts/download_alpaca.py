import json
import urllib.request
from pathlib import Path

def download_alpaca():
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    dest_file = data_dir / "alpaca_data.json"
    url = "https://raw.githubusercontent.com/tatsu-lab/stanford_alpaca/main/alpaca_data.json"
    
    print("=" * 80)
    print("ALPACA INSTRUCTION DATASET DOWNLOADER")
    print("=" * 80)
    print(f"Target URL: {url}")
    print(f"Destination: {dest_file}")
    print("Starting download...")
    
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        
        with urllib.request.urlopen(req) as response:
            total_size = int(response.info().get('Content-Length', 0))
            block_size = 1024 * 16
            read_so_far = 0
            payload = []
            
            # Read all blocks and write to a byte array
            data_bytes = bytearray()
            while True:
                buffer = response.read(block_size)
                if not buffer:
                    break
                read_so_far += len(buffer)
                data_bytes.extend(buffer)
                if total_size > 0:
                    percent = read_so_far * 100 / total_size
                    print(f"Downloaded: {read_so_far / (1024*1024):.2f}MB / {total_size / (1024*1024):.2f}MB ({percent:.1f}%)", end="\r")
                else:
                    print(f"Downloaded: {read_so_far / (1024*1024):.2f}MB", end="\r")
            
            print("\nDownload complete! Parsing and caching dataset...")
            parsed = json.loads(data_bytes.decode('utf-8'))
            
            # Let's save a subset (e.g. 5,000 high quality entries) to keep training extremely fast!
            # The user requested under 2GB, and keeping SFT small makes local iteration take minutes instead of hours!
            max_entries = 5000
            subset = parsed[:max_entries]
            
            with open(dest_file, 'w', encoding='utf-8') as f:
                json.dump(subset, f, indent=2, ensure_ascii=False)
                
            print(f"Success! Cached {len(subset)} Alpaca instruction pairs at: {dest_file}")
            print(f"File size: {dest_file.stat().st_size / (1024*1024):.2f} MB of clean SFT data!")
            print("=" * 80 + "\n")
            return True
            
    except Exception as e:
        print(f"\nERROR during download or extraction: {e}")
        print("Please check your internet connection and try again.")
        print("=" * 80 + "\n")
        return False

if __name__ == "__main__":
    download_alpaca()
