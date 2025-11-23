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

dotenv.load_dotenv()

# API Configuration
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").lower()  # Options: "gemini" or "mistral"
MODEL_NAME = os.getenv("MODEL_NAME")

API_KEY = os.getenv("API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

DAILY_BATCH_LIMIT = int(os.getenv("DAILY_BATCH_LIMIT", 500))
REQUESTS_PER_MINUTE = int(os.getenv("REQUESTS_PER_MINUTE", 15))

# Separate log files
COMPLETED_FILES_LOG = os.path.abspath(os.getenv("COMPLETED_FILES_LOG", "completed_files.log"))
APPLICATION_LOG = os.path.abspath(os.getenv("APPLICATION_LOG", "application.log"))


def setup_logging():
    """Configure logging to write errors and exceptions to application.log"""
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Remove any existing handlers
    logger.handlers = []
    
    # File handler for application log (errors and exceptions)
    file_handler = logging.FileHandler(APPLICATION_LOG, encoding='utf-8')
    file_handler.setLevel(logging.ERROR)
    file_formatter = logging.Formatter('%(asctime)s %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # Console handler for general info
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def load_completed_files():
    """Return a set of completed file paths from completed_files.log"""
    if os.path.exists(COMPLETED_FILES_LOG):
        with open(COMPLETED_FILES_LOG, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f.readlines() if line.strip())
    return set()


def save_completed_file(filename):
    """Save completed file path to completed_files.log"""
    path = os.path.abspath(filename)
    os.makedirs(os.path.dirname(COMPLETED_FILES_LOG), exist_ok=True) if os.path.dirname(COMPLETED_FILES_LOG) else None
    with open(COMPLETED_FILES_LOG, "a", encoding="utf-8") as f:
        f.write(path + "\n")


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
        model=MODEL_NAME,
        contents=[image_part, prompt_text]
    )

    # Extract text response
    if hasattr(response, "text"):
        return response.text.strip()
    if hasattr(response, "output"):
        return str(response.output).strip()
    return str(response).strip()


def tag_image_mistral(client, image_path):
    """Extract tags using Mistral Pixtral"""
    # Get base64 encoded image
    base64_image = encode_image_base64(image_path)
    ext = image_path.lower().split(".")[-1]
    
    # Determine mime type
    mime_types = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png"}
    mime_type = mime_types.get(ext, "image/jpeg")
    
    prompt_text = (
        "Analyze this image and identify up to 15 distinct objects, people, animals, food items, "
        "scenes, activities, or things present in the photo. "
        "Return ONLY a comma-separated list of these items. "
        "Examples: dog, beach, baby, cake, sunrise, beer, car, tree, person, building. "
        "Be specific and concise. Do not include any other text, just the comma-separated list."
    )
    
    # Create message with image
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
    
    # Call Mistral API
    response = client.chat.complete(
        model=MODEL_NAME,
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
            except:
                # If no EXIF data exists, create new
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            
            # Add tags to ImageDescription (0x010e) and UserComment (0x9286)
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = tags.encode('utf-8')
            exif_dict["Exif"][piexif.ExifIFD.UserComment] = tags.encode('utf-8')
            
            # Save EXIF back to image
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, image_path)
            logger.info("Added EXIF metadata to: %s", os.path.basename(image_path))
            
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


def batch_process_images(image_dir, logger):
    """Process images in batches, tracking completed files separately"""
    client = initialize_client(AI_PROVIDER, logger)
    completed = load_completed_files()
    
    # Normalize incoming directory and make sure it exists
    image_dir = os.path.abspath(image_dir)
    if not os.path.isdir(image_dir):
        logger.error("Image directory does not exist: %s", image_dir)
        return

    all_images = [os.path.join(image_dir, f) for f in os.listdir(image_dir)
                  if f.lower().endswith(("jpg", "jpeg", "png", "heic"))]
    
    # Only process new files not in completed_files.log
    to_process = [img for img in all_images if img not in completed]
    
    batch_today = to_process[:int(DAILY_BATCH_LIMIT)]
    
    logger.info("[%s] Starting batch of %d images...", datetime.now(), len(batch_today))
    logger.info("Total images found: %d, Already completed: %d, To process: %d", 
                len(all_images), len(completed), len(to_process))
    
    requests_sent = 0
    
    for img in batch_today:
        try:
            result = tag_image(client, img, AI_PROVIDER)
            
            # Log the comma-separated objects
            logger.info("Processed %s: %s", os.path.basename(img), result)
            
            # Add tags to file metadata
            add_tags_to_metadata(img, result, logger)
            
            # Save to completed files log
            save_completed_file(img)
            requests_sent += 1
            
            # Respect requests per minute limit
            if requests_sent % REQUESTS_PER_MINUTE == 0:
                print(f"Pausing for rate limit... ({requests_sent} requests sent)")
                time.sleep(60)
                
        except Exception as e:
            logger.exception("Error processing %s: %s", os.path.basename(img), str(e))
            # Continue processing other images instead of exiting
            continue
    
    remaining = len(to_process) - len(batch_today)
    logger.info("[%s] Batch done. %d images remaining.", datetime.now(), remaining)


def main():
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("Image Tagging Script Started")
    logger.info("=" * 60)
    
    batch_process_images("./photos", logger)
    
    logger.info("Script completed successfully")


if __name__ == "__main__":
    main()