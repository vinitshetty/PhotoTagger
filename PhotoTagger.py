import os
import time
import argparse
import logging
from google import genai
from google.genai import types
from mistralai import Mistral
from datetime import datetime
import dotenv
from PIL import Image
from PIL.ExifTags import TAGS
from PIL import PngImagePlugin
import piexif
import base64
import json
from pathlib import Path

dotenv.load_dotenv()

# API Configuration
API_KEY = os.getenv("API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").lower()  # Options: "gemini" or "mistral"

# Scanning mode: "backlog" or "incremental"
SCAN_MODE = os.getenv("SCAN_MODE", "backlog").lower()

DAILY_BATCH_LIMIT = int(os.getenv("DAILY_BATCH_LIMIT", 500))
REQUESTS_PER_MINUTE = int(os.getenv("REQUESTS_PER_MINUTE", 15))

# Photos base path
PHOTOS_BASE_PATH = os.getenv("PHOTOS_BASE_PATH", r"\\vinut_syno\home\Photos")

# Log and tracking files
COMPLETED_FILES_LOG = os.path.abspath(os.getenv("COMPLETED_FILES_LOG", "completed_files.log"))
PROCESSING_LIST_FILE = os.path.abspath(os.getenv("PROCESSING_LIST_FILE", "processing_list.json"))
APPLICATION_LOG = os.path.abspath(os.getenv("APPLICATION_LOG", "application.log"))
STATE_FILE = os.path.abspath(os.getenv("STATE_FILE", "scan_state.json"))


def setup_logging():
    """Configure logging to write errors and exceptions to application.log"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers = []
    
    file_handler = logging.FileHandler(APPLICATION_LOG, encoding='utf-8')
    file_handler.setLevel(logging.ERROR)
    file_formatter = logging.Formatter('%(asctime)s %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def normalize_path(full_path):
    """Normalize path to start from Photos folder"""
    full_path = str(full_path)
    if "Photos" in full_path:
        # Find the index of Photos and take everything from there
        idx = full_path.find("Photos")
        return full_path[idx:].replace("\\", "/")
    return full_path.replace("\\", "/")


def load_scan_state():
    """Load the last scan timestamp"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                return state.get("last_scan_timestamp", 0)
        except:
            return 0
    return 0


