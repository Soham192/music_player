import pygame.mixer as mixer
from tkinter import *
from tkinter import filedialog, messagebox
import audio_metadata
from PIL import ImageTk, Image
from io import BytesIO
import os
import time
import sqlite3
import hashlib
#git checkout new-branch-name
# Define database paths and structure
DB_PATH = os.path.join(os.path.expanduser("~"), "music_player.db")
MUSIC_ROOT = os.path.join(os.path.expanduser("~"), "Music")  # Default music folder

def initialize_database():
    """Create the database if it doesn't exist and set up tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create songs table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS songs (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        artist TEXT,
        album TEXT,
        path TEXT NOT NULL UNIQUE,
        duration INTEGER,
        file_hash TEXT,
        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Create playlists table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS playlists (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Create playlist_songs junction table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS playlist_songs (
        playlist_id INTEGER,
        song_id INTEGER,
        position INTEGER,
        PRIMARY KEY (playlist_id, song_id),
        FOREIGN KEY (playlist_id) REFERENCES playlists (id),
        FOREIGN KEY (song_id) REFERENCES songs (id)
    )
    ''')
    
    # Create settings table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    ''')
    
    # Insert default music directory if not exists
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                  ("music_directory", MUSIC_ROOT))
    
    conn.commit()
    conn.close()

def get_file_hash(file_path):
    """Generate a hash for the file to identify it uniquely"""
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        # Read the file in chunks to handle large files
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()

def add_song_to_db(file_path):
    """Add a song to the database, extract metadata"""
    try:
        # Skip if not an audio file
        if not file_path.lower().endswith(('.mp3', '.wav', '.ogg')):
            return None
            
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if song already exists in database
        cursor.execute("SELECT id FROM songs WHERE path = ?", (file_path,))
        result = cursor.fetchone()
        if result:
            conn.close()
            return result[0]  # Return existing song id
            
        # Extract metadata
        metadata = audio_metadata.load(file_path)
        
        # Get basic info
        filename = os.path.basename(file_path)
        title = filename
        artist = "Unknown"
        album = "Unknown"
        
        # Try to extract from metadata
        try:
            # Different metadata formats might have different tag structures
            if hasattr(metadata, 'tags'):
                if 'title' in metadata.tags:
                    title = metadata.tags['title'][0]
                if 'artist' in metadata.tags:
                    artist = metadata.tags['artist'][0]
                if 'album' in metadata.tags:
                    album = metadata.tags['album'][0]
        except:
            # If metadata extraction fails, use defaults
            pass
            
        # Get duration
        duration = int(metadata.streaminfo['duration'])
        
        # Get file hash
        file_hash = get_file_hash(file_path)
        
        # Insert the song
        cursor.execute('''
        INSERT INTO songs (title, artist, album, path, duration, file_hash)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (title, artist, album, file_path, duration, file_hash))
        
        song_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return song_id
    except Exception as e:
        print(f"Error adding song {file_path}: {e}")
        return None

def scan_directory_for_music(directory):
    """Scan directory recursively and add all music files to the database"""
    added_count = 0
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(('.mp3', '.wav', '.ogg')):
                full_path = os.path.join(root, file)
                if add_song_to_db(full_path) is not None:
                    added_count += 1
    return added_count

def get_music_directory():
    """Get the music directory from settings"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'music_directory'")
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return result[0]
    return MUSIC_ROOT

def set_music_directory(directory):
    """Update the music directory in settings"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = ? WHERE key = 'music_directory'", (directory,))
    conn.commit()
    conn.close()

def get_all_songs():
    """Retrieve all songs from the database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, artist, album, path, duration FROM songs ORDER BY title")
    songs = cursor.fetchall()
    conn.close()
    return songs

def create_playlist(name):
    """Create a new playlist"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO playlists (name) VALUES (?)", (name,))
        playlist_id = cursor.lastrowid
        conn.commit()
        return playlist_id
    except sqlite3.IntegrityError:
        # Playlist name already exists
        return None
    finally:
        conn.close()

def get_all_playlists():
    """Get all playlists"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM playlists ORDER BY name")
    playlists = cursor.fetchall()
    conn.close()
    return playlists

