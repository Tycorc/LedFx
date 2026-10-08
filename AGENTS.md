# AGENTS.md — LedFx

Audio-reactive LED controller. `ledfx/__main__.py` is the CLI entrypoint;
`ledfx/effects/`, `ledfx/devices/`, `ledfx/api/`, and `ledfx/virtuals.py` implement
rendering, device transport, HTTP control, and virtual output routing.
`frontend` is a separate submodule; do not replace it with generated assets.

Use Python 3.11–3.14 and the uv version required by `pyproject.toml`.
`uv sync --group dev` installs developer dependencies; `uv run pytest -v` runs
the suite. Follow the existing Ruff/pre-commit configuration. Documentation build:
`uv sync --group docs`, then `uv run sphinx-build -a -b html docs docs/build`.
Preserve actual schema descriptions and upstream attribution. Tests must use
fixtures instead of controlling connected LED hardware. See README.rst and
`docs/README.md` for setup and the process diagram.

## Maintenance policy

- README files and agent instruction files are exempt from the comment limit
  by design. The limit applies to code and configuration files.
- Keep code-file comments at or below 20% of nonblank lines. Only the operator
  may grant a documented, file-specific exception; do not silently exempt files.
- Preserve licenses, tool directives, runtime strings, and behavior. If the limit
  conflicts with these, report the file for an operator decision.
- Keep this file as the repository's single agent instruction source. Keep the
  README and its process/logic diagram consistent with the implementation.
- Remove unused files or features only with evidence that nothing depends on them.
  Keep changes focused; do not add speculative features or abstractions.
