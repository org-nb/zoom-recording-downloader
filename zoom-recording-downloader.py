#!/usr/bin/env python3

# Program Name: zoom-recording-downloader.py
# Description:  Zoom Recording Downloader is a cross-platform Python script
#               that uses Zoom's API (v2) to download and organize all
#               cloud recordings from a Zoom account onto local storage.
#               This Python script uses the OAuth method of accessing the Zoom API.
# Forked from:  
# Website:      https://github.com/ricardorodrigues-ca/zoom-recording-downloader
# Author:       Ricardo Rodrigues
# Created:      2020-04-26

# System modules
import argparse
import base64
import json
import os
import re as regex
import signal
import sys as system
import time
import traceback
from datetime import datetime, date, timezone, timedelta

# Installed modules
import dateutil.parser as parser
import pathvalidate as path_validate
import requests
import tqdm as progress_bar
from zoneinfo import ZoneInfo
from google_drive_client import GoogleDriveClient

class Color:
    PURPLE = "\033[95m"
    CYAN = "\033[96m"
    DARK_CYAN = "\033[36m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"

DEFAULT_CONF_PATH = "zoom-recording-downloader.conf"
CONF_PATH = DEFAULT_CONF_PATH

def parse_args():
    parser = argparse.ArgumentParser(description="Zoom Recording Downloader")
    parser.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONF_PATH,
        help="Path to configuration file (default: zoom-recording-downloader.conf)"
    )
    return parser.parse_args()

args = parse_args()
CONF_PATH = args.config

# Load configuration file and check for proper JSON syntax
try:
    with open(CONF_PATH, encoding="utf-8-sig") as json_file:
        CONF = json.loads(json_file.read())
except json.JSONDecodeError as e:
    print(f"{Color.RED}### Error parsing JSON in {CONF_PATH}: {e}")
    system.exit(1)
except FileNotFoundError:
    print(f"{Color.RED}### Configuqration file {CONF_PATH} not found")
    system.exit(1)
except Exception as e:
    print(f"{Color.RED}### Unexpected error: {e}")
    system.exit(1)

def config(section, key, default=''):
    try:
        return CONF[section][key]
    except KeyError:
        if default == LookupError:
            print(f"{Color.RED}### No value provided for {section}:{key} in {CONF_PATH}")
            system.exit(1)
        else:
            return default

ACCOUNT_ID = config("OAuth", "account_id", LookupError)
CLIENT_ID = config("OAuth", "client_id", LookupError)
CLIENT_SECRET = config("OAuth", "client_secret", LookupError)

APP_VERSION = "3.3-NB (Google Drive Edition)"

API_ENDPOINT_USER_LIST = "https://api.zoom.us/v2/users"

RECORDING_START_YEAR = config("Recordings", "start_year", date.today().year)
RECORDING_START_MONTH = config("Recordings", "start_month", 1)
RECORDING_START_DAY = config("Recordings", "start_day", 1)
RECORDING_START_DATE = parser.parse(config("Recordings", "start_date", f"{RECORDING_START_YEAR}-{RECORDING_START_MONTH}-{RECORDING_START_DAY}")).replace(tzinfo=timezone.utc)
RECORDING_END_DATE = parser.parse(config("Recordings", "end_date", str(date.today()))).replace(tzinfo=timezone.utc)
DOWNLOAD_DIRECTORY = config("Storage", "download_dir", 'downloads')
AUTO_STORAGE_CHOICE = config("Storage", "storage_type", '')
COMPLETED_MEETING_IDS_LOG = config("Storage", "completed_log", 'completed-downloads.log')
COMPLETED_MEETING_IDS_LOGFILEPATH = os.sep.join([DOWNLOAD_DIRECTORY, COMPLETED_MEETING_IDS_LOG])
COMPLETED_MEETING_IDS = set()
SKIP_EXISTING_FILES = config("Storage", "skip_existing_files", False)

