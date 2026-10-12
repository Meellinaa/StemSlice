// AI DJ Engine Frontend Application Logic (Mix Queue & Purged TikTok)

// API URL Endpoints
const API_LIBRARY = '/api/library';
const API_PLAYLIST = '/api/playlist';
const API_STATUS = '/api/mix-status';
const API_GENERATE = '/api/generate-mix';
const API_CUSTOM = '/api/custom-mix';

// Global Application State: Mix Queue list of track objects
let libraryData = {};
let mixQueue = []; // [{title, bpm, camelot_key, key}, ...]
let isCompiling = false;
let statusPollInterval = null;

// DOM Elements
const trackListContainer = document.getElementById('track-list');
const trackCountBadge = document.getElementById('track-count');
const searchInput = document.getElementById('search-input');

const activeTrackTitle = document.getElementById('active-track-title');
const activeTrackBpm = document.getElementById('active-track-bpm');
const activeTrackKey = document.getElementById('active-track-key');
const statusLog = document.getElementById('status-log');
const playhead = document.getElementById('mix-playhead');
const mixQueueContainer = document.getElementById('mix-queue');

const transitionPreset = document.getElementById('transition-preset');
const energyCurve = document.getElementById('energy-curve');
const promptInput = document.getElementById('prompt-input');
const generateBtn = document.getElementById('generate-mashup-btn');
const aiTapBtn = document.getElementById('ai-tap-btn');

const renderModeText = document.getElementById('render-mode');
const progressBarFill = document.getElementById('progress-bar');
const downloadMixBtn = document.getElementById('download-mix-btn');
const outputFilenameText = document.getElementById('output-filename');
const recommendationsList = document.getElementById('recommendations-list');

// Initialize application on load
window.addEventListener('DOMContentLoaded', () => {
    fetchLibrary();
    setupEventListeners();
    initializeWaveforms();
});

// Event Listeners
function setupEventListeners() {
    // Real-time Search Box Filter
    searchInput.addEventListener('input', () => {
        const query = searchInput.value.toLowerCase().trim();
        const items = document.querySelectorAll('.track-item');
        
        items.forEach(item => {
            const title = item.dataset.title.toLowerCase();
            if (title.includes(query)) {
                item.style.display = 'flex';
            } else {
                item.style.display = 'none';
            }
        });
    });

    // Generate Mix / Mashup Click Handler
    generateBtn.addEventListener('click', triggerMixGeneration);
    
    // Prompt Input Enter Key Handler
    promptInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            triggerMixGeneration();
        }
    });

    // AI Tap Button click to generate recommendations
    aiTapBtn.addEventListener('click', triggerAITap);

    // Set up drag events for the Mix Queue container itself
    mixQueueContainer.addEventListener('dragover', (e) => {
        e.preventDefault();
    });
}

// Fetch library tracks from API
async function fetchLibrary() {
    try {
        const response = await fetch(API_LIBRARY);
        libraryData = await response.json();
        renderLibrary();
        generateInitialRecommendations();
    } catch (e) {
        logMessage(`Error loading library database: ${e.message}`, 'error');
    }
}

// Render library list inside the sidebar
function renderLibrary() {
    trackListContainer.innerHTML = '';
    const tracks = Object.values(libraryData);
    trackCountBadge.textContent = `${tracks.length} tracks`;
    
    if (tracks.length === 0) {
        trackListContainer.innerHTML = '<div class="empty-recs">Library is empty. Put MP3 files in Songs/ directory.</div>';
        return;
    }
    
    tracks.forEach(track => {
        const div = document.createElement('div');
        div.className = 'track-item';
        div.dataset.title = track.title;
        div.dataset.key = track.camelot_key;
        div.dataset.bpm = track.bpm;
        
        // Render track item layout
        div.innerHTML = `
            <div class="track-item-info">
                <span class="track-title">${track.title}</span>
                <div class="track-meta-row">
                    <span>⏱️ ${track.bpm} BPM</span>
                    <span>🔑 Key: ${track.camelot_key} (${track.key})</span>
                </div>
            </div>
            <div class="track-action-add" style="font-size: 14px; font-weight: bold; color: var(--accent-navy);">+</div>
        `;
        
        // Click to add to the Mix Queue
        div.addEventListener('click', () => {
            addToMixQueue(track);
        });
        
        trackListContainer.appendChild(div);
    });
    
    // Update matching highlights based on active queue
    updateLibraryCompatibilityHighlights();
}

