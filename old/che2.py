import os
import json
import asyncio
import mpv

# Concurrency limit
CONCURRENCY_LIMIT = 50

def ensure_uri_scheme(url):
    """Ensure the URL has a URI scheme (e.g., http://)."""
    if not url.startswith(('http://', 'https://')):
        return f"http://{url}"
    return url

async def check_stream(player, url):
    # Event to signal when playback has started
    playback_started = asyncio.Event()
    
    # Callback for observing properties
    def on_property_change(property_name, value):
        if property_name == "idle-active" and not value:
            playback_started.set()
    
    # Observe the core-idle property
    player.observe_property("idle-active", on_property_change)
    
    # Start playing the URL
    player.play(url)
    
    # Wait for playback to start
    try:
        await asyncio.wait_for(playback_started.wait(), timeout=15)
        return True
    except asyncio.TimeoutError:
        return False
    finally:
        player.stop()  # Stop the player after checking

async def process_station(station_name, url):
    url = ensure_uri_scheme(url)
    # Create a new player for each station with null audio output
    player = mpv.MPV(ytdl=True, ao="null", audio_display=False, vid=False)
    
    try:
        is_playing = await check_stream(player, url)
        if is_playing:
            print(f"✅ {station_name}")
        else:
            print(f"❌ {station_name}")
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
    import sys
    if len(sys.argv) != 2:
        print("Usage: python script.py <directory>")
        sys.exit(1)
    
    directory = sys.argv[1]
    asyncio.run(find_and_process_all_stations(directory))
