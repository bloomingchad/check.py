import os
import json
import asyncio
import mpv
import sys
import aiohttp
import signal
from tenacity import retry, stop_after_attempt, wait_fixed


""" THIS IS BUILT ON CHE_10 except 8 and 10


    The script is now robust and comprehensive, covering a wide range of valid content types, handling edge cases like SSL handshake errors, and ensuring proper validation for audio streams. However, there are still a few optional enhancements or considerations you might want to explore depending on your specific use case:
    
    ---
    
    ### 1. **Support for Redirects**
       - Some streaming URLs may redirect to another URL (e.g., HTTP 301/302 redirects). By default, `aiohttp` follows redirects, but you might want to explicitly log or handle them.
       - Example: Log the final URL after following redirects.
    
       ```python
       async with session.get(url, timeout=10, allow_redirects=True) as response:
           final_url = str(response.url)
       ```
    
    ---
    
    ### 2. **Timeout Customization**
       - The current timeout for HTTP requests and stream playback is hardcoded to 10 seconds. You might want to make this configurable via command-line arguments or a configuration file.
    
       ```python
       HTTP_TIMEOUT = 10  # Make this configurable
       STREAM_TIMEOUT = 10  # Make this configurable
       ```
    
    ---
    
    ### 3. **Detailed Logging**
       - Add more detailed logging for debugging purposes, such as logging the exact HTTP headers, response size, or other metadata.
    
       ```python
       print(f"Response Headers: {response.headers}")
       print(f"Response Size: {len(await response.read())} bytes")
       ```
    
    ---
    
    ### 4. **Retry Logic**
       - For transient network issues, you can implement retry logic using libraries like [`tenacity`](https://pypi.org/project/tenacity/) or a simple loop.
    
       ```python
       from tenacity import retry, stop_after_attempt, wait_fixed
    
       @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
       async def check_http_connection_with_retry(url):
           return await check_http_connection(url)
       ```
    
    ---
    
    ### 5. **Progress Reporting**
       - If processing a large number of stations, you might want to report progress periodically to keep track of how many stations have been processed.
    
       ```python
       total_stations = len(stations)
       processed = 0
       for station_name, url in stations.items():
           processed += 1
           print(f"Processing {processed}/{total_stations}: {station_name}")
       ```
    
    ---
    
    ### 6. **Parallelism Tuning**
       - The concurrency limit (`CONCURRENCY_LIMIT`) is currently set to 20. Depending on your system resources and network bandwidth, you might need to adjust this value.
    
       ```python
       CONCURRENCY_LIMIT = int(os.getenv("CONCURRENCY_LIMIT", 20))  # Make it configurable
       ```
    
    ---
    
    ### 7. **Error Classification**
       - Classify errors into different categories (e.g., "Network Error", "Invalid Content-Type", "Playback Error") for better analysis.
    
       ```python
       result = f"❌ {station_name} (Error Type: Invalid Content-Type, Details: {content_type})\n"
       ```
    
    ---
    
    ### 8. **Support for Local Files**
       - If some stations point to local files (e.g., `file:///path/to/audio.mp3`), you might want to handle them differently since they don't require an HTTP check.
    
       ```python
       if url.startswith("file://"):
           # Skip HTTP check for local files
           pass
       ```
    
    ---
    
    ### 9. **Graceful Shutdown**
       - Ensure the script handles interruptions (e.g., `Ctrl+C`) gracefully by cleaning up resources like the MPV player.
    
       ```python
       import signal
    
       async def shutdown(signal, loop):
           print(f"Received exit signal {signal.name}...")
           tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
           for task in tasks:
               task.cancel()
           await asyncio.gather(*tasks, return_exceptions=True)
           loop.stop()
    
       loop = asyncio.get_event_loop()
       signals = (signal.SIGTERM, signal.SIGINT)
       for s in signals:
           loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(s, loop)))
       ```
    
    ---
    
    ### 10. **Output Format**
       - Instead of writing results to a plain text file, consider using structured formats like JSON or CSV for easier post-processing.
    
       ```python
       import csv
    
       with open("result.csv", "a", newline="") as f:
           writer = csv.writer(f)
           writer.writerow([station_name, "✅" if is_playing else "❌", reason])
       ```
    
    ---
    
    ### Final Thoughts
    
    The script is already well-optimized for most use cases, but these additional enhancements can make it even more versatile and user-friendly. Here's a summary of what you might consider adding:
    
    - **Redirect Handling**: Log or handle redirects explicitly.
    - **Timeout Customization**: Make timeouts configurable.
    - **Retry Logic**: Handle transient network issues.
    - **Progress Reporting**: Report progress for large datasets.
    - **Error Classification**: Categorize errors for better analysis.
    - **Local File Support**: Handle local files differently.
    - **Graceful Shutdown**: Clean up resources on interruption.
    - **Structured Output**: Use JSON or CSV for results.
    
    If you're satisfied with the current functionality, the script is ready to go! Otherwise, feel free to implement any of these suggestions based on your requirements. 😊
"""




