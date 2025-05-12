#!/usr/bin/env python3

import os
import hashlib
import argparse
import difflib
from collections import defaultdict
import re
import itertools

def calculate_hash(filepath, block_size=65536):
    """Calculates the SHA256 hash of a file."""
    hasher = hashlib.sha256()
    try:
        with open(filepath, 'rb') as file:
            while True:
                buf = file.read(block_size)
                if not buf:
                    break
                hasher.update(buf)
        return hasher.hexdigest()
    except IOError as e:
        print(f"Warning: Could not read file {filepath}: {e}")
        return None
    except Exception as e:
        print(f"Warning: Error processing file {filepath}: {e}")
        return None

def read_file_lines(filepath):
    """Reads a file and returns its lines, handling potential encoding errors."""
    try:
        # Try UTF-8 first, then fallback to default encoding with error handling
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.readlines()
    except UnicodeDecodeError:
        try:
            # Use default encoding and replace errors
            with open(filepath, 'r', encoding=None, errors='replace') as f:
                print(f"Warning: UTF-8 decoding failed for {filepath}. Using default encoding with replacements.")
                return f.readlines()
        except IOError as e:
            print(f"Warning: Could not read file {filepath}: {e}")
            return None
        except Exception as e:
            print(f"Warning: Error reading file {filepath}: {e}")
            return None
    except IOError as e:
        print(f"Warning: Could not read file {filepath}: {e}")
        return None
    except Exception as e:
        print(f"Warning: Error reading file {filepath}: {e}")
        return None


def find_duplicates(folder_path, similarity_threshold=None):
    """
    Finds duplicate files based on exact hash match and optionally similarity.
    Returns a dictionary mapping files to keep to lists of files to delete.
    """
    exact_hashes = defaultdict(list)
    files_to_delete = defaultdict(list)
    unique_files_after_exact = set() # Keep track of files remaining after exact match phase

    print(f"Scanning folder: {folder_path}")
    print("Phase 1: Finding exact duplicates...")

    # --- Phase 1: Exact Hash Matching ---
    for dirpath, _, filenames in os.walk(folder_path):
        # Only process files directly in the target folder
        if dirpath != folder_path:
            continue

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if os.path.isfile(filepath) and not os.path.islink(filepath):
                file_hash = calculate_hash(filepath)
                if file_hash:
                    exact_hashes[file_hash].append(filepath)

    # Identify exact duplicates and decide which to keep/delete
    for file_hash, filepaths in exact_hashes.items():
        if len(filepaths) > 1:
            # Sort alphabetically to consistently choose the first one
            filepaths.sort()
            keep_file = filepaths[0]
            files_to_delete[keep_file].extend(filepaths[1:])
            unique_files_after_exact.add(keep_file) # Add the one we keep
        elif len(filepaths) == 1:
             unique_files_after_exact.add(filepaths[0]) # Add unique files

    print(f"Phase 1: Found {sum(len(v) for v in files_to_delete.values())} exact duplicates.")

    # --- Phase 2: Similarity Matching (if threshold is set) ---
    if similarity_threshold is not None and similarity_threshold < 1.0:
        print(f"\nPhase 2: Finding similar duplicates (Threshold: {similarity_threshold:.2f})...")
        # Convert set to sorted list for consistent comparison order
        unique_list = sorted(list(unique_files_after_exact))
        potential_similar_deletes = set() # Track files marked for deletion in this phase

        # Compare all pairs of unique files
        for i in range(len(unique_list)):
            file1_path = unique_list[i]

            # Skip if file1 is already marked for deletion by similarity check
            if file1_path in potential_similar_deletes:
                continue

            # Read file1 content only once per outer loop iteration
            file1_lines = read_file_lines(file1_path)
            if file1_lines is None:
                continue # Skip if file1 couldn't be read

            for j in range(i + 1, len(unique_list)):
                file2_path = unique_list[j]

                # --- Skip similarity check if either file starts with MM.DD pattern ---
                filename1 = os.path.basename(file1_path)
                filename2 = os.path.basename(file2_path)
                if re.match(r"^\d{2}\.\d{2}", filename1) or re.match(r"^\d{2}\.\d{2}", filename2):
                    # Optional: print a message indicating the skip
                    # print(f"Skipping similarity check involving date-patterned file: {filename1} vs {filename2}")
                    continue
                # --- End skip ---
                # Skip if file2 is already marked for deletion
                if file2_path in potential_similar_deletes:
                    continue

                # Skip if file2 is already listed as a duplicate of *another* file
                # This check prevents deleting a file that's already kept vs an earlier file
                is_already_duplicate = False
                for keep_list in files_to_delete.values():
                    if file2_path in keep_list:
                        is_already_duplicate = True
                        break
                if is_already_duplicate:
                    continue

                # Read file2 content
                file2_lines = read_file_lines(file2_path)
                if file2_lines is None:
                    continue # Skip if file2 couldn't be read

                # Calculate similarity
                try:
                    matcher = difflib.SequenceMatcher(None, file1_lines, file2_lines, autojunk=False)
                    ratio = matcher.ratio()
                except Exception as e:
                    print(f"Warning: Could not compare {file1_path} and {file2_path}: {e}")
                    ratio = 0.0 # Treat as not similar on error

                if ratio >= similarity_threshold:
                    # Files are similar. Keep file1 (earlier in sorted list), mark file2 for deletion.
                    print(f"  - Found similar: '{os.path.basename(file1_path)}' and '{os.path.basename(file2_path)}' (Ratio: {ratio:.3f}). Keeping '{os.path.basename(file1_path)}'.")
                    files_to_delete[file1_path].append(file2_path)
                    potential_similar_deletes.add(file2_path) # Mark file2 for deletion

        num_similar = len(potential_similar_deletes)
        print(f"Phase 2: Found {num_similar} additional similar files to remove.")

    # Clean up: Ensure no file marked for deletion is also a key (a file to keep)
    final_deletes = defaultdict(list)
    all_deleted_files = set()
    for keep_list in files_to_delete.values():
        all_deleted_files.update(keep_list)

    for keep_file, delete_list in files_to_delete.items():
        if keep_file in all_deleted_files:
            # This shouldn't happen often with the current logic, but as a safeguard
            print(f"Warning: File '{keep_file}' was marked to be kept but is also in a delete list. Skipping its deletion rules.")
            continue
        # Filter out any files from delete_list that might have ended up as keys elsewhere
        final_deletes[keep_file] = [f for f in delete_list if f not in files_to_delete]

    return final_deletes


