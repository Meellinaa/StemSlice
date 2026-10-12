import os
import json
import librosa
import numpy as np
import soundfile as sf
from pydub import AudioSegment

# Configuration defaults
DEFAULT_BODY_BARS = 8
DEFAULT_TRANSITION_BARS = 4
DEFAULT_OUTRO_BARS = 12
FADE_DURATION_MS = 4000

# Stem volumes (in dB)
VOL_VOCALS = 1.0
VOL_DRUMS = 0.0
VOL_BASS = -1.0
VOL_OTHER = -2.0

def get_stretched_stem(track_title, stem_name, stem_path, rate, duration_sec_needed, workspace_dir):
    """
    Slices only the required duration of the stem from disk and time-stretches it.
    Uses caching to make subsequent mix compilations instantaneous.
    """
    cache_dir = os.path.join(workspace_dir, "separated", "stretched", track_title)
    os.makedirs(cache_dir, exist_ok=True)
    
    # Create a unique cached file name including duration and rate
    dur_str = f"{duration_sec_needed:.1f}".replace(".", "_")
    rate_str = f"{rate:.3f}".replace(".", "_")
    out_path = os.path.join(cache_dir, f"{stem_name}_dur_{dur_str}_rate_{rate_str}.wav")
    
    if os.path.exists(out_path):
        return AudioSegment.from_file(out_path)
        
    print(f"    [Engine] Slicing & stretching: {stem_name} (duration: {duration_sec_needed:.1f}s, rate: {rate:.3f})...")
    
    # Load ONLY the needed duration from disk to save RAM and CPU
    y, sr = librosa.load(stem_path, sr=None, duration=duration_sec_needed)
    
    # Time-stretch if the rate is not 1.0
    if abs(rate - 1.0) >= 0.005:
        y = librosa.effects.time_stretch(y, rate=rate)
        
    sf.write(out_path, y, sr)
    return AudioSegment.from_file(out_path)

def load_stems(track, rate, duration_sec_needed, workspace_dir, vocal_boost_db=1.0):
    stems = {}
    title = track["title"]
    
    for stem_name, path in track["stems"].items():
        if os.path.exists(path):
            try:
                stems[stem_name] = get_stretched_stem(title, stem_name, path, rate, duration_sec_needed, workspace_dir)
            except Exception as e:
                print(f"Error stretching stem {stem_name} for {title}: {e}")
                stems[stem_name] = AudioSegment.silent(duration=1000)
        else:
            stems[stem_name] = AudioSegment.silent(duration=1000)
            
    # Apply volumes
    stems["vocals"] = stems["vocals"] + vocal_boost_db
    stems["drums"] = stems["drums"] + VOL_DRUMS
    stems["bass"] = stems["bass"] + VOL_BASS
    stems["other"] = stems["other"] + VOL_OTHER
    return stems

def get_beat_times(drum_stem_path, original_bpm, rate):
    try:
        # Load only first 20 seconds to do beat tracking quickly
        y, sr = librosa.load(drum_stem_path, sr=None, duration=20.0)
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beats, sr=sr)
    except Exception:
        beat_times = []
        
    if len(beat_times) < 5:
        # Fallback to mathematical beat grid
        beat_interval = 60.0 / original_bpm
        beat_times = np.arange(0, 180, beat_interval) # generate 3 minutes worth of beats
        
    return beat_times / rate

