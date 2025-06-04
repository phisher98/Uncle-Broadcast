import logging
from flask import Flask, request, Response
import requests
from urllib.parse import urlparse, urljoin, quote
import zlib
import base64
import re

# Setup basic logging to the command line
logging.basicConfig(format="[%(asctime)s] %(levelname)s: %(message)s", level=logging.INFO)

app = Flask(__name__)

# Default headers for outbound requests
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/33.0 Mobile/15E148 Safari/605.1.15",
    "Referer": "https://google.com/",
    "Origin": "https://google.com"
}

def decode_param_value(encoded_value_str):
    """Decode a base64/zlib compressed URL parameter."""
    if not encoded_value_str:
        return ""
    try:
        padding_needed = len(encoded_value_str) % 4
        if padding_needed:
            encoded_value_str += '=' * (4 - padding_needed)
        compressed_bytes = base64.urlsafe_b64decode(encoded_value_str.encode('utf-8'))
        original_value_bytes = zlib.decompress(compressed_bytes)
        original_value = original_value_bytes.decode('utf-8')
        return original_value
    except Exception as e:
        raise ValueError(f"Failed to decode/decompress parameter value: {e}")

def get_stream_id_from_url(m3u_url_str):
    """Extract stream id, e.g. premium123, from a url for key proxying."""
    match = re.search(r'(premium\d+)', m3u_url_str, re.IGNORECASE)
    return match.group(1) if match else None

@app.route('/proxy/m3u')
def proxy_m3u():
    logging.info("Received request for /proxy/m3u")
    encoded_main_url_param = request.args.get('url', '').strip()
    if not encoded_main_url_param:
        logging.error("Missing 'url' parameter")
        return "Error: Missing 'url' parameter", 400

    try:
        # Step 1: Decode the actual target playlist URL
        actual_target_m3u_url = decode_param_value(encoded_main_url_param)
        logging.info(f"Decoded target playlist URL: {actual_target_m3u_url}")
        if not actual_target_m3u_url:
            logging.error("Decoded target URL is empty")
            return "Error: Decoded target URL is empty", 400

        # Step 2: Fetch playlist from the real URL
        logging.info("Fetching playlist from original source...")
        response = requests.get(actual_target_m3u_url, headers=DEFAULT_HEADERS, allow_redirects=True, timeout=10)
        response.raise_for_status()
        final_url_after_redirects = response.url
        m3u_content = response.text
        logging.info(f"Fetched playlist (final URL after redirects: {final_url_after_redirects})")

        # Step 3: Rewrite playlist to proxy keys and segments
        stream_id_for_key = get_stream_id_from_url(actual_target_m3u_url) or get_stream_id_from_url(final_url_after_redirects)
        parsed_m3u_url = urlparse(final_url_after_redirects)
        base_url_for_m3u8_paths = f"{parsed_m3u_url.scheme}://{parsed_m3u_url.netloc}{parsed_m3u_url.path.rsplit('/', 1)[0]}/"

        modified_m3u8_lines = []
        for line in m3u_content.splitlines():
            line = line.strip()
            # Proxy key requests
            if line.startswith("#EXT-X-KEY") and 'URI="' in line:
                if stream_id_for_key:
                    new_key_uri = f"/keygrab/actual_key/{stream_id_for_key}"
                    line = re.sub(r'URI="[^"]+"', f'URI="{new_key_uri}"', line)
                    logging.info(f"Rewriting EXT-X-KEY URI for stream id {stream_id_for_key}")
                else:
                    original_key_uri_match = re.search(r'URI="([^"]+)"', line)
                    if original_key_uri_match:
                        original_key_uri_path = original_key_uri_match.group(1)
                        absolute_original_key_uri = urljoin(base_url_for_m3u8_paths, original_key_uri_path)
                        proxied_original_key = f"/keygrab/original_key_passthrough?url={quote(absolute_original_key_uri)}"
                        line = re.sub(r'URI="[^"]+"', f'URI="{proxied_original_key}"', line)
                        logging.info(f"Rewriting EXT-X-KEY URI to passthrough for {absolute_original_key_uri}")
            # Proxy TS segments
            elif line and not line.startswith("#"):
                segment_path = line
                absolute_segment_url = urljoin(base_url_for_m3u8_paths, segment_path)
                proxied_segment_url = f"/keygrab/ts?url={quote(absolute_segment_url)}"
                line = proxied_segment_url
                logging.info(f"Rewriting segment URI to {proxied_segment_url}")
            modified_m3u8_lines.append(line)

        modified_m3u8_content = "\n".join(modified_m3u8_lines)
        logging.info("Returning modified playlist to client.")
        return Response(modified_m3u8_content, content_type="application/vnd.apple.mpegurl")

    except ValueError as ve:
        logging.error(f"Error processing input parameters: {ve}")
        return f"Error processing input parameters: {str(ve)}", 400
    except requests.RequestException as e:
        logging.error(f"Error fetching M3U: {e}")
        return f"Error fetching M3U: {str(e)}", 500
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return f"An unexpected error occurred: {str(e)}", 500

@app.route('/keygrab/actual_key/<stream_id_for_key>')
def keygrab_proxy_actual_key(stream_id_for_key):
    """
    Placeholder endpoint for key fetching.
    In your streamlined use-case, you may want to replace this with
    a simple passthrough or custom logic as needed.
    """
    return f"Key fetch not implemented for stream_id: {stream_id_for_key}", 501

@app.route('/keygrab/ts')
def keygrab_proxy_ts():
    """Proxy TS segment requests."""
    ts_url = request.args.get('url', '').strip()
    if not ts_url:
        logging.error("Missing 'url' (keygrab ts)")
        return "Error: Missing 'url' (keygrab ts)", 400
    try:
        logging.info(f"Proxying TS segment from: {ts_url}")
        response = requests.get(ts_url, headers=DEFAULT_HEADERS, stream=True, allow_redirects=True, timeout=(5, 25))
        response.raise_for_status()
        content_type = response.headers.get("content-type", "video/mp2t")
        return Response(response.iter_content(chunk_size=32768), content_type=content_type)
    except requests.exceptions.Timeout:
        logging.error(f"Timeout TS (keygrab): {ts_url}")
        return f"Timeout TS (keygrab): {ts_url}", 504
    except requests.RequestException as e:
        logging.error(f"Error TS (keygrab): {e}")
        return f"Error TS (keygrab): {str(e)}", 500

@app.route('/keygrab/original_key_passthrough')
def keygrab_proxy_original_key_passthrough():
    """Proxy key file requests directly."""
    key_url = request.args.get('url', '').strip()
    if not key_url:
        logging.error("Missing 'url' (keygrab passthrough)")
        return "Error: Missing 'url' (keygrab passthrough)", 400
    try:
        logging.info(f"Proxying key file from: {key_url}")
        response = requests.get(key_url, headers=DEFAULT_HEADERS, allow_redirects=True, timeout=10)
        response.raise_for_status()
        return Response(response.content, content_type="application/octet-stream")
    except requests.RequestException as e:
        logging.error(f"Error Key (passthrough): {e}")
        return f"Error Key (passthrough): {str(e)}", 500

if __name__ == '__main__':
    logging.info("Starting Flask M3U proxy server on 0.0.0.0:8888")
    app.run(host="0.0.0.0", port=8888, debug=False, threaded=True)
