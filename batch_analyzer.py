import os
import json
import subprocess
import librosa
import numpy as np

# Camelot Key Mapping Dictionary (Sharps only, as returned by our estimator)
CAMELOT_MAP = {
    # Major keys
    'C Major': '8B', 'G Major': '9B', 'D Major': '10B', 'A Major': '11B', 'E Major': '12B', 'B Major': '1B',
    'F# Major': '2B', 'C# Major': '3B', 'G# Major': '4B', 'D# Major': '5B', 'A# Major': '6B', 'F Major': '7B',
    # Minor keys
    'A Minor': '8A', 'E Minor': '9A', 'B Minor': '10A', 'F# Minor': '11A', 'C# Minor': '12A', 'G# Minor': '1A',
    'D# Minor': '2A', 'A# Minor': '3A', 'F Minor': '4A', 'C Minor': '5A', 'G Minor': '6A', 'D Minor': '7A'
}

def estimate_bpm_and_key(file_path):
    """
    Estimates the tempo (BPM) and musical key (mode-aware) of an audio file using librosa.
    Returns:
        bpm (float): Estimated tempo
        key (str): e.g., "A Minor", "C Major"
        camelot (str): e.g., "8A", "8B"
    """
    print(f"Analyzing audio: {os.path.basename(file_path)}...")
    y, sr = librosa.load(file_path, sr=None)
    
    # 1. Estimate BPM
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    if isinstance(tempo, (np.ndarray, list)):
        bpm = float(tempo[0]) if len(tempo) > 0 else 120.0
    else:
        bpm = float(tempo)
        
    # 2. Estimate Key using Krumhansl-Schmuckler Key Profiles
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_sum = chroma.sum(axis=1) # Sum features over all frames
    
    # Key profiles
    major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    
    # Normalize profiles
    major_profile = major_profile / np.sum(major_profile)
    minor_profile = minor_profile / np.sum(minor_profile)
    
    major_corrs = []
    minor_corrs = []
    
    for i in range(12):
        shifted_major = np.roll(major_profile, i)
        shifted_minor = np.roll(minor_profile, i)
        
        corr_major = np.corrcoef(chroma_sum, shifted_major)[0, 1]
        corr_minor = np.corrcoef(chroma_sum, shifted_minor)[0, 1]
        
        major_corrs.append(corr_major)
        minor_corrs.append(corr_minor)
        
    best_major_idx = np.argmax(major_corrs)
    best_minor_idx = np.argmax(minor_corrs)
    
    notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    
    if major_corrs[best_major_idx] > minor_corrs[best_minor_idx]:
        estimated_key = f"{notes[best_major_idx]} Major"
    else:
        estimated_key = f"{notes[best_minor_idx]} Minor"
        
    camelot = CAMELOT_MAP.get(estimated_key, 'Unknown')
    
    return round(bpm, 1), estimated_key, camelot

def run_demucs_if_needed(file_path, output_root_dir):
    """
    Checks if Demucs stems already exist for the song. If not, runs Demucs.
    Returns:
        stems_dir (str): Absolute path to folder containing the stems.
        stems_paths (dict): Dict of stem names mapped to their absolute paths.
    """
    song_name = os.path.splitext(os.path.basename(file_path))[0]
    # Demucs outputs to {output_root_dir}/htdemucs/{song_name}/
    stems_dir = os.path.join(output_root_dir, "htdemucs", song_name)
    
    required_stems = {
        "vocals": os.path.join(stems_dir, "vocals.wav"),
        "drums": os.path.join(stems_dir, "drums.wav"),
        "bass": os.path.join(stems_dir, "bass.wav"),
        "other": os.path.join(stems_dir, "other.wav")
    }
    
    # Check if all stems already exist
    stems_exist = True
    for stem_name, stem_path in required_stems.items():
        if not os.path.exists(stem_path):
            stems_exist = False
            break
            
    if stems_exist:
        print(f"Stems already exist for: {song_name}. Skipping Demucs.")
        return stems_dir, required_stems
        
    print(f"Stems missing for: {song_name}. Running Demucs (this may take a few minutes)...")
    
    # Path to demucs executable on the system
    demucs_bin = "/Library/Frameworks/Python.framework/Versions/3.12/bin/demucs"
    
    # Fallback to general demucs command if not found at specific path
    if not os.path.exists(demucs_bin):
        demucs_bin = "demucs"
        
    cmd = [demucs_bin, "-o", output_root_dir, file_path]
    
    try:
        subprocess.run(cmd, check=True)
        print(f"Successfully separated stems for: {song_name}")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error running Demucs on {song_name}: {e}")
        # Return path placeholders, but print warning
        return stems_dir, required_stems
        
    return stems_dir, required_stems

def main():
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    songs_dir = os.path.join(workspace_dir, "Songs")
    output_separated_dir = os.path.join(workspace_dir, "separated")
    library_json_path = os.path.join(workspace_dir, "library.json")
    
    # Load existing library if it exists to merge/update
    library = {}
    if os.path.exists(library_json_path):
        try:
            with open(library_json_path, 'r') as f:
                library = json.load(f)
            print(f"Loaded existing library database with {len(library)} tracks.")
        except json.JSONDecodeError:
            print("Failed to load existing library.json. Initializing a new database.")
            
    # Scan the Songs directory
    if not os.path.exists(songs_dir):
        print(f"Error: Songs directory does not exist at {songs_dir}")
        return
        
    mp3_files = []
    for root, dirs, files in os.walk(songs_dir):
        # Exclude hidden directories from search
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for filename in files:
            if filename.startswith('.'):
                continue
            if filename.endswith('_Remix.mp3') or filename.endswith('_Mix.mp3'):
                continue
            if filename.endswith('.mp3'):
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, songs_dir)
                mp3_files.append((rel_path, full_path))
            
    print(f"Found {len(mp3_files)} MP3 songs to analyze.")
    
    # Process each song
    for idx, (rel_path, file_path) in enumerate(mp3_files, start=1):
        rel_key = f"Songs/{rel_path}"
        display_name = os.path.basename(file_path)
        
        print(f"\n--- [{idx}/{len(mp3_files)}] {display_name} ---")
        
        # 1. Estimate BPM and Key
        try:
            bpm, estimated_key, camelot = estimate_bpm_and_key(file_path)
            print(f"-> BPM: {bpm} | Key: {estimated_key} (Camelot: {camelot})")
        except Exception as e:
            print(f"Error analyzing metadata for {display_name}: {e}")
            continue
            
        # 2. Run Demucs stem separation
        try:
            stems_dir, stems_paths = run_demucs_if_needed(file_path, output_separated_dir)
        except Exception as e:
            print(f"Error separating stems for {display_name}: {e}")
            stems_dir = ""
            stems_paths = {}
            
        # 3. Store/Update metadata in the library dictionary
        song_name = os.path.splitext(display_name)[0]
        library[rel_key] = {
            "title": song_name,
            "file_path": file_path,
            "bpm": bpm,
            "key": estimated_key,
            "camelot_key": camelot,
            "stems_dir": stems_dir,
            "stems": stems_paths
        }
        
        # Write library incrementally to avoid losing progress
        with open(library_json_path, 'w') as f:
            json.dump(library, f, indent=2)
            
    print(f"\nFinished! Library saved to: {library_json_path}")
    print(f"Total database size: {len(library)} tracks.")

if __name__ == "__main__":
    main()
