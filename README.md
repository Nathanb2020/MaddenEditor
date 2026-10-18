# Madden Draft Class Builder

A small Windows desktop app that takes a Madden franchise save and creates a separate save beside the selected file. The selected save is used as input and is not modified. New saves are named `CAREER-DRAFTCLASS1`, then `CAREER-DRAFTCLASS2`, `CAREER-DRAFTCLASS3`, and so on, using the first name not already in the folder.

## Start

1. Install Python 3.10 or newer with Tkinter, Node.js, and npm.
2. From this folder, run `python -m pip install -r requirements.txt` and `npm install`.
3. Run `python app.py` or `npm start`.
4. Select a franchise save and choose **Create DraftClass**.

The app randomizes prospect ratings and selected mapped weights, then randomizes QB and WR prospect heights. It scores the class using position-specific NFL skills, physical upside, generated fictional college production, and program context. It writes each prospect's ranking and projected round/pick into the franchise save, updates the stored draft-board evaluations and all 32 team boards, and creates a scouting report beside the output save. The selected franchise save is never modified, and existing `CAREER-DRAFTCLASS#` files are preserved while the app chooses the next unused number.

The scouting model uses 45% NFL-translatable skills, 30% physical upside, 15% college production, and 10% college program context. It ignores Madden overall and development traits. Generated season statistics depend on ratings, position, estimated role/opportunities, and program context. First-round quarterbacks receive at least 70 in short and medium accuracy. Within each round's position targets, prospects follow the model's final scores, with NFL skills, physical upside, then context-adjusted production as tie-breakers.

The draft follows the document's average position mix by round, rounded to whole selections while keeping 32 picks in each round. The source table's rounds 3-7 add up to more than 32, so those rows are normalized to 32 while preserving the listed proportions. Prospects are sorted by scouting score within each position target. The report includes the source average, normalized target, actual count, resulting draft rank, and separate score-only scouting rank.

Fullbacks receive randomized rating profiles and the offensive change-of-direction cap. Kicker, punter, and long-snapper ratings are preserved because the document does not set ranges for them; they still receive separate position-specific scouting scores and valid draft ranks.

Madden stores each player's college as a packed reference instead of a readable school name. By default, the report shows a stable college code and generated program-strength value for that code. You can add an entry to `college_programs.json` to provide a school name and strength when you know a code: `{"programs":{"0x80000732":{"name":"Example State","strength":72}}}`. Strength values are 0-100.

## Build a Windows executable

Run `.\build_exe.ps1` in PowerShell. It creates `dist\DraftClassBuilder.exe` as a single-file Windows app with Python, Node.js, and the required packages bundled. Share that `.exe` file; no franchise saves are included.

## Publish updates

The executable checks the latest GitHub Release on launch and offers to download and install a newer build. To enable it:

1. Set `github_repo` in `update_config.json` to your GitHub `owner/repository`, and set `version` to the current app version.
2. Run `build_exe.ps1` and publish `dist\DraftClassBuilder.exe` as an asset in a GitHub Release. Name the release tag with the same version and a `v` prefix, such as `v1.0.4`.
3. For each fix, increase `version`, rebuild, and publish the new executable as `DraftClassBuilder.exe` on a new release. The app checks automatically when your friend opens it.

Versions before `1.0.3` launch the update script without its required file paths and cannot update themselves. Replace those executables with the `v1.0.3` download once; later versions can install updates from the automatic launch check.

The updater requires a public GitHub repository and a writable folder for the executable. The configured repository is `Nathanb2020/MaddenEditor`. It keeps a backup while replacing the running executable and restores it if the replacement fails. The updater compares numeric versions such as `1.0.2`; keep release tags in that format.
