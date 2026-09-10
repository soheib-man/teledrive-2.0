# TeleDrive 2.0

> **High-Performance, Fault-Tolerant Cloud Storage Engine Powered by Telegram.**

TeleDrive 2.0 transforms Telegram into a resilient, unlimited personal cloud storage backend. Designed from the ground up for data integrity, streaming performance, and safety, TeleDrive 2.0 delivers a modern developer experience featuring an **Electric-Blue TrueColor terminal interface**, zero-RAM bloat chunking, cryptographic verification, and full-featured cloud-drive management.

```text
       ▄▄████████▄▄       TeleDrive 2.0 v2.0.0
     ▄███▀▀▀    ▀▀███▄     Telegram Cloud Storage Engine
    ███▀   ▄▄██▄▄   ▀███   Fast • Resilient • End-to-End Cloud Drive
   ███    ████████    ███  Type teledrive --help for commands
    ███▄   ▀▀██▀▀   ▄███   
     ▀███▄▄▄    ▄▄▄███▀    
       ▀▀████████▀▀       
```

---

## 🚀 Key Highlights

* **⚡ Constant-Memory Streaming Chunker**: Streams files in 64 KB memory buffers into 50 MB chunks without loading multi-gigabyte files into RAM. Zero disk duplication.
* **🛡️ Zero-Collateral Safe Deletion**: Chunks are indexed strictly by exact Telegram message IDs stored in SQLite. Deletion prunes **only** the exact messages belonging to the file—never touching your personal Saved Messages.
* **🔒 End-to-End SHA-256 Integrity**: Incremental SHA-256 hashes are computed on upload and verified on download. Reconstruction writes to atomic `.part` files with automatic overwrite protection.
* **♻️ Resilient Transfers & Resume**: Interrupted uploads can be resumed instantly with `teledrive resume <id> --source <file>` from the last pending chunk. Automatic exponential backoff handles network dropouts and Telegram `FloodWaitError` limits.
* **📁 Deep Recursive Directories**: Preserves complete directory hierarchies, handles nested subfolders without path traversal vulnerabilities, and restores directory trees accurately.
* **🗄️ Full Cloud-Drive Management**:
  * **Soft-Delete Trash & Restore**: Recover accidentally deleted files with `trash` and `restore` before running `purge`.
  * **Zero-Cost Rename & Move**: Update file names and reorganize folder structures in SQLite metadata instantly without re-uploading Telegram chunks.
  * **Self-Healing Repair**: Re-upload only missing or damaged chunks from a local file with `teledrive repair`.
  * **Portable Metadata Backup**: Export and restore your complete storage database across machines using `export` and `import`.
* **🎨 Electric-Blue Rich Terminal UX**: TrueColor 24-bit gradients, dual progress bars with live transfer speeds and ETAs, formatted tables, and an interactive shell (`teledrive interactive`).

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
