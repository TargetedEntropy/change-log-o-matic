#!/usr/bin/env python3
import json
import zipfile
import argparse
import sys
import os
import requests
import time
import re
from bs4 import BeautifulSoup
from typing import Dict, List, Tuple, Any, Optional
from concurrent.futures import ThreadPoolExecutor


def extract_manifest(zip_path: str) -> Dict[str, Any]:
    """Extract and parse manifest.json from a zip file."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            if 'manifest.json' not in zip_ref.namelist():
                raise ValueError(f"No manifest.json found in {zip_path}")
            
            with zip_ref.open('manifest.json') as manifest_file:
                return json.load(manifest_file)
    except zipfile.BadZipFile:
        raise ValueError(f"File is not a valid zip archive: {zip_path}")
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON in manifest.json from {zip_path}")


def compare_manifests(old_manifest: Dict[str, Any], new_manifest: Dict[str, Any]) -> Tuple[List, List, List]:
    """
    Compare two manifests and return lists of additions, removals, and updates.
    Returns: (additions, removals, updates)
    """
    # Extract files from both manifests
    old_files = {item['projectID']: item for item in old_manifest.get('files', [])}
    new_files = {item['projectID']: item for item in new_manifest.get('files', [])}
    
    # Find additions (in new but not in old)
    additions = [new_files[project_id] for project_id in new_files if project_id not in old_files]
    
    # Find removals (in old but not in new)
    removals = [old_files[project_id] for project_id in old_files if project_id not in new_files]
    
    # Find updates (same projectID but different fileID)
    updates = []
    for project_id in old_files:
        if project_id in new_files and old_files[project_id]['fileID'] != new_files[project_id]['fileID']:
            updates.append({
                'projectID': project_id,
                'old_fileID': old_files[project_id]['fileID'],
                'new_fileID': new_files[project_id]['fileID']
            })
    
    return additions, removals, updates


class CurseForgeCache:
    """A simple disk cache for CurseForge mod and file information."""
    
    def __init__(self, cache_dir: str = ".cursecache"):
        """
        Initialize the cache.
        
        Args:
            cache_dir: Directory to store cache files (default: .cursecache)
        """
        self.cache_dir = cache_dir
        self.mod_cache_dir = os.path.join(self.cache_dir, "mods")
        self.file_cache_dir = os.path.join(self.cache_dir, "files")
        
        # Create cache directories if they don't exist
        os.makedirs(self.mod_cache_dir, exist_ok=True)
        os.makedirs(self.file_cache_dir, exist_ok=True)
        
        # Cache stats
        self.mod_hits = 0
        self.mod_misses = 0
        self.file_hits = 0
        self.file_misses = 0
    
    def get_mod_info(self, project_id: int) -> Optional[Dict[str, Any]]:
        """
        Get mod information from cache.
        
        Args:
            project_id: CurseForge project ID
            
        Returns:
            Cached mod information or None if not in cache
        """
        cache_path = os.path.join(self.mod_cache_dir, f"{project_id}.json")
        
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    self.mod_hits += 1
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"Error reading cache for mod {project_id}: {e}", file=sys.stderr)
        
        self.mod_misses += 1
        return None
    
    def set_mod_info(self, project_id: int, mod_info: Dict[str, Any]) -> None:
        """
        Save mod information to cache.
        
        Args:
            project_id: CurseForge project ID
            mod_info: Mod information to cache
        """
        cache_path = os.path.join(self.mod_cache_dir, f"{project_id}.json")
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(mod_info, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"Error writing cache for mod {project_id}: {e}", file=sys.stderr)
    
    def get_file_info(self, project_id: int, file_id: int) -> Optional[Dict[str, Any]]:
        """
        Get file information from cache.
        
        Args:
            project_id: CurseForge project ID
            file_id: CurseForge file ID
            
        Returns:
            Cached file information or None if not in cache
        """
        cache_path = os.path.join(self.file_cache_dir, f"{project_id}_{file_id}.json")
        
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    self.file_hits += 1
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"Error reading cache for file {file_id} of project {project_id}: {e}", file=sys.stderr)
        
        self.file_misses += 1
        return None
    
    def set_file_info(self, project_id: int, file_id: int, file_info: Dict[str, Any]) -> None:
        """
        Save file information to cache.
        
        Args:
            project_id: CurseForge project ID
            file_id: CurseForge file ID
            file_info: File information to cache
        """
        cache_path = os.path.join(self.file_cache_dir, f"{project_id}_{file_id}.json")
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(file_info, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"Error writing cache for file {file_id} of project {project_id}: {e}", file=sys.stderr)
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache hit/miss statistics."""
        return {
            "mod_hits": self.mod_hits,
            "mod_misses": self.mod_misses,
            "file_hits": self.file_hits,
            "file_misses": self.file_misses,
            "total_hits": self.mod_hits + self.file_hits,
            "total_misses": self.mod_misses + self.file_misses
        }


