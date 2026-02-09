#!/usr/bin/env python3
"""
Main aggregation script to combine all sources and generate final output files.
"""

import requests
import json
import os
from typing import Set, Dict, List, Tuple
from datetime import datetime

def load_domains_from_file(file_path: str) -> Set[str]:
    """Load domains from a file, one per line, ignoring empty lines and comments."""
    domains = set()
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    domains.add(line.lower())
    return domains

def download_source(url: str, output_file: str) -> None:
    """Download a source file."""
    print(f"Downloading {url}...")
    response = requests.get(url)
    response.raise_for_status()
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(response.text)
    print(f"Saved to {output_file}")

def categorize_domains() -> Tuple[Set[str], Set[str], Set[str]]:
    """Categorize domains into disposable, free, and paid personal."""

    # Create temp directory
    os.makedirs('temp', exist_ok=True)

    # Load sources configuration
    with open('sources/sources.json', 'r') as f:
        sources = json.load(f)

    # Track per-source domain sets for stats
    source_domains: Dict[str, Set[str]] = {}

    # Download and combine all disposable domain sources
    print("Loading disposable domain sources...")
    disposable_domains = set()

    for i, source in enumerate(sources['disposable']):
        temp_file = f'temp/disposable_{i}.txt'
        download_source(source['url'], temp_file)
        domains = load_domains_from_file(temp_file)
        source_domains[source['name']] = domains
        disposable_domains.update(domains)
        print(f"  - {source['name']}: {len(domains):,} domains")

    # Add our custom disposable domains
    custom_disposable = load_domains_from_file('sources/custom_disposable.txt')
    source_domains['custom-disposable'] = custom_disposable
    disposable_domains.update(custom_disposable)
    print(f"  - custom disposable: {len(custom_disposable)} domains")

    print(f"Total disposable domains (after deduplication): {len(disposable_domains):,}")

    # Load paid personal domains
    paid_personal_domains = load_domains_from_file('sources/paid_personal.txt')
    source_domains['paid-personal'] = paid_personal_domains
    print(f"Paid personal domains: {len(paid_personal_domains)} domains")

    # Download and combine all free/paid provider sources
    print("Loading free/paid email provider sources...")
    all_provider_domains = set()

    for i, source in enumerate(sources['free_paid']):
        temp_file = f'temp/free_paid_{i}.txt'
        download_source(source['url'], temp_file)
        domains = load_domains_from_file(temp_file)
        source_domains[source['name']] = domains
        all_provider_domains.update(domains)
        print(f"  - {source['name']}: {len(domains):,} domains")

    print(f"Total free/paid domains (after deduplication): {len(all_provider_domains):,}")

    # Load allowlist
    allowlist = load_domains_from_file('sources/allowlist.txt')
    print(f"Allowlist domains: {len(allowlist)} domains")

    # Remove disposable, paid personal, and allowlisted domains from all_providers
    print("Categorizing domains...")
    free_domains = all_provider_domains - disposable_domains - paid_personal_domains - allowlist

    # Remove paid personal and allowlisted domains from disposable lists
    disposable_domains -= allowlist
    disposable_domains -= paid_personal_domains

    print(f"Final categorization:")
    print(f"  - Disposable: {len(disposable_domains):,} domains")
    print(f"  - Free: {len(free_domains):,} domains")
    print(f"  - Paid Personal: {len(paid_personal_domains)} domains")

    # Write source stats
    write_source_stats(source_domains, disposable_domains, free_domains, paid_personal_domains)

    return disposable_domains, free_domains, paid_personal_domains


def write_source_stats(source_domains: Dict[str, Set[str]],
                       disposable: Set[str], free: Set[str],
                       paid_personal: Set[str]) -> None:
    """Write per-source contribution stats to output/source_stats.json."""
    all_domains = disposable | free | paid_personal
    seen: Set[str] = set()
    stats = {}

    # Process sources in order: largest first for unique-contribution calc
    for name, domains in sorted(source_domains.items(), key=lambda x: -len(x[1])):
        unique = domains - seen
        seen.update(domains)
        stats[name] = {
            'total': len(domains),
            'unique_contribution': len(unique),
            'overlap': len(domains) - len(unique),
        }

    source_stats = {
        'generated': datetime.now().isoformat(),
        'total_final_domains': len(all_domains),
        'sources': stats,
    }

    os.makedirs('output', exist_ok=True)
    with open('output/source_stats.json', 'w') as f:
        json.dump(source_stats, f, indent=2)
    print("  Source stats written to output/source_stats.json")

