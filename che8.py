import os
import json
import asyncio
import mpv
import sys
import aiohttp

# Concurrency limit
CONCURRENCY_LIMIT = 20

def ensure_uri_scheme(url):
    """Ensure the URL has a URI scheme (e.g., http://)."""
    if not url.startswith(('http://', 'https://')):
        return f"http://{url}"
    return url

async def check_http_connection(url):
    """Check if the URL is reachable via HTTP and return the status code and reason."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                # Return the status code and a success message
                return response.status, "Success"
    except aiohttp.ClientError as e:
        # Return a status code of 0 and the exception message for client errors
        return 0, str(e)
    except Exception as e:
        # Return a status code of 0 and the exception message for other errors
        return 0, str(e)

async def check_stream(player, url):
    playback_started = asyncio.Event()
    playback_failed = asyncio.Event()
    audio_detected = asyncio.Event()

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
        elif property_name == "audio-params":
            # Check if audio parameters are valid
            if value and "samplerate" in value and "channels" in value:
                audio_detected.set()

    def on_event(event):
        if event.event_id == mpv.MpvEventID.END_FILE:
            if event.reason == mpv.MpvEventEndFileReason.ERROR:
                playback_failed.set()

    player.observe_property("idle-active", on_property_change)
    player.observe_property("paused-for-cache", on_property_change)
    player.observe_property("eof-reached", on_property_change)
    player.observe_property("demuxer-cache-state", on_property_change)
    player.observe_property("audio-params", on_property_change)  # Observe audio parameters
    player.register_event_callback(on_event)

    player.play(url)

    try:
        # Wait for playback to start
        await asyncio.wait_for(playback_started.wait(), timeout=10)
        
        # Wait for audio data to be detected or playback to fail
        await asyncio.wait_for(asyncio.wait(
            [audio_detected.wait(), playback_failed.wait()],
            return_when=asyncio.FIRST_COMPLETED
        ), timeout=10)
        
        # Ensure audio was detected and playback didn't fail
        return audio_detected.is_set() and not playback_failed.is_set()
    except asyncio.TimeoutError:
        return False
    finally:
        player.stop()

async def process_station(station_name, url):
    url = ensure_uri_scheme(url)
    
    # First, check if the URL is reachable
    status_code, reason = await check_http_connection(url)
    if status_code not in range(100, 400):
        result = f"❌ {station_name} (HTTP connection failed: Status Code {status_code}, Reason: {reason})\n"
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
            result = f"❌ {station_name} (Stream playback failed)\n"
        
        with open("result.txt", "a") as f:
            f.write(result)
    except Exception as e:
        # Catch any exceptions (e.g., connection errors) and mark the station as dead
        print(f"Error processing {station_name}: {e}")
        result = f"❌ {station_name} (Error: {e})\n"
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