def get_playlist_songs(playlist_id):
    """Get all songs in a playlist"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT s.id, s.title, s.artist, s.album, s.path, s.duration 
    FROM songs s
    JOIN playlist_songs ps ON s.id = ps.song_id
    WHERE ps.playlist_id = ?
    ORDER BY ps.position
    ''', (playlist_id,))
    songs = cursor.fetchall()
    conn.close()
    return songs

def add_song_to_playlist(playlist_id, song_id, position=None):
    """Add a song to a playlist"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get the next position if not specified
    if position is None:
        cursor.execute("SELECT MAX(position) FROM playlist_songs WHERE playlist_id = ?", (playlist_id,))
        result = cursor.fetchone()
        position = 1 if result[0] is None else result[0] + 1
        
    try:
        cursor.execute('''
        INSERT INTO playlist_songs (playlist_id, song_id, position)
        VALUES (?, ?, ?)
        ''', (playlist_id, song_id, position))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Song already in playlist
        return False
    finally:
        conn.close()

# Function to play the selected song
def play_song(song_name: StringVar, song_list: Listbox, status: StringVar):
    selection = song_list.curselection()
    if not selection:
        status.set("Please select a song!")
        return
        
    index = selection[0]
    selected_song = playlist_data[index]
    song_id, title, artist, album, path, duration = selected_song
    
    # Set the name of the current played song on the window
    display_name = f"{title} - {artist}" if artist != "Unknown" else title
    if len(display_name) > 40:
        display_name = display_name[:37] + "..."
    song_name.set(display_name)

    try:
        # Load the selected song and start the mixer/play the song
        mixer.music.load(path)
        mixer.music.play()
        
        # Format the duration
        global song_duration
        song_duration = time.strftime('%M:%S', time.gmtime(duration))
        
        # Call the play_time function when the song is played
        play_time()
        
        # Set the status of the player to Playing
        status.set("Song Playing..")
        
        # Active the disabled resume button
        if resume_btn['state'] == DISABLED:
            resume_btn['state'] = NORMAL
    except Exception as e:
        status.set(f"Error playing song: {str(e)}")

# Function to stop the current song
def stop_song(status: StringVar):
    mixer.music.stop()
    status.set("Song Stopped!!")
    
    # Disable the resume button when the song is stopped
    resume_btn['state'] = DISABLED

# Function to pause the current song 
def pause_song(status: StringVar):
    mixer.music.pause()
    status.set("Song Paused!")

# Function to resume the paused song
def resume_song(status: StringVar):
    mixer.music.unpause()
    if status.get() == "<Not Available>":
        status.set("Please Select a song!")
    else:
        status.set("Song Playing..")

# Function to load songs from the database
def load_songs(listbox, status: StringVar):
    global playlist_data
    
    # Check if database needs initialization
    if not os.path.exists(DB_PATH):
        initialize_database()
    
    # Check if we need to scan for songs
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM songs")
    song_count = cursor.fetchone()[0]
    conn.close()
    
    if song_count == 0:
        # First time setup - scan the default music directory
        music_dir = get_music_directory()
        if os.path.exists(music_dir):
            songs_added = scan_directory_for_music(music_dir)
            if songs_added == 0:
                # No songs found, ask user to select a directory
                ask_for_music_directory(status)
                return
        else:
            # Default directory doesn't exist, ask user
            ask_for_music_directory(status)
            return
    
    # Clear the current playlist
    listbox.delete(0, END)
    
    # Fetch all songs from database
    playlist_data = get_all_songs()
    
    # Display in listbox
    for song in playlist_data:
        song_id, title, artist, album, path, duration = song
        display_text = f"{title} - {artist}" if artist != "Unknown" else title
        listbox.insert(END, display_text)
    
    status.set(f"Loaded {len(playlist_data)} songs from database")