// Append track to active Mix Queue
function addToMixQueue(track) {
    // Add to array
    mixQueue.push({
        title: track.title,
        bpm: track.bpm,
        camelot_key: track.camelot_key,
        key: track.key
    });
    
    logMessage(`Added to queue: ${track.title}`);
    renderMixQueue();
    updateActiveMonitor();
    updateLibraryCompatibilityHighlights();
}

// Render Mix Queue visual cards
function renderMixQueue() {
    mixQueueContainer.innerHTML = '';
    
    if (mixQueue.length === 0) {
        mixQueueContainer.innerHTML = '<div class="empty-queue-hint">Click tracks in your library to add them to the mix sequence.</div>';
        return;
    }
    
    mixQueue.forEach((track, index) => {
        const card = document.createElement('div');
        card.className = 'queue-card';
        card.draggable = true;
        card.dataset.index = index;
        
        card.innerHTML = `
            <span class="queue-card-title">${track.title}</span>
            <span class="queue-card-meta">${track.bpm} BPM | ${track.camelot_key}</span>
            <button class="queue-card-remove" data-index="${index}">&times;</button>
        `;
        
        // Remove button handler
        card.querySelector('.queue-card-remove').addEventListener('click', (e) => {
            e.stopPropagation(); // prevent drag triggers
            removeFromMixQueue(index);
        });
        
        // Setup HTML5 Drag & Drop handlers for reordering
        card.addEventListener('dragstart', (e) => {
            card.classList.add('dragging');
            e.dataTransfer.setData('text/plain', index);
            e.dataTransfer.effectAllowed = 'move';
        });
        
        card.addEventListener('dragend', () => {
            card.classList.remove('dragging');
            document.querySelectorAll('.queue-card').forEach(c => c.classList.remove('drag-over'));
        });
        
        card.addEventListener('dragover', (e) => {
            e.preventDefault();
            card.classList.add('drag-over');
        });
        
        card.addEventListener('dragleave', () => {
            card.classList.remove('drag-over');
        });
        
        card.addEventListener('drop', (e) => {
            e.preventDefault();
            card.classList.remove('drag-over');
            const fromIndex = parseInt(e.dataTransfer.getData('text/plain'));
            const toIndex = index;
            
            if (fromIndex !== toIndex) {
                // Reorder array elements
                const draggedItem = mixQueue.splice(fromIndex, 1)[0];
                mixQueue.splice(toIndex, 0, draggedItem);
                
                logMessage(`Rearranged mix: ${mixQueue.map(t => t.title).join(" ➔ ")}`);
                renderMixQueue();
                updateActiveMonitor();
                updateLibraryCompatibilityHighlights();
            }
        });
        
        mixQueueContainer.appendChild(card);
    });
}

// Remove track from active Mix Queue
function removeFromMixQueue(index) {
    const title = mixQueue[index].title;
    mixQueue.splice(index, 1);
    logMessage(`Removed from queue: ${title}`);
    renderMixQueue();
    updateActiveMonitor();
    updateLibraryCompatibilityHighlights();
}

// Update the compatibility styling in the sidebar
function updateLibraryCompatibilityHighlights() {
    const items = document.querySelectorAll('.track-item');
    
    // Clear existing compatible flags
    items.forEach(item => {
        item.classList.remove('compatible');
        const oldBadge = item.querySelector('.match-badge');
        if (oldBadge) oldBadge.remove();
    });
    
    if (mixQueue.length === 0) return;
    
    // Get last track currently in the queue
    const tailTrack = mixQueue[mixQueue.length - 1];
    
    items.forEach(item => {
        // Skip if it's the exact same song as the last song in queue
        if (item.dataset.title === tailTrack.title) return;
        
        const itemKey = item.dataset.key;
        
        // Calculate key and tempo compatibility
        const isKeyCompat = areCamelotCompatible(tailTrack.camelot_key, itemKey);
        
        if (isKeyCompat) {
            item.classList.add('compatible');
            
            // Append badge if not already present
            const badge = document.createElement('span');
            badge.className = 'match-badge';
            badge.textContent = 'Match';
            item.appendChild(badge);
        }
    });
}

