import os
import json
import asyncio
import mpv
import sys
import aiohttp
from tenacity import retry, stop_after_attempt, wait_fixed
import psutil  # For monitoring system resources

# Initial concurrency limit
INITIAL_CONCURRENCY_LIMIT = 20
MIN_CONCURRENCY_LIMIT = 5  # Minimum allowed concurrency
MAX_CONCURRENCY_LIMIT = 50  # Maximum allowed concurrency

# Semaphore for dynamic concurrency
semaphore = asyncio.Semaphore(INITIAL_CONCURRENCY_LIMIT)

# Mozilla User-Agent string
MOZILLA_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
)

def ensure_uri_scheme(url):
    """Ensure the URL has a URI scheme (e.g., http://)."""
    if not url.startswith(('http://', 'https://')):
        return f"http://{url}"
    return url

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def check_http_connection_with_retry(url):
    return await check_http_connection(url)

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def check_http_connection(url):
    try:
        headers = {
            "User-Agent": MOZILLA_USER_AGENT  # Add Mozilla User-Agent here
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15, allow_redirects=True, headers=headers) as response:
                final_url = str(response.url)
                print(f"Final URL after redirects: {final_url}")

                if response.status not in range(200, 400):
                    if "ICY" in response.reason.upper():
                        return 200, "Success (ICY)", "audio/mpeg"
                    return response.status, "HTTP connection failed", None
                
                content_type = response.headers.get("Content-Type", "").lower()
                valid_content_types = [
                    "audio/", "application/x-mpegurl", "application/vnd.apple.mpegurl",
                    "audio/x-mpegurl", "application/dash+xml", "video/mp4", "video/quicktime",
                    "application/octet-stream", "text/plain", "application/ogg", "audio/ogg",
                    "audio/webm", "audio/flac", "audio/wav", "audio/x-flac", "audio/x-wav",
                    "audio/mp4", "audio/aac", "audio/mpeg", "audio/x-m4a", "audio/x-ms-wma",
                    "application/pls+xml"
                ]
                
                if any(content_type.startswith(valid_type) for valid_type in valid_content_types):
                    return response.status, "Success", content_type
                else:
                    return response.status, "Invalid Content-Type", content_type
    except aiohttp.ClientError as e:
        return 0, str(e), None
    except Exception as e:
        return 0, str(e), None

async def check_stream(player, url):
    playback_started = asyncio.Event()
    playback_failed = asyncio.Event()
    audio_detected = asyncio.Event()
    failure_reason = None

    def on_property_change(property_name, value):
        nonlocal failure_reason
        if property_name == "idle-active" and not value:
            playback_started.set()
        elif property_name == "paused-for-cache" and value:
            failure_reason = "Paused for cache"
            playback_failed.set()
        elif property_name == "eof-reached" and value:
            failure_reason = "End of file reached"
            playback_failed.set()
        elif property_name == "demuxer-cache-state":
            if value and value.get("underrun", False):
                failure_reason = "Demuxer cache underrun"
                playback_failed.set()
        elif property_name == "audio-params":
            if value and "samplerate" in value and "channels" in value:
                audio_detected.set()

    def on_event(event):
        nonlocal failure_reason
        if event.event_id == mpv.MpvEventID.END_FILE:
            if event.reason == mpv.MpvEventEndFileReason.ERROR:
                failure_reason = "MPV error during playback"
                playback_failed.set()

    player.observe_property("idle-active", on_property_change)
    player.observe_property("paused-for-cache", on_property_change)
    player.observe_property("eof-reached", on_property_change)
    player.observe_property("demuxer-cache-state", on_property_change)
    player.observe_property("audio-params", on_property_change)
    player.register_event_callback(on_event)

    player.play(url)

    try:
        await asyncio.wait_for(playback_started.wait(), timeout=15)
        await asyncio.wait_for(asyncio.wait(
            [audio_detected.wait(), playback_failed.wait()],
            return_when=asyncio.FIRST_COMPLETED
        ), timeout=15)
        
        if playback_failed.is_set():
            return False, failure_reason
        return True, None
    except asyncio.TimeoutError:
        return False, "Playback timed out"
    finally:
        player.stop()

async def process_station(station_name, url):
    url = ensure_uri_scheme(url)
    
    try:
        status_code, reason, content_type = await check_http_connection_with_retry(url)
    except Exception as e:
        status_code, reason, content_type = 0, str(e), None
    
    if status_code == 0 and ("SSL" in reason or "handshake" in reason or "ICY" in reason):
        print(f"⚠️ {station_name} bypassing HTTP check due to SSL/handshake/ICY issue: {reason}")
        result = f"⚠️ {station_name} (Bypassed HTTP check: {reason})\n"
        with open("result.txt", "a") as f:
            f.write(result)
    elif status_code not in range(200, 400) and status_code != 400:
        result = f"❌ {station_name} (HTTP connection failed: Status Code {status_code}, Reason: {reason})\n"
        with open("result.txt", "a") as f:
            f.write(result)
        return
    elif reason == "Invalid Content-Type":
        result = f"❌ {station_name} (Invalid Content-Type: {content_type})\n"
        with open("result.txt", "a") as f:
            f.write(result)
        return
    
    player = mpv.MPV(
        ao="null",
        audio_display=False,
        vid=False,
        msg_level="all=error"
    )
    
    try:
        is_playing, failure_reason = await check_stream(player, url)
        if is_playing:
            result = f"✅ {station_name}\n"
        else:
            if failure_reason == "Demuxer cache underrun":
                result = f"⚠️ {station_name} (Stream playback warning: {failure_reason})\n"
            else:
                result = f"❌ {station_name} (Stream playback failed: {failure_reason})\n"
        
        with open("result.txt", "a") as f:
            f.write(result)
    except Exception as e:
        print(f"Error processing {station_name}: {e}")
        result = f"❌ {station_name} (Error: {e})\n"
        with open("result.txt", "a") as f:
            f.write(result)
    finally:
        player.terminate()

async def adjust_concurrency_limit():
    global semaphore
    while True:
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_usage = psutil.virtual_memory().percent

        if cpu_usage > 80 or memory_usage > 80:
            new_limit = max(MIN_CONCURRENCY_LIMIT, semaphore._value - 5)
        else:
            new_limit = min(MAX_CONCURRENCY_LIMIT, semaphore._value + 5)

        if new_limit != semaphore._value:
            print(f"Adjusting concurrency limit from {semaphore._value} to {new_limit}")
            semaphore = asyncio.Semaphore(new_limit)

        await asyncio.sleep(10)

async def find_and_process_all_stations(directory):
    all_tasks = []
    
    asyncio.create_task(adjust_concurrency_limit())

    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.json'):
                file_path = os.path.join(root, file)
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    stations = data.get('stations', {})
                    
                    for station_name, url in stations.items():
                        async def process_with_semaphore(name, url):
                            async with semaphore:
                                await process_station(name, url)
                        
                        task = asyncio.create_task(process_with_semaphore(station_name, url))
                        all_tasks.append(task)
    
    await asyncio.gather(*all_tasks)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <directory>")
        sys.exit(1)
    
    directory = sys.argv[1]
    
    if os.path.exists("result.txt"):
        os.remove("result.txt")
    
    asyncio.run(find_and_process_all_stations(directory))
