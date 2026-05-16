param()

if (-not (Test-Path "backend/requirements.txt")) {
    Write-Error "backend/requirements.txt not found"
    exit 1
}

python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
pip freeze > backend/requirements-pinned.txt
Write-Host "Pinned requirements written to backend/requirements-pinned.txt"