MEETING_TIMEZONE = ZoneInfo(config("Recordings", "timezone", 'UTC'))
MEETING_STRFTIME = config("Recordings", "strftime", '%Y.%m.%d - %I.%M %p UTC')
MEETING_FILENAME = config("Recordings", "filename", '{meeting_time} - {topic} - {rec_type} - {recording_id}.{file_extension}')
MEETING_FOLDER = config("Recordings", "folder", '{topic} - {meeting_time}')
SKIP_GALLERY_VIEW_VIDEOS = config("Recordings", "skip_gallery_view_videos", False)

# Google Drive configuration
GDRIVE_ENABLED = False
GDRIVE_CREDENTIALS_FILE = config("GoogleDrive", "credentials_file", "service-account.json")
GDRIVE_ROOT_FOLDER = config("GoogleDrive", "root_folder_name", "zoom-recording-downloader")
GDRIVE_RETRY_DELAY = int(config("GoogleDrive", "retry_delay", "5"))
GDRIVE_MAX_RETRIES = int(config("GoogleDrive", "max_retries", "3"))
GDRIVE_FAILED_LOG = config("GoogleDrive", "failed_log", "failed-uploads.log")

# Debugging
DEBUG_ENABLED = config("Debug", "enabled", False)
DEBUG_DUMP_DIR = config("Debug", "dump_dir", 'debugdumps')

def setup_google_drive():
    """Initialize Google Drive client with OAuth authentication"""
    try:
        drive_client = GoogleDriveClient(CONF.get('GoogleDrive', {}))
        if not drive_client.authenticate():
            choice = input("Would you like to continue with local storage instead? (y/n): ")
            if choice.lower() != 'y':
                system.exit(1)
            return None
            
        if not drive_client.initialize_root_folder():
            print(f"{Color.RED}### Failed to create root folder in Google Drive{Color.END}")
            choice = input("Would you like to continue with local storage instead? (y/n): ")
            if choice.lower() != 'y':
                system.exit(1)
            return None
            
        return drive_client
    except Exception as e:
        tb = traceback.extract_tb(system.exc_info()[2])
        print(
            f"{Color.RED}### Google Drive initialization failed:{Color.END}"
            f"  {e}\n"
            f"  {Color.RED}@ line number: {tb[-1].lineno}{Color.END}"
        )
        choice = input("Would you like to continue with local storage instead? (y/n): ")
        if choice.lower() != 'y':
            system.exit(1)
        return None