def ask_for_music_directory(status: StringVar):
    """Ask user to select a music directory"""
    music_dir = filedialog.askdirectory(title="Select your Music Directory")
    if music_dir:
        set_music_directory(music_dir)
        songs_added = scan_directory_for_music(music_dir)
        status.set(f"Added {songs_added} songs to database from {music_dir}")
        # Reload songs
        load_songs(playlist, status)
    else:
        status.set("No music directory selected")

def change_music_directory(status: StringVar):
    """Change the music directory and scan for new songs"""
    ask_for_music_directory(status)

def show_playlists():
    """Open a window to manage playlists"""
    playlist_window = Toplevel(root)
    playlist_window.title("Playlists")
    playlist_window.geometry("400x500")
    playlist_window.resizable(False, False)
    
    # Get all playlists
    all_playlists = get_all_playlists()
    
    # Create a frame for the playlist list
    playlist_frame = Frame(playlist_window)
    playlist_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)
    
    # Create a listbox for playlists
    playlist_listbox = Listbox(playlist_frame, font=('Helvetica', 11))
    playlist_listbox.pack(side=LEFT, fill=BOTH, expand=True)
    
    # Add a scrollbar
    playlist_scrollbar = Scrollbar(playlist_frame)
    playlist_scrollbar.pack(side=RIGHT, fill=Y)
    playlist_listbox.config(yscrollcommand=playlist_scrollbar.set)
    playlist_scrollbar.config(command=playlist_listbox.yview)
    
    # Populate the listbox
    for playlist_id, name in all_playlists:
        playlist_listbox.insert(END, name)
    
    # Button frame
    button_frame = Frame(playlist_window)
    button_frame.pack(fill=X, padx=10, pady=5)
    
    # Create new playlist button
    def create_new_playlist():
        from tkinter import simpledialog
        name = simpledialog.askstring("New Playlist", "Enter playlist name:")
        if name:
            playlist_id = create_playlist(name)
            if playlist_id:
                playlist_listbox.insert(END, name)
            else:
                messagebox.showerror("Error", "Playlist name already exists")
    
    new_btn = Button(button_frame, text="New Playlist", command=create_new_playlist)
    new_btn.pack(side=LEFT, padx=5)
    
    # Load playlist button
    def load_selected_playlist():
        selection = playlist_listbox.curselection()
        if selection:
            index = selection[0]
            playlist_id = all_playlists[index][0]
            global playlist_data
            playlist_data = get_playlist_songs(playlist_id)
            
            # Update main playlist
            playlist.delete(0, END)
            for song in playlist_data:
                song_id, title, artist, album, path, duration = song
                display_text = f"{title} - {artist}" if artist != "Unknown" else title
                playlist.insert(END, display_text)
            
            playlist_window.destroy()
            song_status.set(f"Loaded playlist: {all_playlists[index][1]}")
    
    load_btn = Button(button_frame, text="Load Playlist", command=load_selected_playlist)
    load_btn.pack(side=LEFT, padx=5)
    
    # Close button
    close_btn = Button(button_frame, text="Close", command=playlist_window.destroy)
    close_btn.pack(side=RIGHT, padx=5)

# Function to change the sound volume.
def volume(x):
    value = volume_slider.get()
    mixer.music.set_volume(value/100)

def play_time():
    # Fetch the song's current time position
    current_time = mixer.music.get_pos() / 1000
    
    # Handle negative time (can happen when song ends)
    if current_time < 0:
        current_time = 0

    # Convert the time into minute and second format
    converted_current_time = time.strftime('%M:%S', time.gmtime(current_time))
    
    # Show the time on the duration frame and reset the timer when the song is stopped
    if song_status.get() != 'Song Stopped!!':
        duration_frame.config(text=f"Time Elapsed: {converted_current_time} / {song_duration}")
    else:
       duration_frame.config(text=f"Time Elapsed: 00:00 / {song_duration}") 

    duration_frame.after(1000, play_time)

# Starting the mixer.
mixer.init()

# Initialize database on startup
if not os.path.exists(DB_PATH):
    initialize_database()