def compute_deltas(new_domains: Dict[str, List[str]], max_samples: int = 20) -> Dict:
    """Compare new domains against existing output files and write delta.json.

    Must be called BEFORE output files are overwritten so that the old
    files on disk still reflect the previous release.
    """
    old_domains: Dict[str, Set[str]] = {}
    for category in ('disposable', 'free', 'paid_personal'):
        path = f'output/{category}.txt'
        old_domains[category] = load_domains_from_file(path)

    all_added: List[str] = []
    all_removed: List[str] = []

    delta: Dict = {'categories': {}, 'total_added': 0, 'total_removed': 0}
    for category in ('disposable', 'free', 'paid_personal'):
        new_set = set(new_domains[category])
        old_set = old_domains[category]
        added = sorted(new_set - old_set)
        removed = sorted(old_set - new_set)
        delta['categories'][category] = {
            'added': len(added),
            'removed': len(removed),
            'total': len(new_set),
        }
        delta['total_added'] += len(added)
        delta['total_removed'] += len(removed)
        all_added.extend(added)
        all_removed.extend(removed)

    delta['total_domains'] = sum(d['total'] for d in delta['categories'].values())

    # Include up to max_samples domain names for the release notes
    delta['added_samples'] = sorted(all_added)[:max_samples]
    delta['removed_samples'] = sorted(all_removed)[:max_samples]

    with open('output/delta.json', 'w') as f:
        json.dump(delta, f, indent=2)
    print(f"  Delta: +{delta['total_added']} / -{delta['total_removed']} domains")
    return delta


def generate_outputs(disposable: Set[str], free: Set[str], paid_personal: Set[str]) -> None:
    """Generate final output files in multiple formats."""
    
    os.makedirs('output', exist_ok=True)
    
    # Prepare new domain data for comparison
    new_domains = {
        'disposable': sorted(list(disposable)),
        'free': sorted(list(free)),
        'paid_personal': sorted(list(paid_personal))
    }
    
    # Compute deltas BEFORE overwriting output files so we compare against
    # the previous release's data still on disk.
    delta = compute_deltas(new_domains)

    # Check if domain content has actually changed
    existing_timestamp = None
    content_changed = True  # Default to True if no existing file

    if os.path.exists('output/email_domains.json'):
        try:
            with open('output/email_domains.json', 'r') as f:
                existing_data = json.load(f)
                existing_domains = existing_data.get('domains', {})
                existing_timestamp = existing_data.get('metadata', {}).get('generated')

                # Compare domain content (ignore metadata)
                content_changed = existing_domains != new_domains
        except (json.JSONDecodeError, KeyError):
            # If we can't parse existing file, assume content changed
            content_changed = True

    # Use existing timestamp if content hasn't changed, otherwise use current time
    if content_changed or existing_timestamp is None:
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).isoformat()
    else:
        timestamp = existing_timestamp
    
    # Combined data structure
    data = {
        'metadata': {
            'generated': timestamp,
            'total_domains': len(disposable) + len(free) + len(paid_personal),
            'categories': {
                'disposable': len(disposable),
                'free': len(free),
                'paid_personal': len(paid_personal)
            }
        },
        'domains': new_domains
    }
    
    # JSON output (most compact)
    with open('output/email_domains.json', 'w') as f:
        json.dump(data, f, separators=(',', ':'))
    
    # CSV output for easy consumption
    import csv
    with open('output/email_domains.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['domain', 'category'])
        
        for domain in sorted(disposable):
            writer.writerow([domain, 'disposable'])
        for domain in sorted(free):
            writer.writerow([domain, 'free'])
        for domain in sorted(paid_personal):
            writer.writerow([domain, 'paid_personal'])
    
    # Individual category files for convenience
    with open('output/disposable.txt', 'w') as f:
        for domain in sorted(disposable):
            f.write(f"{domain}\n")
    
    with open('output/free.txt', 'w') as f:
        for domain in sorted(free):
            f.write(f"{domain}\n")
    
    with open('output/paid_personal.txt', 'w') as f:
        for domain in sorted(paid_personal):
            f.write(f"{domain}\n")
    
    print(f"Generated outputs:")
    print(f"  - Disposable: {len(disposable)} domains")
    print(f"  - Free: {len(free)} domains") 
    print(f"  - Paid Personal: {len(paid_personal)} domains")
    print(f"  - Total: {len(disposable) + len(free) + len(paid_personal)} domains")
    
    if content_changed:
        print("  ✓ Domain content has changed - timestamp updated")
    else:
        print("  ✓ Domain content unchanged - timestamp preserved")

def main():
    print("Starting email domain aggregation...")
    
    disposable, free, paid_personal = categorize_domains()
    generate_outputs(disposable, free, paid_personal)
    
    print("Aggregation complete!")

if __name__ == "__main__":
    main()