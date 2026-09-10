"""Command-line interface and interactive shell for TeleDrive 2.0."""

import argparse
import asyncio
import json
import logging
import shlex
import sys
from pathlib import Path
from typing import List, Optional

from teledrive import __version__, __app_name__
from teledrive.config import Config
from teledrive.constants import (
    EXIT_CONFIG_AUTH,
    EXIT_ERROR,
    EXIT_INTEGRITY,
    EXIT_SUCCESS,
    EXIT_TRANSFER,
    EXIT_USAGE,
)
from teledrive.exceptions import (
    AmbiguousQueryError,
    ConfigurationError,
    FileExistsSafetyError,
    IntegrityError,
    ItemNotFoundError,
    TeleDriveError,
    TelegramServiceError,
    TransferError,
)
from teledrive.models import TransferProgress
from teledrive.services import StorageService
from teledrive.ui import (
    console,
    make_transfer_progress,
    print_banner,
    print_error,
    print_info,
    print_success,
    print_warning,
    render_file_table,
    render_info_card,
    render_verify_results,
    render_directory_tree,
    COLOR_CYAN,
    COLOR_SKY_BLUE,
    COLOR_ICE_WHITE,
    COLOR_MUTED,
)

logger = logging.getLogger("teledrive")


def build_parser() -> argparse.ArgumentParser:
    """Builds the comprehensive CLI parser."""
    parser = argparse.ArgumentParser(
        prog="teledrive",
        description=f"{__app_name__} - Telegram-backed resilient cloud storage.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", "-v", action="version", version=f"{__app_name__} {__version__}")
    parser.add_argument("--config", "-c", type=str, help="Path to config.json file")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress non-essential banner and info")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # upload
    p_upload = subparsers.add_parser("upload", help="Upload a file or directory to Telegram cloud")
    p_upload.add_argument("path", type=str, help="Path to file or directory to upload")

    # download
    p_download = subparsers.add_parser("download", help="Download and reconstruct a file or directory")
    p_download.add_argument("query", type=str, help="File/directory ID, name, or search term")
    p_download.add_argument("--output", "-o", type=str, help="Destination directory or filename")
    p_download.add_argument("--force", "-f", action="store_true", help="Overwrite destination if it already exists")

    # list
    p_list = subparsers.add_parser("list", help="List stored files and directories")
    p_list.add_argument("--trashed", action="store_true", help="Show items currently in the trash bin")
    p_list.add_argument("--all", "-a", action="store_true", help="Show active and trashed items")

    # info
    p_info = subparsers.add_parser("info", help="Inspect detailed metadata and chunk status")
    p_info.add_argument("query", type=str, help="Item ID, name, or query")

    # tree
    p_tree = subparsers.add_parser("tree", help="Visualize recursive directory hierarchy")
    p_tree.add_argument("query", type=str, help="Directory ID or name")

    # verify
    p_verify = subparsers.add_parser("verify", help="Check remote chunk availability and checksum integrity")
    p_verify.add_argument("query", type=str, help="Item ID, name, or query")

    # repair
    p_repair = subparsers.add_parser("repair", help="Repair missing or corrupted remote chunks from local file")
    p_repair.add_argument("query", type=str, help="File ID or name")
    p_repair.add_argument("--source", "-s", type=str, required=True, help="Path to original local source file")

    # resume
    p_resume = subparsers.add_parser("resume", help="Resume an interrupted upload from the last chunk")
    p_resume.add_argument("query", type=str, help="File ID or name")
    p_resume.add_argument("--source", "-s", type=str, required=True, help="Path to original local source file")

    # rename
    p_rename = subparsers.add_parser("rename", help="Rename an item in metadata without re-uploading")
    p_rename.add_argument("query", type=str, help="Item ID or name")
    p_rename.add_argument("new_name", type=str, help="New name for the file or directory")

    # move
    p_move = subparsers.add_parser("move", help="Move a file into a logical directory")
    p_move.add_argument("query", type=str, help="File ID or name")
    p_move.add_argument("target_dir", type=str, help="Target directory ID or name")

    # trash
    p_trash = subparsers.add_parser("trash", help="Soft-delete an item to the trash bin")
    p_trash.add_argument("query", type=str, help="Item ID or name")

    # restore
    p_restore = subparsers.add_parser("restore", help="Restore an item from the trash bin")
    p_restore.add_argument("query", type=str, help="Item ID or name")

    # purge
    p_purge = subparsers.add_parser("purge", help="Permanently delete items from Telegram and database")
    p_purge.add_argument("query", nargs="?", default=None, help="Item ID to permanently delete (or all if omitted)")
    p_purge.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompt")

    # export
    p_export = subparsers.add_parser("export", help="Export metadata backup to JSON")
    p_export.add_argument("query", nargs="?", default=None, help="Optional specific item ID to export")
    p_export.add_argument("--output", "-o", type=str, help="Destination JSON backup path")

    # import
    p_import = subparsers.add_parser("import", help="Import/restore database metadata from JSON")
    p_import.add_argument("file", type=str, help="Path to metadata JSON backup")

    # interactive
    subparsers.add_parser("interactive", help="Start interactive shell session")

    return parser


