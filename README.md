# Minecraft Modpack Manifest Comparator

A Python utility for comparing Minecraft modpack manifest files to generate a detailed changelog between versions.

## Overview

This tool compares the `manifest.json` files from two Minecraft modpack archives (ZIP files) and generates a comprehensive changelog in Markdown format. It identifies added mods, removed mods, and updated mods, as well as changes to Minecraft versions and mod loaders.

For enhanced output, it can optionally scrape the CurseForge website to retrieve mod names and file information, making the changelog more user-friendly.

## Features

- Compare two modpack manifest files to identify:
  - Added mods
  - Removed mods
  - Updated mods (same mod but different file versions)
  - Minecraft version changes
  - Mod loader changes
- Web scraping capabilities:
  - Retrieve mod names from CurseForge
  - Get file version information
  - Disk-based caching to improve performance and reduce requests
- Markdown output for easy sharing and publishing
- Highly configurable with multiple command-line options

## Requirements

- Python 3.8 or higher
- Required Python packages:
  - `requests`
  - `beautifulsoup4`

## Installation

1. Clone or download this repository
2. Install the required dependencies:

```bash
pip install requests beautifulsoup4
```

## Usage

Basic comparison (no web scraping):

```bash
python manifest_compare.py old_modpack.zip new_modpack.zip -o changelog.md
```

With web scraping (retrieves mod names and file info):

```bash
python manifest_compare.py old_modpack.zip new_modpack.zip -o changelog.md --scrape
```

Faster web scraping (skip file info):

```bash
python manifest_compare.py old_modpack.zip new_modpack.zip -o changelog.md --scrape --no-scrape-files
```

## Command-Line Options

| Option | Description |
|--------|-------------|
| `old_zip` | Path to the old/first modpack zip file |
| `new_zip` | Path to the new/second modpack zip file |
| `-o, --output` | Output file path (if not specified, outputs to console) |
| `--scrape` | Enable web scraping for additional mod information |
| `--no-scrape-files` | Skip scraping file information (faster) |
| `--delay` | Delay between requests in seconds (default: 0.5) |
| `--max-workers` | Maximum number of parallel workers (default: 3) |
| `--cache-dir` | Directory for cache files (default: .cursecache) |
| `--no-cache` | Disable caching |

## Example Output

```markdown
# Manifest Comparison

Comparing MyModpack v1.0.0 to MyModpack v1.1.0

## Minecraft Version Change

- Changed from `1.18.2` to `1.19.2`

## Mod Loader Changes

### Old Loaders:
- `forge-40.1.0` (primary)

### New Loaders:
- `forge-43.2.0` (primary)

## Additions

| Mod Name | File Name | Version | Required |
|-----------|----------|-----------|---------|----------|
| Create | create-1.19.2-0.5.0.g.jar | v0.5.0g for 1.19.2 | True |

## Removals

| Mod Name | File Name | Version | Required |
|-----------|----------|-----------|---------|----------|
| JEI | jei-1.18.2-9.7.0.209.jar | 9.7.0.209 | True |

## Updates

| Mod Name | From Version | To Version |
|-----------|----------|--------------|------------|
| Architectury API | 4.9.83 | 6.4.62 |
```

## Caching

The tool uses a disk-based cache to store mod and file information to improve performance when running multiple comparisons. By default, cache files are stored in the `.cursecache` directory.

Cache structure:
- `.cursecache/mods/`: Contains cached mod information
- `.cursecache/files/`: Contains cached file information

Cache stats are displayed at the end of the scraping process.

## Notes on Web Scraping

- The script uses respectful web scraping techniques with reasonable delays between requests
- Multiple URL formats are tried to accommodate changes in the CurseForge website
- User-agent headers are used to avoid being blocked
- Requests are spread out to avoid overwhelming the server

## License

This project is released under the MIT License. Feel free to use, modify, and distribute it as needed.

## Acknowledgments

This tool was created to help modpack developers and users track changes between modpack versions. It's designed to be minimally invasive to external websites while providing useful information for the Minecraft modding community.