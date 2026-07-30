import streamlit as st
import streamlit.components.v1 as components
import yt_dlp
from faster_whisper import WhisperModel  # ✅ Changed from whisper
import re
import os
import glob
import html
import json
import tempfile
import hashlib
import time
from deep_translator import GoogleTranslator

# ============================================
# COMMON FUNCTIONS
# ============================================

def extract_video_id(url):
    patterns = [
        r'(?:v=|/)([0-9A-Za-z_-]{11})(?:[?&]|$)',
        r'(?:youtu\.be/)([0-9A-Za-z_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

def time_to_seconds(time_str):
    parts = time_str.replace(',', '.').split(':')
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return int(parts[0]) * 60 + float(parts[1])

def seconds_to_vtt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')

def translate_segments(segments):
    try:
        translator = GoogleTranslator(source='auto', target='en')
        for i, seg in enumerate(segments):
            try:
                if len(seg['text']) > 3:
                    seg['translated'] = translator.translate(seg['text'])
                else:
                    seg['translated'] = seg['text']
            except:
                seg['translated'] = seg['text']
    except:
        for seg in segments:
            seg['translated'] = seg['text']
    return segments

def remove_overlap(previous, current):
    prev = previous.split()
    curr = current.split()
    max_overlap = min(len(prev), len(curr))
    for i in range(max_overlap, 0, -1):
        if prev[-i:] == curr[:i]:
            return " ".join(curr[i:])
    return current

def remove_duplicate_words(text):
    words = text.split()
    result = []
    for w in words:
        if len(result) == 0 or result[-1] != w:
            result.append(w)
    return " ".join(result)

def parse_vtt(vtt_content):
    raw_segments = []
    current_time = ""
    block_lines = []

    for line in vtt_content.split('\n'):
        line = line.strip()
        if '-->' in line:
            if current_time and block_lines:
                cleaned_block = [html.unescape(re.sub(r'<[^>]+>', '', l)).strip() for l in block_lines if l.strip()]
                if cleaned_block:
                    text = " ".join(cleaned_block)
                    raw_segments.append({'time': current_time, 'text': text})
            current_time = line.split(' --> ')[0]
            block_lines = []
        elif line and 'WEBVTT' not in line and not line.isdigit():
            if not line.startswith('Kind:') and not line.startswith('Language:') and not line.startswith('Style:'):
                block_lines.append(line)

    if current_time and block_lines:
        cleaned_block = [html.unescape(re.sub(r'<[^>]+>', '', l)).strip() for l in block_lines if l.strip()]
        if cleaned_block:
            text = " ".join(cleaned_block)
            raw_segments.append({'time': current_time, 'text': text})

    filtered_phrases = []
    previous_text = ""
    for seg in raw_segments:
        text = seg["text"].strip()
        text = remove_overlap(previous_text, text)
        previous_text = seg["text"].strip()
        if not text:
            continue
        if text.lower() in ["[musik]", "[music]", "♪", "[räuspern]"]:
            continue
        text = remove_duplicate_words(text)
        if not text:
            continue
        filtered_phrases.append({
            "time": seg["time"],
            "text": text
        })
    return filtered_phrases

def format_srt(segments):
    srt = []
    for i, seg in enumerate(segments, 1):
        start = seg['time']
        end = seconds_to_vtt(time_to_seconds(start) + 3) if i >= len(segments) else segments[i]['time']
        srt.append(str(i))
        srt.append(f"{start} --> {end}")
        srt.append(f"{seg['text']}\n{seg['translated']}")
        srt.append("")
    return '\n'.join(srt)

def build_synced_player(segments, video_id):
    segments_json = json.dumps(segments, ensure_ascii=False)
    html_code = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body, html {{ height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #0a0a1a; overflow: hidden; }}
.container {{ display: flex; flex-direction: column; height: 100vh; width: 100%; background: #1a1a2e; overflow: hidden; position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 9999; }}
.video-panel {{ flex-shrink: 0; width: 100%; background: #000; z-index: 100; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }}
.video-wrapper {{ position: relative; padding-bottom: 56.25%; height: 0; width: 100%; }}
.video-wrapper iframe {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none; }}
.transcript-panel {{ flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #1a1a2e; }}
.header {{ padding: 10px 15px; background: #16213e; color: #e94560; font-weight: bold; font-size: 13px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #0f3460; flex-shrink: 0; }}
.progress {{ height: 4px; background: #0f3460; width: 100%; flex-shrink: 0; }}
.progress-fill {{ height: 100%; background: #e94560; width: 0%; transition: width 0.3s linear; }}
.transcript-body {{ flex: 1; overflow-y: auto; padding: 15px; scroll-behavior: smooth; -webkit-overflow-scrolling: touch; }}
.line {{ padding: 14px; margin-bottom: 12px; border-radius: 10px; cursor: pointer; border-left: 4px solid transparent; background: rgba(255,255,255,0.02); transition: all 0.3s ease; }}
.line:active {{ background: rgba(255,255,255,0.05); }}
.line.active {{ background: rgba(233,69,96,0.2); border-left-color: #e94560; transform: scale(1.01); box-shadow: 0 4px 12px rgba(0,0,0,0.3); }}
.ts {{ color: #e94560; font-size: 11px; font-weight: bold; margin-bottom: 5px; display: inline-block; background: rgba(233,69,96,0.1); padding: 2px 8px; border-radius: 12px; }}
.de {{ font-size: 17px; color: #ffffff; font-weight: 500; margin-bottom: 5px; line-height: 1.4; }}
.en {{ font-size: 14px; color: #a0a0b5; font-style: italic; line-height: 1.3; }}
.transcript-body::-webkit-scrollbar {{ width: 4px; }}
.transcript-body::-webkit-scrollbar-track {{ background: transparent; }}
.transcript-body::-webkit-scrollbar-thumb {{ background: #e94560; border-radius: 4px; }}
</style>
</head>
<body>
<div class="container">
    <div class="video-panel">
        <div class="video-wrapper">
            <iframe id="player" src="https://www.youtube.com/embed/{video_id}?enablejsapi=1&playsinline=1" allow="autoplay; fullscreen" allowfullscreen></iframe>
        </div>
    </div>
    <div class="transcript-panel">
        <div class="header">
            <span>📝 Lerne Deutsch (Sync)</span>
            <span id="timer">00:00</span>
        </div>
        <div class="progress"><div class="progress-fill" id="progress"></div></div>
        <div class="transcript-body" id="body"><div id="lines"></div></div>
    </div>
</div>
<script>
var segments = {segments_json};
var player;
var currentIdx = -1;
var intervalId;

function buildLines() {{
    var html = '';
    segments.forEach(function(s, i) {{
        html += '<div class="line" id="line-' + i + '" onclick="jump(' + i + ')">';
        html += '<div class="ts">⏱ ' + s.time + '</div>';
        html += '<div class="de">🇩🇪 ' + s.text + '</div>';
        html += '<div class="en">🇬🇧 ' + s.translated + '</div>';
        html += '</div>';
    }});
    document.getElementById('lines').innerHTML = html;
}}

function timeToSec(t) {{
    var p = t.replace(',', '.').split(':');
    return p.length === 3 ? parseInt(p[0])*3600 + parseInt(p[1])*60 + parseFloat(p[2]) : parseInt(p[0])*60 + parseFloat(p[1]);
}}

function update() {{
    if (!player || !player.getCurrentTime) return;
    var ct = player.getCurrentTime();
    var dur = player.getDuration();
    if(dur > 0) document.getElementById('progress').style.width = (ct/dur*100) + '%';
    
    var m = Math.floor(ct/60), s = Math.floor(ct%60);
    document.getElementById('timer').textContent = (m<10?'0':'')+m+':'+(s<10?'0':'')+s;
    
    var idx = -1;
    for (var i = segments.length-1; i >= 0; i--) {{
        if (ct >= timeToSec(segments[i].time)) {{ idx = i; break; }}
    }}
    
    if (idx !== currentIdx) {{
        var old = document.querySelector('.line.active');
        if (old) old.classList.remove('active');
        if (idx >= 0) {{
            var el = document.getElementById('line-' + idx);
            if (el) {{ 
                el.classList.add('active'); 
                el.scrollIntoView({{ behavior: 'smooth', block: 'center' }}); 
            }}
        }}
        currentIdx = idx;
    }}
}}

function jump(i) {{
    if (player && segments[i]) {{
        player.seekTo(timeToSec(segments[i].time), true);
        player.playVideo();
    }}
}}

var tag = document.createElement('script');
tag.src = "https://www.youtube.com/iframe_api";
document.head.appendChild(tag);

function onYouTubeIframeAPIReady() {{
    player = new YT.Player('player', {{
        events: {{ 'onReady': function() {{ buildLines(); intervalId = setInterval(update, 300); }} }}
    }});
}}
</script>
</body>
</html>"""
    return html_code

# ============================================
# SECURE COOKIE HANDLING
# ============================================

def secure_cookie_upload():
    """Handle cookie upload with security measures"""
    if 'cookies_uploaded' in st.session_state and st.session_state.cookies_uploaded:
        st.success("✅ Cookies loaded successfully")
        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption(f"🔒 Cookies active • Session: {st.session_state.get('cookie_session_id', 'N/A')}")
        with col2:
            if st.button("🗑️ Clear Cookies", type="secondary"):
                clear_cookies()
                st.rerun()
        return True

    st.info("🔒 **Your cookies are safe:** They are stored only in your browser session and never saved to disk or shared.")
    uploaded_file = st.file_uploader(
        "📁 Upload cookies.txt (from your browser)",
        type=['txt'],
        help="Export cookies using 'Get cookies.txt' extension from your logged-in YouTube session"
    )
    if uploaded_file is not None:
        content = uploaded_file.getvalue().decode('utf-8')
        if not content.startswith('# Netscape HTTP Cookie File'):
            st.error("❌ Invalid cookie file format. Please export as Netscape format.")
            return False
        try:
            temp_dir = tempfile.mkdtemp(prefix='cookies_')
            cookie_path = os.path.join(temp_dir, 'cookies.txt')
            with open(cookie_path, 'w', encoding='utf-8') as f:
                f.write(content)
            st.session_state.cookie_path = cookie_path
            st.session_state.cookies_uploaded = True
            st.session_state.cookie_session_id = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
            st.success("✅ Cookies loaded successfully! (Session-only)")
            st.rerun()
            return True
        except Exception as e:
            st.error(f"❌ Error saving cookies: {str(e)}")
            return False
    return False

def clear_cookies():
    """Securely clear cookies from session"""
    if 'cookie_path' in st.session_state:
        try:
            cookie_dir = os.path.dirname(st.session_state.cookie_path)
            if os.path.exists(st.session_state.cookie_path):
                os.remove(st.session_state.cookie_path)
            if os.path.exists(cookie_dir):
                os.rmdir(cookie_dir)
        except:
            pass
    st.session_state.cookies_uploaded = False
    st.session_state.cookie_path = None
    if 'cookie_session_id' in st.session_state:
        del st.session_state.cookie_session_id

def get_cookie_path():
    """Get the current cookie path or None"""
    if 'cookies_uploaded' in st.session_state and st.session_state.cookies_uploaded:
        return st.session_state.get('cookie_path', None)
    return None

# ============================================
# YT-DLP FUNCTIONS
# ============================================

def download_captions(video_id, lang='de'):
    for f in glob.glob('temp_subs*'):
        try: os.remove(f)
        except: pass

    cookie_path = get_cookie_path()
    
    ydl_opts = {
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': [lang],
        'subtitlesformat': 'vtt',
        'skip_download': True,
        'outtmpl': 'temp_subs',
        'quiet': True,
        'ignoreerrors': True,
        'extractor_args': {'youtube': ['player_client=ios,android']}
    }
    
    if cookie_path and os.path.exists(cookie_path):
        ydl_opts['cookiefile'] = cookie_path
        st.write("🔑 Using session cookies...")
    else:
        st.warning("⚠️ No cookies found, using anonymous access (may be blocked)")
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://youtu.be/{video_id}"])
    except Exception as e:
        if "cookiefile" in str(e) or "HTTP Error 403" in str(e):
            st.error("❌ Access blocked. Please upload valid cookies.txt")
        return None

    files = glob.glob('temp_subs*.vtt')
    return files[0] if files else None

def method_cc(video_id, lang):
    vtt_file = download_captions(video_id, lang)
    if not vtt_file and lang != 'en':
        vtt_file = download_captions(video_id, 'en')
    if not vtt_file:
        return None
    with open(vtt_file, 'r', encoding='utf-8') as f:
        vtt_content = f.read()
    os.remove(vtt_file)
    return parse_vtt(vtt_content)

def download_audio(video_id):
    for f in glob.glob('temp_audio*') + glob.glob('*.mp3'):
        try: os.remove(f)
        except: pass

    cookie_path = get_cookie_path()
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
        'outtmpl': 'temp_audio',
        'quiet': True,
        'extractor_args': {'youtube': ['player_client=ios,android']}
    }
    
    if cookie_path and os.path.exists(cookie_path):
        ydl_opts['cookiefile'] = cookie_path
        st.write("🔑 Using session cookies...")
    else:
        st.warning("⚠️ No cookies found, using anonymous access (may be blocked)")
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://youtu.be/{video_id}"])
    except Exception as e:
        if "cookiefile" in str(e) or "HTTP Error 403" in str(e):
            st.error("❌ Access blocked. Please upload valid cookies.txt")
        return None
    return 'temp_audio.mp3' if os.path.exists('temp_audio.mp3') else None

# ============================================
# UPDATED WHISPER METHOD USING FASTER-WHISPER
# ============================================

def method_whisper(video_id, lang, model_size):
    audio_path = download_audio(video_id)
    if not audio_path:
        return None
    
    try:
        # Map model sizes
        model_map = {
            "tiny": "tiny",
            "base": "base", 
            "small": "small",
            "medium": "medium",
            "large": "large"
        }
        
        model_name = model_map.get(model_size, "tiny")
        st.write(f"🔄 Loading {model_name} model... (This may take a moment)")
        
        # Load model with CPU and int8 for speed
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        
        # Transcribe with better settings
        segments_result, info = model.transcribe(
            audio_path,
            language=lang if lang != 'auto' else None,
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=False
        )
        
        # Convert to segments
        segments = []
        for seg in segments_result:
            segments.append({
                'time': seconds_to_vtt(seg.start),
                'text': seg.text.strip()
            })
        
        os.remove(audio_path)
        return segments if segments else None
        
    except Exception as e:
        st.error(f"❌ Whisper error: {str(e)}")
        if os.path.exists(audio_path):
            os.remove(audio_path)
        return None

# ============================================
# STREAMLIT UI
# ============================================

st.set_page_config(page_title="Lerne Deutsch - Sync Player", page_icon="🎬", layout="centered")
st.markdown("<h2 style='text-align: center; color: #e94560;'>📱 Mobile Video Sync App</h2>", unsafe_allow_html=True)

# --- Cookie Upload Section ---
with st.expander("🔐 Cookie Authentication (Required for YouTube Access)", expanded=False):
    st.markdown("""
    **Why do you need cookies?** YouTube often blocks cloud servers. Using your cookies from a logged-in browser session proves you're a real user.
    
    **How to get cookies:**
    1. Install a browser extension like "Get cookies.txt LOCALLY"
    2. Log into YouTube in your browser
    3. Export cookies as `cookies.txt` (Netscape format)
    4. Upload below
    """)
    cookies_loaded = secure_cookie_upload()

if not st.session_state.get('cookies_uploaded', False):
    st.warning("⚠️ **YouTube access may be blocked** without cookies. Please upload your cookies.txt above.")

# --- Main Input ---
url_input = st.text_input("📺 YouTube URL", placeholder="Paste YouTube Link Here...")

col1, col2 = st.columns(2)
with col1:
    method_choice = st.radio("🛠️ Method", ["⚡ YouTube CC", "🎤 Whisper AI"])
with col2:
    language = st.selectbox("🎤 Language", ["de", "en", "auto"], index=0)

# Add model size selector for Whisper
if "Whisper" in method_choice:
    model_size = st.selectbox(
        "📊 Model Size", 
        ["tiny", "base", "small", "medium"], 
        index=0,
        help="tiny=fastest/least accurate, medium=slower/most accurate"
    )
else:
    model_size = "tiny"

# --- Process Button ---
if st.button("🚀 Load Sync Player", use_container_width=True):
    if not url_input:
        st.error("❌ Link toh daalo ustad!")
    else:
        video_id = extract_video_id(url_input)
        if not video_id:
            st.error("❌ Invalid URL")
        else:
            if not st.session_state.get('cookies_uploaded', False):
                st.warning("⚠️ No cookies uploaded. YouTube may block access. If it fails, upload cookies and try again.")
            
            segments = None
            html_player = ""
            interleaved_text = original_text = translated_text = srt_content = ""
            
            with st.status("⏳ Video process hora, thoda sabr karo...", expanded=True) as status:
                if "CC" in method_choice:
                    st.write("📥 CC Captions download aur clean hore...")
                    segments = method_cc(video_id, language)
                else:
                    st.write("📥 Audio download hora...")
                    st.write("🎤 Faster-Whisper AI transcribe karra...")
                    segments = method_whisper(video_id, language, model_size)

                if not segments:
                    status.update(label="❌ Failed to extract subtitles.", state="error")
                    if not st.session_state.get('cookies_uploaded', False):
                        st.info("💡 **Tip:** Upload your cookies.txt from a logged-in YouTube session to bypass access blocks.")
                    else:
                        st.info("💡 **Tip:** Try a different video or use the YouTube CC method instead.")
                else:
                    st.write("🌍 English mein translate hora...")
                    segments = translate_segments(segments)
                    st.write("🎬 Player generate hora...")
                    html_player = build_synced_player(segments, video_id)
                    
                    interleaved_text = '\n\n'.join([f"[{s['time']}] 🇩🇪 {s['text']}\n         🇬🇧 {s['translated']}" for s in segments])
                    original_text = '\n'.join([f"[{s['time']}] {s['text']}" for s in segments])
                    translated_text = '\n'.join([f"[{s['time']}] {s['translated']}" for s in segments])
                    srt_content = format_srt(segments)
                    status.update(label="✅ Player is Ready!", state="complete")

            if segments and html_player:
                st.markdown("---")
                components.html(html_player, height=600, scrolling=False)

                st.markdown("### 📝 Transcripts")
                tab1, tab2, tab3 = st.tabs(["Interleaved (DE + EN)", "German Only", "English Only"])
                with tab1:
                    st.text_area("Line by Line", interleaved_text, height=300)
                with tab2:
                    st.text_area("Original", original_text, height=300)
                with tab3:
                    st.text_area("Translation", translated_text, height=300)
                
                st.download_button(
                    label="💾 Download SRT Subtitles",
                    data=srt_content,
                    file_name=f"{video_id}_subtitles.srt",
                    mime="text/plain",
                    use_container_width=True
                )