# Global variables
playlist_data = []
song_duration = "00:00"

# Initializing the parent window of the GUI
root = Tk()
root.geometry('1920x1200')
root.title('My Music Player')
root.resizable(False, False)

# Creating the frames of the music player
song_frame = LabelFrame(root, text="Current song", bg='LightBlue', width=1400, height=150)
song_frame.place(x=10, y=10)

button_frame = LabelFrame(root, text="Control Buttons", bg='Turquoise', width=1400, height=250)
button_frame.place(x=10, y=170)

listbox_frame = LabelFrame(root, text='Playlist', bg="RoyalBlue", height=900, width=500)
listbox_frame.place(x=1420, y=10)

volume_frame = LabelFrame(root, text="Volume", bg="Turquoise", width=150, height=300)
volume_frame.place(x=1250, y=300)

duration_frame = Label(root, bg='pink', text='Time Elapsed: 00:00 / 00:00', bd=2, relief=GROOVE, width=40, height=3, font=('Times', 14, 'bold'))
duration_frame.place(x=1420, y=1100)

# StringVar is used to manipulate text in entry, labels
current_song = StringVar(root, value='<Not selected>')
song_status = StringVar(root, value='<Not Available>')

# Playlist Listbox
playlist = Listbox(listbox_frame, font=('Helvetica', 14), selectbackground='Gold', height=40, width=60)

# Make the scroll bar to scroll the playlist
scroll_bar = Scrollbar(listbox_frame, orient=VERTICAL)
scroll_bar.pack(side=RIGHT, fill=BOTH)
scroll_bar.config(command=playlist.yview)

playlist.config(yscrollcommand=scroll_bar.set)
playlist.pack(fill=BOTH, padx=10, pady=10)

# SongFrame labels
Label(song_frame, text="CURRENTLY PLAYING: ", bg="LightBlue", font=('Times', 14, 'bold')).place(x=20, y=40)

song_lbl = Label(song_frame, textvariable=current_song, font=('Times', 16), bg='GoldenRod')
song_lbl.place(x=250, y=40)

# Buttons in the main screen
pause_btn = Button(button_frame, text="Pause", bg='Aqua', font=('Georgia', 14), width=10, command=lambda: pause_song(song_status))
pause_btn.place(x=50, y=50)

stop_btn = Button(button_frame, text="Stop", bg='Aqua', font=("Georgia", 14), width=10, command=lambda: stop_song(song_status))
stop_btn.place(x=250, y=50)

play_btn = Button(button_frame, text="Play", bg='Aqua', font=("Georgia", 14), width=10, command=lambda: play_song(current_song, playlist, song_status))
play_btn.place(x=450, y=50)

resume_btn = Button(button_frame, text='Resume', bg="Aqua", font=("Georgia", 14), width=10, command=lambda: resume_song(song_status))
resume_btn.place(x=650, y=50)

# Database buttons
db_btn = Button(button_frame, text="Load Library", bg='Aqua', font=("Georgia", 14), width=18, command=lambda: load_songs(playlist, song_status))
db_btn.place(x=50, y=150)

dir_btn = Button(button_frame, text="Add Music Folder", bg='Aqua', font=("Georgia", 14), width=18, command=lambda: change_music_directory(song_status))
dir_btn.place(x=350, y=150)

playlist_btn = Button(button_frame, text="Playlists", bg='Aqua', font=("Georgia", 14), width=12, command=show_playlists)
playlist_btn.place(x=650, y=150)

# Control the volume of the song
volume_slider = Scale(volume_frame, from_=100, to=0, orient=VERTICAL, command=volume, length=250, bg='orange', cursor='hand2')
volume_slider.set(30)
volume_slider.pack()

Label(root, textvariable=song_status, bg='SteelBlue', font=('Times', 12), justify=LEFT).pack(side=BOTTOM, fill=X)

# Load songs from the database on startup
load_songs(playlist, song_status)

# Finalize and start the main loop of the GUI
root.update()
root.mainloop()