// Update the main monitor display details
function updateActiveMonitor() {
    if (mixQueue.length === 0) {
        activeTrackTitle.textContent = "Select tracks to mix";
        activeTrackBpm.textContent = "--";
        activeTrackKey.textContent = "--";
        animatePlayhead(false);
        return;
    }
    
    if (mixQueue.length === 1) {
        activeTrackTitle.textContent = mixQueue[0].title;
        activeTrackBpm.textContent = mixQueue[0].bpm;
        activeTrackKey.textContent = mixQueue[0].camelot_key;
    } else {
        activeTrackTitle.textContent = `${mixQueue.length} Tracks Sequence`;
        activeTrackBpm.textContent = mixQueue[0].bpm;
        activeTrackKey.textContent = mixQueue[0].camelot_key;
    }
}

// Output log message to status log console
function logMessage(text, type = 'log') {
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    entry.textContent = `[${time}] ${text}`;
    
    statusLog.appendChild(entry);
    statusLog.scrollTop = statusLog.scrollHeight;
}

// Draw Mock Waveforms using HTML5 Canvas
function initializeWaveforms() {
    drawWaveform('canvas-vocals', '#001f3f'); // Deep Navy Vocals
    drawWaveform('canvas-drums', '#64748b');  // Slate Drums
    drawWaveform('canvas-bass', '#475569');   // Steel Bass
    drawWaveform('canvas-other', '#2563eb');  // Royal Blue Melody (Other)
}

function drawWaveform(canvasId, color) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = canvas.parentElement.clientHeight;
    
    const width = canvas.width;
    const height = canvas.height;
    const midY = height / 2;
    
    ctx.clearRect(0, 0, width, height);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    
    ctx.beginPath();
    ctx.moveTo(0, midY);
    
    const isVocals = canvasId.includes('vocals');
    const isDrums = canvasId.includes('drums');
    const isBass = canvasId.includes('bass');
    
    for (let x = 0; x < width; x++) {
        let amp = 0;
        
        if (isVocals) {
            amp = Math.sin(x * 0.03) * Math.cos(x * 0.007) * (midY - 4);
            if (Math.abs(amp) < (midY - 8)) amp = amp * 0.15;
        } else if (isDrums) {
            amp = (Math.sin(x * 0.15) > 0.85) ? (midY - 4) * (0.8 + 0.2 * Math.sin(x)) : 2;
            if (x % 32 < 2) amp = midY - 6;
        } else if (isBass) {
            amp = Math.sin(x * 0.05) * 0.7 * (midY - 6);
            if (Math.abs(amp) > (midY - 12)) amp = (midY - 8) * Math.sign(amp);
        } else {
            amp = Math.sin(x * 0.08) * Math.sin(x * 0.02) * (midY - 6);
        }
        
        amp += (Math.random() - 0.5) * 2;
        ctx.lineTo(x, midY + amp);
    }
    
    ctx.stroke();
}

// Animate Mix Playhead line scanning back and forth
let playheadInterval = null;
function animatePlayhead(shouldPlay) {
    clearInterval(playheadInterval);
    if (!shouldPlay) {
        playhead.style.left = '45%';
        return;
    }
    
    let position = 0;
    playheadInterval = setInterval(() => {
        position = (position + 0.5) % 100;
        playhead.style.left = `${position}%`;
    }, 40);
}

