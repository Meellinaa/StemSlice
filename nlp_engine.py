import os
import json
import re
import librosa
import numpy as np

class NLPEngine:
    def __init__(self, library_path):
        self.library_path = library_path
        self.library = {}
        if os.path.exists(library_path):
            try:
                with open(library_path, 'r') as f:
                    self.library = json.load(f)
            except Exception as e:
                print(f"Error loading library.json in NLPEngine: {e}")
                
    def get_available_tracks(self):
        return list(self.library.values())
        
    def parse_prompt(self, prompt_text):
        """
        Queries the Gemini API to parse the natural language prompt into a structured config.
        Falls back to a local parser if the API key is not available or if the request fails.
        """
        available_tracks = self.get_available_tracks()
        available_titles = [t["title"] for t in available_tracks]
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            try:
                print("Connecting to Gemini API for prompt parsing...")
                from google import genai
                from google.genai import types
                from pydantic import BaseModel, Field
                
                class DJConfig(BaseModel):
                    song_order: list[str] = Field(description="Ordered list of track titles matching available titles exactly")
                    body_bars: int = Field(default=8, description="Number of bars to play each track solo")
                    transition_bars: int = Field(default=4, description="Number of bars to crossfade tracks")
                    vocal_boost_db: float = Field(default=1.0, description="Volume adjustment in dB for vocals")
                    bpm_override: float | None = Field(default=None, description="Global BPM override for the mix")
                
                client = genai.Client(api_key=api_key)
                
                system_instruction = (
                    "You are a professional AI DJ mix planner.\n"
                    f"You have access to these exact tracks: {json.dumps(available_titles)}\n"
                    "Your task is to parse the user's prompt and plan the DJ mix by outputting the JSON config schema.\n"
                    "Map any fuzzy song names, artists, or keywords to the closest matching title in the list.\n"
                    "If the user asks for a fast, short, or quick mix, set body_bars to 4 and transition_bars to 2.\n"
                    "If the user asks for a long mix, set body_bars to 16 and transition_bars to 8.\n"
                    "If the user doesn't specify a sequence, arrange the available songs in a harmonically compatible order."
                )
                
                # Call gemini-2.5-flash (or fallback to gemini-1.5-flash if needed, but 2.5-flash is standard)
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt_text,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=DJConfig,
                    ),
                )
                
                config = json.loads(response.text)
                
                # Post-process: Validate all songs against available titles using matching rules
                validated_songs = []
                for song_ref in config.get("song_order", []):
                    matched = self.find_best_match(song_ref, available_titles)
                    if matched:
                        validated_songs.append(matched)
                        
                config["song_order"] = validated_songs
                return config
                
            except Exception as e:
                print(f"Gemini API parsing failed: {e}. Falling back to local NLP parser.")
                
        # Fallback to local rule-based matching
        return self._local_parse(prompt_text, available_titles)
        
    def find_best_match(self, keyword, titles):
        # Exact match
        if keyword in titles:
            return keyword
            
        keyword_clean = keyword.lower().strip()
        # Substring matches
        for t in titles:
            t_clean = t.lower()
            if keyword_clean in t_clean or t_clean in keyword_clean:
                return t
                
        # Word token matching
        words = re.findall(r'\w+', keyword_clean)
        for t in titles:
            t_clean = t.lower()
            if any(w in t_clean for w in words if len(w) > 3):
                return t
                
        return None
        
    def _local_parse(self, prompt_text, titles):
        """
        Regex-based fallback parser for local execution.
        """
        print("Using local parser (analyzing keywords)...")
        prompt_lower = prompt_text.lower()
        matched_songs = []
        
        # Look for keywords in the prompt matching track title words
        for title in titles:
            # Extract main keywords (avoiding file extensions or common words)
            title_parts = re.split(r'[-_\s\(\)]', title.lower())
            keywords = [p for p in title_parts if len(p) > 2 and p not in ["mp3", "wav", "feat", "remix"]]
            
            if any(kw in prompt_lower for kw in keywords):
                matched_songs.append(title)
                
        # Maintain order of mentions
        unique_matches = []
        for s in matched_songs:
            if s not in unique_matches:
                unique_matches.append(s)
                
        # If no songs matched, use all songs
        if not unique_matches:
            unique_matches = list(titles)
            
        # Analyze parameters
        body_bars = 8
        transition_bars = 4
        vocal_boost = 1.0
        
        if any(w in prompt_lower for w in ["quick", "fast", "short", "speedy"]):
            body_bars = 4
            transition_bars = 2
        elif any(w in prompt_lower for w in ["long", "slow", "extended"]):
            body_bars = 16
            transition_bars = 8
            
        if "vocal" in prompt_lower:
            if any(w in prompt_lower for w in ["boost", "loud", "heavy", "up"]):
                vocal_boost = 3.0
            elif any(w in prompt_lower for w in ["quiet", "lower", "down"]):
                vocal_boost = -3.0
                
        return {
            "song_order": unique_matches,
            "body_bars": body_bars,
            "transition_bars": transition_bars,
            "vocal_boost_db": vocal_boost,
            "bpm_override": None
        }

class AITransitionSelector:
    @staticmethod
    def select_transition(track_a, track_b):
        """
        Analyzes audio characteristics of track stems to choose the best transition style.
        Returns:
            transition_type (str): e.g. "vocal_overlay_beatmatch" or "bass_swap_beatmatch"
            reason (str): Human-readable explanation of why this transition was selected.
        """
        vocals_path_a = track_a["stems"].get("vocals")
        drums_path_b = track_b["stems"].get("drums")
        
        # Defaults if stems are missing
        default_type = "bass_swap_beatmatch"
        default_reason = "Standard rhythmic transition with mid-point bass frequency swapping."
        
        if not vocals_path_a or not os.path.exists(vocals_path_a):
            return default_type, default_reason
        if not drums_path_b or not os.path.exists(drums_path_b):
            return default_type, default_reason
            
        try:
            # 1. Check Vocal Presence in Song A Outro (last 12 seconds)
            dur_a = librosa.get_duration(path=vocals_path_a)
            offset_a = max(0, dur_a - 12)
            y_voc, sr_voc = librosa.load(vocals_path_a, sr=None, offset=offset_a, duration=12)
            
            # Compute Root-Mean-Square (RMS) energy to check for vocal loudness
            rms_voc = librosa.feature.rms(y=y_voc).mean()
            
            # 2. Check Drum Presence in Song B Intro (first 12 seconds)
            y_drum, sr_drum = librosa.load(drums_path_b, sr=None, offset=0, duration=12)
            rms_drum = librosa.feature.rms(y=y_drum).mean()
            
            # Print diagnostic logs
            print(f"  AI Analyzer -> {track_a['title']} outro vocal RMS: {rms_voc:.4f}")
            print(f"  AI Analyzer -> {track_b['title']} intro drum RMS: {rms_drum:.4f}")
            
            # If vocals are active (>0.02 RMS) and drums are strong (>0.05 RMS)
            if rms_voc > 0.02 and rms_drum > 0.04:
                return "vocal_overlay_beatmatch", f"Active vocals detected in {track_a['title']}'s outro. Layering them over the clean drum intro of {track_b['title']}."
                
            return "bass_swap_beatmatch", f"Balanced groove transition. Swapping sub-bass lines to prevent frequency clashing."
            
        except Exception as e:
            print(f"  AI Transition Selection error: {e}. Defaulting to bass_swap.")
            return default_type, default_reason
