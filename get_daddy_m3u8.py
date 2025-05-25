import requests
from bs4 import BeautifulSoup # For parsing HTML
import re
from urllib.parse import urljoin, quote_plus, urlparse, urlunparse # urllib.parse for encoder
import os # For path handling
import time
import base64 # for encoder
import zlib # for encoder
import json
import html # For html.unescape
import yaml # For YAML handling

# --- ANSI Color Codes ---
PURPLE = '\033[95m'
GREEN = '\033[92m'
GREY = '\033[90m'
RED = '\033[91m'
RESET = '\033[0m'

# --- Configuration ---
YAML_CONFIG_FILE = "search_substrings.yaml"
OUTPUT_M3U_FILE = "daddylive_channels_proxied.m3u"
TVG_ID_OUTPUT_FILE = "daddylive-channels-tvg-ids.txt" # New: Output file for TVG IDs

REQUEST_TIMEOUT = 25
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
BASE_URL = "https://daddylive.dad"
FETCH_DELAY_SECONDS = 2

PROXY_HOST_IP = "127.0.0.1"
PROXY_PORT = 8888

AUTH_SERVER = "https://top2new.newkso.ru"
CDN1_BASE = "https://top1.newkso.ru/top1/cdn"
CDN_DEFAULT = "newkso.ru"

session = requests.Session()
session.headers.update({'User-Agent': USER_AGENT, 'Referer': BASE_URL + "/"})

# --- Functions ---

def smart_encode_url_for_proxy_compress_base64(target_url, proxy_host_ip=PROXY_HOST_IP, proxy_port=PROXY_PORT, h_referer_val=None, h_origin_val=None, h_user_agent_val=None):
    """
    Encodes a target URL and optional headers for the proxy.
    """
    current_proxy_prefix = f"http://{proxy_host_ip}:{proxy_port}/proxy/m3u?url="
    target_url_bytes = target_url.encode('utf-8')
    compressed_target_url_bytes = zlib.compress(target_url_bytes)
    encoded_target_url_value_bytes = base64.urlsafe_b64encode(compressed_target_url_bytes)
    encoded_target_url_value = encoded_target_url_value_bytes.decode('utf-8').rstrip('=')
    final_url = f"{current_proxy_prefix}{encoded_target_url_value}"
    h_params_to_process = {}
    if h_referer_val: h_params_to_process["h_referer"] = h_referer_val
    if h_origin_val: h_params_to_process["h_origin"] = h_origin_val
    if h_user_agent_val: h_params_to_process["h_User-Agent"] = h_user_agent_val
    for h_key, h_value in h_params_to_process.items():
        h_value_bytes = h_value.encode('utf-8')
        compressed_h_value_bytes = zlib.compress(h_value_bytes)
        encoded_h_value_bytes = base64.urlsafe_b64encode(compressed_h_value_bytes)
        encoded_h_value = encoded_h_value_bytes.decode('utf-8').rstrip('=')
        final_url += f"&{h_key}={encoded_h_value}"
    return final_url

def find_var(name, html_content):
    """Extracts JavaScript variable values."""
    try:
        match_re = re.search(fr"var\s+{name}\s*=\s*['\"]([^'\"]+)['\"]", html_content)
        if not match_re:
            match_re = re.search(fr"{name}\s*=\s*['\"]([^'\"]+)['\"]", html_content)
            if not match_re: raise ValueError(f"Couldn't find variable '{name}'")
        return match_re.group(1)
    except Exception as e:
        print(f"{GREY}      L_HOST_VAR_FAIL: Error finding var '{name}': {type(e).__name__}{RESET}")
        raise

