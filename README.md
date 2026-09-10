# TeleDrive 2.0

> Use your Telegram account as an unlimited, free personal cloud drive from the terminal.

TeleDrive turns Telegram's Saved Messages into a full-featured cloud storage backend. It slices large files into 50 MB chunks, streams them to Telegram, and reconstructs them whenever you need them.

The original prototype worked in theory, but suffered from critical flaws: it wiped users' Saved Messages on deletion, ran out of RAM on files larger than 1 GB, couldn't handle folders with subdirectories, and corrupted re-downloaded files.

**TeleDrive 2.0 is a complete rewrite** focused on reliability, data integrity, and real cloud-drive features like trash, rename, move, and directory tree preservation.

```text
       ▄▄████████▄▄       TeleDrive 2.0
     ▄███▀▀▀    ▀▀███▄     Telegram Cloud Storage Engine
    ███▀   ▄▄██▄▄   ▀███   Fast • Resilient • End-to-End
   ███    ████████    ███  Type 'teledrive --help' for commands
    ███▄   ▀▀██▀▀   ▄███   
     ▀███▄▄▄    ▄▄▄███▀    
       ▀▀████████▀▀       
```

---

## Why TeleDrive 2.0?

* **No RAM spikes on big files**: Reads and uploads in 64 KB streaming buffers. Uploading a 20 GB file uses the same ~30 MB of RAM as a 5 MB file.
* **Safe message deletion**: Every chunk's exact Telegram message ID is tracked in SQLite. Deleting or purging files removes *only* the specific chunk messages—it will never touch your personal notes or messages in Saved Messages.
* **Full folder trees & subdirectories**: Upload an entire folder hierarchy (including nested subfolders and empty directories). Downloading it restores the exact same tree structure locally.
* **End-to-end SHA-256 checks**: Every chunk and file is hashed on upload and verified on download. If a byte gets corrupted during transfer, it catches it immediately before touching your destination file.
* **Resume interrupted transfers**: Network cut out at 90%? Run `teledrive resume <id> --source <file>` to continue right from the last chunk instead of starting over.
* **Self-healing repair**: If Telegram loses or corrupts a chunk down the road, `teledrive repair` re-uploads just the missing pieces.
* **Real cloud drive features**:
  * **Soft-delete Trash**: Files go to the trash bin first (`teledrive trash` / `teledrive restore`) before permanent removal (`teledrive purge`).
  * **Instant rename & move**: Reorganize files and folders in SQLite without re-uploading anything to Telegram.
  * **Portable backups**: Export your metadata to JSON and restore it on another computer (`teledrive export` / `import`).
* **Clean terminal interface**: Electric-blue theme with real-time transfer speeds, dual progress bars, tree visualizer, and an interactive shell (`teledrive interactive`).

---

## 🏗️ Architecture

```text
                    ┌─────────────────────────┐
                    │      CLI / REPL         │
                    │  argparse • Rich UI     │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │    Storage Service      │
                    │ Upload • Download • Sync│
                    ├────────────┬────────────┤
                    │            │            │
       ┌────────────▼───┐        │       ┌────▼───────────┐
       │     SQLite     │        │       │    Telegram    │
       │ Normalized DB  │        │       │ Async Telethon │
       │  Foreign Keys  │        │       │  Message IDs   │
       └────────────────┘        │       └────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Streaming I/O & SHA256 │
                    │ Atomic .part • Chunker  │
                    └─────────────────────────┘
```

---

## 📦 Installation & Setup

### 1. Prerequisites
* Python 3.10 or higher
* Telegram account and API credentials from [my.telegram.org](https://my.telegram.org)

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Credentials
Copy `example.config.json` to `config.json`:
```bash
cp example.config.json config.json
```

Edit `config.json` with your credentials:
```json
{
  "telegram_api_id": 1234567,
  "telegram_api_hash": "your_api_hash_here",
  "phone_number": "+1234567890",
  "db_file": "teledrive.db",
  "session_name": "teledrive.session",
  "temp_dir": ".teledrive_temp",
  "chunk_size": 52428800,
  "verbose": false
}
```

> **Note**: You can also set configuration paths via the `TELEDRIVE_CONFIG` or `TELESYNC_CONFIG` environment variable or the `--config` CLI option.

---

## 💻 CLI Reference

### 📤 Upload Files & Directories
```bash
# Upload a single file
python main.py upload /path/to/movie.iso

# Upload an entire directory recursively
python main.py upload /path/to/my_project/
```

### 📥 Download & Reconstruct
```bash
# Download by ID or name
python main.py download 7f89d3a1

# Specify output destination
python main.py download 7f89d3a1 --output ./restored/

# Overwrite existing destination file safely
python main.py download 7f89d3a1 --force
```

### 📋 List & Search
```bash
# List all active files and folders
python main.py list

# View items in the trash bin
python main.py list --trashed

# Output structured JSON for automation/scripts
python main.py list --json
```

### 🔍 Metadata & Remote Verification
```bash
# Inspect file details, chunk breakdown, and hashes
python main.py info 7f89d3a1

# Audit remote Telegram storage for missing or damaged chunks
python main.py verify 7f89d3a1
```

### 🔧 Self-Healing & Resume
```bash
# Resume an interrupted upload from the last chunk
python main.py resume 7f89d3a1 --source /path/to/local/file.iso

# Repair missing remote chunks from original file
python main.py repair 7f89d3a1 --source /path/to/local/file.iso
```

### ✏️ Rename & Organize
```bash
# Rename file in metadata (zero-cost, no re-upload)
python main.py rename 7f89d3a1 "new_name.iso"

# Move file into a logical directory
python main.py move 7f89d3a1 "Projects"
```

### 🗑️ Trash System (Soft Delete & Permanent Purge)
```bash
# Move file to trash (chunks remain safe in Telegram)
python main.py trash 7f89d3a1

# Restore file from trash
python main.py restore 7f89d3a1

# Permanently delete an item from Telegram and database
python main.py purge 7f89d3a1 --force

# Empty the entire trash bin permanently
python main.py purge --force
```

### 💾 Backup & Restore Metadata
```bash
# Export metadata backup to JSON
python main.py export --output teledrive_backup.json

# Restore metadata onto a new computer without re-uploading
python main.py import teledrive_backup.json
```

### 🖥️ Interactive Shell
Run TeleDrive without arguments or use the `interactive` subcommand to enter the real-time shell:
```bash
python main.py interactive
```

---

## 🧪 Testing

TeleDrive 2.0 includes a test suite covering CLI parsing, streaming chunkers, cryptographic hashing, atomic reconstruction, and Telegram mocks:

```bash
python -m pytest tests -v
```

---

## ⚙️ Standard Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | General application error |
| `2` | Invalid CLI syntax or arguments |
| `3` | Configuration or authentication error |
| `4` | Transfer or network error |
| `5` | SHA-256 integrity mismatch |

---

## ⚠️ Limitations

* **Telegram File Size Limit**: Telegram limits individual uploaded media to 2 GB per file (4 GB for Telegram Premium accounts). TeleDrive automatically chunks large files into 50 MB parts to ensure compatibility.
* **FloodWait Limits**: Telegram enforces rate limits on rapid message creation. TeleDrive automatically catches `FloodWaitError` and backs off gracefully.
* **Saved Messages**: Chunks are stored in your private Saved Messages chat (`"me"`). Do not manually delete numbered `TELEDRIVE_V2` messages from your Telegram client, or use `teledrive repair` if accidentally deleted.

---

## 📄 License
MIT License.