def scrape_mod_info(project_id: int, cache: Optional[CurseForgeCache] = None) -> Dict[str, Any]:
    """
    Scrape mod information from the CurseForge website.
    
    Args:
        project_id: The CurseForge project ID
        cache: Optional cache to use
        
    Returns:
        Dictionary containing mod information or None if request failed
    """
    # Check cache first if provided
    if cache:
        cached_info = cache.get_mod_info(project_id)
        if cached_info:
            print("Cached")
            return cached_info
    
    # Try different URL formats
    urls = [
        f"https://www.curseforge.com/minecraft/mc-mods/{project_id}",  # Try with direct project ID
        f"https://legacy.curseforge.com/minecraft/mc-mods/p{project_id}"  # Try legacy format with p prefix
    ]
    
    for url in urls:
        try:
            # Use a realistic user agent
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            print('1')
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                print(f"nope: {response.status_code}")
                continue  # Try next URL if this one fails
                
            # Parse the HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract mod name from the title
            title_element = soup.find("h1", class_="project-title") or soup.select_one("h1.text-xl")
            print(f"title_element: {title_element}")
            
            if not title_element:
                # Try other common selectors
                title_element = soup.select_one("main h1") or soup.select_one(".project-header h1")
            
            mod_name = title_element.text.strip() if title_element else f"Project-{project_id}"
            
            # Create a mod info dictionary
            mod_info = {
                "id": project_id,
                "name": mod_name,
                "url": url
            }
            
            # Cache the result if cache is provided
            if cache:
                cache.set_mod_info(project_id, mod_info)
                
            return mod_info
        
        except (requests.RequestException, AttributeError) as e:
            print(f"Error with URL {url} for project {project_id}: {e}", file=sys.stderr)
            continue  # Try next URL
    
    # If we get here, all URLs failed
    print(f"Failed to scrape info for project {project_id}", file=sys.stderr)
    
    # Return minimal information with project ID
    minimal_info = {
        "id": project_id,
        "name": f"Project-{project_id}",
        "url": f"https://www.curseforge.com/minecraft/mc-mods/{project_id}"
    }
    
    # Cache the minimal result if cache is provided
    if cache:
        cache.set_mod_info(project_id, minimal_info)
        
    return minimal_info


def scrape_file_info(project_id: int, file_id: int, cache: Optional[CurseForgeCache] = None) -> Dict[str, Any]:
    """
    Scrape file information from the CurseForge website.
    
    Args:
        project_id: The CurseForge project ID
        file_id: The CurseForge file ID
        cache: Optional cache to use
        
    Returns:
        Dictionary containing file information or None if request failed
    """
    # Check cache first if provided
    if cache:
        cached_info = cache.get_file_info(project_id, file_id)
        if cached_info:
            return cached_info
            
    # Try different URL formats
    urls = [
        f"https://www.curseforge.com/minecraft/mc-mods/{project_id}/files/{file_id}",
        f"https://legacy.curseforge.com/minecraft/mc-mods/p{project_id}/files/{file_id}"
    ]
    
    for url in urls:
        try:
            # Use a realistic user agent
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                continue  # Try next URL if this one fails
                
            # Parse the HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try multiple ways to extract file name
            file_name_element = (
                soup.find("h2", class_="font-bold text-lg") or 
                soup.find("h3", class_="text-primary-500") or
                soup.select_one(".project-file-name") or
                soup.select_one("main h1") or
                soup.select_one(".project-file-page-header")
            )
            
            file_name = file_name_element.text.strip() if file_name_element else f"File-{file_id}"
            
            # Create a file info dictionary
            file_info = {
                "id": file_id,
                "fileName": file_name,
                "displayName": file_name,
                "url": url
            }
            
            # Cache the result if cache is provided
            if cache:
                cache.set_file_info(project_id, file_id, file_info)
                
            return file_info
        
        except (requests.RequestException, AttributeError) as e:
            print(f"Error with URL {url} for file {file_id} of project {project_id}: {e}", file=sys.stderr)
            continue  # Try next URL
    
    # If we get here, all URLs failed
    print(f"Failed to scrape info for file {file_id} of project {project_id}", file=sys.stderr)
    
    # Return minimal information
    minimal_info = {
        "id": file_id,
        "fileName": f"File-{file_id}",
        "displayName": f"File-{file_id}",
        "url": f"https://www.curseforge.com/minecraft/mc-mods/{project_id}/files/{file_id}"
    }
    
    # Cache the minimal result if cache is provided
    if cache:
        cache.set_file_info(project_id, file_id, minimal_info)
        
    return minimal_info


