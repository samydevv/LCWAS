#!/usr/bin/env python3
"""
Script to download and install Stockfish chess engine
"""
import os
import platform
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path
import logging
import requests
import tempfile

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Stockfish download URLs (updated to latest stable release)
STOCKFISH_URLS = {
    "Windows": "https://github.com/official-stockfish/Stockfish/releases/download/sf_16.1/stockfish-windows-x86-64-avx2.zip",
    "Darwin-x86_64": "https://github.com/official-stockfish/Stockfish/releases/download/sf_16.1/stockfish-macos-x86-64-avx2.tar",  # Intel Mac
    "Darwin-arm64": "https://github.com/official-stockfish/Stockfish/releases/download/sf_16.1/stockfish-macos-m1-apple-silicon.tar",  # Apple Silicon Mac
    "Linux": "https://github.com/official-stockfish/Stockfish/releases/download/sf_16.1/stockfish-ubuntu-x86-64-avx2.tar"
}

def download_file(url, output_path):
    """Download a file from a URL to a specific location"""
    logger.info(f"Downloading from {url}...")
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        block_size = 8192
        downloaded = 0
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=block_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Simple progress indicator
                    if total_size:
                        percent = int((downloaded / total_size) * 100)
                        sys.stdout.write(f"\rDownloaded: {percent}% ({downloaded}/{total_size} bytes)")
                        sys.stdout.flush()
        
        logger.info(f"\nDownload completed: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Download failed: {str(e)}")
        logger.info("You can manually download Stockfish from https://stockfishchess.org/download/")
        logger.info("Place the executable in a directory named 'stockfish' in the project root")
        return False

def extract_stockfish(archive_path, extract_dir):
    """Extract Stockfish from archive"""
    logger.info(f"Extracting Stockfish from {archive_path}...")
    try:
        archive_str = str(archive_path)
        if archive_str.endswith(".zip"):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        elif archive_str.endswith(".tar.gz"):
            with tarfile.open(archive_path, 'r:gz') as tar_ref:
                tar_ref.extractall(extract_dir)
        elif archive_str.endswith(".tar"):
            with tarfile.open(archive_path, 'r') as tar_ref:
                tar_ref.extractall(extract_dir)
        else:
            logger.error(f"Unsupported archive format: {archive_path}")
            return False
        
        logger.info("Extraction completed")
        return True
    except Exception as e:
        logger.error(f"Extraction failed: {str(e)}")
        return False

def find_executable(extract_dir):
    """Find the Stockfish executable in the extracted directory"""
    system = platform.system()
    
    logger.info(f"Looking for Stockfish executable in {extract_dir}")
    # Walk through the extracted directory to find the Stockfish executable
    for root, dirs, files in os.walk(extract_dir):
        # Log what we're finding to help with debugging
        logger.info(f"Searching in directory: {root}")
        logger.info(f"Found files: {files}")
        
        for file in files:
            # Look for the Stockfish executable based on the platform
            if system == "Windows" and file.startswith("stockfish") and file.endswith(".exe"):
                logger.info(f"Found Windows Stockfish executable: {file}")
                return Path(root) / file
            elif system != "Windows":
                # For macOS and Linux, look for any file that might be the stockfish binary
                if "stockfish" in file.lower():
                    logger.info(f"Found potential Stockfish executable: {file}")
                    return Path(root) / file
    
    logger.error("Could not find Stockfish executable in extracted files")
    return None

def main():
    """Main function to download and install Stockfish"""
    # Determine the system
    system = platform.system()
    
    # Set up directories - now using the app root directory
    script_dir = Path(__file__).parent
    stockfish_dir = script_dir / "stockfish"
    
    # Create stockfish directory if it doesn't exist
    stockfish_dir.mkdir(exist_ok=True)
    
    # Determine the appropriate URL for the current system
    if system == "Darwin":
        # Check if M1/M2 Mac
        if platform.processor() == 'arm':
            stockfish_url = STOCKFISH_URLS["Darwin-arm64"]
            dest_filename = "stockfish-macos-arm"
        else:
            stockfish_url = STOCKFISH_URLS["Darwin-x86_64"]
            dest_filename = "stockfish-macos-x86"
    elif system == "Windows":
        stockfish_url = STOCKFISH_URLS[system]
        dest_filename = "stockfish-windows-x86-64-avx2.exe"
    elif system == "Linux":
        stockfish_url = STOCKFISH_URLS[system]
        dest_filename = "stockfish-ubuntu-x86-64-avx2"
    else:
        logger.error(f"Unsupported operating system: {system}")
        return False
    
    logger.info(f"Installing for {system}, will save as {dest_filename}")
    
    # Set up paths
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        archive_path = temp_dir_path / os.path.basename(stockfish_url)
        
        # Download the file
        if not download_file(stockfish_url, archive_path):
            return False
        
        # Extract the archive
        extract_dir = temp_dir_path / "extract"
        extract_dir.mkdir(exist_ok=True)
        if not extract_stockfish(archive_path, extract_dir):
            return False
        
        # Find the executable
        executable_path = find_executable(extract_dir)
        if not executable_path:
            # If we couldn't find it automatically, try a manual approach for macOS
            if system == "Darwin":
                # For macOS tar files, sometimes the binary is directly the stockfish file in the archive
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        file_path = Path(root) / file
                        if os.access(file_path, os.X_OK):
                            logger.info(f"Found executable file: {file_path}")
                            executable_path = file_path
                            break
                    if executable_path:
                        break
            
            if not executable_path:
                logger.error("Could not find Stockfish executable in extracted files")
                return False
        
        dest_path = stockfish_dir / dest_filename
        
        # Copy the executable to the stockfish directory
        logger.info(f"Installing Stockfish to {dest_path}")
        shutil.copy2(executable_path, dest_path)
        
        # Make the file executable on Unix systems
        if system != "Windows":
            os.chmod(dest_path, 0o755)
        
        logger.info(f"Stockfish has been successfully installed to: {dest_path}")
        return True

if __name__ == "__main__":
    if main():
        logger.info("Stockfish installation completed successfully")
    else:
        logger.error("Stockfish installation failed")
        sys.exit(1)
