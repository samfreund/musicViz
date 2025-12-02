from typing import List
import os
import json
from tqdm import tqdm
import musicbrainzngs
import requests

GENRE_CACHE_FILE = "genre_cache.json"
JELLYFIN_CACHE_FILE = "jellyfin_library_cache.json"

def load_cache(filepath: str) -> dict:
    """Loads a JSON cache file if it exists."""
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return json.load(f)
    return {}

def save_cache(cache: dict, filepath: str):
    """Saves a cache dictionary to a JSON file."""
    with open(filepath, "w") as f:
        json.dump(cache, f, indent=2)

def get_jellyfin_library(server_url: str, api_key: str, user_id: str) -> List[dict]:
    """
    Fetches all music items from Jellyfin server.
    
    Args:
        server_url: The base URL of your Jellyfin server (e.g., http://localhost:8096)
        api_key: Your Jellyfin API key
        user_id: Your Jellyfin user ID
    
    Returns:
        list: List of music items from Jellyfin
    """
    headers = {
        "X-Emby-Token": api_key
    }
    
    # Get all audio items
    params = {
        "userId": user_id,
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "Fields": "Genres,DateCreated,MediaSources,Duration,Album,AlbumArtist,Artists,ProductionYear"
    }
    
    response = requests.get(
        f"{server_url}/Items",
        headers=headers,
        params=params
    )
    response.raise_for_status()
    
    return response.json().get("Items", [])

def get_genres(artist_name: str, song_title: str) -> List[str]:
    """
    Retrieves genres for a song using its title and artist name from MusicBrainz.

    Args:
        artist_name (str): The name of the artist.
        song_title (str): The title of the song.

    Returns:
        list: A list of genres for the song, or an empty list if not found.
    """

    musicbrainzngs.set_useragent(
        "Henry Martin's Jumbled Music Taste Analysis", "0.1", "henrymartin.co@outlook.com"
    )

    try:
        result = musicbrainzngs.search_recordings(
            artist=artist_name, recording=song_title, limit=1
        )

        if result['recording-list']:
            recording = result['recording-list'][0]
            
            if 'tag-list' in recording:
                return [tag['name'] for tag in recording['tag-list']]

            elif 'artist-credit' in recording and recording['artist-credit']:
                artist_id = recording['artist-credit'][0]['artist']['id']
                artist_info = musicbrainzngs.get_artist_by_id(artist_id, includes=['tags'])
                if 'artist' in artist_info and 'tag-list' in artist_info['artist']:
                    return [tag['name'] for tag in artist_info['artist']['tag-list']]

    except musicbrainzngs.WebServiceError as exc:
        print(f"Something went wrong with the request: {exc}")

    return []

# Get Jellyfin connection details from environment variables
JELLYFIN_URL = os.getenv("JELLYFIN_URL", "http://localhost:8096")
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
JELLYFIN_USER_ID = os.getenv("JELLYFIN_USER_ID")

if not JELLYFIN_API_KEY:
    print("Error: JELLYFIN_API_KEY environment variable not set")
    print("You can find your API key in Jellyfin Dashboard -> API Keys")
    exit(1)

if not JELLYFIN_USER_ID:
    print("Error: JELLYFIN_USER_ID environment variable not set")
    print("You can find your user ID in Jellyfin Dashboard -> Users")
    exit(1)

print(f"Connecting to Jellyfin server at {JELLYFIN_URL}...")

if not os.path.exists(JELLYFIN_CACHE_FILE):
    print("Fetching music library from Jellyfin...")
    try:
        library = get_jellyfin_library(JELLYFIN_URL, JELLYFIN_API_KEY, JELLYFIN_USER_ID)
        with open(JELLYFIN_CACHE_FILE, "w") as f:
            json.dump(library, f)
        print(f"Found {len(library)} tracks")
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Jellyfin: {e}")
        exit(1)
else:
    print(f"Loading library from {JELLYFIN_CACHE_FILE}...")
    with open(JELLYFIN_CACHE_FILE, "r") as f:
        library = json.load(f)
    print(f"Loaded {len(library)} tracks from cache")

print("Loading API caches...")
genre_cache = load_cache(GENRE_CACHE_FILE)

out = []

try:
    print("Processing tracks...")
    for song in tqdm(library):
        title = song.get('Name', 'Unknown Title')
        
        # Get artist - prefer AlbumArtist, fall back to Artists
        artists = []
        if song.get('AlbumArtist'):
            artists = [song['AlbumArtist']]
        elif song.get('Artists'):
            artists = song['Artists']
        
        primary_artist = artists[0] if artists else 'Unknown Artist'
        
        # Check if Jellyfin already has genre tags
        jellyfin_genres = song.get('Genres', [])
        
        # Only query MusicBrainz if we don't have genres from Jellyfin
        if not jellyfin_genres:
            genre_cache_key = f"{primary_artist}::{title}".lower()
            
            if genre_cache_key in genre_cache:
                genres = genre_cache[genre_cache_key]
            else:
                genres = get_genres(primary_artist, title)
                genre_cache[genre_cache_key] = genres
        else:
            genres = jellyfin_genres
        
        # Get duration in seconds (Jellyfin stores in ticks, 10,000,000 ticks = 1 second)
        duration_seconds = None
        if 'RunTimeTicks' in song:
            duration_seconds = song['RunTimeTicks'] / 10000000
        
        # Get album and year
        album_name = song.get('Album', 'Unknown Album')
        release_year = song.get('ProductionYear')
        
        out.append({
            'title': title,
            'artists': artists,
            'duration': duration_seconds,
            'genres': genres,
            'album': album_name,
            'year': release_year
        })
        
except KeyboardInterrupt:
    print("\nInterrupted, saving anyway")
finally:
    print("Writing out...")
    with open("out.json", "w") as f:
        json.dump(out, f, indent=2)
    
    print("Saving caches...")
    save_cache(genre_cache, GENRE_CACHE_FILE)
    print("Done.")