def scrape_all_mod_info(manifest: Dict[str, Any], cache: Optional[CurseForgeCache] = None) -> Dict[int, Dict[str, Any]]:
    """
    Scrape information for all mods in a manifest file using parallel requests.
    
    Args:
        manifest: The parsed manifest.json
        cache: Optional cache to use
        
    Returns:
        Dictionary mapping project IDs to mod information
    """
    project_ids = [item['projectID'] for item in manifest.get('files', [])]
    mod_info = {}
    
    # Deduplicate project IDs
    project_ids = list(set(project_ids))
    
    print(f"Processing information for {len(project_ids)} mods...")
    
    # Check cache first for all project IDs
    if cache:
        for pid in project_ids[:]:  # Create a copy to modify while iterating
            cached_info = cache.get_mod_info(pid)
            if cached_info:
                mod_info[pid] = cached_info
                project_ids.remove(pid)
    
    # Only scrape the remaining project IDs
    if project_ids:
        print(f"Scraping information for {len(project_ids)} mods (not in cache)...")
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(scrape_mod_info, pid, cache): pid for pid in project_ids}
            for future in futures:
                pid = futures[future]
                try:
                    result = future.result()
                    if result:
                        mod_info[pid] = result
                        print(f"Scraped info for {result.get('name', 'Unknown')} (ID: {pid})")
                    # Add a small delay to avoid overwhelming the server
                    time.sleep(0.5)
                except Exception as e:
                    print(f"Error processing project {pid}: {e}", file=sys.stderr)
    
    return mod_info


def scrape_all_file_info(manifest: Dict[str, Any], cache: Optional[CurseForgeCache] = None) -> Dict[Tuple[int, int], Dict[str, Any]]:
    """
    Scrape information for all files in a manifest using parallel requests.
    
    Args:
        manifest: The parsed manifest.json
        cache: Optional cache to use
        
    Returns:
        Dictionary mapping (project_id, file_id) tuples to file information
    """
    file_info = {}
    files = [(item['projectID'], item['fileID']) for item in manifest.get('files', [])]
    
    # Deduplicate file entries
    files = list(set(files))
    
    print(f"Processing information for {len(files)} files...")
    
    # Check cache first for all file IDs
    if cache:
        for file_tuple in files[:]:  # Create a copy to modify while iterating
            pid, fid = file_tuple
            cached_info = cache.get_file_info(pid, fid)
            if cached_info:
                file_info[file_tuple] = cached_info
                files.remove(file_tuple)
    
    # Only scrape the remaining files
    if files:
        print(f"Scraping information for {len(files)} files (not in cache)...")
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(scrape_file_info, pid, fid, cache): (pid, fid) for pid, fid in files}
            for future in futures:
                pid, fid = futures[future]
                try:
                    result = future.result()
                    if result:
                        file_info[(pid, fid)] = result
                        print(f"Scraped info for file {result.get('fileName', f'File-{fid}')} (Project: {pid})")
                    # Add a small delay to avoid overwhelming the server
                    time.sleep(0.5)
                except Exception as e:
                    print(f"Error processing file {fid} of project {pid}: {e}", file=sys.stderr)
    
    return file_info


