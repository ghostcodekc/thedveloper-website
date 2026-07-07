# Extract HEVC headers (VPS/SPS/PPS) from app-downloaded eufy video.
# MP4 containers don't use Annex B start codes, so we demux to a raw
# .h265 bitstream first, then find the first IDR frame.

import argparse
import os
import subprocess
import sys
import tempfile

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
    sys.exit(1)

# Output name is derived from the input; the intermediate bitstream goes to a
# temp file so we never overwrite an existing '.h265' next to the video.
base_name = os.path.splitext(MP4_FILE)[0]
OUTPUT_FILE = f'{base_name}_hevc_headers.bin'
h265_fd, H265_FILE = tempfile.mkstemp(suffix='.h265')
os.close(h265_fd)

try:
    # Step 1: Demux raw Annex-B H.265 bitstream from the MP4
    result = subprocess.run([
        'ffmpeg', '-y', '-i', MP4_FILE,
        '-c:v', 'copy', '-bsf:v', 'hevc_mp4toannexb',
        '-an', H265_FILE
    ], capture_output=True)

    if result.returncode != 0:
        print("ERROR: ffmpeg demux failed:")
        print(result.stderr.decode())
        sys.exit(1)

    # Step 2: Scan the bitstream for the first IDR frame (NAL type 19 or 20).
    # The headers we want are everything before it, and they sit at the very
    # start of the stream, so we read in chunks and stop at the first IDR
    # instead of loading the whole (potentially huge) bitstream into memory.
    CHUNK_SIZE = 1 << 16  # 64 KiB
    headers = None
    buf = bytearray()
    search_start = 0
    with open(H265_FILE, 'rb') as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            buf.extend(chunk)
            i = search_start
            limit = len(buf) - 5  # need 4-byte start code + 1 NAL header byte
            while i <= limit:
                if buf[i:i + 4] == b'\x00\x00\x00\x01':
                    nal_type = (buf[i + 4] >> 1) & 0x3F
                    if nal_type in (19, 20):  # IDR_W_RADL or IDR_N_LP
                        headers = bytes(buf[:i])
                        break
                    i += 4
                else:
                    i += 1
            if headers is not None:
                break
            # Keep 4 bytes of overlap so a start code straddling the read
            # boundary is still detected on the next pass.
            search_start = max(0, len(buf) - 4)

    if headers is None:
        print("ERROR: No IDR frame (NAL type 19/20) found in the bitstream.")
        sys.exit(1)

    with open(OUTPUT_FILE, 'wb') as f:
        f.write(headers)
    print(f"Success! Extracted {len(headers)} bytes of VPS/SPS/PPS headers -> {OUTPUT_FILE}")
finally:
    # Always remove the intermediate, including on ffmpeg failure / no IDR.
    if os.path.exists(H265_FILE):
        os.remove(H265_FILE)