def load_access_token():
    """ OAuth function, thanks to https://github.com/freelimiter
    """
    url = f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={ACCOUNT_ID}"

    client_cred = f"{CLIENT_ID}:{CLIENT_SECRET}"
    client_cred_base64_string = base64.b64encode(client_cred.encode("utf-8")).decode("utf-8")

    headers = {
        "Authorization": f"Basic {client_cred_base64_string}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = json.loads(requests.request("POST", url, headers=headers).text)

    global ACCESS_TOKEN
    global AUTHORIZATION_HEADER

    try:
        ACCESS_TOKEN = response["access_token"]
        AUTHORIZATION_HEADER = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

    except KeyError:
        print(f"{Color.RED}### The key 'access_token' wasn't found.{Color.END}")


def maybe_refresh_token(token_refresh_start_time):
    # Check if an hour has elapsed and refresh token if needed
    elapsed_time = time.time() - token_refresh_start_time
    if elapsed_time >= 3600:  # 3600 seconds = 1 hour
        # refresh the access token so it does not expire for long running downloads
        load_access_token()
        token_refresh_start_time = time.time()  # Reset the timer
    return token_refresh_start_time


def get_users():
    """ loop through pages and return all users """
    response = requests.get(url=API_ENDPOINT_USER_LIST, headers=AUTHORIZATION_HEADER)

    if not response.ok:
        print(response)
        print(
            f"{Color.RED}### Could not retrieve users. Please make sure that your access "
            f"token is still valid{Color.END}"
        )

        system.exit(1)

    page_data = response.json()
    total_pages = int(page_data["page_count"]) + 1

    all_users = []

    for page in range(1, total_pages):
        url = f"{API_ENDPOINT_USER_LIST}?page_number={str(page)}"
        user_data = requests.get(url=url, headers=AUTHORIZATION_HEADER).json()
        users = ([
            (
                user["email"],
                user["id"],
                user.get("first_name", ""),  # Use .get() with a default value
                user.get("last_name", "")    # Use .get() with a default value
            )
            for user in user_data["users"]
        ])

        all_users.extend(users)

    return all_users


def format_filename(file_extension, recording, recording_id, recording_type, recording_start, alldetails, interpretation_counter):
    file_extension = file_extension.lower()

    invalid_chars_pattern = r'[<>:"/\\|?*\x00-\x1F]'
    topic = regex.sub(invalid_chars_pattern, '', recording["topic"])
    rec_type = recording_type.replace("_", " ").title().replace(" ", "").replace("(Cc)", "(CC)")
    is_interpretation = False
    if recording_type == "audio_interpretation":
        is_interpretation = True
        zoom_fn = alldetails["file_name"]
        # extract the language code from the filename
        # example "file_name": "Audio only - Interpretation (简体中文)"
        lang_match = regex.search(r'Interpretation \((.*?)\)', zoom_fn)
        if lang_match:
            lang_code = lang_match.group(1)
            # change known values to standard 2-letter language codes
            lang_map = {
                "简体中文": "zh-CN",
                "繁體中文": "zh-TW",
                "Español": "es",
                "Français": "fr",
                "Deutsch": "de",
                "日本語": "ja",
                "한국어": "ko",
                "Português": "pt",
                "Русский": "ru"
            }
            # case-insensitive lookup of language code in lang_map
            if lang_code in lang_map:
                lang_code = lang_map[lang_code]
            rec_type += f"-{lang_code}"
        else:
            # fallback if no language code is recognized
            rec_type += f"-{interpretation_counter + 1}"
    meeting_time_utc = parser.parse(recording["start_time"]).replace(tzinfo=timezone.utc)
    meeting_time_local = meeting_time_utc.astimezone(MEETING_TIMEZONE)
    year = meeting_time_local.strftime("%Y")
    month = meeting_time_local.strftime("%m")
    day = meeting_time_local.strftime("%d")
    meeting_time = meeting_time_local.strftime(MEETING_STRFTIME)

    filename = MEETING_FILENAME.format(**locals())
    folder = MEETING_FOLDER.format(**locals())
    metadata_filename = f"meta-{meeting_time}-{topic}.json"
    return (filename, folder, metadata_filename, is_interpretation)


def get_downloads(recording):
    if not recording.get("recording_files"):
        raise Exception

    downloads = []
    for download in recording["recording_files"]:
        file_type = download["file_type"]
        file_extension = download["file_extension"]
        recording_id = download["id"]

        if file_type == "":
            recording_type = "incomplete"
        elif file_type != "TIMELINE":
            recording_type = download["recording_type"]
        else:
            recording_type = download["file_type"]

        # recording_start typical value: "2024-06-23T02:00:29Z"
        recording_start = download["recording_start"].replace("-", "").replace(":", "")

        # must append access token to download_url
        download_url = f"{download['download_url']}?access_token={ACCESS_TOKEN}"
        downloads.append((file_type, file_extension, download_url, recording_type, recording_id, recording_start, download))

    return downloads


def get_recordings(email, page_size, rec_start_date, rec_end_date):
    return {
        "userId": email,
        "page_size": page_size,
        "from": rec_start_date,
        "to": rec_end_date
    }


def per_delta(start, end, delta):
    """ Generator used to create deltas for recording start and end dates
    """
    curr = start
    while curr < end:
        yield curr, min(curr + delta, end)
        curr += delta


def list_recordings(user_id, email = None):
    """ Start date now split into YEAR, MONTH, and DAY variables (Within 6 month range)
        then get recordings within that range
    """
    
    recordings = []

    for start, end in per_delta(RECORDING_START_DATE, RECORDING_END_DATE, timedelta(days=30)):
        post_data = get_recordings(user_id, 300, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        response = requests.get(
            url=f"https://api.zoom.us/v2/users/{user_id}/recordings",
            headers=AUTHORIZATION_HEADER,
            params=post_data
        )

        if DEBUG_ENABLED:
            debug_basefn = f"api_user_{email if email else user_id}_recordings_{start.strftime('%Y%m%d')}_to_{end.strftime('%Y%m%d')}"
            debug_filename = os.sep.join([DEBUG_DUMP_DIR, f"{debug_basefn}.json"])
            with open(debug_filename, 'w', encoding='utf-8') as debug_file:
                debug_file.write(response.text) 

        recordings_data = response.json()
        if "meetings" in recordings_data:
            # call the /meetings/{meetingId}/recordings endpoint for each meeting so that we also get language interpretation recordings
            # the /user/{userId}/recordings endpoint does not return interpretation recordings
            for meeting in recordings_data["meetings"]:
                meeting_uuid = meeting["uuid"]
                response2 = requests.get(
                    url=f"https://api.zoom.us/v2/meetings/{meeting_uuid}/recordings",
                    headers=AUTHORIZATION_HEADER,
                    params=post_data
                )
                if DEBUG_ENABLED:
                    sanitized_uuid = path_validate.sanitize_filename(meeting_uuid)
                    debug_filename2 = os.sep.join([DEBUG_DUMP_DIR, f"{debug_basefn}_ mtg_{sanitized_uuid}.json"])
                    with open(debug_filename2, 'w', encoding='utf-8') as debug_file2:
                        debug_file2.write(response2.text)
                meeting_data = response2.json()
                recordings.append(meeting_data)
        else:
            print(f"No 'meetings' key found in response for {user_id} from {start} to {end}")
    return recordings


def download_recording(download_url, email, filename, folder_name):
    dl_dir = os.sep.join([DOWNLOAD_DIRECTORY, folder_name])
    sanitized_download_dir = path_validate.sanitize_filepath(dl_dir)
    sanitized_filename = path_validate.sanitize_filename(filename)
    tmp_filename = f"{sanitized_filename}.~TMP"
    full_filename = os.sep.join([sanitized_download_dir, sanitized_filename])
    tmpdl_filename = os.sep.join([sanitized_download_dir, tmp_filename])

    try:
        os.makedirs(sanitized_download_dir, exist_ok=True)

        response = requests.get(download_url, stream=True)
        # total size in bytes.
        total_size = int(response.headers.get("content-length", 0))

        first_byte = 0
        if (os.path.exists(tmpdl_filename)):
            # file exists: resume download
            first_byte = os.path.getsize(tmpdl_filename)
            if first_byte < total_size:
                headers = {"Range": f"bytes={first_byte}-{total_size}"}
                response = requests.get(download_url, headers=headers, stream=True)
            else:
                os.rename(tmpdl_filename, full_filename)
                return True

        # create TQDM progress bar
        prog_bar = progress_bar.tqdm(dynamic_ncols=True, total=total_size, unit="iB", unit_scale=True)
        prog_bar.update(first_byte)

        block_size = 32 * 1024  # 32 Kibibytes
        with open(tmpdl_filename, "wb") as fd:
            for chunk in response.iter_content(block_size):
                prog_bar.update(len(chunk))
                fd.write(chunk)  # write video chunk to disk

        prog_bar.close()
        os.rename(tmpdl_filename, full_filename)    
        return True

    except Exception as e:
        tb = traceback.extract_tb(system.exc_info()[2])
        print(
            f"{Color.RED}### The video recording with filename '{filename}' for user with email "
            f"'{email}' could not be downloaded because:{Color.END}\n"
            f"  {e}\n"
            f"  {Color.RED}@ line number: {tb[-1].lineno}{Color.END}"
        )

        return False


def load_completed_meeting_ids():
    try:
        with open(COMPLETED_MEETING_IDS_LOGFILEPATH, 'r', encoding="utf-8") as fd:
            for line in fd:
                parts = line.strip().split()
                # Add only the UUID part
                COMPLETED_MEETING_IDS.add(parts[0])

    except FileNotFoundError:
        print(
            f"{Color.DARK_CYAN}Log file not found. Creating new log file: {Color.END}"
            f"{COMPLETED_MEETING_IDS_LOGFILEPATH}\n"
        )


def handle_graceful_shutdown(signal_received, frame):
    print(f"\n{Color.DARK_CYAN}SIGINT or CTRL-C detected. System exiting gracefully.{Color.END}")

    system.exit(0)

def init_debug():
    if not DEBUG_ENABLED:
        return

    os.makedirs(DEBUG_DUMP_DIR, exist_ok=True)

# ################################################################
# #                        MAIN                                  #
# ################################################################

def main():
    init_debug()

    # # clear the screen buffer
    # os.system('cls' if os.name == 'nt' else 'clear')

    # show the logo
    print(f"""
        {Color.DARK_CYAN}


                             ,*****************.
                          *************************
                        *****************************
                      *********************************
                     ******               ******* ******
                    *******                .**    ******
                    *******                       ******/
                    *******                       /******
                    ///////                 //    //////
                    ///////*              ./////.//////
                     ////////////////////////////////*
                       /////////////////////////////
                          /////////////////////////
                             ,/////////////////

                        Zoom Recording Downloader

                        V{APP_VERSION}

        {Color.END}
    """)

    global GDRIVE_ENABLED
    GDRIVE_ENABLED = False

    if AUTO_STORAGE_CHOICE:
        if AUTO_STORAGE_CHOICE.lower() == 'local':
            pass
        elif AUTO_STORAGE_CHOICE.lower() == 'googledrive':
            GDRIVE_ENABLED = True
        else:
            print(f"{Color.RED}### Configuration 'storage_type' must be 'local' or 'googledrive' (case-insensitive) or blank to prompt. Unknown value: {AUTO_STORAGE_CHOICE}{Color.END}")
            system.exit(1)
        print(f"\nUsing storage type: '{AUTO_STORAGE_CHOICE}\n")
    else:
        # Storage choice prompt
        print("\nChoose download method:")
        print("1. Local Storage")
        print("2. Google Drive")
        choice = input("Enter choice (1-2): ")
        GDRIVE_ENABLED = (choice == "2")

    drive_service = None
    if GDRIVE_ENABLED:
        drive_service = setup_google_drive()
        if not drive_service:
            GDRIVE_ENABLED = False

    load_access_token()
    load_completed_meeting_ids()

    print(f"{Color.BOLD}Getting user accounts...{Color.END}")
    users = get_users()

    for email, user_id, first_name, last_name in users:
        userInfo = (
            f"{first_name} {last_name} - {email}" if first_name and last_name else f"{email}"
        )
        print(f"\n{Color.BOLD}Getting recording list for {userInfo}{Color.END}")

        recordings = list_recordings(user_id, email)
        total_count = len(recordings)
        print(f"==> Found {total_count} recordings")
        #continue

        # Initialize elapsed time monitor
        token_refresh_start_time = time.time()

        for index, recording in enumerate(recordings):
            token_refresh_start_time = maybe_refresh_token(token_refresh_start_time)
            
            try:
                recording_uuid = recording["uuid"]

                if recording_uuid in COMPLETED_MEETING_IDS:
                    print(
                        f"\n==> Skipping already downloaded recording {index + 1} of {total_count} ('{recording['topic']}' @ {recording['start_time']})"
                    )
                    continue

                downloads = get_downloads(recording)

            except Exception as e:
                tb = traceback.extract_tb(system.exc_info()[2])
                print(
                    f"{Color.RED}### Failed to get download URLs for recording {index + 1} "
                    f"of {total_count} due to error:{Color.END}\n"
                    f"  {str(e)}"
                    f"  {Color.RED}@ line number: {tb[-1].lineno}{Color.END}"
                )
                continue

            print(f"\n==> Processing recording {index + 1} of {total_count}")

            file_counter = 0
            interpretation_counter = 0
            download_count = len(downloads)
            download_error_ct = 0
            for file_type, file_extension, download_url, recording_type, recording_id, recording_start, alldetails in downloads:
                file_counter += 1

                token_refresh_start_time = maybe_refresh_token(token_refresh_start_time)
                
                try:
                    filename, folder_name, metadata_filename, is_interpretation = format_filename(file_extension, recording, recording_id, 
                                                                                                  recording_type, recording_start, alldetails, interpretation_counter)
                    if is_interpretation:
                        interpretation_counter += 1
                    
                    # Skip gallery view video files if configured to do so
                    if SKIP_GALLERY_VIEW_VIDEOS and "gallery_view" in recording_type:
                        print(f"    > Skipping gallery view video file: {filename}")
                        continue

                    print(f"    > Downloading {file_counter} of {download_count}: {filename}")
                    sanitized_download_dir = path_validate.sanitize_filepath(
                        os.sep.join([DOWNLOAD_DIRECTORY, folder_name])
                    )
                    sanitized_filename = path_validate.sanitize_filename(filename)
                    full_filename = os.sep.join([sanitized_download_dir, sanitized_filename])

                    # write the recording variable as JSON metadata to a file in the download folder
                    if file_counter == 1:
                        os.makedirs(sanitized_download_dir, exist_ok=True)
                        metadata_filename = os.sep.join([
                            sanitized_download_dir, 
                            metadata_filename
                        ])
                        with open(metadata_filename, "w", encoding="utf-8") as metadata_file:
                            json.dump(recording, metadata_file, indent=4)

                    if SKIP_EXISTING_FILES and os.path.exists(full_filename):
                        print(f"        Skip: File already exists: {full_filename}")
                        continue
                    
                    if download_recording(download_url, email, filename, folder_name):
                        if GDRIVE_ENABLED and drive_service:
                            print(f"        > Uploading to Google Drive...")
                            success = drive_service.upload_file(full_filename, folder_name, sanitized_filename)
                            if success and os.path.exists(full_filename):
                                os.remove(full_filename)
                                if not os.listdir(sanitized_download_dir):
                                    os.rmdir(sanitized_download_dir)
                    else:
                        print(
                            f"{Color.RED}### Download failed for {file_counter} of {download_count}: {filename}"
                        )
                        download_error_ct += 1
                        continue

                except Exception as e:
                    tb = traceback.extract_tb(system.exc_info()[2])
                    print(
                        f"{Color.RED}### Failed to process file {file_type} "
                        f"for recording {index + 1} of {total_count} due to error:{Color.END}\n"
                        f"    {str(e)}\n"
                        f"  {Color.RED}@ line number: {tb[-1].lineno}{Color.END}"
                    )
                    download_error_ct += 1
                    continue

            if download_error_ct == 0:
                with open(COMPLETED_MEETING_IDS_LOGFILEPATH, "a", encoding="utf-8") as fd:
                    # Write the completed recording UUID to the log file with additional human-friendly info
                    fd.write(f"{recording_uuid} Start:{recording['start_time']} TZ:{recording['timezone']} Topic:'{recording['topic']}' # Files:{recording['recording_count']} Size: {recording['total_size']}\n")
                    COMPLETED_MEETING_IDS.add(recording_uuid)
            else:
                print(
                    f"{Color.RED}### INCOMPLETE: Recording {index + 1} of {total_count} had "
                    f"{download_error_ct} download errors.{Color.END}"
                )


if __name__ == "__main__":
    # tell Python to shutdown gracefully when SIGINT is received
    signal.signal(signal.SIGINT, handle_graceful_shutdown)

    main()