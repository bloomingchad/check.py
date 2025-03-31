import os
import json
import asyncio
import mpv
import sys
import aiohttp

# Concurrency limit
CONCURRENCY_LIMIT = 50

def ensure_uri_scheme(url):
    """Ensure the URL has a URI scheme (e.g., http://)."""
    if not url.startswith(('http://', 'https://')):
        return f"http://{url}"
    return url

async def check_http_connection(url):
    """Check if the URL is reachable via HTTP."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as response:
                return response.status == 200
    except Exception as e:
        print(f"HTTP connection error for {url}: {e}")
        return False

async def check_stream(player, url):
    playback_started = asyncio.Event()
    playback_failed = asyncio.Event()

    def on_property_change(property_name, value):
        if property_name == "idle-active" and not value:
            playback_started.set()
        elif property_name == "paused-for-cache" and value:
            playback_failed.set()
        elif property_name == "eof-reached" and value:
            playback_failed.set()
        elif property_name == "demuxer-cache-state":
            if value and value.get("underrun", False):
                playback_failed.set()

    def on_event(event):
        if event.event_id == mpv.MpvEventID.END_FILE:
            if event.reason == mpv.MpvEventEndFileReason.ERROR:
                playback_failed.set()

    player.observe_property("idle-active", on_property_change)
    player.observe_property("paused-for-cache", on_property_change)
    player.observe_property("eof-reached", on_property_change)
    player.observe_property("demuxer-cache-state", on_property_change)
    player.register_event_callback(on_event)

    player.play(url)

    try:
        await asyncio.wait_for(asyncio.wait(
            [playback_started.wait(), playback_failed.wait()],
            return_when=asyncio.FIRST_COMPLETED
        ), timeout=10)  # Reduced timeout to 10 seconds for faster detection
        return playback_started.is_set() and not playback_failed.is_set()
    except asyncio.TimeoutError:
        return False
    finally:
        player.stop()

async def process_station(station_name, url):
    url = ensure_uri_scheme(url)
    
    # First, check if the URL is reachable
    if not await check_http_connection(url):
        result = f"❌ {station_name} (HTTP connection failed)\n"
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
        is_playing = await check_stream(player, url)
        if is_playing:
            result = f"✅ {station_name}\n"
        else:
            result = f"❌ {station_name}\n"
        
        with open("result.txt", "a") as f:
            f.write(result)
    except Exception as e:
        # Catch any exceptions (e.g., connection errors) and mark the station as dead
        print(f"Error processing {station_name}: {e}")
        result = f"❌ {station_name}\n"
        with open("result.txt", "a") as f:
            f.write(result)
    finally:
        player.terminate()

async def find_and_process_all_stations(directory):
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    all_tasks = []
    
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