async def run_command_async(service: StorageService, args: argparse.Namespace) -> int:
    """Dispatches CLI commands to the StorageService asynchronously."""
    cmd = args.command

    # --- UPLOAD ---
    if cmd == "upload":
        target = Path(args.path).resolve()
        if not target.exists():
            print_error(f"Path does not exist: {target}")
            return EXIT_ERROR

        if target.is_dir():
            print_info(f"Scanning directory: [bold {COLOR_ICE_WHITE}]{target.name}[/]")
            dir_rec, files = await service.upload_directory(target)
            print_success(f"Uploaded directory '{dir_rec.name}' ({len(files)} files, ID: {dir_rec.id}).")
        else:
            with make_transfer_progress() as progress:
                task_id = progress.add_task(f"Uploading {target.name}", total=target.stat().st_size)

                def _cb(p: TransferProgress):
                    progress.update(task_id, completed=p.transferred_bytes)

                file_rec = await service.upload_file(target, progress_callback=_cb)

            print_success(f"Uploaded '{file_rec.name}' ({file_rec.size:,} bytes, ID: {file_rec.id}).")
        return EXIT_SUCCESS

    # --- DOWNLOAD ---
    if cmd == "download":
        dest_dir = Path(args.output).resolve() if args.output else None
        item_file, item_dir = service.resolve_single_item(args.query)

        if item_file:
            with make_transfer_progress() as progress:
                task_id = progress.add_task(f"Downloading {item_file.name}", total=item_file.size)

                def _cb(p: TransferProgress):
                    progress.update(task_id, completed=p.transferred_bytes)

                out_path = await service.download_file(
                    item_file.id,
                    destination_dir=dest_dir,
                    force=args.force,
                    progress_callback=_cb,
                )
            print_success(f"Downloaded file to [bold {COLOR_ICE_WHITE}]{out_path}[/]")
            return EXIT_SUCCESS

        if item_dir:
            print_info(f"Downloading directory structure for '{item_dir.name}'...")
            out_path = await service.download_directory(
                item_dir.id,
                destination_dir=dest_dir,
                force=args.force,
            )
            print_success(f"Downloaded directory to [bold {COLOR_ICE_WHITE}]{out_path}[/]")
            return EXIT_SUCCESS

    # --- LIST ---
    if cmd == "list":
        include_trashed = args.trashed or args.all
        if args.trashed:
            files, dirs = service.db.list_trashed_items()
            render_file_table(files, dirs, title="TeleDrive Trash Bin")
        else:
            files = service.db.list_files(include_trashed=include_trashed)
            dirs = service.db.list_directories(include_trashed=include_trashed)
            render_file_table(files, dirs)
        return EXIT_SUCCESS

    # --- INFO ---
    if cmd == "info":
        data = service.info(args.query)
        if args.json:
            console.print(json.dumps(data, indent=2))
        else:
            render_info_card(data)
        return EXIT_SUCCESS

    # --- TREE ---
    if cmd == "tree":
        tree_data = service.get_tree(args.query)
        if args.json:
            console.print(json.dumps(tree_data, indent=2))
        else:
            render_directory_tree(tree_data)
        return EXIT_SUCCESS

    # --- VERIFY ---
    if cmd == "verify":
        print_info(f"Auditing Telegram cloud storage for '{args.query}'...")
        results = await service.verify(args.query)
        if args.json:
            console.print(json.dumps(results, indent=2))
        else:
            render_verify_results(results)
        return EXIT_SUCCESS if results["verified"] else EXIT_INTEGRITY

    # --- REPAIR ---
    if cmd == "repair":
        source_file = Path(args.source).resolve()
        print_info(f"Scanning and repairing missing chunks from '{source_file.name}'...")
        res = await service.repair(args.query, source_file)
        print_success(f"Repaired {res['repaired_count']} chunk(s) for file ID {res['file_id']}.")
        return EXIT_SUCCESS

    # --- RESUME ---
    if cmd == "resume":
        source_file = Path(args.source).resolve()
        print_info(f"Resuming upload for '{args.query}'...")
        rec = await service.resume(args.query, source_file)
        print_success(f"Resumed and completed upload for '{rec.name}'.")
        return EXIT_SUCCESS

    # --- RENAME ---
    if cmd == "rename":
        service.rename(args.query, args.new_name)
        print_success(f"Renamed item to '{args.new_name}'.")
        return EXIT_SUCCESS

    # --- MOVE ---
    if cmd == "move":
        service.move(args.query, args.target_dir)
        print_success(f"Moved item into '{args.target_dir}'.")
        return EXIT_SUCCESS

    # --- TRASH ---
    if cmd == "trash":
        service.trash(args.query)
        print_success(f"Moved item '{args.query}' to trash. Use 'restore' to undo or 'purge' to remove permanently.")
        return EXIT_SUCCESS

    # --- RESTORE ---
    if cmd == "restore":
        service.restore(args.query)
        print_success(f"Restored item '{args.query}' from trash.")
        return EXIT_SUCCESS

    # --- PURGE ---
    if cmd == "purge":
        if not args.force:
            target_desc = f"item '{args.query}'" if args.query else "ALL items in the trash"
            console.print(f"[bold {COLOR_WARNING}]WARNING:[/] This will permanently delete {target_desc} from Telegram.")
            confirm = input("Are you sure you want to proceed? [y/N]: ").strip().lower()
            if confirm not in ("y", "yes"):
                print_info("Purge cancelled.")
                return EXIT_SUCCESS

        deleted_count = await service.purge(args.query)
        print_success(f"Permanently purged metadata and pruned {deleted_count} Telegram message(s).")
        return EXIT_SUCCESS

    # --- EXPORT ---
    if cmd == "export":
        out_path = Path(args.output).resolve() if args.output else None
        saved_file = service.export_metadata(args.query, out_path)
        print_success(f"Exported metadata backup to [bold {COLOR_ICE_WHITE}]{saved_file}[/]")
        return EXIT_SUCCESS

    # --- IMPORT ---
    if cmd == "import":
        import_path = Path(args.file).resolve()
        count = service.import_metadata(import_path)
        print_success(f"Imported {count} record(s) from '{import_path.name}'.")
        return EXIT_SUCCESS

    # --- INTERACTIVE ---
    if cmd == "interactive":
        await run_interactive_shell(service)
        return EXIT_SUCCESS

    return EXIT_USAGE