def generate_markdown(old_manifest: Dict[str, Any], new_manifest: Dict[str, Any], 
                      additions: List, removals: List, updates: List,
                      old_mod_info: Dict[int, Dict[str, Any]] = None,
                      new_mod_info: Dict[int, Dict[str, Any]] = None,
                      file_info: Dict[Tuple[int, int], Dict[str, Any]] = None) -> str:
    """
    Generate markdown output based on comparison results.
    
    Args:
        old_manifest: The old manifest.json
        new_manifest: The new manifest.json
        additions: List of added mods
        removals: List of removed mods
        updates: List of updated mods
        old_mod_info: Optional dictionary of mod information for old mods
        new_mod_info: Optional dictionary of mod information for new mods
        file_info: Optional dictionary of file information
    
    Returns:
        Markdown formatted comparison
    """
    old_version = old_manifest.get('version', 'Unknown')
    new_version = new_manifest.get('version', 'Unknown')
    old_name = old_manifest.get('name', 'Unknown')
    new_name = new_manifest.get('name', 'Unknown')
    
    markdown = f"# Manifest Comparison\n\n"
    markdown += f"Comparing {old_name} v{old_version} to {new_name} v{new_version}\n\n"
    
    # Minecraft version and loader comparison
    old_mc = old_manifest.get('minecraft', {}).get('version', 'Unknown')
    new_mc = new_manifest.get('minecraft', {}).get('version', 'Unknown')
    
    if old_mc != new_mc:
        markdown += f"## Minecraft Version Change\n\n"
        markdown += f"- Changed from `{old_mc}` to `{new_mc}`\n\n"
    
    # Mod loader comparison
    old_loaders = old_manifest.get('minecraft', {}).get('modLoaders', [])
    new_loaders = new_manifest.get('minecraft', {}).get('modLoaders', [])
    
    if old_loaders != new_loaders:
        markdown += f"## Mod Loader Changes\n\n"
        markdown += "### Old Loaders:\n"
        for loader in old_loaders:
            primary = "primary" if loader.get('primary', False) else "secondary"
            markdown += f"- `{loader.get('id', 'Unknown')}` ({primary})\n"
        
        markdown += "\n### New Loaders:\n"
        for loader in new_loaders:
            primary = "primary" if loader.get('primary', False) else "secondary"
            markdown += f"- `{loader.get('id', 'Unknown')}` ({primary})\n\n"
    
    # Additions section
    if additions:
        markdown += "## Additions\n\n"
        
        # Enhanced table with mod names if API info is available
        if new_mod_info and file_info:
            markdown += "| Project ID | Mod Name | File Name | Version | Required |\n"
            markdown += "|-----------|----------|-----------|---------|----------|\n"
            for mod in additions:
                project_id = mod['projectID']
                file_id = mod['fileID']
                required = str(mod.get('required', False))
                
                mod_name = "Unknown"
                file_name = "Unknown"
                version = "Unknown"
                
                if project_id in new_mod_info:
                    mod_name = new_mod_info[project_id].get('name', 'Unknown')
                
                if (project_id, file_id) in file_info:
                    file_data = file_info[(project_id, file_id)]
                    file_name = file_data.get('fileName', 'Unknown')
                    version = file_data.get('displayName', file_data.get('fileName', 'Unknown'))
                
                markdown += f"| {project_id} | {mod_name} | {file_name} | {version} | {required} |\n"
        else:
            # Basic table without API info
            markdown += "| Project ID | File ID | Required |\n"
            markdown += "|-----------|---------|----------|\n"
            for mod in additions:
                required = str(mod.get('required', False))
                markdown += f"| {mod['projectID']} | {mod['fileID']} | {required} |\n"
        
        markdown += "\n"
    
    # Removals section
    if removals:
        markdown += "## Removals\n\n"
        
        # Enhanced table with mod names if API info is available
        if old_mod_info and file_info:
            markdown += "| Project ID | Mod Name | File Name | Version | Required |\n"
            markdown += "|-----------|----------|-----------|---------|----------|\n"
            for mod in removals:
                project_id = mod['projectID']
                file_id = mod['fileID']
                required = str(mod.get('required', False))
                
                mod_name = "Unknown"
                file_name = "Unknown"
                version = "Unknown"
                
                if project_id in old_mod_info:
                    mod_name = old_mod_info[project_id].get('name', 'Unknown')
                
                if (project_id, file_id) in file_info:
                    file_data = file_info[(project_id, file_id)]
                    file_name = file_data.get('fileName', 'Unknown')
                    version = file_data.get('displayName', file_data.get('fileName', 'Unknown'))
                
                markdown += f"| {project_id} | {mod_name} | {file_name} | {version} | {required} |\n"
        else:
            # Basic table without API info
            markdown += "| Project ID | File ID | Required |\n"
            markdown += "|-----------|---------|----------|\n"
            for mod in removals:
                required = str(mod.get('required', False))
                markdown += f"| {mod['projectID']} | {mod['fileID']} | {required} |\n"
        
        markdown += "\n"
    
    # Updates section
    if updates:
        markdown += "## Updates\n\n"
        
        # Enhanced table with mod names if API info is available
        if new_mod_info and file_info:
            markdown += "| Project ID | Mod Name | From Version | To Version |\n"
            markdown += "|-----------|----------|--------------|------------|\n"
            for mod in updates:
                project_id = mod['projectID']
                old_file_id = mod['old_fileID']
                new_file_id = mod['new_fileID']
                
                mod_name = "Unknown"
                old_version = "Unknown"
                new_version = "Unknown"
                
                if project_id in new_mod_info:
                    mod_name = new_mod_info[project_id].get('name', 'Unknown')
                
                if (project_id, old_file_id) in file_info:
                    file_data = file_info[(project_id, old_file_id)]
                    old_version = file_data.get('displayName', file_data.get('fileName', 'Unknown'))
                
                if (project_id, new_file_id) in file_info:
                    file_data = file_info[(project_id, new_file_id)]
                    new_version = file_data.get('displayName', file_data.get('fileName', 'Unknown'))
                
                markdown += f"| {project_id} | {mod_name} | {old_version} | {new_version} |\n"
        else:
            # Basic table without API info
            markdown += "| Project ID | Old File ID | New File ID |\n"
            markdown += "|-----------|------------|------------|\n"
            for mod in updates:
                markdown += f"| {mod['projectID']} | {mod['old_fileID']} | {mod['new_fileID']} |\n"
        
        markdown += "\n"
    
    return markdown


