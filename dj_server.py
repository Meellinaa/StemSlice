import os
import json
import asyncio
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from nlp_engine import NLPEngine, AITransitionSelector
from playlist_builder import are_camelot_compatible, check_bpm_compatibility
from mashup_engine import generate_mix_from_playlist

app = FastAPI(title="StemSlice Backend API", description="FastAPI service for the NLP prompt-controlled StemSlice AI DJ Mixer.")

# Global status tracking for mix compilation tasks
mix_status = {
    "status": "idle",       # "idle", "running", "completed", "failed"
    "progress": 0.0,
    "message": "No active compilation."
}

script_dir = os.path.dirname(os.path.abspath(__file__))
library_path = os.path.join(script_dir, "library.json")
playlist_path = os.path.join(script_dir, "playlist.json")
output_mix_path = os.path.join(script_dir, "Songs", "AI_DJ_Mix.mp3")

# Pydantic schemas for request validation
class PromptRequest(BaseModel):
    prompt: str

class CustomMixRequest(BaseModel):
    song_order: list[str]
    body_bars: int = 8
    transition_bars: int = 4
    vocal_boost_db: float = 1.0

def update_status(message, progress):
    global mix_status
    mix_status["status"] = "running"
    mix_status["message"] = message
    if progress is not None:
        mix_status["progress"] = progress

def compile_mix_background():
    global mix_status
    try:
        mix_status["status"] = "running"
        mix_status["progress"] = 0.0
        mix_status["message"] = "Initializing mix compilation..."
        
        generate_mix_from_playlist(playlist_path, output_mix_path, script_dir, status_updater=update_status)
        
        mix_status["status"] = "completed"
        mix_status["progress"] = 1.0
        mix_status["message"] = "Mix compiled successfully!"
    except Exception as e:
        print(f"Background compilation failed: {e}")
        mix_status["status"] = "failed"
        mix_status["message"] = f"Compilation failed: {str(e)}"
        mix_status["progress"] = 0.0

def build_playlist_data(song_order, body_bars, transition_bars, vocal_boost_db):
    if not os.path.exists(library_path):
        raise HTTPException(status_code=400, detail="library.json not found. Run batch analyzer first.")
        
    with open(library_path, 'r') as f:
        library = json.load(f)
        
    playlist_output = []
    
    # Resolve and load track data
    for song_title in song_order:
        matched_track = None
        for key, track in library.items():
            if track["title"] == song_title or key.endswith(song_title) or os.path.basename(track["file_path"]) == song_title:
                matched_track = track
                break
        
        if not matched_track:
            continue
            
        playlist_output.append({
            "title": matched_track["title"],
            "file_path": matched_track["file_path"],
            "bpm": matched_track["bpm"],
            "key": matched_track["key"],
            "camelot_key": matched_track["camelot_key"],
            "stems_dir": matched_track["stems_dir"],
            "stems": matched_track["stems"],
            "body_bars": body_bars,
            "transition_bars": transition_bars,
            "vocal_boost_db": vocal_boost_db,
            "transition_to_next": None
        })
        
    if not playlist_output:
        raise HTTPException(status_code=400, detail="No matching tracks from the requested song list were found in the library database.")
        
    # Run AI Transition Selection on adjacent pairs
    for i in range(len(playlist_output) - 1):
        track_a = playlist_output[i]
        track_b = playlist_output[i+1]
        
        key_compat = are_camelot_compatible(track_a["camelot_key"], track_b["camelot_key"])
        bpm_compat, target_bpm, trans_mode = check_bpm_compatibility(track_a["bpm"], track_b["bpm"])
        
        if key_compat and bpm_compat:
            trans_style, ai_reason = AITransitionSelector.select_transition(track_a, track_b)
            track_a["transition_to_next"] = {
                "type": "beatmatch",
                "mode": trans_mode,
                "style": trans_style,
                "target_bpm": target_bpm,
                "reason": ai_reason
            }
        else:
            track_a["transition_to_next"] = {
                "type": "fade",
                "reason": f"Incompatible keys ({track_a['camelot_key']} vs {track_b['camelot_key']}) or BPMs ({track_a['bpm']} vs {track_b['bpm']}). Performing fade transition."
            }
            
    # Save the updated playlist.json
    with open(playlist_path, 'w') as f:
        json.dump(playlist_output, f, indent=2)

@app.get("/api/library")
def get_library():
    if not os.path.exists(library_path):
        return {}
    with open(library_path, 'r') as f:
        return json.load(f)

@app.get("/api/playlist")
def get_playlist():
    if not os.path.exists(playlist_path):
        return []
    with open(playlist_path, 'r') as f:
        return json.load(f)

@app.get("/api/mix-status")
def get_mix_status():
    return mix_status

@app.get("/api/download-mix")
def download_mix():
    if not os.path.exists(output_mix_path):
        raise HTTPException(status_code=404, detail="AI_DJ_Mix.mp3 has not been compiled yet.")
    return FileResponse(output_mix_path, media_type="audio/mpeg", filename="AI_DJ_Mix.mp3")

@app.post("/api/generate-mix")
def generate_mix(request: PromptRequest, background_tasks: BackgroundTasks):
    global mix_status
    if mix_status["status"] == "running":
        raise HTTPException(status_code=409, detail="An operation is already in progress.")
        
    nlp = NLPEngine(library_path)
    config = nlp.parse_prompt(request.prompt)
    
    song_order = config.get("song_order", [])
    body_bars = config.get("body_bars", 8)
    transition_bars = config.get("transition_bars", 4)
    vocal_boost_db = config.get("vocal_boost_db", 1.0)
    
    build_playlist_data(song_order, body_bars, transition_bars, vocal_boost_db)
    background_tasks.add_task(compile_mix_background)
    
    return {
        "status": "queued",
        "message": "AI prompt successfully parsed. Mix compilation started in background.",
        "config": {
            "prompt_text": request.prompt,
            "song_order": song_order,
            "body_bars": body_bars,
            "transition_bars": transition_bars,
            "vocal_boost_db": vocal_boost_db
        }
    }

@app.post("/api/custom-mix")
def custom_mix(request: CustomMixRequest, background_tasks: BackgroundTasks):
    global mix_status
    if mix_status["status"] == "running":
        raise HTTPException(status_code=409, detail="An operation is already in progress.")
        
    build_playlist_data(
        request.song_order, 
        request.body_bars, 
        request.transition_bars, 
        request.vocal_boost_db
    )
    background_tasks.add_task(compile_mix_background)
    
    return {
        "status": "queued",
        "message": "Custom playlist created. Mix compilation started in background."
    }

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    try:
        uvicorn.run(app, host=host, port=port)
    except OSError as exc:
        print(f"Failed to start server on {host}:{port}: {exc}")
        print("If the port is already in use, stop the other process or set PORT to a different value, e.g. PORT=8001 python3 dj_server.py")
        raise