def save_scan_state(timestamp):
    """Save the current scan timestamp"""
    state = {"last_scan_timestamp": timestamp}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def load_processing_list():
    """Load the processing list with file paths and timestamps"""
    if os.path.exists(PROCESSING_LIST_FILE):
        try:
            with open(PROCESSING_LIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Return as dict for easy lookup
                return {item["normalized_path"]: item for item in data}
        except:
            return {}
    return {}


def save_processing_list(processing_dict):
    """Save the processing list as array"""
    # Convert dict to list for JSON storage
    processing_list = list(processing_dict.values())
    with open(PROCESSING_LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(processing_list, f, indent=2)


def load_completed_files():
    """Return dict of completed files with timestamps from completed_files.log"""
    if os.path.exists(COMPLETED_FILES_LOG):
        try:
            with open(COMPLETED_FILES_LOG, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {item["normalized_path"]: item for item in data}
        except:
            # Try legacy format (plain text)
            with open(COMPLETED_FILES_LOG, "r", encoding="utf-8") as f:
                legacy_set = set(line.strip() for line in f.readlines() if line.strip())
                return {path: {"normalized_path": path, "completed_time": 0} for path in legacy_set}
    return {}


def save_completed_file(normalized_path, full_path):
    """Add completed file to completed_files.log"""
    completed_dict = load_completed_files()
    
    completed_dict[normalized_path] = {
        "normalized_path": normalized_path,
        "full_path": full_path,
        "completed_time": time.time()
    }
    
    # Save as JSON array
    completed_list = list(completed_dict.values())
    with open(COMPLETED_FILES_LOG, "w", encoding="utf-8") as f:
        json.dump(completed_list, f, indent=2)


def get_file_modification_time(filepath):
    """Get file modification timestamp"""
    try:
        return os.path.getmtime(filepath)
    except:
        return 0


def scan_for_new_files(base_path, last_scan_time, scan_mode, logger):
    """
    Recursively scan for image files.
    In 'backlog' mode: scans ALL files regardless of timestamp
    In 'incremental' mode: only files modified after last_scan_time
    Returns dict of {normalized_path: file_info}
    """
    new_files = {}
    supported_extensions = ('.jpg', '.jpeg', '.png', '.heic')
    
    logger.info("Scanning for files in: %s", base_path)
    
    if scan_mode == "backlog":
        logger.info("BACKLOG MODE: Scanning ALL files (ignoring timestamps)")
    else:
        logger.info("INCREMENTAL MODE: Scanning files modified after: %s", 
                    datetime.fromtimestamp(last_scan_time).strftime('%Y-%m-%d %H:%M:%S') if last_scan_time > 0 else "beginning of time")
    
    file_count = 0
    try:
        for root, dirs, files in os.walk(base_path):
            for file in files:
                if file.lower().endswith(supported_extensions):
                    full_path = os.path.join(root, file)
                    mod_time = get_file_modification_time(full_path)
                    
                    # In backlog mode, add all files. In incremental mode, only new files
                    if scan_mode == "backlog" or mod_time > last_scan_time:
                        normalized = normalize_path(full_path)
                        new_files[normalized] = {
                            "full_path": full_path,
                            "mod_time": mod_time
                        }
                        file_count += 1
                        
                        # Log progress every 100 files in backlog mode
                        if scan_mode == "backlog" and file_count % 100 == 0:
                            logger.info("Scanned %d files so far... (latest: %s)", file_count, normalized)
        
        logger.info("Scan complete: Found %d files total", len(new_files))
        return new_files
    
    except Exception as e:
        logger.error("Error scanning directory: %s", str(e))
        return {}


def update_processing_list(base_path, scan_mode, logger):
    """
    Update processing list with files.
    In 'backlog' mode: scans all files
    In 'incremental' mode: only scans files modified after last scan timestamp
    """
    # Load existing processing list
    processing_dict = load_processing_list()
    
    # Get last scan timestamp (only relevant for incremental mode)
    last_scan_time = load_scan_state() if scan_mode == "incremental" else 0
    
    # Scan for files based on mode
    new_files = scan_for_new_files(base_path, last_scan_time, scan_mode, logger)
    
    # Add new files to processing list (avoiding duplicates)
    added_count = 0
    for normalized_path, file_info in new_files.items():
        if normalized_path not in processing_dict:
            processing_dict[normalized_path] = {
                "normalized_path": normalized_path,
                "full_path": file_info["full_path"],
                "mod_time": file_info["mod_time"],
                "added_time": time.time()
            }
            added_count += 1
    
    # Save updated processing list
    save_processing_list(processing_dict)
    
    # Update scan timestamp (for incremental mode)
    if scan_mode == "incremental":
        current_time = time.time()
        save_scan_state(current_time)
    
    logger.info("Added %d new files to processing list", added_count)
    logger.info("Total files in processing list: %d", len(processing_dict))
    
    return processing_dict


def encode_image_base64(image_path):
    """Encode image to base64 for Mistral API"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode('utf-8')


def tag_image_gemini(client, image_path):
    """Extract tags using Google Gemini"""
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    ext = image_path.lower().split(".")[-1]
    mime_types = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png", "heic": "image/heic"}
    
    mime_type = mime_types.get(ext)
    if not mime_type:
        raise ValueError(f"Unsupported format: {ext}")
    
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    
    prompt_text = (
        "Analyze this image and identify up to 15 distinct objects, people, animals, food items, "
        "scenes, activities, or things present in the photo. "
        "Return ONLY a comma-separated list of these items. "
        "Examples: dog, beach, baby, cake, sunrise, beer, car, tree, person, building. "
        "Be specific and concise. Do not include any other text, just the comma-separated list."
    )
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[image_part, prompt_text]
    )

    if hasattr(response, "text"):
        return response.text.strip()
    if hasattr(response, "output"):
        return str(response.output).strip()
    return str(response).strip()


def tag_image_mistral(client, image_path):
    """Extract tags using Mistral Pixtral"""
    base64_image = encode_image_base64(image_path)
    ext = image_path.lower().split(".")[-1]
    
    mime_types = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png"}
    mime_type = mime_types.get(ext, "image/jpeg")
    
    prompt_text = (
        "Analyze this image and identify up to 15 distinct objects, people, animals, food items, "
        "scenes, activities, or things present in the photo. "
        "Return ONLY a comma-separated list of these items. "
        "Examples: dog, beach, baby, cake, sunrise, beer, car, tree, person, building. "
        "Be specific and concise. Do not include any other text, just the comma-separated list."
    )
    
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt_text
                },
                {
                    "type": "image_url",
                    "image_url": f"data:{mime_type};base64,{base64_image}"
                }
            ]
        }
    ]
    
    response = client.chat.complete(
        model="pixtral-12b-2409",
        messages=messages
    )
    
    return response.choices[0].message.content.strip()


def tag_image(client, image_path, provider):
    """Route to appropriate tagging function based on provider"""
    if provider == "gemini":
        return tag_image_gemini(client, image_path)
    elif provider == "mistral":
        return tag_image_mistral(client, image_path)
    else:
        raise ValueError(f"Unsupported AI provider: {provider}")


def create_png_info(metadata):
    """Helper to create PNG info object"""
    png_info = PngImagePlugin.PngInfo()
    for key, value in metadata.items():
        if isinstance(value, str):
            png_info.add_text(key, value)
    return png_info


def add_tags_to_metadata(image_path, tags, logger):
    """Add tags to image file metadata (EXIF for JPEG, PNG metadata for PNG)"""
    try:
        ext = image_path.lower().split(".")[-1]
        
        if ext in ['jpg', 'jpeg']:
            # Handle JPEG files with EXIF
            try:
                exif_dict = piexif.load(image_path)
            except Exception as e:
                logger.warning("Could not load existing EXIF from %s: %s. Creating new EXIF.", 
                             os.path.basename(image_path), str(e))
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            
            # Clean the EXIF dict to remove problematic tags
            # Remove tags that commonly cause issues with piexif
            problematic_tags = [
                41729,  # FileSource
                41730,  # SceneType
                41988,  # DigitalZoomRatio
                41985,  # CustomRendered
                41986,  # ExposureMode
                41987,  # WhiteBalance
                41989,  # FocalLengthIn35mmFilm
                41990,  # SceneCaptureType
                41991,  # GainControl
                41992,  # Contrast
                41993,  # Saturation
                41994,  # Sharpness
                41995,  # DeviceSettingDescription
                41996,  # SubjectDistanceRange
            ]
            if "Exif" in exif_dict:
                for tag in problematic_tags:
                    exif_dict["Exif"].pop(tag, None)
            
            # Add tags to ImageDescription (0x010e) and UserComment (0x9286)
            try:
                exif_dict["0th"][piexif.ImageIFD.ImageDescription] = tags.encode('utf-8')
                exif_dict["Exif"][piexif.ExifIFD.UserComment] = tags.encode('utf-8')
                
                # Save EXIF back to image
                exif_bytes = piexif.dump(exif_dict)
                piexif.insert(exif_bytes, image_path)
                logger.info("Added EXIF metadata to: %s", os.path.basename(image_path))
            except Exception as e:
                # If dump/insert fails, try with minimal EXIF (only our tags)
                logger.warning("Standard EXIF write failed for %s, trying minimal EXIF: %s", 
                             os.path.basename(image_path), str(e))
                minimal_exif = {
                    "0th": {piexif.ImageIFD.ImageDescription: tags.encode('utf-8')},
                    "Exif": {piexif.ExifIFD.UserComment: tags.encode('utf-8')},
                    "GPS": {},
                    "1st": {},
                    "thumbnail": None
                }
                exif_bytes = piexif.dump(minimal_exif)
                piexif.insert(exif_bytes, image_path)
                logger.info("Added minimal EXIF metadata to: %s", os.path.basename(image_path))
            
        elif ext == 'png':
            # Handle PNG files with PIL
            img = Image.open(image_path)
            metadata = img.info.copy()
            metadata['Description'] = tags
            metadata['Title'] = tags
            metadata['Comment'] = tags
            
            # Save with metadata
            img.save(image_path, "PNG", pnginfo=create_png_info(metadata))
            logger.info("Added PNG metadata to: %s", os.path.basename(image_path))
            
        elif ext == 'heic':
            # HEIC files are more complex, log that we're skipping
            logger.warning("HEIC metadata writing not supported, skipping: %s", os.path.basename(image_path))
            
    except Exception as e:
        logger.error("Failed to add metadata to %s: %s", os.path.basename(image_path), str(e))


def initialize_client(provider, logger):
    """Initialize the appropriate AI client based on provider"""
    if provider == "gemini":
        if not API_KEY:
            logger.error("API_KEY not found in environment variables for Gemini")
            raise ValueError("API_KEY is required for Gemini provider")
        logger.info("Using Google Gemini (gemini-2.5-flash)")
        return genai.Client(api_key=API_KEY)
    
    elif provider == "mistral":
        if not MISTRAL_API_KEY:
            logger.error("MISTRAL_API_KEY not found in environment variables")
            raise ValueError("MISTRAL_API_KEY is required for Mistral provider")
        logger.info("Using Mistral Pixtral (pixtral-12b-2409)")
        return Mistral(api_key=MISTRAL_API_KEY)
    
    else:
        logger.error(f"Unknown AI provider: {provider}")
        raise ValueError(f"Unsupported AI provider: {provider}. Use 'gemini' or 'mistral'")


def batch_process_images(base_path, logger):
    """Process images in batches using processing list and completed list delta"""
    client = initialize_client(AI_PROVIDER, logger)
    
    # Load existing processing list first
    processing_dict = load_processing_list()
    existing_count = len(processing_dict)
    
    if existing_count > 0:
        logger.info("=" * 60)
        logger.info("FOUND EXISTING PROCESSING LIST with %d files", existing_count)
        logger.info("Checking if backlog is complete...")
        logger.info("=" * 60)
    
    # Load completed files
    logger.info("Loading completed files list...")
    completed_dict = load_completed_files()
    
    # Calculate delta for existing processing list
    to_process = []
    for normalized_path, file_info in processing_dict.items():
        if normalized_path not in completed_dict:
            to_process.append((normalized_path, file_info["full_path"]))
    
    # If existing processing list is fully completed, scan for new files
    if existing_count > 0 and len(to_process) == 0:
        logger.info("=" * 60)
        logger.info("EXISTING PROCESSING LIST FULLY COMPLETED!")
        logger.info("Now scanning for new files based on SCAN_MODE: %s", SCAN_MODE.upper())
        logger.info("=" * 60)
        # Rebuild processing list
        processing_dict = update_processing_list(base_path, SCAN_MODE, logger)
        logger.info("Processing list updated and saved to: %s", PROCESSING_LIST_FILE)
        
        # Recalculate delta with new processing list
        to_process = []
        for normalized_path, file_info in processing_dict.items():
            if normalized_path not in completed_dict:
                to_process.append((normalized_path, file_info["full_path"]))
    
    # If no existing processing list, build it now
    elif existing_count == 0:
        logger.info("Step 1: Building processing list (Mode: %s)...", SCAN_MODE.upper())
        processing_dict = update_processing_list(base_path, SCAN_MODE, logger)
        logger.info("Processing list built and saved to: %s", PROCESSING_LIST_FILE)
        
        # Calculate delta
        to_process = []
        for normalized_path, file_info in processing_dict.items():
            if normalized_path not in completed_dict:
                to_process.append((normalized_path, file_info["full_path"]))
    
    logger.info("Processing list: %d files", len(processing_dict))
    logger.info("Completed list: %d files", len(completed_dict))
    logger.info("Delta (to process): %d files", len(to_process))
    
    if len(to_process) == 0:
        logger.info("No files to process. All caught up!")
        return
    
    # Step 4: Limit to daily batch size
    batch_today = to_process[:DAILY_BATCH_LIMIT]
    
    logger.info("[%s] Starting batch of %d images...", datetime.now(), len(batch_today))
    
    requests_sent = 0
    
    for normalized_path, full_path in batch_today:
        try:
            # Check if file still exists
            if not os.path.exists(full_path):
                logger.warning("File not found, skipping: %s", normalized_path)
                # Still mark as completed to avoid repeated checks
                save_completed_file(normalized_path, full_path)
                continue
            
            result = tag_image(client, full_path, AI_PROVIDER)
            
            logger.info("Processed %s: %s", os.path.basename(full_path), result)
            
            # Add tags to file metadata
            add_tags_to_metadata(full_path, result, logger)
            
            # Add to completed files list
            save_completed_file(normalized_path, full_path)
            requests_sent += 1
            
            # Respect requests per minute limit
            if requests_sent % REQUESTS_PER_MINUTE == 0:
                print(f"Pausing for rate limit... ({requests_sent} requests sent)")
                time.sleep(60)
                
        except Exception as e:
            logger.exception("Error processing %s: %s", normalized_path, str(e))
            continue
    
    # Calculate remaining after this batch
    remaining = len(to_process) - len(batch_today)
    logger.info("[%s] Batch done. %d images remaining in delta.", datetime.now(), remaining)


def main():
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("Image Tagging Script Started")
    logger.info("Scan Mode: %s", SCAN_MODE.upper())
    logger.info("AI Provider: %s", AI_PROVIDER.upper())
    logger.info("Photos base path: %s", PHOTOS_BASE_PATH)
    logger.info("=" * 60)
    
    batch_process_images(PHOTOS_BASE_PATH, logger)
    
    logger.info("Script completed successfully")


if __name__ == "__main__":
    main()