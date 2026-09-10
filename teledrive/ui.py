"""Electric-Blue terminal interface, TrueColor block gradients, and Rich formatting for TeleDrive 2.0."""

import sys
from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import (
    Progress,
    TextColumn,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    SpinnerColumn,
)
from rich.tree import Tree
from rich.text import Text

from teledrive import __version__, __app_name__
from teledrive.chunking import parse_bytes
from teledrive.models import DirectoryRecord, FileRecord

# Configure UTF-8 encoding on Windows to prevent UnicodeEncodeError
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Initialize console with UTF-8 safe settings
console = Console(force_terminal=True)

# Electric Blue Color Palette Constants
COLOR_DEEP_BLUE = "#1e3a8a"
COLOR_ROYAL_BLUE = "#2563eb"
COLOR_SKY_BLUE = "#38bdf8"
COLOR_CYAN = "#67e8f9"
COLOR_ICE_WHITE = "#f0f9ff"
COLOR_MUTED = "#94a3b8"
COLOR_SUCCESS = "#34d399"
COLOR_WARNING = "#fb923c"
COLOR_ERROR = "#f87171"


def print_banner() -> None:
    """Displays the signature TeleDrive 2.0 Electric-Blue TrueColor banner."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(no_wrap=True)
    grid.add_column(no_wrap=True)

    grid.add_row(
        f"[bold {COLOR_CYAN}]  ▄██▄  [/]",
        f"[bold {COLOR_ICE_WHITE}]{__app_name__}[/] [dim {COLOR_MUTED}]v{__version__}[/]",
    )
    grid.add_row(
        f"[bold {COLOR_SKY_BLUE}] ▄████▄ [/]",
        f"[{COLOR_SKY_BLUE}]Telegram Cloud Storage[/]",
    )
    grid.add_row(
        f"[bold {COLOR_ROYAL_BLUE}]███  ███[/]",
        f"[{COLOR_MUTED}]Fast • Resilient • End-to-End[/]",
    )
    grid.add_row(
        f"[bold {COLOR_DEEP_BLUE}] ▀████▀ [/]",
        f"[{COLOR_MUTED}]Type [bold {COLOR_CYAN}]teledrive --help[/][/]",
    )
    grid.add_row(
        f"[bold {COLOR_DEEP_BLUE}]  ▀██▀  [/]",
        "",
    )

    console.print()
    console.print(grid)
    console.print()


def print_success(message: str) -> None:
    console.print(f"[bold {COLOR_SUCCESS}]✔[/]  [{COLOR_ICE_WHITE}]{message}[/]")


def print_info(message: str) -> None:
    console.print(f"[bold {COLOR_SKY_BLUE}]ℹ[/]  [{COLOR_ICE_WHITE}]{message}[/]")


def print_warning(message: str) -> None:
    console.print(f"[bold {COLOR_WARNING}]⚠[/]  [{COLOR_ICE_WHITE}]{message}[/]")


def print_error(message: str) -> None:
    console.print(f"[bold {COLOR_ERROR}]✖[/]  [bold {COLOR_ERROR}]{message}[/]")


def make_transfer_progress() -> Progress:
    """Creates a sleek electric-blue progress bar."""
    return Progress(
        SpinnerColumn(style=f"bold {COLOR_CYAN}"),
        TextColumn(f"[bold {COLOR_ICE_WHITE}]{{task.description}}"),
        BarColumn(
            bar_width=35,
            style=COLOR_DEEP_BLUE,
            complete_style=f"bold {COLOR_SKY_BLUE}",
            finished_style=f"bold {COLOR_SUCCESS}",
        ),
        TextColumn(f"[{COLOR_CYAN}]{{task.percentage:>3.0f}}%"),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    )


def render_file_table(
    files: List[FileRecord],
    directories: List[DirectoryRecord],
    title: str = "TeleDrive Storage",
) -> None:
    """Renders a clean electric-blue table of stored files and directories."""
    table = Table(
        title=f"[{COLOR_CYAN}]{title}[/]",
        border_style=COLOR_ROYAL_BLUE,
        header_style=f"bold {COLOR_SKY_BLUE}",
        title_justify="left",
    )
    table.add_column("Type", justify="center", style=COLOR_MUTED, width=6)
    table.add_column("Name", style=f"bold {COLOR_ICE_WHITE}")
    table.add_column("Size", justify="right", style=COLOR_CYAN)
    table.add_column("Status", justify="center")
    table.add_column("ID", style=f"dim {COLOR_MUTED}", width=12)
    table.add_column("Uploaded", style=COLOR_MUTED)

    # Render Directories first
    for d in directories:
        status_text = f"[{COLOR_WARNING}]trashed[/]" if d.trashed_at else f"[{COLOR_SUCCESS}]active[/]"
        table.add_row(
            f"[{COLOR_SKY_BLUE}]DIR[/]",
            f"[bold {COLOR_SKY_BLUE}]{d.name}/[/]",
            "—",
            status_text,
            d.id[:10] + "..",
            d.created_at[:19].replace("T", " "),
        )

    # Render Files
    for f in files:
        if f.trashed_at:
            status_badge = f"[{COLOR_WARNING}]trashed[/]"
        elif f.status == "completed":
            status_badge = f"[{COLOR_SUCCESS}]completed[/]"
        elif f.status == "uploading":
            status_badge = f"[{COLOR_SKY_BLUE}]uploading[/]"
        else:
            status_badge = f"[{COLOR_ERROR}]{f.status}[/]"

        table.add_row(
            f"[{COLOR_MUTED}]FILE[/]",
            f.name,
            parse_bytes(f.size),
            status_badge,
            f.id[:10] + "..",
            f.created_at[:19].replace("T", " "),
        )

    if not files and not directories:
        console.print(f"[{COLOR_MUTED}]No items found in storage.[/]")
    else:
        console.print(table)


def render_info_card(data: Dict[str, Any]) -> None:
    """Renders a detailed information card for a file or directory."""
    if data["type"] == "file":
        rec = data["record"]
        chunks = data.get("chunks", [])
        content = (
            f"[bold {COLOR_SKY_BLUE}]Name:[/]         [{COLOR_ICE_WHITE}]{rec['name']}[/]\n"
            f"[bold {COLOR_SKY_BLUE}]ID:[/]           [{COLOR_ICE_WHITE}]{rec['id']}[/]\n"
            f"[bold {COLOR_SKY_BLUE}]Size:[/]         [{COLOR_CYAN}]{parse_bytes(rec['size'])}[/] ({rec['size']:,} bytes)\n"
            f"[bold {COLOR_SKY_BLUE}]Status:[/]       [{COLOR_SUCCESS}]{rec['status']}[/]\n"
            f"[bold {COLOR_SKY_BLUE}]SHA-256:[/]      [{COLOR_MUTED}]{rec['sha256']}[/]\n"
            f"[bold {COLOR_SKY_BLUE}]Chunks:[/]       [{COLOR_ICE_WHITE}]{len(chunks)}[/]\n"
            f"[bold {COLOR_SKY_BLUE}]Created:[/]      [{COLOR_MUTED}]{rec['created_at'][:19].replace('T', ' ')}[/]"
        )
        panel = Panel(
            content,
            title=f"[{COLOR_CYAN}]File Details[/]",
            border_style=COLOR_ROYAL_BLUE,
        )
        console.print(panel)

        if chunks:
            chunk_table = Table(
                title=f"[{COLOR_SKY_BLUE}]Chunks ({len(chunks)})[/]",
                border_style=COLOR_DEEP_BLUE,
                header_style=f"bold {COLOR_CYAN}",
            )
            chunk_table.add_column("#", justify="right", width=4)
            chunk_table.add_column("Size", justify="right", style=COLOR_CYAN)
            chunk_table.add_column("Telegram Msg ID", justify="center", style=COLOR_ICE_WHITE)
            chunk_table.add_column("Status", justify="center")
            chunk_table.add_column("SHA-256 (partial)", style=f"dim {COLOR_MUTED}")

            for c in chunks:
                c_status = f"[{COLOR_SUCCESS}]OK[/]" if c["status"] == "completed" else f"[{COLOR_ERROR}]{c['status']}[/]"
                msg_id_str = str(c["telegram_message_id"]) if c["telegram_message_id"] else "—"
                chunk_table.add_row(
                    str(c["chunk_index"]),
                    parse_bytes(c["size"]),
                    msg_id_str,
                    c_status,
                    c["sha256"][:16] + "...",
                )
            console.print(chunk_table)

    elif data["type"] == "directory":
        rec = data["record"]
        files = data.get("files", [])
        content = (
            f"[bold {COLOR_SKY_BLUE}]Name:[/]         [{COLOR_ICE_WHITE}]{rec['name']}[/]\n"
            f"[bold {COLOR_SKY_BLUE}]ID:[/]           [{COLOR_ICE_WHITE}]{rec['id']}[/]\n"
            f"[bold {COLOR_SKY_BLUE}]Files:[/]        [{COLOR_ICE_WHITE}]{data['file_count']}[/]\n"
            f"[bold {COLOR_SKY_BLUE}]Total Size:[/]   [{COLOR_CYAN}]{parse_bytes(data['total_size'])}[/]\n"
            f"[bold {COLOR_SKY_BLUE}]Created:[/]      [{COLOR_MUTED}]{rec['created_at'][:19].replace('T', ' ')}[/]"
        )
        panel = Panel(
            content,
            title=f"[{COLOR_CYAN}]Directory Details[/]",
            border_style=COLOR_ROYAL_BLUE,
        )
        console.print(panel)


def render_verify_results(data: Dict[str, Any]) -> None:
    """Renders verification audit results."""
    is_ok = data["verified"]
    status_msg = f"[bold {COLOR_SUCCESS}]✔ All chunks verified on Telegram![/]" if is_ok else f"[bold {COLOR_ERROR}]✖ Integrity check failed! Some chunks are missing.[/]"
    console.print(status_msg)

    if data["type"] == "file":
        table = Table(
            title=f"[{COLOR_SKY_BLUE}]Chunk Audit for '{data['name']}'[/]",
            border_style=COLOR_ROYAL_BLUE,
        )
        table.add_column("Chunk #", justify="right")
        table.add_column("Telegram Msg ID", justify="center")
        table.add_column("Remote Status", justify="center")

        for c in data["chunks"]:
            status_badge = f"[{COLOR_SUCCESS}]Present ✓[/]" if c["exists"] else f"[{COLOR_ERROR}]Missing ✗[/]"
            table.add_row(str(c["chunk_index"]), str(c.get("message_id", "—")), status_badge)

        console.print(table)


def render_directory_tree(data: Dict[str, Any]) -> None:
    """Renders a visual directory tree using Rich's Tree widget."""
    root_rec = data["root"]
    subdirs = data.get("subdirectories", [])
    files = data.get("files", [])

    root_tree = Tree(
        f"[bold {COLOR_CYAN}]📁 {root_rec['name']}/[/] [dim {COLOR_MUTED}](ID: {root_rec['id'][:8]}..)[/]"
    )

    # Map relative path to tree branch node
    node_map: Dict[str, Tree] = {"": root_tree}

    # Build directory branches sorted by depth
    for d in sorted(subdirs, key=lambda s: len(s.get("relative_path", "").split("/"))):
        rel = d.get("relative_path", "")
        if not rel:
            continue
        parts = rel.split("/")
        parent_rel = "/".join(parts[:-1]) if len(parts) > 1 else ""
        parent_node = node_map.get(parent_rel, root_tree)
        sub_node = parent_node.add(f"[bold {COLOR_SKY_BLUE}]📁 {d['name']}/[/]")
        node_map[rel] = sub_node

    # Add files to their parent directory branch
    for f in files:
        f_rel = f.get("relative_path", f["name"])
        parts = f_rel.split("/")
        parent_rel = "/".join(parts[:-1]) if len(parts) > 1 else ""
        parent_node = node_map.get(parent_rel, root_tree)
        parent_node.add(
            f"[bold {COLOR_ICE_WHITE}]📄 {f['name']}[/] [dim {COLOR_CYAN}]({parse_bytes(f['size'])})[/]"
        )

    console.print()
    console.print(root_tree)
    console.print()