def load_or_create_filter_config():
    """Loads filter configuration from YAML or creates a default one."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    yaml_path = os.path.join(script_dir, YAML_CONFIG_FILE)

    default_example_substrings = [
        "sky", "espn", "tnt", "fox", "bein", "dazn", "nbc", "cbs", "abc",
        "wwe", "nfl", "nba", "mlb", "premier league", "golf", "f1", "football"
    ]
    config_data_for_new_file = {
        'filtering_enabled': False,
        'search_substrings': default_example_substrings
    }

    runtime_filtering_enabled = False
    runtime_search_substrings_lower = []
    original_case_substrings_for_print = []

    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        if data and isinstance(data, dict):
            runtime_filtering_enabled = data.get('filtering_enabled', False)
            if not isinstance(runtime_filtering_enabled, bool):
                print(f"{RED}Warning: 'filtering_enabled' in {YAML_CONFIG_FILE} is not a valid boolean. Defaulting to False.{RESET}")
                runtime_filtering_enabled = False

            loaded_substrings = data.get('search_substrings', [])
            if isinstance(loaded_substrings, list) and all(isinstance(s, str) for s in loaded_substrings):
                runtime_search_substrings_lower = [s.lower() for s in loaded_substrings]
                original_case_substrings_for_print = loaded_substrings
            else:
                print(f"{RED}Warning: 'search_substrings' in {YAML_CONFIG_FILE} is not valid. Substring filtering will be based on an empty list if enabled.{RESET}")
                runtime_search_substrings_lower = []
                original_case_substrings_for_print = []
            print(f"{GREEN}Successfully loaded filter configuration from {YAML_CONFIG_FILE}.{RESET}")
        else:
            print(f"{RED}Warning: {YAML_CONFIG_FILE} is empty or not structured correctly. Proceeding with no filtering.{RESET}")
            runtime_filtering_enabled = False
    except FileNotFoundError:
        print(f"{PURPLE}Configuration file '{YAML_CONFIG_FILE}' not found.{RESET}")
        print(f"{PURPLE}Creating an example file with 'filtering_enabled: False'.{RESET}")
        print(f"{PURPLE}For THIS RUN, no filtering will be applied.{RESET}")
        try:
            with open(yaml_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_data_for_new_file, f, sort_keys=False, allow_unicode=True)
            print(f"{GREEN}Example configuration file created at: {yaml_path}{RESET}")
        except Exception as e:
            print(f"{RED}Error creating example configuration file: {e}{RESET}")
        runtime_filtering_enabled = False # Ensure it's false for this run
    except yaml.YAMLError as e:
        print(f"{RED}Error parsing YAML file '{YAML_CONFIG_FILE}': {e}. Proceeding with no filtering.{RESET}")
        runtime_filtering_enabled = False
    except Exception as e:
        print(f"{RED}An unexpected error occurred loading '{YAML_CONFIG_FILE}': {e}. Proceeding with no filtering.{RESET}")
        runtime_filtering_enabled = False
        
    return {
        'filtering_enabled': runtime_filtering_enabled,
        'search_substrings_lower': runtime_search_substrings_lower,
        'original_search_substrings_for_print': original_case_substrings_for_print
    }

def get_all_channels():
    """Fetches the list of 24/7 channels and their IDs using BeautifulSoup."""
    channels_url = f"{BASE_URL}/24-7-channels.php"
    print(f"Fetching channel list from: {channels_url}")
    try:
        resp = session.post(channels_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp_text = resp.text
        soup = BeautifulSoup(resp_text, 'html.parser')
        full_list_label = soup.find('label', {'for': 'tab-1'})
        grid_container = None
        if full_list_label:
            full_list_content = full_list_label.find_next_sibling('div', class_='tabby-content')
            if full_list_content: grid_container = full_list_content.find('div', class_='grid-container')
        if not grid_container:
            print(f"{RED}Warning: 'Full List' tab structure not found, trying first grid-container.{RESET}")
            grid_container = soup.find('div', class_='grid-container')
        if not grid_container:
            print(f"{RED}Error: Could not find 'grid-container'.{RESET}"); return []
        links = grid_container.find_all('a', href=re.compile(r'/stream/stream-\d+\.php'))
        channels_list = []
        for link in links:
            href, name_tag = link.get('href'), link.find('strong')
            if href and name_tag:
                match = re.search(r'/stream/stream-(\d+)\.php', href)
                if match:
                    channel_id, channel_name = match.group(1), html.unescape(name_tag.text.strip())
                    if "18+" not in channel_name: channels_list.append({'id': channel_id, 'name': channel_name})
        return channels_list
    except requests.exceptions.RequestException as e: print(f"{RED}Error fetching channel list: {e}{RESET}"); return []
    except Exception as e: print(f"{RED}Error parsing channel list: {e}{RESET}"); import traceback; traceback.print_exc(); return []

def get_m3u8_url_for_id(numeric_id, channel_name):
    """Navigates, auths, and builds M3U8 URL for a single channel ID."""
    daddylive_url = f"{BASE_URL}/stream/stream-{numeric_id}.php"
    try:
        print(f"{GREY}    L1: Attempting to fetch main stream page: {daddylive_url}{RESET}")
        response_stream_page = session.get(daddylive_url, timeout=REQUEST_TIMEOUT)
        response_stream_page.raise_for_status(); stream_html = response_stream_page.text
        print(f"{GREY}    L1: Successfully fetched main stream page.{RESET}")
        soup = BeautifulSoup(stream_html, 'html.parser')
        iframe = soup.find('iframe', src=re.compile(r'daddylivehd\.php|embed\.php'))
        raw_iframe_url = None
        if iframe and iframe.get('src'): raw_iframe_url = urljoin(daddylive_url, iframe['src'])
        else:
            match = re.search(r"(https?:\/\/[^\s'\"]+(?:daddylivehd|embed)\.php\?[^\s'\"]+)", stream_html)
            if match: raw_iframe_url = match.group(0)
        if not raw_iframe_url: print(f"{RED}    L2_FAIL: Could not locate embed/iframe URL for {channel_name}.{RESET}"); return None, None
        print(f"{GREY}    L2: Found iframe URL: {raw_iframe_url}{RESET}")
        mirrors = []
        print(f"{GREY}    L3: Attempting to find mirrors from iframe page...{RESET}")
        try:
            tmp_resp = session.get(raw_iframe_url, timeout=REQUEST_TIMEOUT); tmp_resp.raise_for_status(); tmp = tmp_resp.text
            m_dom = re.search(r'var\s+encodedDomains\s*=\s*"([^"]+)"', tmp)
            if m_dom: decoded = base64.b64decode(m_dom.group(1)).decode('utf-8'); mirrors = json.loads(decoded); print(f"{GREY}    L3: Found mirrors: {mirrors}{RESET}")
            else: print(f"{GREY}    L3: No 'encodedDomains' variable found on iframe page.{RESET}")
        except Exception as e: print(f"{GREY}    L3_WARN: Could not find or decode mirrors: {type(e).__name__} - {e}{RESET}")
        hosts_to_try = [None] + mirrors; final_host_root_for_headers = None
        for i, host_override in enumerate(hosts_to_try):
            parsed_raw_iframe_url = urlparse(raw_iframe_url); current_host_name = host_override if host_override else parsed_raw_iframe_url.netloc
            print(f"{GREY}    L_HOST: --- Attempting Host {i+1}/{len(hosts_to_try)}: {current_host_name} ---{RESET}")
            try:
                iframe_url = raw_iframe_url if host_override is None else urlunparse(parsed_raw_iframe_url._replace(netloc=host_override))
                host_root = f"{parsed_raw_iframe_url.scheme}://{current_host_name}"; final_host_root_for_headers = host_root
                print(f"{GREY}      L_HOST_1: Using Iframe URL: {iframe_url}{RESET}")
                iframe_headers = {'Referer': daddylive_url, 'User-Agent': USER_AGENT}
                response_embed_page = session.get(iframe_url, headers=iframe_headers, timeout=REQUEST_TIMEOUT); response_embed_page.raise_for_status(); embed_html = response_embed_page.text
                print(f"{GREY}      L_HOST_1: Fetched embed page successfully.{RESET}")
                print(f"{GREY}      L_HOST_2: Attempting to extract auth variables...{RESET}")
                channel_key = find_var('channelKey', embed_html); auth_ts = find_var('authTs', embed_html); auth_rnd = find_var('authRnd', embed_html); auth_sig = find_var('authSig', embed_html)
                print(f"{GREY}      L_HOST_2: Extracted auth variables (channelKey: {channel_key}).{RESET}")
                auth_url = f"{AUTH_SERVER}/auth.php?channel_id={channel_key}&ts={auth_ts}&rnd={auth_rnd}&sig={quote_plus(auth_sig)}"
                auth_headers = iframe_headers.copy(); auth_headers['Referer'] = iframe_url
                print(f"{GREY}      L_HOST_3: Calling Auth Server: {auth_url}{RESET}")
                r_auth = session.get(auth_url, headers=auth_headers, timeout=REQUEST_TIMEOUT); r_auth.raise_for_status()
                print(f"{GREY}      L_HOST_3: Auth server call successful.{RESET}")
                lookup_url = f"{host_root}/server_lookup.php?channel_id={channel_key}"
                print(f"{GREY}      L_HOST_4: Calling Server Lookup: {lookup_url}{RESET}")
                r_lookup = session.get(lookup_url, headers=auth_headers, timeout=REQUEST_TIMEOUT); r_lookup.raise_for_status(); server_key_data = r_lookup.json(); server_key = server_key_data.get('server_key')
                if not server_key: print(f"{GREY}      L_HOST_4_FAIL: 'server_key' not found. Response: {server_key_data}{RESET}"); raise ValueError("server_key missing.")
                print(f"{GREY}      L_HOST_4: Server lookup successful (server_key: {server_key}).{RESET}")
                if server_key == "top1/cdn": m3u8_url = f"{CDN1_BASE}/{channel_key}/mono.m3u8"
                else: m3u8_url = f"https://{server_key}.{CDN_DEFAULT}/{server_key}/{channel_key}/mono.m3u8"
                print(f"{GREY}      L_HOST_5: Built M3U8 URL: {m3u8_url}{RESET}")
                m3u8_headers_for_test = {'Referer': host_root + "/", 'Origin': host_root, 'User-Agent': USER_AGENT}
                print(f"{GREY}      L_HOST_6: Testing M3U8 URL (HEAD request)...{RESET}")
                test_resp = session.head(m3u8_url, headers=m3u8_headers_for_test, timeout=10); test_resp.raise_for_status()
                print(f"{GREY}      L_HOST_6: M3U8 URL test successful (Status: {test_resp.status_code}).{RESET}")
                print(f"{GREEN}    -> Success! Found M3U8 for {channel_name}.{RESET}"); return m3u8_url, final_host_root_for_headers
            except Exception as e: print(f"{GREY}      L_HOST_FAIL: Host {current_host_name} failed: {type(e).__name__} - {str(e)}{RESET}")
        print(f"{RED}    L_ALL_HOSTS_FAIL: All hosts failed for {channel_name}.{RESET}"); return None, None
    except Exception as e: print(f"{RED}    L_CRITICAL_FAIL: Critical error for {channel_name}: {type(e).__name__} - {str(e)}{RESET}"); return None, None

# --- Main Execution ---
if __name__ == "__main__":
    config = load_or_create_filter_config()
    filtering_active = config['filtering_enabled']
    substrings_to_search_lower = config['search_substrings_lower']
    original_substrings_for_print = config['original_search_substrings_for_print']

    initial_channels_list = get_all_channels()
    print(f"Initially found {len(initial_channels_list)} channels.")

    if not initial_channels_list:
        print(f"{RED}Could not fetch or parse any channels. Exiting.{RESET}"); exit()

    channels_to_process = []
    if filtering_active and substrings_to_search_lower:
        print(f"{PURPLE}Filtering enabled. Processing channels containing: {', '.join(original_substrings_for_print)}{RESET}")
        for channel in initial_channels_list:
            if any(substring in channel['name'].lower() for substring in substrings_to_search_lower):
                channels_to_process.append(channel)
        if not channels_to_process:
             print(f"{RED}No channels matched your filter criteria from '{YAML_CONFIG_FILE}'. Exiting.{RESET}"); exit()
    elif filtering_active and not substrings_to_search_lower:
        print(f"{PURPLE}Filtering is enabled in '{YAML_CONFIG_FILE}', but no 'search_substrings' are defined. Processing all channels.{RESET}")
        channels_to_process = initial_channels_list
    else:
        print(f"{PURPLE}Filtering is disabled or config not properly loaded. Processing all {len(initial_channels_list)} channels.{RESET}")
        channels_to_process = initial_channels_list

    print(f"Will attempt to process {len(channels_to_process)} channels.")
    print(f"\nStarting to build M3U playlist with PROXIED URLs...")
    m3u_lines = ["#EXTM3U"]
    successful_tvg_ids = [] # New: List to store TVG IDs of successful channels
    success_count = 0
    total_to_filter_process = len(channels_to_process)

    for idx, channel in enumerate(channels_to_process):
        print(f"{PURPLE}  -> [{idx+1}/{total_to_filter_process}] Processing {channel['name']} (ID: {channel['id']}){RESET}")
        raw_m3u8_url, m3u8_host_root = get_m3u8_url_for_id(channel['id'], channel['name'])

        if raw_m3u8_url:
            encoded_proxy_url = smart_encode_url_for_proxy_compress_base64(target_url=raw_m3u8_url)
            print(f"{GREEN}    ++ Encoded Proxy URL: {encoded_proxy_url}{RESET}")
            
            channel_name_for_m3u = channel['name'] # This is used as tvg-id
            m3u_lines.append(f"#EXTINF:-1 tvg-id=\"{channel_name_for_m3u}\" tvg-name=\"{channel_name_for_m3u}\",{channel_name_for_m3u}")
            m3u_lines.append(encoded_proxy_url)
            successful_tvg_ids.append(channel_name_for_m3u) # Add to our list
            success_count += 1
        else:
             print(f"{RED}    !! Failed to get M3U8 for {channel['name']} after all attempts.{RESET}")

        if idx < total_to_filter_process - 1:
            print(f"{GREY}    --- Delaying for {FETCH_DELAY_SECONDS}s before next channel ---{RESET}")
            time.sleep(FETCH_DELAY_SECONDS)

    print(f"\nProcessed {total_to_filter_process} channels based on filter (or all if not filtered).")
    
    # --- Write the M3U File ---
    if success_count > 0:
        try:
            with open(OUTPUT_M3U_FILE, 'w', encoding='utf-8') as f: f.write("\n".join(m3u_lines))
            print(f"\n{GREEN}✅ Combined M3U file with {success_count} proxied channels saved as: {OUTPUT_M3U_FILE}{RESET}")
        except IOError as e: print(f"\n{RED}❌ Failed to save M3U file: {e}{RESET}")
    else:
        if total_to_filter_process > 0: print(f"\n{RED}❌ All {total_to_filter_process} (filtered) channels failed to process. M3U file not saved or is empty.{RESET}")
        else: print(f"\n{RED}❌ No channels processed. M3U file not saved or is empty.{RESET}")

    # --- Write the TVG IDs File ---
    if successful_tvg_ids:
        try:
            # Ensure output path is relative to script, same as epg_downloader.py expects
            script_dir_for_tvg = os.path.dirname(os.path.abspath(__file__))
            tvg_ids_path = os.path.join(script_dir_for_tvg, TVG_ID_OUTPUT_FILE)

            with open(tvg_ids_path, 'w', encoding='utf-8') as f_tvg:
                for tvg_id in successful_tvg_ids:
                    f_tvg.write(f"{tvg_id}\n")
            print(f"{GREEN}✅ TVG IDs file with {len(successful_tvg_ids)} entries saved as: {tvg_ids_path}{RESET}")
        except IOError as e:
            print(f"\n{RED}❌ Failed to save TVG IDs file: {e}{RESET}")
    else:
        print(f"{PURPLE}No successful channels to write to TVG IDs file.{RESET}")
