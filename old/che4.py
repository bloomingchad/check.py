import os
import json
import asyncio
import mpv
import sys

# Concurrency limit
CONCURRENCY_LIMIT = 50

def ensure_uri_scheme(url):
    """Ensure the URL has a URI scheme (e.g., http://)."""
    if not url.startswith(('http://', 'https://')):
        return f"http://{url}"
    return url

async def check_stream(player, url):
    # Events to signal playback status
    playback_started = asyncio.Event()
    playback_failed = asyncio.Event()
    
    # Callback for observing properties
    def on_property_change(property_name, value):
        if property_name == "idle-active" and not value:
            playback_started.set()
        elif property_name == "paused-for-cache" and value:
            playback_failed.set()
    
    # Callback for handling errors
    def on_event(event):
        if event.event_id == mpv.MpvEventID.END_FILE:
            # Check the reason for the end of playback
            if event.reason == mpv.MpvEventEndFileReason.ERROR:
                playback_failed.set()
    
    # Observe properties and events
    player.observe_property("idle-active", on_property_change)
    player.observe_property("paused-for-cache", on_property_change)
    player.register_event_callback(on_event)
    
    # Start playing the URL
    player.play(url)
    
    # Wait for playback to start or fail
    try:
        await asyncio.wait_for(asyncio.wait(
            [playback_started.wait(), playback_failed.wait()],
            return_when=asyncio.FIRST_COMPLETED
        ), timeout=30)
        return playback_started.is_set()
    except asyncio.TimeoutError:
        return False
    finally:
        player.stop()  # Stop the player after checking

async def process_station(station_name, url):
    url = ensure_uri_scheme(url)
    # Create a new player for each station with null audio output
    player = mpv.MPV(ao="null", audio_display=False, vid=False, msg_level="all=error")
    
    try:
        is_playing = await check_stream(player, url)
        if is_playing:
            result = f"✅ {station_name}\n"
        else:
            result = f"❌ {station_name}\n"
        
        # Write the result to result.txt
        with open("result.txt", "a") as f:
            f.write(result)
    finally:
        player.terminate()  # Clean up the player

async def find_and_process_all_stations(directory):
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    all_tasks = []
    
    # First, collect all stations from all JSON files
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.json'):
                file_path = os.path.join(root, file)
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    stations = data.get('stations', {})
                    
                    for station_name, url in stations.items():
                        # Create a task for each station, wrapped with the semaphore
                        async def process_with_semaphore(name, url):
                            async with semaphore:
                                await process_station(name, url)
                        
                        task = asyncio.create_task(process_with_semaphore(station_name, url))
                        all_tasks.append(task)
    
    # Now wait for all station tasks to complete
    await asyncio.gather(*all_tasks)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <directory>")
        sys.exit(1)
    
    directory = sys.argv[1]
    
    # Clear the result.txt file before starting
    if os.path.exists("result.txt"):
        os.remove("result.txt")
    
    asyncio.run(find_and_process_all_stations(directory))