def delete_files(files_to_delete, dry_run=True):
    """Deletes the specified files."""
    if not files_to_delete:
        print("\nNo duplicate files found to delete.")
        return

    print("\n--- Files Marked for Deletion ---")
    total_to_delete_count = sum(len(v) for v in files_to_delete.values())
    total_deleted_count = 0

    if total_to_delete_count == 0:
         print("No duplicate files found to delete.")
         return

    for keep_file, delete_list in files_to_delete.items():
        if not delete_list:
            continue
        print(f"\nKeeping: {keep_file}")
        # Use set to avoid printing duplicates if a file was somehow listed twice
        unique_delete_list = sorted(list(set(delete_list)))
        for file_path in unique_delete_list:
            if dry_run:
                print(f"  [DRY RUN] Would delete: {file_path}")
            else:
                try:
                    os.remove(file_path)
                    print(f"  Deleted: {file_path}")
                    total_deleted_count += 1
                except OSError as e:
                    print(f"  Error deleting {file_path}: {e}")
        print("-" * 20)

    if dry_run:
        print(f"\n[DRY RUN] Completed. {total_to_delete_count} duplicate files identified (exact + similar).")
        print("Run with '--delete' and potentially '--similarity <ratio>' to actually delete files.")
    else:
        print(f"\nDeletion complete. {total_deleted_count} duplicate files removed.")

def main():
    parser = argparse.ArgumentParser(
        description="Find and optionally delete duplicate (exact or similar) files in a folder based on content.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter # Show default values in help
        )
    parser.add_argument("folder", help="The folder to scan for duplicates.")
    parser.add_argument("--delete", action="store_false", dest="dry_run", default=True,
                        help="Actually delete duplicate files. Default is dry run (list only).")
    parser.add_argument("--similarity", type=float, default=None, metavar='RATIO',
                        help="Similarity threshold (0.0 to 1.0). If set, performs similarity check "
                             "after exact match check. E.g., 0.95 for 95%% similar. "
                             "If not set, only exact duplicates are checked.")
    # Removed recursive option for now, sticking to original request scope
    # parser.add_argument("--recursive", action="store_true",
    #                     help="Scan subfolders recursively.")

    args = parser.parse_args()

    target_folder = os.path.abspath(args.folder)

    if not os.path.isdir(target_folder):
        print(f"Error: Folder not found: {target_folder}")
        return

    if args.similarity is not None and not (0.0 <= args.similarity <= 1.0):
         print("Error: Similarity threshold must be between 0.0 and 1.0")
         return

    delete_mode = not args.dry_run
    if delete_mode:
        confirm_msg = f"WARNING: You are about to permanently delete "
        if args.similarity is not None:
             confirm_msg += f"similar (>= {args.similarity:.1%}) and "
        confirm_msg += f"exact duplicate files in '{target_folder}'.\n"
        confirm_msg += ("The script attempts to keep the alphabetically first copy "
                        "among duplicates/similar files found.\n"
                        "Are you absolutely sure? (yes/no): ")
        confirm = input(confirm_msg).lower()
        if confirm != 'yes':
            print("Aborting deletion.")
            return

    duplicates_to_delete = find_duplicates(target_folder, args.similarity)
    delete_files(duplicates_to_delete, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
