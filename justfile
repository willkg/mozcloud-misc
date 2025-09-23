@_default:
    just --list

lint:
    uv run ruff check *.py

format:
    uv run ruff format *.py
