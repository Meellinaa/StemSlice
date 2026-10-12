# StemSlice 🎧🤖

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Demucs](https://img.shields.io/badge/AI-Demucs%20v4-FF6F00?style=flat-square&logo=meta&logoColor=white)](https://github.com/facebookresearch/demucs)
[![Librosa](https://img.shields.io/badge/Audio-Librosa-2B5B84?style=flat-square)](https://librosa.org)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Gemini](https://img.shields.io/badge/LLM-Google%20Gemini-4285F4?style=flat-square&logo=google&logoColor=white)](https://ai.google.dev)

> **StemSlice** is an automated AI audio pipeline that splits full tracks into isolated stems (vocals, drums, bass, and melody) and seamlessly blends them into continuous, professional DJ transitions. Instead of treating songs as solid blocks of audio, it uses **Demucs** and **Librosa** to detect transients on clean drum stems, crossfade stems independently, and swap basslines at transition midpoints. To solve real-world CPU and RAM bottlenecks, the engine dynamically loads and time-stretches only the exact audio time-slices needed per transition (calculated from BPM and bar counts), backed by an intelligent disk-caching layer for instantaneous re-mixes.

---

## 💡 Why Stem-Level Mixing?

Traditional DJ software crossfades two full stereo files together, which causes muddy low-end clashes and clashing vocals. StemSlice solves this by breaking tracks down to their fundamental stems:

* **Pristine Beat Tracking via Drum Isolation**: Full audio mixes have vocal swells, chords, and synth pads that confuse tempo detection. Running `librosa.beat.beat_track` strictly on the isolated **drum stem** yields sharp, transient-focused kick and snare pulses for sample-accurate beat grids.
* **Midpoint Bass Swapping**: Two sub-bass lines playing at once instantly destroy mix clarity. The engine ducks and drops Outgoing Bass at the exact transition midpoint while Incoming Bass takes over.
* **Stem Layering**: Outgoing vocal hooks can effortlessly ride over incoming drum intros before the full melody arrives (`vocal_overlay_beatmatch`).

---

## ⚡ Key Engineering Highlights & Bottleneck Fixes

### 1. Dynamic Time-Slicing (CPU & Memory Optimization)
Loading 4 uncompressed 32-bit float WAV stems for multiple full-length tracks quickly saturates system RAM and creates significant latency when phase-vocoding time-stretches.
* **The Fix**: The engine computes the exact time-slice required for each transition:
  beats_needed = (body_bars + transition_bars) * 4
* **Targeted Disk Read**: Audio stems are sliced during file load (`librosa.load(stem_path, sr=None, duration=duration_sec_needed)`), reducing RAM footprint by **over 75%** and ensuring CPU phase-vocoder routines only process what will actually be heard.

### 2. Multi-Tiered Disk Caching Layer
* **Separation Cache**: Demucs runs only once per track, storing stems under `separated/htdemucs/{track_name}/`.
* **Stretched Slice Cache**: Time-stretched slices are hashed and persisted by stem name, slice duration, and stretch factor (`{stem}_dur_{duration}_rate_{rate}.wav`). Subsequent compilations or re-arrangements run instantaneously.

### 3. Prompt-Driven DJ Planning (Gemini + Local Fallback)
* Takes natural language instructions (e.g., *"Make a high-energy mix starting with track A and boost the vocals"*) and parses them into structured JSON mix specifications using `gemini-2.5-flash` with strict Pydantic schemas.
* Automatically includes an offline regex fallback parser for environments without internet or API keys.

---

## 🚀 Pipeline Architecture

```text
               ┌───────────────────────────────┐
               │    Songs Directory (MP3s)     │
               └──────────────┬────────────────┘
                              │
                              ▼
               ┌───────────────────────────────┐
               │   1. batch_analyzer.py        │
               │   • Demucs Stem Separation    │
               │   • Librosa Key & BPM (CQT)   │
               │   • Camelot Harmonic Mapping  │
               └──────────────┬────────────────┘
                              │ Writes library.json
                              ▼
 ┌────────────────────────────┴────────────────────────────┐
 │                                                         │
 │  2. nlp_engine.py                                       │
 │  • LLM Prompt Parsing (Gemini / Local Regex)            │
 │  • AITransitionSelector (Stem RMS Energy Analysis)      │
 │                                                         │
 └────────────────────────────┬────────────────────────────┘
                              │ Generates playlist.json
                              ▼
               ┌───────────────────────────────┐
               │   3. mashup_engine.py         │
               │   • Exact Time-Slice Loading  │
               │   • Phase-Vocode Time-Stretch │
               │   • Midpoint Bassline Swapping│
               │   • ID3 Tagging & MP3 Export  │
               └──────────────┬────────────────┘
                              │
                              ▼
               ┌───────────────────────────────┐
               │ Continuous AI DJ Mix (MP3)    │
               └───────────────────────────────┘
```

---

## 📂 Project Structure

| File / Directory | Purpose |
| :--- | :--- |
| **`batch_analyzer.py`** | Scans `Songs/`, runs Demucs separation, calculates BPM & mode-aware Camelot keys, and populates `library.json`. |
| **`mashup_engine.py`** | The core rendering engine. Implements dynamic time-slice stem loading, beat alignment, midpoint bass swaps, and audio export. |
| **`nlp_engine.py`** | Natural language processing module; connects to Google Gemini to interpret user prompts and selects transition styles using stem RMS energy. |
| **`dj_server.py`** | FastAPI REST backend exposing endpoints for track libraries, custom mix configurations, prompt generation, and audio downloads. |
| **`dj_engine.py`** | High-level CLI wrapper integrating the analyzer and mixer into a one-command workflow. |
| **`analyze.py`** | Standalone utility script for analyzing single tracks on demand. |
| **`blend.py`** | Audio prototyping script for testing stem balance, volume offsets, and `pydub` layering operations. |
| **`playlist_builder.py`**| Utility to construct and validate structured `playlist.json` sequences. |
| **`Songs/`** | Input track library and generated mix exports (`AI_DJ_Mix.mp3`). |
| **`separated/`** | Cached Demucs stem outputs and cached time-sliced audio buffers. |

---

## 🔌 REST API Endpoints (`dj_server.py`)

Run the server locally:
```bash
python3 dj_server.py
```
*Server runs at `http://127.0.0.1:8000`.*

* **`GET /api/library`**: Returns scanned track database and metadata.
* **`GET /api/playlist`**: Retrieves currently active mix queue.
* **`POST /api/generate-mix`**: Parses a text prompt via Gemini, builds playlist, and launches background mix rendering.
* **`POST /api/custom-mix`**: Triggers rendering with explicit track orders, bar counts, and vocal gain settings.
* **`GET /api/mix-status`**: Streams real-time render progress (`0.0` to `1.0`).
* **`GET /api/download-mix`**: Streams the compiled `AI_DJ_Mix.mp3` with embedded ID3 metadata.

---

## 🛠️ Quickstart

### 1. Environment Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Analyze Tracks
Drop MP3 tracks into the `Songs/` folder and run the analyzer:
```bash
python3 batch_analyzer.py
```

### 3. Generate Mix
Start the API and trigger an automated mix via prompt:
```bash
python3 dj_server.py
```
```bash
curl -X POST http://127.0.0.1:8000/api/generate-mix \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Make an energetic quick mix with strong vocals"}'
```
