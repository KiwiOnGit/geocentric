import os
import urllib.request
import zipfile
import tarfile
from pathlib import Path

def download_wikitext103():
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    dest_file = data_dir / "wikipedia_pretrain.txt"
    
    # List of mirror URLs to try sequentially in case of DNS or network issues
    urls = [
        "https://s3.amazonaws.com/fast-ai-nlp/wikitext-103.tgz",
        "https://dax-cdn.cdn.appdomain.cloud/dax-wikitext-103/1.0.1/wikitext-103.tar.gz",
        "https://smerity.com/code/datasets/wikitext-103.zip"
    ]
    
    print("=" * 80)
    print("ENGLISH WIKIPEDIA DATASET DOWNLOADER (WIKITEXT-103)")
    print("=" * 80)
    
    success = False
    downloaded_url = None
    archive_path = None
    
    for url in urls:
        ext = ".tar.gz" if (url.endswith(".tar.gz") or url.endswith(".tgz")) else ".zip"
        archive_path = data_dir / f"wikitext-103{ext}"
        print(f"Attempting download from: {url}")
        print(f"Destination: {archive_path}")
        
        try:
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            )
            
            with urllib.request.urlopen(req, timeout=15) as response, open(archive_path, 'wb') as out_file:
                total_size = int(response.info().get('Content-Length', 0))
                block_size = 1024 * 16
                read_so_far = 0
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    read_so_far += len(buffer)
                    out_file.write(buffer)
                    if total_size > 0:
                        percent = read_so_far * 100 / total_size
                        print(f"Downloaded: {read_so_far / (1024*1024):.1f}MB / {total_size / (1024*1024):.1f}MB ({percent:.1f}%)", end="\r")
                    else:
                        print(f"Downloaded: {read_so_far / (1024*1024):.1f}MB", end="\r")
            
            print(f"\nDownload complete from mirror!")
            downloaded_url = url
            success = True
            break
        except Exception as e:
            print(f"\nMirror failed with error: {e}")
            if archive_path.exists():
                archive_path.unlink()
            print("-" * 50)
            
    if not success:
        print("\nERROR: All dataset download mirrors failed.")
        print("Please check your internet/DNS connection or try downloading manually.")
        print("=" * 80 + "\n")
        return False
        
    try:
        print("Extracting dataset...")
        # Decompress archive
        if downloaded_url.endswith(".tar.gz") or downloaded_url.endswith(".tgz"):
            with tarfile.open(archive_path, "r:gz") as tar_ref:
                tar_ref.extractall(data_dir)
        else:
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                zip_ref.extractall(data_dir)
            
        print("Extraction complete! Formatting training tokens...")
        
        # Recursively search for training files inside data_dir to handle different mirror structures
        train_tokens_path = None
        possible_names = [
            "**/wiki.train.tokens",
            "**/train.txt",
            "**/wiki.train.txt",
            "**/wiki.train.tokens.txt",
            "**/train.csv",
            "**/wiki.train.csv"
        ]
        for pattern in possible_names:
            for p in data_dir.glob(pattern):
                train_tokens_path = p
                break
            if train_tokens_path:
                break
            
        if train_tokens_path and train_tokens_path.exists():
            if dest_file.exists():
                dest_file.unlink()
            
            # If it's a CSV, extract raw text rows cleanly into wikipedia_pretrain.txt
            if train_tokens_path.suffix.lower() == ".csv":
                print("Parsing CSV and extracting clean text rows...")
                import csv
                csv.field_size_limit(100_000_000)
                from geocentric.data import format_record_for_text
                with train_tokens_path.open("r", encoding="utf-8", newline="") as infile, \
                     dest_file.open("w", encoding="utf-8") as outfile:
                    reader = csv.reader(infile)
                    try:
                        first_row = next(reader)
                        header_keys = {"instruction", "input", "output", "response", "text", "messages"}
                        has_header = any(col.lower() in header_keys for col in first_row if isinstance(col, str))
                        
                        if has_header:
                            headers = first_row
                            for row in reader:
                                if len(row) <= len(headers):
                                    row_dict = {headers[i]: row[i] for i in range(len(row))}
                                    outfile.write(format_record_for_text(row_dict) + "\n")
                        else:
                            outfile.write(("\n".join(first_row)) + "\n")
                            for row in reader:
                                outfile.write(("\n".join(row)) + "\n")
                    except StopIteration:
                        pass
            else:
                train_tokens_path.rename(dest_file)
                
            print(f"Success! Clean pretraining dataset created at: {dest_file}")
            print(f"File size: {dest_file.stat().st_size / (1024*1024):.2f} MB of clean Wikipedia text!")
        else:
            print("ERROR: Could not locate wiki.train.tokens after extraction!")
            
        # Clean up archive
        if archive_path.exists():
            archive_path.unlink()
        
        # Robustly clean up any newly extracted directory structure under data_dir
        if train_tokens_path:
            try:
                parts = train_tokens_path.relative_to(data_dir).parts
                if parts:
                    top_extracted = data_dir / parts[0]
                    if top_extracted.is_dir() and top_extracted.exists():
                        import shutil
                        shutil.rmtree(top_extracted)
            except Exception:
                pass
        
        # Fallback to check if wikitext-103 folder exists and delete it
        temp_folder = data_dir / "wikitext-103"
        if temp_folder.exists() and temp_folder.is_dir():
            import shutil
            shutil.rmtree(temp_folder)
            
        print("Temporary download files cleaned up.")
        print("=" * 80 + "\n")
        return True
        
    except Exception as e:
        print(f"\nERROR during extraction: {e}")
        print("=" * 80 + "\n")
        return False

if __name__ == "__main__":
    download_wikitext103()
