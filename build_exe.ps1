$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $env:TEMP 'MaddenDraftClassBuilder-build-env'
$python = Join-Path $venv 'Scripts\python.exe'
$node = (Get-Command node.exe -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $python)) {
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the packaging environment.' }
}

& $python -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements.txt') -r (Join-Path $root 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install packaging requirements.' }

$dist = Join-Path $root 'dist'
$work = Join-Path $env:TEMP 'MaddenDraftClassBuilder-pyinstaller-work'
$spec = Join-Path $env:TEMP 'MaddenDraftClassBuilder-pyinstaller-spec'
$pyinstallerArgs = @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
    '--name', 'DraftClassBuilder',
    '--distpath', $dist,
    '--workpath', $work,
    '--specpath', $spec,
    '--paths', $root,
    '--hidden-import', 'randomize_prospects',
    '--hidden-import', 'randomize_heights',
    '--hidden-import', 'rank_draft_class',
    '--add-data', "$root\randomize_prospects.py;.",
    '--add-data', "$root\randomize_heights.py;.",
    '--add-data', "$root\rank_draft_class.py;.",
    '--add-data', "$root\export.mjs;.",
    '--add-data', "$root\apply.mjs;.",
    '--add-data', "$root\export_draft_class.mjs;.",
    '--add-data', "$root\apply_draft_order.mjs;.",
    '--add-data', "$root\update_config.json;.",
    '--add-data', "$root\college_programs.json;.",
    '--add-data', "$root\node_modules;node_modules",
    '--add-binary', "$node;node",
    (Join-Path $root 'app.py')
)
& $python @pyinstallerArgs
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed to build DraftClassBuilder.exe.' }

Write-Output "Built: $(Join-Path $dist 'DraftClassBuilder.exe')"
