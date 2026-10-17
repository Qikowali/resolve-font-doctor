param(
    [string]$Python = "python",
    [switch]$CliOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "Python: $Python"
& $Python --version

$hasPyInstaller = $true
& $Python -c "import PyInstaller" *> $null
if ($LASTEXITCODE -ne 0) {
    $hasPyInstaller = $false
}
if (-not $hasPyInstaller) {
    Write-Host "Installing PyInstaller..."
    & $Python -m pip install --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed" }
}

$separator = [IO.Path]::PathSeparator
$addData = "assets$separator" + "assets"
$common = @(
    "--noconfirm", "--clean", "--onefile",
    "--paths", "src",
    "--add-data", $addData,
    "--hidden-import", "winreg"
)

if (-not $CliOnly) {
    Write-Host "Building GUI..."
    & $Python -m PyInstaller @common `
        --windowed `
        --name "ResolveFontDoctor" `
        --icon "assets\font-doctor.ico" `
        "run_gui.py"
    if ($LASTEXITCODE -ne 0) { throw "GUI build failed" }
}

Write-Host "Building CLI..."
& $Python -m PyInstaller @common `
    --console `
    --name "ResolveFontDoctor-CLI" `
    "run_cli.py"
if ($LASTEXITCODE -ne 0) { throw "CLI build failed" }

if (Test-Path "dist\ResolveFontDoctor.exe") {
    Copy-Item "dist\ResolveFontDoctor.exe" "dist\达芬奇字体管家.exe" -Force
}
Copy-Item "README.md", "LICENSE" "dist\" -Force
if (Test-Path "docs") {
    if (Test-Path "dist\docs") { Remove-Item "dist\docs" -Recurse -Force }
    Copy-Item "docs" "dist\docs" -Recurse -Force
}

Write-Host ""
Get-ChildItem "dist" | Select-Object Name, Length | Format-Table -AutoSize
