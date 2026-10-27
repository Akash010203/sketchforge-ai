# Troubleshooting

- **Import or image decoding fails:** confirm the image is readable and within the size and pixel limits in `config/app.yaml`.
- **The desktop UI cannot start:** confirm the project's Python environment has the GUI dependencies listed in `pyproject.toml` and run `python -m sketchforge info` to inspect the active environment.
- **Dataset manifest validation fails:** run `python scripts/validate_manifest.py` and resolve the reported schema or provenance issue before downloading data.
- **Nebius integration is unavailable:** remote use is optional and disabled by default. Check `docs/NEBIUS_NVIDIA_INTEGRATION.md`; do not place credentials in tracked configuration files.
- **Generated output is missing:** check the configured `output/` path and the command's reported errors; generated files are intentionally ignored by Git.
