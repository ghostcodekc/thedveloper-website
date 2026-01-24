#!/usr/bin/env python3
"""
eufy SD Card Full Extraction Tool
Extracts and converts all media from eufy security camera SD cards:
  - .zxvideo → .mp4 (with synced audio)
  - .jpg → copied (encrypted, preserved for future)
  - .txt → copied (JSON metadata)

Usage:
  # Batch mode - extract all from SD card
  python3 convert_eufy_videos.py --source /path/to/Camera00 --dest ~/Downloads/eufy_converted

  # Single file mode
  python3 convert_eufy_videos.py --source /path/to/file.zxvideo --dest ~/Downloads/eufy_converted

  # Examples with typical eufy paths:
  # python3 convert_eufy_videos.py --source "/Volumes/8416P0023340562/Camera00" --dest ~/Downloads/eufy_converted
  # python3 convert_eufy_videos.py --source "/Volumes/8416P0023340562 2/Camera00/event/202404/20240425/20240425182650.zxvideo" --dest ~/output
"""

import argparse
import os
import sys
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

# === CONFIGURATION ===
SCRIPT_DIR = Path(__file__).parent
HEADERS_FILE = SCRIPT_DIR / "hevc_headers.bin"

# Audio sync offset (seconds) - matches eufy app behavior
AUDIO_OFFSET = -0.127

# Video encoding settings
# CRF: 18=high quality/large files, 23=balanced, 28=smaller, 32=matches app size
VIDEO_CRF = 32

# Preset: ultrafast, fast, medium, slow (slower = better compression)
VIDEO_PRESET = "medium"

FFMPEG_VIDEO_OPTS = [
    "-c:v", "libx265",
    "-preset", VIDEO_PRESET,
    "-crf", str(VIDEO_CRF),
    "-tag:v", "hvc1",
    "-pix_fmt", "yuv420p"
]

# Audio encoding
FFMPEG_AUDIO_OPTS = ["-c:a", "aac", "-b:a", "64k"]


def extract_audio_from_zxvideo(data: bytes) -> bytes:
    """Extract AAC audio frames from zxvideo data"""
    
    def parse_adts(data, pos):
        """Parse ADTS header, return (is_valid, frame_length)"""
        if pos + 7 > len(data):
            return False, 0
        if data[pos] != 0xFF or (data[pos+1] & 0xF0) != 0xF0:
            return False, 0
        
        profile = ((data[pos+2] >> 6) & 0x03) + 1
        sample_rate_idx = (data[pos+2] >> 2) & 0x0F
        channel_cfg = ((data[pos+2] & 0x01) << 2) | ((data[pos+3] >> 6) & 0x03)
        frame_len = ((data[pos+3] & 0x03) << 11) | (data[pos+4] << 3) | ((data[pos+5] >> 5) & 0x07)
        
        sample_rates = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 
                       16000, 12000, 11025, 8000, 7350, 0, 0, 0]
        sample_rate = sample_rates[sample_rate_idx] if sample_rate_idx < 16 else 0
        
        is_valid = (
            7 <= frame_len <= 1024 and
            sample_rate in [8000, 16000, 24000, 32000] and
            channel_cfg in [1, 2] and
            profile == 2  # AAC-LC
        )
        return is_valid, frame_len
    
    audio_data = bytearray()
    i = 0
    while i < len(data) - 7:
        if data[i] == 0xFF and (data[i+1] & 0xF0) == 0xF0:
            is_valid, frame_len = parse_adts(data, i)
            if is_valid and i + frame_len <= len(data):
                audio_data.extend(data[i:i+frame_len])
                i += frame_len
                continue
        i += 1
    
    return bytes(audio_data)


def extract_video_from_zxvideo(data: bytes, headers: bytes) -> bytes:
    """Extract video NAL units and prepend headers"""
    video_start = data.find(b'\x00\x00\x00\x01', 0x10)
    if video_start == -1:
        return None
    return headers + data[video_start:]


