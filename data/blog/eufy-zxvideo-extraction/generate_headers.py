# Extract HEVC headers (VPS/SPS/PPS) from app-downloaded eufy video.
# MP4 containers don't use Annex B start codes, so we demux to a raw
# .h265 bitstream first, then find the first IDR frame.

import subprocess, os, sys, argparse

# Parse command-line arguments
parser = argparse.ArgumentParser(
    description='Extract HEVC headers (VPS/SPS/PPS) from Eufy app-downloaded MP4 video'
)
parser.add_argument('--file', required=True, 
                    help='Path to the MP4 video file')
args = parser.parse_args()

MP4_FILE = args.file

# Validate that the file exists
if not os.path.isfile(MP4_FILE):
    print(f"ERROR: File not found: {MP4_FILE}")
    exit(1)

# Generate output filenames based on input
base_name = os.path.splitext(MP4_FILE)[0]
H265_FILE = f'{base_name}.h265'
OUTPUT_FILE = f'{base_name}_hevc_headers.bin'

# Step 1: Demux raw Annex-B H.265 bitstream from the MP4
result = subprocess.run([
    'ffmpeg', '-y', '-i', MP4_FILE,
    '-c:v', 'copy', '-bsf:v', 'hevc_mp4toannexb',
    '-an', H265_FILE
], capture_output=True)

if result.returncode != 0:
    print("ERROR: ffmpeg demux failed:")
    print(result.stderr.decode())
    exit(1)

# Step 2: Scan bitstream for the first IDR frame (NAL type 19 or 20)
with open(H265_FILE, 'rb') as f:
    data = f.read()

headers = None
for i in range(len(data) - 4):
    if data[i:i+4] == b'\x00\x00\x00\x01':
        nal_type = (data[i+4] >> 1) & 0x3F
        if nal_type in (19, 20):  # IDR_W_RADL or IDR_N_LP
            headers = data[:i]
            break

if headers:
    with open(OUTPUT_FILE, 'wb') as f:
        f.write(headers)
    print(f"Success! Extracted {len(headers)} bytes of VPS/SPS/PPS headers -> {OUTPUT_FILE}")
    # Clean up intermediate file
    os.remove(H265_FILE)
    print(f"Removed intermediate {H265_FILE}")
else:
    print("ERROR: No IDR frame (NAL type 19/20) found in the bitstream.")