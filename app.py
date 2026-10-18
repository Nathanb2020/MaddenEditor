#!/usr/bin/env python3
"""Small desktop UI for creating a randomized Madden draft-class save."""
from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
CONFIG_PATH = APP_DIR / "update_config.json"
NODE_DIR = APP_DIR / "node"
if NODE_DIR.is_dir():
    os.environ["PATH"] = str(NODE_DIR) + os.pathsep + os.environ.get("PATH", "")


def next_draft_save_path(directory: Path) -> Path:
    """Return the first unused CAREER-DRAFTCLASS save path in a directory."""
    index = 1
    while True:
        candidate = directory / f"CAREER-DRAFTCLASS{index}"
        if not candidate.exists():
            return candidate
        index += 1


def move_without_overwrite(source: Path, destination: Path) -> None:
    """Move a file without replacing a destination created by another process."""
    try:
        os.rename(source, destination)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise

    # The system temp directory may be on another drive. Create the destination
    # exclusively before copying so a concurrent save cannot be overwritten.
    reserved = False
    try:
        with destination.open("xb") as output_file:
            reserved = True
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output_file)
        shutil.copystat(source, destination)
        source.unlink()
    except Exception:
        if reserved:
            destination.unlink(missing_ok=True)
        raise


class DraftClassApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Madden Draft Class Builder")
        self.root.minsize(700, 540)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.save_path = tk.StringVar()
        self.output_path = tk.StringVar(value="Choose a save file to see the output location.")
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.running = False
        self.update_checking = False

        self.build_ui()
        self.root.after(100, self.poll_events)
        self.root.after(500, self.check_for_updates)

    def build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Madden Draft Class Builder", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text=("Select a franchise save. The app creates a separate CAREER-DRAFTCLASS save "
                  "beside it and leaves the selected save unchanged."),
            wraplength=650,
        ).pack(anchor="w", pady=(6, 18))

        ttk.Label(frame, text="Franchise save").pack(anchor="w")
        select_row = ttk.Frame(frame)
        select_row.pack(fill="x", pady=(4, 12))
        self.save_entry = ttk.Entry(select_row, textvariable=self.save_path)
        self.save_entry.pack(side="left", fill="x", expand=True)
        self.browse_button = ttk.Button(select_row, text="Browse…", command=self.browse)
        self.browse_button.pack(side="left", padx=(8, 0))

        ttk.Label(frame, text="New save location").pack(anchor="w")
        ttk.Label(frame, textvariable=self.output_path, wraplength=650).pack(anchor="w", pady=(4, 14))

        action_row = ttk.Frame(frame)
        action_row.pack(anchor="w")
        self.create_button = ttk.Button(action_row, text="Create DraftClass", command=self.create)
        self.create_button.pack(side="left")

        ttk.Label(frame, text="Progress").pack(anchor="w", pady=(18, 4))
        self.log = scrolledtext.ScrolledText(frame, height=12, state="disabled", wrap="word", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="This randomizes prospect ratings and physical profiles, re-ranks the class from "
                 "position-specific scouting scores and the requested round-by-round position mix, "
                 "and writes a scouting report beside the new save.",
            wraplength=650,
        ).pack(anchor="w", pady=(10, 0))

    def browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select a Madden franchise save",
            filetypes=[("Madden franchise saves", "*"), ("All files", "*.*")],
        )
        if path:
            self.save_path.set(path)
            self.output_path.set(str(next_draft_save_path(Path(path).resolve().parent)))

    def append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    @staticmethod
    def update_settings() -> tuple[str, str]:
        try:
            settings = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            version = str(settings.get("version", "")).strip()
            repository = str(settings.get("github_repo", "")).strip()
        except (OSError, json.JSONDecodeError):
            return "", ""
        return version, repository

    def check_for_updates(self) -> None:
        if self.update_checking or not getattr(sys, "frozen", False):
            return
        version, repository = self.update_settings()
        if not repository or "/" not in repository:
            self.append_log("Automatic update check skipped: GitHub repository is not configured.")
            return
        self.update_checking = True
        self.append_log("Checking for updates…")
        threading.Thread(target=self.fetch_update, args=(version, repository), daemon=True).start()

    def fetch_update(self, current_version: str, repository: str) -> None:
        try:
            request = Request(
                f"https://api.github.com/repos/{repository}/releases/latest",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "DraftClassBuilder-Updater"},
            )
            with urlopen(request, timeout=20) as response:
                release = json.loads(response.read().decode("utf-8"))
            latest_version = str(release.get("tag_name", "")).strip().lstrip("v")
            assets = release.get("assets", [])
            asset = next((item for item in assets if item.get("name") == "DraftClassBuilder.exe"), None)
            if not latest_version or not asset:
                raise RuntimeError("The latest GitHub release must have a version tag and DraftClassBuilder.exe asset.")
            if compare_versions(latest_version, current_version) <= 0:
                self.events.put(("update_current", latest_version))
                return
            self.events.put(("update_available", json.dumps({
                "version": latest_version,
                "url": asset.get("browser_download_url", ""),
                "size": str(asset.get("size") or ""),
                "digest": str(asset.get("digest") or ""),
                "notes": str(release.get("body", ""))[:1500],
            })))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            self.events.put(("update_error", str(exc)))

    def download_and_install_update(self, update: dict[str, str]) -> None:
        try:
            url = update.get("url", "")
            if not url.startswith("https://github.com/"):
                raise RuntimeError("The release download link is missing or is not a GitHub HTTPS link.")
            request = Request(url, headers={"User-Agent": "DraftClassBuilder-Updater"})
            with urlopen(request, timeout=60) as response:
                payload = response.read()
            expected_size = update.get("size", "").strip()
            if expected_size:
                try:
                    parsed_expected_size = int(expected_size)
                except ValueError as exc:
                    raise RuntimeError("The release returned an invalid update file size.") from exc
                if len(payload) != parsed_expected_size:
                    raise RuntimeError(
                        f"The update download is incomplete ({len(payload)} of {parsed_expected_size} bytes). "
                        "Your current app was not replaced."
                    )
            expected_digest = update.get("digest", "").strip().lower()
            if expected_digest:
                algorithm, separator, expected_digest = expected_digest.partition(":")
                if not separator or algorithm != "sha256":
                    raise RuntimeError("The release returned an unsupported update checksum format.")
                actual_digest = hashlib.sha256(payload).hexdigest()
                if actual_digest != expected_digest:
                    raise RuntimeError("The update file failed GitHub's SHA-256 check. Your current app was not replaced.")
            if len(payload) < 1024 or not payload.startswith(b"MZ"):
                raise RuntimeError("The downloaded file does not look like a Windows executable.")
            install_path = Path(sys.executable).resolve()
            with tempfile.NamedTemporaryFile(prefix="DraftClassBuilder-update-", suffix=".exe", delete=False) as staged:
                staged.write(payload)
                staged_path = Path(staged.name)
            script_path = create_update_script(install_path, staged_path, os.getpid())
            subprocess.Popen(
                [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path),
                    "-ProcessId", str(os.getpid()),
                    "-Target", str(install_path),
                    "-Staged", str(staged_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.root.after(0, self.root.destroy)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
            self.events.put(("update_error", str(exc)))

    def accept_update(self, update_json: str) -> None:
        update = json.loads(update_json)
        notes = update.get("notes", "").strip()
        details = f"Version {update['version']} is available. Download and install it now?"
        if notes:
            details += f"\n\nRelease notes:\n{notes}"
        if not messagebox.askyesno("Update available", details, parent=self.root):
            return
        self.append_log(f"Downloading version {update['version']}…")
        threading.Thread(target=self.download_and_install_update, args=(update,), daemon=True).start()

    def create(self) -> None:
        source_text = self.save_path.get().strip()
        if not source_text:
            messagebox.showerror("Select a save", "Browse to a franchise save file first.", parent=self.root)
            return

        source = Path(source_text).expanduser().resolve()
        if not source.is_file():
            messagebox.showerror("Save not found", f"Could not find this file:\n{source}", parent=self.root)
            return

        output = next_draft_save_path(source.parent)
        self.output_path.set(str(output))
        if source.stat().st_size == 0:
            messagebox.showerror("Empty save", "The selected file is empty.", parent=self.root)
            return

        missing = self.missing_requirements()
        if missing:
            messagebox.showerror("Requirements missing", missing, parent=self.root)
            return

        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.set_running(True)
        threading.Thread(target=self.run_pipeline, args=(source, output), daemon=True).start()

    @staticmethod
    def missing_requirements() -> str | None:
        missing = []
        if shutil.which("node") is None:
            missing.append("Node.js is not installed or not available on PATH.")
        if importlib.util.find_spec("numpy") is None:
            missing.append("NumPy is missing. Install it with: python -m pip install -r requirements.txt")
        if not (APP_DIR / "node_modules" / "madden-franchise").exists():
            missing.append("The Madden franchise package is missing. Install it with: npm install")
        for script in ("randomize_prospects.py", "randomize_heights.py", "rank_draft_class.py",
                       "export.mjs", "apply.mjs", "export_draft_class.mjs", "apply_draft_order.mjs",
                       "college_programs.json"):
            if not (APP_DIR / script).is_file():
                missing.append(f"Required app file is missing: {script}")
        return "\n\n".join(missing) or None

    def run_pipeline(self, source: Path, output: Path) -> None:
        try:
            with tempfile.TemporaryDirectory(prefix="madden-draftclass-") as work_dir:
                stage1 = Path(work_dir) / "Stage1"
                stage2 = Path(work_dir) / "Stage2"
                completed_save = Path(work_dir) / "DraftClass"
                report_path = Path(work_dir) / "ScoutingReport.csv"
                seed = random.SystemRandom().randrange(1, 10 ** 9)
                self.events.put(("log", f"Randomization seed: {seed}"))
                commands = [
                    ("Randomizing ratings and mapped weights…", "randomize_prospects.py", source, stage1,
                     ["--seed", str(seed)]),
                    ("Randomizing QB and WR heights…", "randomize_heights.py", stage1, stage2,
                     ["--seed", str(seed ^ 0x45A9)]),
                    ("Scoring prospects and writing the new draft order…", "rank_draft_class.py", stage2,
                     completed_save, ["--seed", str(seed ^ 0x61C3), "--report", str(report_path)]),
                ]
                frozen = getattr(sys, "frozen", False)
                for index, (label, script_name, input_save, output_save, extra_args) in enumerate(commands, start=1):
                    self.events.put(("log", label))
                    if frozen:
                        log_path = Path(work_dir) / f"stage-{index}.log"
                        command = [
                            sys.executable, "--backend", script_name, "--log-file", str(log_path),
                            str(input_save), "--output", str(output_save), *extra_args,
                        ]
                    else:
                        command = [
                            sys.executable, "-u", str(APP_DIR / script_name),
                            str(input_save), "--output", str(output_save), *extra_args,
                        ]
                    self.events.put(("log", "$ " + subprocess.list2cmdline(command)))
                    if frozen:
                        result = subprocess.Popen(
                            command, cwd=work_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        offset = 0
                        while result.poll() is None:
                            offset = self.read_backend_log(log_path, offset)
                            time.sleep(0.1)
                        self.read_backend_log(log_path, offset)
                        return_code = result.returncode
                    else:
                        result = subprocess.Popen(
                            command,
                            cwd=work_dir,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            bufsize=1,
                        )
                        assert result.stdout is not None
                        for line in result.stdout:
                            self.events.put(("log", line.rstrip()))
                        return_code = result.wait()
                    if return_code != 0:
                        raise RuntimeError(f"The step failed with exit code {return_code}.")
                if not completed_save.is_file() or completed_save.stat().st_size == 0:
                    raise RuntimeError("The final save was not created or is empty.")
                if not report_path.is_file() or report_path.stat().st_size == 0:
                    raise RuntimeError("The prospect scouting report was not created or is empty.")
                while True:
                    try:
                        move_without_overwrite(completed_save, output)
                        break
                    except FileExistsError:
                        output = next_draft_save_path(source.parent)
                report_output = source.parent / "DraftClass-Scouting-Report.csv"
                suffix = 2
                while report_output.exists():
                    report_output = source.parent / f"DraftClass-Scouting-Report-{suffix}.csv"
                    suffix += 1
                shutil.move(str(report_path), str(report_output))
                self.events.put(("success", json.dumps({"save": str(output), "report": str(report_output)})))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.events.put(("finished", ""))

    def read_backend_log(self, path: Path, offset: int) -> int:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as log_file:
                log_file.seek(offset)
                for line in log_file:
                    self.events.put(("log", line.rstrip()))
                return log_file.tell()
        except FileNotFoundError:
            return offset

    def poll_events(self) -> None:
        try:
            while True:
                kind, message = self.events.get_nowait()
                if kind == "log":
                    self.append_log(message)
                elif kind == "success":
                    result = json.loads(message)
                    self.output_path.set(result["save"])
                    self.append_log(f"\nDraft class created: {result['save']}")
                    self.append_log(f"Scouting report created: {result['report']}")
                    messagebox.showinfo(
                        "Draft class created",
                        f"Your new save is ready:\n{result['save']}\n\nScouting report:\n{result['report']}",
                        parent=self.root,
                    )
                elif kind == "error":
                    self.append_log(f"\nERROR: {message}")
                    messagebox.showerror("Could not create draft class", message, parent=self.root)
                elif kind == "update_current":
                    self.update_checking = False
                    self.append_log(f"App is up to date ({message}).")
                elif kind == "update_available":
                    self.update_checking = False
                    self.accept_update(message)
                elif kind == "update_error":
                    self.update_checking = False
                    self.append_log(f"Automatic update check failed: {message}")
                elif kind == "finished":
                    self.set_running(False)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_events)

    def set_running(self, running: bool) -> None:
        self.running = running
        state = "disabled" if running else "normal"
        self.save_entry.configure(state=state)
        self.browse_button.configure(state=state)
        self.create_button.configure(state=state)
        self.create_button.configure(text="Creating…" if running else "Create DraftClass")

    def close(self) -> None:
        if self.running:
            messagebox.showwarning("Still working", "Wait for the save creation to finish before closing.", parent=self.root)
            return
        self.root.destroy()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--backend":
        run_backend_mode()
        return
    root = tk.Tk()
    DraftClassApp(root)
    startup_marker = os.environ.pop("DRAFTCLASSBUILDER_UPDATE_READY", "")
    if startup_marker:
        def signal_update_ready() -> None:
            try:
                Path(startup_marker).write_text("ready", encoding="ascii")
            except OSError:
                pass

        root.after(500, signal_update_ready)
    root.mainloop()


def compare_versions(left: str, right: str) -> int:
    """Compare numeric dot-separated release versions, ignoring a leading v."""
    def parts(value: str) -> tuple[int, ...]:
        value = value.strip().lstrip("v")
        pieces = value.split(".")
        if not pieces or any(not piece.isdigit() for piece in pieces):
            raise ValueError(f"Invalid app version: {value}")
        return tuple(int(piece) for piece in pieces)

    a, b = parts(left), parts(right)
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return (a > b) - (a < b)


def create_update_script(target: Path, staged: Path, process_id: int) -> Path:
    script = r'''param([int]$ProcessId, [string]$Target, [string]$Staged)
$ErrorActionPreference = 'Stop'
$backupSuffix = [guid]::NewGuid().ToString('N')
$backup = "$Target.previous-$ProcessId-$backupSuffix"
$readyMarker = Join-Path $env:TEMP "DraftClassBuilder-update-ready-$ProcessId"
$log = Join-Path $env:TEMP "DraftClassBuilder-update-$ProcessId.log"
$updatedProcess = $null
try {
    if (Test-Path -LiteralPath $readyMarker) { Remove-Item -LiteralPath $readyMarker -Force }
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($process) { $process.WaitForExit() }
    Move-Item -LiteralPath $Target -Destination $backup
    Move-Item -LiteralPath $Staged -Destination $Target
    $env:DRAFTCLASSBUILDER_UPDATE_READY = $readyMarker
    $updatedProcess = Start-Process -FilePath $Target -PassThru
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $readyMarker) {
            Remove-Item -LiteralPath $backup -Force
            exit 0
        }
        $updatedProcess.Refresh()
        if ($updatedProcess.HasExited) {
            throw "The updated app exited before confirming startup (exit code $($updatedProcess.ExitCode))."
        }
        Start-Sleep -Milliseconds 200
    }
    throw 'The updated app did not confirm startup within 30 seconds.'
} catch {
    $failure = $_.Exception.Message
    if ($updatedProcess) {
        try {
            $updatedProcess.Refresh()
            if (-not $updatedProcess.HasExited) { Stop-Process -Id $updatedProcess.Id -Force -ErrorAction SilentlyContinue }
        } catch { }
    }
    if (Test-Path -LiteralPath $backup) {
        try {
            Remove-Item Env:\DRAFTCLASSBUILDER_UPDATE_READY -ErrorAction SilentlyContinue
            if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Force }
            Move-Item -LiteralPath $backup -Destination $Target -Force
            Start-Process -FilePath $Target
        } catch { $failure += " Rollback also failed: $($_.Exception.Message)" }
    }
    try {
        Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) Update failed; previous executable restored when available. $failure"
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            "The update could not start. The previous version was restored when possible.`n`nDetails: $failure`nLog: $log",
            'Madden Draft Class Builder update',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
    } catch { }
    exit 1
} finally {
    Remove-Item Env:\DRAFTCLASSBUILDER_UPDATE_READY -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $readyMarker) { Remove-Item -LiteralPath $readyMarker -Force }
    if (Test-Path -LiteralPath $Staged) { Remove-Item -LiteralPath $Staged -Force }
}'''
    script_path = Path(tempfile.gettempdir()) / f"DraftClassBuilder-updater-{process_id}.ps1"
    script_path.write_text(script, encoding="utf-8")
    return script_path


def run_backend_mode() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("Missing backend stage.")
    stage_name = sys.argv[2]
    backend_args = sys.argv[3:]
    if backend_args and backend_args[0] == "--log-file":
        if len(backend_args) < 2:
            raise SystemExit("Missing backend log file path.")
        log_file = open(backend_args[1], "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stdout = log_file
        sys.stderr = log_file
        backend_args = backend_args[2:]
    sys.argv = [stage_name, *backend_args]
    if stage_name == "randomize_prospects.py":
        from randomize_prospects import main as run_stage
    elif stage_name == "randomize_heights.py":
        from randomize_heights import main as run_stage
    elif stage_name == "rank_draft_class.py":
        from rank_draft_class import main as run_stage
    else:
        raise SystemExit(f"Unknown backend stage: {stage_name}")
    run_stage()


if __name__ == "__main__":
    main()
