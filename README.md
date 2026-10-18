# Madden Draft Class Builder

A small Windows desktop app that takes a Madden franchise save and creates a separate save named `DraftClass` beside the selected file. The selected save is used as input and is not modified.

## Start

1. Install Python 3.10 or newer with Tkinter, Node.js, and npm.
2. From this folder, run `python -m pip install -r requirements.txt` and `npm install`.
3. Run `python app.py` or `npm start`.
4. Select a franchise save and choose **Create DraftClass**.

The app randomizes prospect ratings and mapped weights, then randomizes QB and WR prospect heights. Draft-order changes are not included yet. The app refuses to overwrite an existing `DraftClass` file. Temporary working files are removed after each run.

## Build a Windows executable

Run `.\build_exe.ps1` in PowerShell. It creates `dist\DraftClassBuilder.exe` as a single-file Windows app with Python, Node.js, and the required packages bundled. Share that `.exe` file; no franchise saves are included.

## Publish updates

The executable has a **Check for updates** button that checks the latest GitHub Release and can download and install a newer build. To enable it:

1. Set `github_repo` in `update_config.json` to your GitHub `owner/repository`, and set `version` to the current app version.
2. Run `build_exe.ps1` and publish `dist\DraftClassBuilder.exe` as an asset in a GitHub Release. Name the release tag with the same version and a `v` prefix, such as `v1.0.1`.
3. For each fix, increase `version`, rebuild, and publish the new executable as `DraftClassBuilder.exe` on a new release. Your friend clicks **Check for updates** in the app.

The updater requires a public GitHub repository and a writable folder for the executable. The configured repository is `Nathanb2020/MaddenEditor`. It keeps a backup while replacing the running executable and restores it if the replacement fails. The updater compares numeric versions such as `1.0.2`; keep release tags in that format.