// Trigger Mix compilation on server
async function triggerMixGeneration() {
    if (isCompiling) return;
    
    const promptText = promptInput.value.trim();
    
    // If prompt is not empty, run AI prompt parser first
    if (promptText !== "") {
        logMessage(`Submitting AI DJ prompt: "${promptText}"...`);
        try {
            setLoadingState(true);
            const response = await fetch(API_GENERATE, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: promptText })
            });
            
            if (response.status === 409) {
                alert("A mix compilation task is already running.");
                setLoadingState(false);
                return;
            }
            
            const data = await response.json();
            logMessage(data.message, 'system');
            
            if (data.config && data.config.song_order.length > 0) {
                logMessage(`NLP Parsed Order: ${data.config.song_order.join(" ➔ ")}`);
                // Load tracks into the mixQueue
                mixQueue = [];
                data.config.song_order.forEach(title => {
                    const track = Object.values(libraryData).find(t => t.title === title);
                    if (track) mixQueue.push(track);
                });
                renderMixQueue();
                updateActiveMonitor();
                updateLibraryCompatibilityHighlights();
            }
            
            startStatusPolling();
        } catch (e) {
            logMessage(`Prompt trigger failed: ${e.message}`, 'error');
            setLoadingState(false);
        }
    } else {
        // Run Mix based on visual Mix Queue order
        if (mixQueue.length < 2) {
            logMessage("Warning: Please click songs in library to add at least 2 tracks to the Mix Sequence.", "error");
            alert("Please select at least 2 tracks in your Mix Sequence to compile.");
            return;
        }
        
        const orderedTitles = mixQueue.map(t => t.title);
        logMessage(`Compiling ordered mix: ${orderedTitles.join(" ➔ ")}...`);
        
        const payload = {
            song_order: orderedTitles,
            body_bars: parseInt(energyCurve.value) > 50 ? 8 : 4,
            transition_bars: parseInt(energyCurve.value) > 50 ? 4 : 2,
            vocal_boost_db: 1.0
        };
        
        try {
            setLoadingState(true);
            const response = await fetch(API_CUSTOM, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            logMessage(data.message, 'system');
            startStatusPolling();
        } catch (e) {
            logMessage(`Mix trigger failed: ${e.message}`, 'error');
            setLoadingState(false);
        }
    }
}

// Toggle loading/compiling UI states
function setLoadingState(loading) {
    isCompiling = loading;
    generateBtn.disabled = loading;
    
    if (loading) {
        generateBtn.textContent = 'MIXING IN PROGRESS...';
        renderModeText.textContent = 'Real-time rendering...';
        downloadMixBtn.classList.add('hidden');
        animatePlayhead(true);
    } else {
        generateBtn.textContent = 'GENERATE MASHUP';
        animatePlayhead(false);
    }
}

// Start polling API status endpoint
function startStatusPolling() {
    clearInterval(statusPollInterval);
    statusPollInterval = setInterval(pollStatus, 1000);
}

// Poll mix compilation status
async function pollStatus() {
    try {
        const response = await fetch(API_STATUS);
        const data = await response.json();
        
        renderModeText.textContent = data.message;
        progressBarFill.style.width = `${data.progress * 100}%`;
        
        if (data.message && data.status === 'running') {
            logMessage(data.message);
        }
        
        if (data.status === 'completed') {
            clearInterval(statusPollInterval);
            logMessage("Mixing completed! Mix file compiled with ID3 tags.", 'system');
            
            outputFilenameText.textContent = "Output: AI_DJ_Mix.mp3 (128 BPM / 9B Camelot)";
            downloadMixBtn.classList.remove('hidden');
            
            setLoadingState(false);
            fetchLibrary();
            
        } else if (data.status === 'failed') {
            clearInterval(statusPollInterval);
            logMessage(data.message, 'error');
            setLoadingState(false);
            alert(`Mix failed: ${data.message}`);
        }
        
    } catch (e) {
        console.error("Error polling mix status:", e);
    }
}

// Client-Side Camelot Compatibility check rules
function areCamelotCompatible(key1, key2) {
    if (!key1 || !key2 || key1 === 'Unknown' || key2 === 'Unknown') return false;
    
    const num1 = parseInt(key1.slice(0, -1));
    const let1 = key1.slice(-1);
    const num2 = parseInt(key2.slice(0, -1));
    const let2 = key2.slice(-1);
    
    if (num1 === num2 && let1 === let2) return true;
    if (let1 === let2) {
        const diff = Math.abs(num1 - num2);
        if (diff === 1 || diff === 11) return true;
    }
    if (num1 === num2 && let1 !== let2) return true;
    
    return false;
}