# Concurrency limit
CONCURRENCY_LIMIT = int(os.getenv("CONCURRENCY_LIMIT", 20))  # Configurable
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", 15))  # Configurable
STREAM_TIMEOUT = int(os.getenv("STREAM_TIMEOUT", 15))  # Configurable

def ensure_uri_scheme(url):
    """Ensure the URL has a URI scheme (e.g., http://)."""
    if not url.startswith(('http://', 'https://')):
        return f"http://{url}"
    return url

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def check_http_connection(url):
    """Check if the URL is reachable via HTTP and validate its Content-Type."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True) as response:
                final_url = str(response.url)  # Log final URL after redirects
                print(f"Final URL: {final_url}")
                
                # Log response headers and size for debugging
                print(f"Response Headers: {response.headers}")
                print(f"Response Size: {len(await response.read())} bytes")
                
                # Check status code
                if response.status not in range(200, 400):
                    return response.status, "HTTP connection failed", None
                
                # Check Content-Type header
                content_type = response.headers.get("Content-Type", "").lower()
                valid_content_types = [
                    "audio/",  # Any audio format (e.g., audio/mpeg, audio/aac)
                    "application/x-mpegurl",  # M3U8 playlists
                    "application/vnd.apple.mpegurl",  # M3U8 playlists
                    "audio/x-mpegurl",  # M3U playlists
                    "application/dash+xml",  # DASH manifests
                    "video/mp4",  # MP4 files with audio tracks
                    "video/quicktime",  # QuickTime files with audio tracks
                    "application/octet-stream",  # Generic binary data
                    "text/plain",  # Simple playlist files
                ]
                
                # Check if the content type matches any valid type
                if any(content_type.startswith(valid_type) for valid_type in valid_content_types):
                    return response.status, "Success", content_type
                else:
                    return response.status, "Invalid Content-Type", content_type
    except aiohttp.ClientError as e:
        # Return a status code of 0 and the exception message for client errors
        return 0, str(e), None
    except Exception as e:
        # Return a status code of 0 and the exception message for other errors
        return 0, str(e), None

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
        await asyncio.wait_for(playback_started.wait(), timeout=STREAM_TIMEOUT)
        
        # Wait for audio data to be detected or playback to fail
        await asyncio.wait_for(asyncio.wait(
            [audio_detected.wait(), playback_failed.wait()],
            return_when=asyncio.FIRST_COMPLETED
        ), timeout=STREAM_TIMEOUT)
        
        # Ensure audio was detected and playback didn't fail
        return audio_detected.is_set() and not playback_failed.is_set()
    except asyncio.TimeoutError:
        return False
    finally:
        player.stop()

async def process_station(station_name, url, total_stations, processed):
    url = ensure_uri_scheme(url)
    
    # First, check if the URL is reachable
    status_code, reason, content_type = await check_http_connection(url)
    
    # Allow specific HTTP errors to bypass the first check
    if status_code == 0 and ("SSL" in reason or "handshake" in reason):
        print(f"⚠️ {station_name} bypassing HTTP check due to SSL/handshake issue: {reason}")
        result = f"⚠️ {station_name} (Bypassed HTTP check: {reason})\n"
        with open("result.txt", "a") as f:
            f.write(result)
    elif status_code not in range(200, 400):
        result = f"❌ {station_name} (Network Error: Status Code {status_code}, Reason: {reason})\n"
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
        is_playing = await check_stream(player, url)
        if is_playing:
            result = f"✅ {station_name}\n"
        else:
            result = f"❌ {station_name} (Playback Error)\n"
        
        with open("result.txt", "a") as f:
            f.write(result)
    except Exception as e:
        # Catch any exceptions (e.g., connection errors) and mark the station as dead
        print(f"Error processing {station_name}: {e}")
        result = f"❌ {station_name} (Unknown Error: {e})\n"
        with open("result.txt", "a") as f:
            f.write(result)
    finally:
        player.terminate()
    
    # Report progress
    processed += 1
    print(f"Processed {processed}/{total_stations}: {station_name}")

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
                    
                    total_stations = len(stations)
                    processed = 0
                    
                    for station_name, url in stations.items():
                        async def process_with_semaphore(name, url, total, processed):
                            async with semaphore:
                                await process_station(name, url, total, processed)
                        
                        task = asyncio.create_task(process_with_semaphore(station_name, url, total_stations, processed))
                        all_tasks.append(task)
    
    await asyncio.gather(*all_tasks)

async def shutdown(signal, loop):
    """Gracefully shut down the application."""
    print(f"Received exit signal {signal.name}...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <directory>")
        sys.exit(1)
    
    directory = sys.argv[1]
    
    if os.path.exists("result.txt"):
        os.remove("result.txt")
    
    loop = asyncio.get_event_loop()
    signals = (signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(s, loop)))
    
    try:
        loop.run_until_complete(find_and_process_all_stations(directory))
    finally:
        loop.close()