def convert_single_video(zxvideo_path: Path, output_path: Path, headers: bytes) -> tuple:
    """Convert a single .zxvideo file to MP4 with synced audio"""
    try:
        # Read source file
        data = zxvideo_path.read_bytes()
        
        # Extract video and audio
        video_data = extract_video_from_zxvideo(data, headers)
        audio_data = extract_audio_from_zxvideo(data)
        
        if video_data is None:
            return (zxvideo_path, False, "No video NAL found")
        
        # Create output directory
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Use temp files for intermediate data
        with tempfile.NamedTemporaryFile(suffix='.h265', delete=False) as vf:
            vf.write(video_data)
            video_temp = vf.name
        
        audio_temp = None
        has_audio = bool(audio_data)
        if has_audio:
            with tempfile.NamedTemporaryFile(suffix='.aac', delete=False) as af:
                af.write(audio_data)
                audio_temp = af.name
        
        try:
            # Build ffmpeg command
            cmd = ['ffmpeg', '-y', '-f', 'hevc', '-r', '15', '-i', video_temp]
            
            if has_audio:
                # Add audio with sync offset
                cmd.extend(['-itsoffset', str(AUDIO_OFFSET), '-i', audio_temp])
            
            cmd.extend(FFMPEG_VIDEO_OPTS)
            
            if has_audio:
                cmd.extend(FFMPEG_AUDIO_OPTS)
                cmd.extend(['-map', '0:v', '-map', '1:a', '-shortest'])
            
            cmd.extend(['-movflags', '+faststart', str(output_path)])
            
            # Run ffmpeg
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode == 0 and output_path.exists():
                size_mb = output_path.stat().st_size / (1024 * 1024)
                return (zxvideo_path, True, f"{size_mb:.1f} MB")
            else:
                return (zxvideo_path, False, result.stderr[:200] if result.stderr else "Unknown error")
        
        finally:
            # Cleanup temp files
            if os.path.exists(video_temp):
                os.unlink(video_temp)
            if audio_temp and os.path.exists(audio_temp):
                os.unlink(audio_temp)
    
    except Exception as e:
        return (zxvideo_path, False, str(e))


def copy_file(src: Path, dst: Path) -> bool:
    """Copy a file, creating parent directories if needed"""
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except Exception:
        return False


def is_encrypted_image(filepath: Path) -> bool:
    """Check if image file is eufy-encrypted (starts with 'eufysecurity:')"""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(13)
            return header == b'eufysecurity:'
    except:
        return False


def generate_thumbnail(video_path: Path, output_path: Path, timestamp: str = "00:00:01") -> bool:
    """Generate a thumbnail from a video file using ffmpeg"""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            'ffmpeg', '-y', '-ss', timestamp,
            '-i', str(video_path),
            '-vframes', '1',
            '-q:v', '2',
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        return result.returncode == 0 and output_path.exists()
    except:
        return False


def generate_thumbnails(video_path: Path, output_base: Path, timestamps: list = ["00:00:01", "00:00:05"]) -> int:
    """Generate multiple thumbnails from a video at specified timestamps"""
    count = 0
    for ts in timestamps:
        # Convert timestamp to filename suffix (00:00:01 -> 1s, 00:00:05 -> 5s)
        seconds = ts.split(":")[-1].lstrip("0") or "0"
        suffix = f"_thumb_{seconds}s.jpg"
        output_path = output_base.with_name(output_base.stem + suffix)
        if generate_thumbnail(video_path, output_path, ts):
            count += 1
    return count


