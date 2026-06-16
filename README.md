# Energy Optimizer

Dieses Repository enthält die Python-basierte Energieoptimierung für dein Smarthome.

## Container-Build

Der Container-Build wurde in das Python-Modul `containers.build` ausgelagert.

### Ausführung über PowerShell

```powershell
.uild-container.ps1
```

### Direkte Ausführung über Python

```powershell
python -m containers.build --tag deinusername/ernie-energy:latest
```

### Optionen

- `--tag`: Docker-Image-Tag
- `--platforms`: Komma-separierte Liste von Plattformen (z. B. `linux/amd64,linux/arm64`)
- `--dockerfile`: Pfad zur Dockerfile
- `--context`: Build-Kontext
- `--no-push`: Image nicht pushen
- `--builder-name`: Name des Buildx-Builders

## Hinweise

- Stelle sicher, dass `python` und `docker` installiert sind.
- `build-container.ps1` ruft das Python-Modul `containers.build` auf.