def generate_mix_from_playlist(playlist_path, output_mix_path, workspace_dir, status_updater=None):
    def log(msg, progress=None):
        print(f"[Mixer] {msg}")
        if status_updater:
            status_updater(msg, progress)

    if not os.path.exists(playlist_path):
        raise FileNotFoundError(f"playlist.json not found at {playlist_path}")
        
    with open(playlist_path, 'r') as f:
        playlist = json.load(f)
        
    if not playlist:
        raise ValueError("playlist.json is empty")
        
    log(f"Compiling mix for {len(playlist)} tracks...", 0.05)
    
    main_mix = None
    current_stems = None
    current_beat_times = None
    current_bpm = None
    current_track_idx = 0
    current_time_offset_ms = 0
    
    total_tracks = len(playlist)
    
    while current_track_idx < total_tracks:
        track_a = playlist[current_track_idx]
        title_a = track_a["title"]
        progress_val = 0.1 + (current_track_idx / total_tracks) * 0.8
        
        log(f"Processing track [{current_track_idx + 1}/{total_tracks}]: {title_a}", progress_val)
        
        body_bars = track_a.get("body_bars", DEFAULT_BODY_BARS)
        transition_bars = track_a.get("transition_bars", DEFAULT_TRANSITION_BARS)
        vocal_boost = track_a.get("vocal_boost_db", VOL_VOCALS)
        
        next_track_idx = current_track_idx + 1
        has_next = next_track_idx < total_tracks
        
        # Calculate exactly how many seconds we need to load from Track A
        if has_next:
            beats_needed = (body_bars + transition_bars) * 4
        else:
            beats_needed = DEFAULT_OUTRO_BARS * 4
        duration_sec_needed = beats_needed * (60.0 / track_a["bpm"]) + 2.0  # +2s buffer
        
        if current_stems is None:
            # First track - load with calculated slice limit
            current_bpm = track_a["bpm"]
            current_stems = load_stems(track_a, 1.0, duration_sec_needed, workspace_dir, vocal_boost)
            current_beat_times = get_beat_times(track_a["stems"]["drums"], track_a["bpm"], 1.0)
            current_time_offset_ms = 0
            
        # Determine transition starting beat
        transition_start_beat = int(current_time_offset_ms / (60.0 / current_bpm * 1000)) + (body_bars * 4)
        
        if transition_start_beat >= len(current_beat_times):
            transition_start_beat = max(0, len(current_beat_times) - (transition_bars * 4) - 4)
            
        trans_start_ms = int(current_beat_times[transition_start_beat] * 1000)
        
        # Extract solo segment
        body_vocals = current_stems["vocals"][current_time_offset_ms : trans_start_ms]
        body_drums = current_stems["drums"][current_time_offset_ms : trans_start_ms]
        body_bass = current_stems["bass"][current_time_offset_ms : trans_start_ms]
        body_other = current_stems["other"][current_time_offset_ms : trans_start_ms]
        
        body_mix = body_vocals.overlay(body_drums).overlay(body_bass).overlay(body_other)
        
        if main_mix is None:
            main_mix = body_mix
        else:
            main_mix = main_mix + body_mix
            
        if not has_next:
            # Cap the final track's duration and fade it out
            log(f"  Capping final outro track: {title_a}")
            final_end_beat = transition_start_beat + (DEFAULT_OUTRO_BARS * 4)
            if final_end_beat >= len(current_beat_times):
                final_end_beat = len(current_beat_times) - 1
                
            trans_end_ms = int(current_beat_times[final_end_beat] * 1000)
            
            outro_vocals = current_stems["vocals"][trans_start_ms : trans_end_ms]
            outro_drums = current_stems["drums"][trans_start_ms : trans_end_ms]
            outro_bass = current_stems["bass"][trans_start_ms : trans_end_ms]
            outro_other = current_stems["other"][trans_start_ms : trans_end_ms]
            
            outro_mix = outro_vocals.overlay(outro_drums).overlay(outro_bass).overlay(outro_other)
            outro_mix = outro_mix.fade_out(duration=4000)
            main_mix = main_mix + outro_mix
            break
            
        track_b = playlist[next_track_idx]
        title_b = track_b["title"]
        trans_info = track_a.get("transition_to_next")
        
        # Calculate B duration needed in its own timeline
        body_bars_b = track_b.get("body_bars", DEFAULT_BODY_BARS)
        trans_bars_b = track_b.get("transition_bars", DEFAULT_TRANSITION_BARS)
        has_after_b = (next_track_idx + 1) < total_tracks
        
        if has_after_b:
            beats_needed_b = (body_bars_b + trans_bars_b) * 4
        else:
            beats_needed_b = DEFAULT_OUTRO_BARS * 4
        duration_sec_needed_b = beats_needed_b * (60.0 / track_b["bpm"]) + 2.0
        
        if trans_info and trans_info["type"] == "beatmatch":
            trans_style = trans_info.get("style", "bass_swap_beatmatch")
            log(f"  AI Mixed Beatmatch [{trans_style}] to: {title_b}")
            
            scale_factor = 1.0
            if trans_info.get("mode") == "half_time":
                scale_factor = 0.5
            elif trans_info.get("mode") == "double_time":
                scale_factor = 2.0
                
            target_bpm = current_bpm * scale_factor
            rate_b = target_bpm / track_b["bpm"]
            
            # Load sliced and stretched stems for Track B
            stems_b = load_stems(track_b, rate_b, duration_sec_needed_b, workspace_dir, track_b.get("vocal_boost_db", VOL_VOCALS))
            beat_times_b = get_beat_times(track_b["stems"]["drums"], track_b["bpm"], rate_b)
            
            start_b_ms = int(beat_times_b[0] * 1000)
            
            beat_duration_ms = (60.0 / current_bpm) * 1000
            trans_duration_ms = int((transition_bars * 4) * beat_duration_ms)
            
            trans_end_a_ms = trans_start_ms + trans_duration_ms
            end_b_ms = start_b_ms + trans_duration_ms
            
            # Slices
            vocals_a = current_stems["vocals"][trans_start_ms : trans_end_a_ms]
            drums_a = current_stems["drums"][trans_start_ms : trans_end_a_ms]
            bass_a = current_stems["bass"][trans_start_ms : trans_end_a_ms]
            other_a = current_stems["other"][trans_start_ms : trans_end_a_ms]
            
            vocals_b = stems_b["vocals"][start_b_ms : end_b_ms]
            drums_b = stems_b["drums"][start_b_ms : end_b_ms]
            bass_b = stems_b["bass"][start_b_ms : end_b_ms]
            other_b = stems_b["other"][start_b_ms : end_b_ms]
            
            if "vocal_overlay" in trans_style:
                mixed_vocals = vocals_a.overlay(vocals_b - 20)
                drums_fade_out = drums_a.fade(to_gain=-30.0, start=0, duration=trans_duration_ms)
                drums_fade_in = drums_b.fade(from_gain=-30.0, start=0, duration=trans_duration_ms)
                mixed_drums = drums_fade_out.overlay(drums_fade_in)
                
                midpoint = int(trans_duration_ms / 2)
                swap_len = int(beat_duration_ms * 4)
                bass_a_swap = bass_a.fade(to_gain=-30.0, start=midpoint - int(swap_len/2), duration=swap_len)
                bass_a_swap = bass_a_swap[0:midpoint] + AudioSegment.silent(duration=trans_duration_ms - midpoint)
                bass_b_swap = AudioSegment.silent(duration=midpoint) + bass_b[midpoint:]
                bass_b_swap = bass_b_swap.fade(from_gain=-30.0, start=midpoint - int(swap_len/2), duration=swap_len)
                mixed_bass = bass_a_swap.overlay(bass_b_swap)
                
                other_fade_out = other_a.fade(to_gain=-25.0, start=0, duration=trans_duration_ms)
                other_fade_in = other_b.fade(from_gain=-25.0, start=0, duration=trans_duration_ms)
                mixed_other = other_fade_out.overlay(other_fade_in)
            else:
                mixed_vocals = vocals_a.fade(to_gain=-30.0, start=0, duration=trans_duration_ms).overlay(vocals_b.fade(from_gain=-30.0, start=0, duration=trans_duration_ms))
                drums_fade_out = drums_a.fade(to_gain=-30.0, start=0, duration=trans_duration_ms)
                drums_fade_in = drums_b.fade(from_gain=-30.0, start=0, duration=trans_duration_ms)
                mixed_drums = drums_fade_out.overlay(drums_fade_in)
                
                midpoint = int(trans_duration_ms / 2)
                swap_len = int(beat_duration_ms * 4)
                bass_a_swap = bass_a.fade(to_gain=-30.0, start=midpoint - int(swap_len/2), duration=swap_len)
                bass_a_swap = bass_a_swap[0:midpoint] + AudioSegment.silent(duration=trans_duration_ms - midpoint)
                bass_b_swap = AudioSegment.silent(duration=midpoint) + bass_b[midpoint:]
                bass_b_swap = bass_b_swap.fade(from_gain=-30.0, start=midpoint - int(swap_len/2), duration=swap_len)
                mixed_bass = bass_a_swap.overlay(bass_b_swap)
                
                other_fade_out = other_a.fade(to_gain=-25.0, start=0, duration=trans_duration_ms)
                other_fade_in = other_b.fade(from_gain=-25.0, start=0, duration=trans_duration_ms)
                mixed_other = other_fade_out.overlay(other_fade_in)
                
            transition_mix = mixed_vocals.overlay(mixed_drums).overlay(mixed_bass).overlay(mixed_other)
            main_mix = main_mix + transition_mix
            
            current_stems = stems_b
            current_beat_times = beat_times_b
            current_bpm = target_bpm
            current_time_offset_ms = end_b_ms
            
        else:
            log(f"  Performing FADE transition to: {title_b}")
            
            out_vocals = current_stems["vocals"][trans_start_ms : trans_start_ms + FADE_DURATION_MS]
            out_drums = current_stems["drums"][trans_start_ms : trans_start_ms + FADE_DURATION_MS]
            out_bass = current_stems["bass"][trans_start_ms : trans_start_ms + FADE_DURATION_MS]
            out_other = current_stems["other"][trans_start_ms : trans_start_ms + FADE_DURATION_MS]
            segment_a = out_vocals.overlay(out_drums).overlay(out_bass).overlay(out_other)
            
            stems_b = load_stems(track_b, 1.0, duration_sec_needed_b, workspace_dir, track_b.get("vocal_boost_db", VOL_VOCALS))
            beat_times_b = get_beat_times(track_b["stems"]["drums"], track_b["bpm"], 1.0)
            
            in_vocals = stems_b["vocals"][0 : FADE_DURATION_MS]
            in_drums = stems_b["drums"][0 : FADE_DURATION_MS]
            in_bass = stems_b["bass"][0 : FADE_DURATION_MS]
            in_other = stems_b["other"][0 : FADE_DURATION_MS]
            segment_b = in_vocals.overlay(in_drums).overlay(in_bass).overlay(in_other)
            
            fade_mix = segment_a.append(segment_b, crossfade=FADE_DURATION_MS)
            main_mix = main_mix + fade_mix
            
            current_stems = stems_b
            current_beat_times = beat_times_b
            current_bpm = track_b["bpm"]
            current_time_offset_ms = FADE_DURATION_MS
            
        current_track_idx += 1
        
    log("Exporting final continuous DJ mix with ID3 tags...", 0.90)
    
    mix_sequence = " -> ".join([t["title"] for t in playlist])
    id3_tags = {
        "artist": "StemSlice",
        "album": "StemSlice Mixes",
        "comment": f"Continuous AI DJ Mix. Sequence: {mix_sequence}"
    }
    
    os.makedirs(os.path.dirname(output_mix_path), exist_ok=True)
    main_mix.export(output_mix_path, format="mp3", tags=id3_tags)
    log("Mix compilation complete!", 1.0)

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    playlist_path = os.path.join(script_dir, "playlist.json")
    output_mix_path = os.path.join(script_dir, "Songs", "AI_DJ_Mix.mp3")
    generate_mix_from_playlist(playlist_path, output_mix_path, script_dir)

if __name__ == "__main__":
    main()