async def run_interactive_shell(service: StorageService) -> None:
    """Interactive shell session with instant command loop and auto-formatting."""
    print_banner()
    print_info("Entered interactive mode. Type [bold cyan]help[/] for commands or [bold cyan]exit[/] to quit.")

    while True:
        try:
            raw_input = input(f"\n[teledrive] > ").strip()
            if not raw_input:
                continue
            if raw_input in ("exit", "quit", "q"):
                print_info("Goodbye!")
                break
            if raw_input in ("clear", "cls"):
                console.clear()
                print_banner()
                continue
            if raw_input in ("help", "?"):
                console.print(
                    f"[{COLOR_CYAN}]Commands:[/] upload <path>, download <id>, list, info <id>, verify <id>, "
                    f"rename <id> <name>, move <id> <dir>, trash <id>, restore <id>, purge, exit"
                )
                continue

            cmd_parts = shlex.split(raw_input)
            parser = build_parser()
            parsed_args = parser.parse_args(cmd_parts)
            await run_command_async(service, parsed_args)

        except KeyboardInterrupt:
            console.print("\n")
            break
        except Exception as exc:
            print_error(str(exc))


def main() -> int:
    """Main CLI entrypoint with graceful exception interception."""
    parser = build_parser()

    # If executed with no arguments, display banner and launch interactive mode
    if len(sys.argv) == 1:
        print_banner()
        parser.print_help()
        console.print(f"\n[bold {COLOR_SKY_BLUE}]Tip:[/] Run [bold {COLOR_CYAN}]teledrive interactive[/] for the interactive shell.")
        return EXIT_SUCCESS

    args = parser.parse_args()

    # Logging level
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    # Banner display
    if not args.quiet and not args.json and args.command != "interactive":
        print_banner()

    # Load configuration
    try:
        config = Config.load(explicit_path=args.config, allow_missing=(args.command in ("list", "info", "tree", "export", "import", "rename", "move", "trash", "restore")))
    except ConfigurationError as exc:
        print_error(str(exc))
        return EXIT_CONFIG_AUTH

    service = StorageService(config)

    try:
        return asyncio.run(run_command_async(service, args))

    except KeyboardInterrupt:
        print_warning("\nOperation cancelled by user.")
        return EXIT_ERROR

    except ConfigurationError as exc:
        print_error(str(exc))
        return EXIT_CONFIG_AUTH

    except (TransferError, TelegramServiceError) as exc:
        print_error(str(exc))
        return EXIT_TRANSFER

    except IntegrityError as exc:
        print_error(str(exc))
        return EXIT_INTEGRITY

    except (ItemNotFoundError, AmbiguousQueryError, FileExistsSafetyError) as exc:
        print_error(str(exc))
        return EXIT_ERROR

    except TeleDriveError as exc:
        print_error(str(exc))
        return exc.exit_code

    except Exception as exc:
        if args.verbose:
            logger.exception("Unexpected error")
        else:
            print_error(f"Unexpected error: {exc}")
        return EXIT_ERROR

    finally:
        service.close()


if __name__ == "__main__":
    sys.exit(main())