def find_all_files(base_path: str) -> dict:
    """Find all extractable files, grouped by type"""
    files = {
        "videos": [],      # .zxvideo
        "images": [],      # .jpg
        "metadata": [],    # .txt (per-video metadata)
    }
    
    for root, dirs, filenames in os.walk(base_path):
        for f in filenames:
            filepath = Path(root) / f
            
            # Skip temp files
            if f.startswith('tmprec'):
                continue
            
            if f.endswith('.zxvideo'):
                files["videos"].append(filepath)
            elif f.endswith('.jpg'):
                files["images"].append(filepath)
            elif f.endswith('.txt') and not f.endswith('.stats'):
                # Only per-video metadata, not daily stats
                files["metadata"].append(filepath)
    
    # Sort all lists
    for key in files:
        files[key] = sorted(files[key])
    
    return files


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="eufy SD Card Full Extraction Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Batch mode - extract all from SD card
  python3 convert_eufy_videos.py --source "/Volumes/8416P0023340562/Camera00" --dest ~/Downloads/eufy_converted

  # Single file mode
  python3 convert_eufy_videos.py --source "/path/to/file.zxvideo" --dest ~/output
        """
    )
    parser.add_argument("--source", "-s", required=True,
                        help="Source path: SD card Camera00 folder (batch) or single .zxvideo file")
    parser.add_argument("--dest", "-d", required=True,
                        help="Destination folder for converted files")
    parser.add_argument("--headers", "-H", default=str(HEADERS_FILE),
                        help=f"Path to hevc_headers.bin (default: {HEADERS_FILE})")
    
    args = parser.parse_args()
    
    source_path = Path(args.source)
    output_base = Path(args.dest).expanduser()
    headers_file = Path(args.headers)
    
    print("=" * 70)
    print("  eufy SD Card Full Extraction Tool")
    print("  - Videos: .zxvideo → .mp4 (synced audio, QuickTime compatible)")
    print("  - Images: .jpg snapshots & detection crops (encrypted, preserved)")
    print("  - Metadata: .txt JSON files with timestamps & detection info")
    print("=" * 70)
    
    # Load HEVC headers
    if not headers_file.exists():
        print(f"\n[ERROR] Headers file not found: {headers_file}")
        print("Please ensure hevc_headers.bin exists or specify with --headers")
        sys.exit(1)
    
    headers = headers_file.read_bytes()
    print(f"\n[✓] Loaded HEVC headers ({len(headers)} bytes)")
    
    # Check if source exists
    if not source_path.exists():
        print(f"[ERROR] Source not found: {source_path}")
        sys.exit(1)
    
    # Determine mode: single file or batch
    is_single_file = source_path.is_file() and source_path.suffix == '.zxvideo'
    
    if is_single_file:
        # Single file mode
        input_file = source_path
        output_base.mkdir(parents=True, exist_ok=True)
        base_name = input_file.stem  # e.g., "20240425182650"
        input_dir = input_file.parent
        
        output_file = output_base / input_file.name.replace('.zxvideo', '.mp4')
        print(f"\n[*] Converting: {input_file.name}")
        print(f"[*] Output: {output_file}")
        print(f"[*] Audio offset: {AUDIO_OFFSET}s")
        print("")
        
        # Copy metadata file
        associated_copied = 0
        txt_file = input_dir / f"{base_name}.txt"
        if txt_file.exists():
            dest = output_base / txt_file.name
            if copy_file(txt_file, dest):
                print(f"[✓] Copied: {txt_file.name}")
                associated_copied += 1
        
        # Copy encrypted images (preserved for future decryption attempts)
        copied_images = set()
        for img_file in input_dir.glob(f"{base_name}_*.jpg"):
            if img_file.name not in copied_images:
                dest = output_base / img_file.name
                if copy_file(img_file, dest):
                    print(f"[✓] Copied (encrypted): {img_file.name}")
                    associated_copied += 1
                    copied_images.add(img_file.name)
        
        # Convert video
        path, success, msg = convert_single_video(input_file, output_file, headers)
        
        # Generate thumbnails from converted video (since SD card images are encrypted)
        if success:
            thumb_count = generate_thumbnails(output_file, output_file, ["00:00:01", "00:00:05"])
            if thumb_count > 0:
                print(f"[✓] Generated: {thumb_count} thumbnails (1s, 5s)")
                associated_copied += thumb_count
        
        if success:
            print(f"[✓] SUCCESS: {output_file} ({msg})")
            print(f"\n[*] Total files: 1 video + {associated_copied} associated files")
            print(f"[!] Note: SD card images are encrypted (copied but not viewable)")
            print(f"[!] Thumbnails generated from video as viewable alternatives")
        else:
            print(f"[✗] FAILED: {msg}")
        
        sys.exit(0 if success else 1)
    
    # Batch mode
    sd_card_path = str(source_path)
    
    print(f"\n[*] Scanning: {sd_card_path}")
    files = find_all_files(sd_card_path)
    
    print(f"\n[✓] Found:")
    print(f"    Videos:   {len(files['videos']):,} .zxvideo files")
    print(f"    Images:   {len(files['images']):,} .jpg files")
    print(f"    Metadata: {len(files['metadata']):,} .txt files")
    
    total_files = sum(len(v) for v in files.values())
    if total_files == 0:
        print("\nNo files to extract!")
        sys.exit(0)
    
    output_base.mkdir(parents=True, exist_ok=True)
    print(f"\n[*] Output: {output_base}")
    
    # Estimate time
    video_count = len(files['videos'])
    est_minutes = video_count * 2  # ~2 min per video
    est_hours = est_minutes / 60
    
    print(f"\n[!] Estimated time: {est_hours:.1f} hours (for video conversion)")
    print(f"[!] Press Ctrl+C to cancel\n")
    
    try:
        input("Press Enter to start extraction...")
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)
    
    # ===== PHASE 1: Copy Images (encrypted but preserved) =====
    print("\n" + "=" * 70)
    print("PHASE 1: Copying Images (encrypted)")
    print("=" * 70)
    
    # Check if images are encrypted
    encrypted_count = 0
    for img_path in files['images'][:5]:  # Sample check
        if is_encrypted_image(img_path):
            encrypted_count += 1
    
    images_encrypted = encrypted_count > 0
    if images_encrypted:
        print(f"[!] Images are ENCRYPTED (eufy proprietary format)")
        print(f"[!] Cannot decrypt - copying anyway for preservation")
        print(f"[!] Will generate viewable thumbnails from converted videos")
    
    img_success = 0
    for i, img_path in enumerate(files['images']):
        rel_path = img_path.relative_to(sd_card_path)
        output_path = output_base / rel_path
        
        if (i + 1) % 100 == 0 or i == 0:
            print(f"[{i+1}/{len(files['images'])}] Copying images...", flush=True)
        
        if copy_file(img_path, output_path):
            img_success += 1
    
    print(f"[✓] Images: {img_success:,} copied" + (" (encrypted)" if images_encrypted else ""))
    
    # ===== PHASE 2: Copy Metadata =====
    print("\n" + "=" * 70)
    print("PHASE 2: Copying Metadata")
    print("=" * 70)
    
    meta_success = 0
    meta_fail = 0
    
    for i, meta_path in enumerate(files['metadata']):
        rel_path = meta_path.relative_to(sd_card_path)
        output_path = output_base / rel_path
        
        if (i + 1) % 100 == 0 or i == 0:
            print(f"[{i+1}/{len(files['metadata'])}] Copying metadata...", flush=True)
        
        if copy_file(meta_path, output_path):
            meta_success += 1
        else:
            meta_fail += 1
    
    print(f"[✓] Metadata: {meta_success:,} copied, {meta_fail} failed")
    
    # ===== PHASE 3: Convert Videos =====
    print("\n" + "=" * 70)
    print("PHASE 3: Converting Videos")
    print("=" * 70)
    
    vid_success = 0
    vid_fail = 0
    failed_videos = []
    
    for i, video_path in enumerate(files['videos']):
        rel_path = video_path.relative_to(sd_card_path)
        output_path = output_base / rel_path.with_suffix('.mp4')
        
        print(f"[{i+1}/{len(files['videos'])}] {rel_path.name}...", end=" ", flush=True)
        
        path, success, msg = convert_single_video(video_path, output_path, headers)
        
        if success:
            vid_success += 1
            print(f"✓ ({msg})", end="")
            
            # Generate thumbnails from converted video (at 1s and 5s)
            thumb_count = generate_thumbnails(output_path, output_path, ["00:00:01", "00:00:05"])
            if thumb_count > 0:
                print(f" +{thumb_count} thumbs")
            else:
                print("")
        else:
            vid_fail += 1
            failed_videos.append((rel_path.name, msg[:50]))
            print(f"✗")
    
    # ===== SUMMARY =====
    print("\n" + "=" * 70)
    print("EXTRACTION COMPLETE")
    print("=" * 70)
    print(f"\n  Videos:     {vid_success:,} converted, {vid_fail} failed")
    print(f"  Thumbnails: {vid_success * 2:,} generated (2 per video at 1s & 5s)")
    print(f"  Images:     {img_success:,} copied (encrypted, preserved for future)")
    print(f"  Metadata:   {meta_success:,} copied")
    print(f"\n  [!] Original images are encrypted with eufy proprietary format")
    print(f"  [!] Viewable thumbnails generated from converted videos")
    print(f"\n  Output: {output_base}")
    
    if failed_videos:
        print(f"\n  Failed videos ({len(failed_videos)}):")
        for name, reason in failed_videos[:10]:
            print(f"    - {name}: {reason}")
        if len(failed_videos) > 10:
            print(f"    ... and {len(failed_videos) - 10} more")
    
    # Write summary file
    summary = {
        "extraction_date": datetime.now().isoformat(),
        "source": sd_card_path,
        "output": str(output_base),
        "stats": {
            "videos_converted": vid_success,
            "videos_failed": vid_fail,
            "thumbnails_generated": vid_success * 2,
            "images_copied": img_success,
            "images_encrypted": True,
            "metadata_copied": meta_success,
        },
        "settings": {
            "video_crf": VIDEO_CRF,
            "video_preset": VIDEO_PRESET,
            "audio_offset": AUDIO_OFFSET,
        },
        "failed_videos": [{"name": n, "reason": r} for n, r in failed_videos]
    }
    
    summary_path = output_base / "extraction_summary.json"
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n  Summary saved: {summary_path}")


if __name__ == '__main__':
    main()