def main():
    parser = argparse.ArgumentParser(description='Compare mod manifest files from two zip archives.')
    parser.add_argument('old_zip', help='Path to the old/first zip file')
    parser.add_argument('new_zip', help='Path to the new/second zip file')
    parser.add_argument('-o', '--output', help='Output file path (default: stdout)')
    parser.add_argument('--scrape', action='store_true', help='Scrape additional mod information from CurseForge website')
    parser.add_argument('--no-scrape-files', action='store_true', help='Skip scraping file information (faster)')
    parser.add_argument('--delay', type=float, default=0.5, help='Delay between requests in seconds (default: 0.5)')
    parser.add_argument('--max-workers', type=int, default=3, help='Maximum number of parallel workers (default: 3)')
    parser.add_argument('--cache-dir', type=str, default='.cursecache', help='Directory for cache files (default: .cursecache)')
    parser.add_argument('--no-cache', action='store_true', help='Disable caching')
    
    try:
        args = parser.parse_args()
        
        old_manifest = extract_manifest(args.old_zip)
        new_manifest = extract_manifest(args.new_zip)
        
        # Scrape additional mod information if requested
        old_mod_info = {}
        new_mod_info = {}
        file_info = {}
        
        if args.scrape:
            # Initialize cache if not disabled
            cache = None
            if not args.no_cache:
                cache = CurseForgeCache(args.cache_dir)
                print(f"Using cache directory: {args.cache_dir}")
            
            # Scrape mod information
            old_mod_info = scrape_all_mod_info(old_manifest, cache)
            
            # Only scrape new mod info if there are different projects
            old_project_ids = {item['projectID'] for item in old_manifest.get('files', [])}
            new_project_ids = {item['projectID'] for item in new_manifest.get('files', [])}
            if old_project_ids != new_project_ids:
                new_mod_info = scrape_all_mod_info(new_manifest, cache)
            else:
                new_mod_info = old_mod_info
            
            # Scrape file information if not disabled
            if not args.no_scrape_files:
                # Create combined manifest for file info scraping
                all_files = []
                for item in old_manifest.get('files', []):
                    all_files.append({"projectID": item['projectID'], "fileID": item['fileID']})
                for item in new_manifest.get('files', []):
                    # Skip if already added
                    if not any(f['projectID'] == item['projectID'] and f['fileID'] == item['fileID'] for f in all_files):
                        all_files.append({"projectID": item['projectID'], "fileID": item['fileID']})
                
                combined_manifest = {"files": all_files}
                file_info = scrape_all_file_info(combined_manifest, cache)
            
            # Print cache statistics if cache was used
            if cache:
                stats = cache.get_stats()
                print(f"\nCache statistics:")
                print(f"  Mod info: {stats['mod_hits']} hits, {stats['mod_misses']} misses")
                print(f"  File info: {stats['file_hits']} hits, {stats['file_misses']} misses")
                print(f"  Total: {stats['total_hits']} hits, {stats['total_misses']} misses")
        
        additions, removals, updates = compare_manifests(old_manifest, new_manifest)
        markdown = generate_markdown(old_manifest, new_manifest, additions, removals, updates, 
                                    old_mod_info, new_mod_info, file_info)
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(markdown)
            print(f"Comparison saved to {args.output}")
        else:
            print(markdown)
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    #main()
    results = scrape_mod_info('1226739')
    print(results)