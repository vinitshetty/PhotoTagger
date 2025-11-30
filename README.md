# Photo Metadata Tagger with AI 
## (Google Photos Search Experience for all your photos)

Automatically tag your photo library using AI vision models. The script analyzes images and writes descriptive tags directly to photo metadata (EXIF/PNG properties), making your photos searchable in any file explorer or photo management app.

## 🌟 Key Features

- **AI-Powered Tagging**: Identifies up to 15 objects, people, animals, scenes, and activities per photo
- **Dual AI Provider Support**: Choose between Google Gemini or Mistral Pixtral models
- **Universal Storage Support**: Works with local disks, external drives, NAS (Synology, QNAP, etc.), and network shares
- **Cross-Platform**: Runs on Windows and Linux without reprocessing photos
- **Metadata Integration**: Writes tags to EXIF (JPEG) and PNG metadata fields (Description, Title, UserComment)
- **Incremental Processing**: Smart tracking prevents reprocessing already-tagged photos
- **Two Scanning Modes**:
  - **Backlog Mode**: Process entire existing photo library
  - **Incremental Mode**: Only scan and process new/modified photos
- **Rate Limiting**: Respects API limits with configurable batch sizes
- **Kill-Safe**: Resume from exactly where you left off after interruption
- **Detailed Logging**: Separate logs for processing status and errors
  
## Tagging
<img width="400" height="223" alt="image" src="https://github.com/user-attachments/assets/9180717e-2b80-495d-89a7-f1e6e68829ce" />

## Search
<img width="400" height="223" alt="image" src="https://github.com/user-attachments/assets/433edcb7-f395-49dd-bc6f-6a088e110b7f" />

## 📋 Requirements

```bash
pip install google-genai mistralai python-dotenv Pillow piexif
```

## 🚀 Quick Start

### 1. Create `.env` Configuration using sample file `.env-sample`

```env
# AI Provider: "gemini" or "mistral"
AI_PROVIDER=gemini

# Scan Mode: "backlog" (all files) or "incremental" (new files only)
SCAN_MODE=backlog

# API Keys (get from respective providers)
API_KEY=your_google_api_key_here
MISTRAL_API_KEY=your_mistral_api_key_here

# Photos Location (see examples below)
PHOTOS_BASE_PATH=/path/to/your/Photos

# Processing Limits
DAILY_BATCH_LIMIT=500
REQUESTS_PER_MINUTE=15

# Tracking Files (optional, uses defaults if not specified)
COMPLETED_FILES_LOG=completed_files.log
PROCESSING_LIST_FILE=processing_list.json
APPLICATION_LOG=application.log
STATE_FILE=scan_state.json
```

### 2. Set Your Photos Path

**Local Disk (Windows):**
```env
PHOTOS_BASE_PATH=C:\Users\YourName\Pictures\Photos
```

**Local Disk (Linux/Mac):**
```env
PHOTOS_BASE_PATH=/home/yourname/Pictures/Photos
```

**External Hard Drive (Windows):**
```env
PHOTOS_BASE_PATH=E:\Photos
```

**External Hard Drive (Linux/Mac):**
```env
PHOTOS_BASE_PATH=/mnt/external/Photos
PHOTOS_BASE_PATH=/Volumes/MyDrive/Photos
```

**Network Share/NAS (Windows):**
```env
PHOTOS_BASE_PATH=\\synology_nas\home\Photos
PHOTOS_BASE_PATH=\\192.168.1.100\photos\Photos
```

**Network Share/NAS (Linux - mounted):**
```env
PHOTOS_BASE_PATH=/mnt/synology/Photos
PHOTOS_BASE_PATH=/mnt/nas/Photos
```

### 3. Run the Script

```bash
python PhotoTagger.py
```

## 🔄 Workflow

### Initial Processing

