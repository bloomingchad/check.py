import os
import json
import asyncio
import mpv

# Concurrency limit (e.g., 5 streams checked at the same time)
CONCURRENCY_LIMIT = 10

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
        if property_name == "core-idle" and not value:
            #print(f"Playback started: {url}")
            playback_started.set()

    # Observe the core-idle property
    player.observe_property("core-idle", on_property_change)

    # Start playing the URL
    player.play(url)

    # Wait for playback to start
    try:
        await asyncio.wait_for(playback_started.wait(), timeout=15)  # Timeout after 10 seconds
        return True
    except asyncio.TimeoutError:
        #print(f"Timeout: Playback did not start for {url}")
        return False
    finally:
        player.stop()  # Stop the player after checking

async def process_station(semaphore, player, station_name, url):
    async with semaphore:  # Limit concurrency
        url = ensure_uri_scheme(url)  # Ensure the URL has a URI scheme
        is_playing = await check_stream(player, url)
        if is_playing:
            print(f"✅ {station_name}")
        else:
            print(f"❌ {station_name}")

async def process_json_file(semaphore, player, file_path):
    with open(file_path, 'r') as file:
        data = json.load(file)
        stations = data.get('stations', {})
        
        tasks = []
        for station_name, url in stations.items():
            task = asyncio.create_task(process_station(semaphore, player, station_name, url))
            tasks.append(task)
        
        await asyncio.gather(*tasks)  # Wait for all tasks to complete

async def find_and_process_json_files(directory):
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)  # Concurrency limit
    player = mpv.MPV(ytdl=True)  # Single MPV instance
    tasks = []
    
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.json'):
                file_path = os.path.join(root, file)
                task = asyncio.create_task(process_json_file(semaphore, player, file_path))
                tasks.append(task)
    
    await asyncio.gather(*tasks)  # Wait for all JSON files to be processed
    player.terminate()  # Clean up the MPV instance

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python script.py <directory>")
        sys.exit(1)
    
    directory = sys.argv[1]
    asyncio.run(find_and_process_json_files(directory))
