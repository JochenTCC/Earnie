import argparse
import zipfile
from pathlib import Path


def collect_py_files(root: Path):
    return sorted(root.glob("*.py"))


def filter_excluded_files(files, root: Path, excluded_paths):
    exclusion_set = set()
    for exclude_path in excluded_paths:
        path = Path(exclude_path)
        if not path.is_absolute():
            path = root.joinpath(path)
        exclusion_set.add(path.resolve())
    return [file for file in files if file.resolve() not in exclusion_set]


def create_zip(files, destination: Path, root: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for path in files:
            relative_path = path.relative_to(root)
            zip_file.write(path, relative_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a ZIP archive containing all .py files from the workspace."
    )
    parser.add_argument(
        "--output",
        "-o",
        default="python_sources.zip",
        help="Output ZIP file path (default: python_sources.zip)",
    )
    parser.add_argument(
        "--root",
        "-r",
        default=".",
        help="Root folder to scan for .py files (default: current workspace).",
    )
    parser.add_argument(
        "--exclude",
        "-e",
        nargs="+",
        action="append",
        default=[],
        help="Optional list of .py files to exclude from the ZIP, relative to root or absolute.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        print(f"Root path does not exist or is not a directory: {root}")
        return 1

    excluded_paths = [item for sublist in args.exclude for item in sublist]
    py_files = collect_py_files(root)
    if excluded_paths:
        py_files = filter_excluded_files(py_files, root, excluded_paths)

    if not py_files:
        print(f"No Python files found under {root}")
        return 1

    destination = Path(args.output).resolve()
    create_zip(py_files, destination, root)

    print(f"Packed {len(py_files)} .py files into: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