1. Set `SCAN_MODE=backlog` in `.env`
2. Run script - it will scan all photos recursively in all nested folders
3. Processes up to `DAILY_BATCH_LIMIT` photos per run
4. If failed or killed - run again to process next batch (automatically handles processed photos)
5. Repeat until all photos are tagged

### Incremental New Photos Only

1. After backlog complete, set `SCAN_MODE=incremental`
2. Script only scans for new/modified photos since last run
3. Schedule with cron/Task Scheduler for automatic tagging

## 📊 How It Works

1. **Processing List**: Maintains complete list of all discovered photos
2. **Completed List**: Tracks all successfully processed photos
3. **Delta Calculation**: `processing_list - completed_list = files_to_process`
4. **Batch Processing**: Processes delta up to daily limit
5. **Metadata Writing**: Tags written to photo file properties
6. **Resume on Restart**: Always continues from last position to handle resuming from failures

## 💾 Storage Compatibility

### Local Storage
- ✅ Internal hard drives (HDD/SSD)
- ✅ External USB drives
- ✅ SD cards, portable storage, and just anything.

### Network Storage (NAS)
- ✅ Synology NAS (SMB/CIFS mount)
- ✅ QNAP NAS
- ✅ FreeNAS/TrueNAS
- ✅ Windows Network Shares
- ✅ Any SMB/NFS mounted storage

### Cloud-Synced Folders
- ✅ Dropbox, Google Drive, OneDrive (local sync folders)
- ⚠️ Note: Tags written to local files will sync to cloud

## 🔀 Cross-Platform Migration

Move your project between Windows, MacBook and Linux without reprocessing:

1. **Copy tracking files**:
   - `processing_list.json`
   - `completed_files.log`
   - `scan_state.json`

2. **Update `.env`** with new platform path

3. **Run script** - skips already completed photos automatically

Works because paths are normalized starting from "Photos" folder.

## 📁 Output Files

- **`processing_list.json`**: All discovered photos (never removes files)
- **`completed_files.log`**: Successfully tagged photos (never removes files)
- **`application.log`**: Errors and exceptions only
- **`scan_state.json`**: Last scan timestamp (incremental mode)

## 🎯 AI Models

### Google Gemini (gemini-2.5-flash)
- Fast and efficient
- Good for large batches
- Requires Google AI API key

### Mistral Pixtral (pixtral-12b-2409)
- Excellent vision capabilities
- Strong object detection
- Requires Mistral API key

## 📝 Example Tags Output

```
dog, beach, sunset, family, ocean, sand, golden retriever, waves, summer, vacation
```

Tags are written to:
- **JPEG**: EXIF ImageDescription and UserComment fields
- **PNG**: Description, Title, and Comment metadata
- **HEIC**: Not supported (logged as warning)

## 🔍 Viewing Tags

**Windows**: Right-click photo → Properties → Details tab
**Mac**: Get Info → More Info section  
**Linux**: Use `exiftool` command
**Photo Apps**: Most display Description/Title in info panels

## ⚙️ Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_PROVIDER` | `gemini` | AI model to use (`gemini` or `mistral`) |
| `SCAN_MODE` | `backlog` | Scanning mode (`backlog` or `incremental`) |
| `DAILY_BATCH_LIMIT` | `500` | Max photos to process per run |
| `REQUESTS_PER_MINUTE` | `15` | API rate limit |
| `PHOTOS_BASE_PATH` | Required | Root path to your photos |

## 🛠️ Troubleshooting

**Network path not found (Windows)**:
```bash
# Test access first
dir \\synology_nas\home\Photos
```

**Permission denied (Linux)**:
```bash
# Check mount permissions
ls -la /mnt/nas/Photos
chmod -R u+rw /mnt/nas/Photos
```

**API rate limits**:
- Adjust `REQUESTS_PER_MINUTE` in `.env`
- Reduce `DAILY_BATCH_LIMIT` if needed

## 📜 License

MIT License - Feel free to use and modify

## 🤝 Contributing

Issues and pull requests welcome!

---

**Made with ❤️ for organizing photo libraries**