// Generate Initial recommendations for the deck on load
function generateInitialRecommendations() {
    recommendationsList.innerHTML = '';
    const tracks = Object.values(libraryData);
    
    if (tracks.length < 2) {
        recommendationsList.innerHTML = '<div class="empty-recs">Add more tracks to view AI transition recommendations.</div>';
        return;
    }
    
    const recs = [];
    
    for (let i = 0; i < tracks.length; i++) {
        for (let j = 0; j < tracks.length; j++) {
            if (i === j) continue;
            
            const trackA = tracks[i];
            const trackB = tracks[j];
            
            if (areCamelotCompatible(trackA.camelot_key, trackB.camelot_key)) {
                let matchType = "Hour shift";
                if (trackA.camelot_key === trackB.camelot_key) {
                    matchType = "Perfect key match";
                } else if (trackA.camelot_key.slice(-1) !== trackB.camelot_key.slice(-1)) {
                    matchType = "Relative Major/Minor swap";
                }
                
                recs.push({
                    trackA: trackA,
                    trackB: trackB,
                    reason: `${matchType} (BPM delta: ${Math.abs(trackA.bpm - trackB.bpm).toFixed(1)} BPM)`
                });
            }
        }
    }
    
    if (recs.length === 0) {
        recommendationsList.innerHTML = '<div class="empty-recs">No harmonic key matches found.</div>';
        return;
    }
    
    recs.slice(0, 3).forEach(rec => {
        const div = document.createElement('div');
        div.className = 'rec-item';
        div.innerHTML = `
            <div class="rec-flow">
                <span>${rec.trackA.title}</span>
                <span class="rec-arrow">➔</span>
                <span>${rec.trackB.title}</span>
            </div>
            <div class="rec-reason">${rec.reason}</div>
            <span class="rec-badge">${rec.trackA.camelot_key} ➔ ${rec.trackB.camelot_key}</span>
        `;
        
        // Clicking a recommendation automatically loads them into the Mix Queue
        div.addEventListener('click', () => {
            mixQueue = [rec.trackA, rec.trackB];
            renderMixQueue();
            updateActiveMonitor();
            updateLibraryCompatibilityHighlights();
            logMessage(`AI Recommendation loaded into sequence: ${rec.trackA.title} ➔ ${rec.trackB.title}. Ready to mix!`);
            transitionPreset.value = "bass_swap_beatmatch";
        });
        
        recommendationsList.appendChild(div);
    });
}

// AI TAP handler to shuffle/highlight recommended pairings
function triggerAITap() {
    logMessage("AI TAP triggered. Calculating compatible transition paths...", 'system');
    
    const tracks = Object.values(libraryData);
    if (tracks.length < 2) {
        logMessage("Not enough songs in library to match. Add tracks first!", "error");
        return;
    }
    
    // Pick a starting track
    let startTrack;
    if (mixQueue.length > 0) {
        startTrack = mixQueue[mixQueue.length - 1];
    } else {
        startTrack = tracks[Math.floor(Math.random() * tracks.length)];
    }
    
    // Find compatible matches
    const matches = tracks.filter(t => t.title !== startTrack.title && areCamelotCompatible(startTrack.camelot_key, t.camelot_key));
    
    if (matches.length > 0) {
        const targetTrack = matches[Math.floor(Math.random() * matches.length)];
        
        // Append it to Mix Queue
        if (mixQueue.length === 0) {
            mixQueue.push(startTrack);
        }
        mixQueue.push(targetTrack);
        
        renderMixQueue();
        updateActiveMonitor();
        updateLibraryCompatibilityHighlights();
        
        logMessage(`AI TAP Suggestion appended: ${startTrack.title} (${startTrack.camelot_key}) matched with ${targetTrack.title} (${targetTrack.camelot_key}).`, 'system');
        transitionPreset.value = Math.random() > 0.5 ? "vocal_overlay_beatmatch" : "bass_swap_beatmatch";
        
    } else {
        // If queue tail has no matches, suggest a fresh matching pair from recommendations
        logMessage(`AI TAP search from ${startTrack.title} (${startTrack.camelot_key}) found no compatible harmonic keys. Shuffling active recommendations...`);
        generateInitialRecommendations();
    }
}
