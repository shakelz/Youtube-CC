import streamlit as st
import streamlit.components.v1 as components
import yt_dlp
import whisper
import re
import os
import glob
import html
import json
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

# ============================================
# METHOD 1: YOUTUBE CC (WITH SMART PARSER)
# ============================================

def download_captions(video_id, lang='de'):
    for f in glob.glob('temp_subs*'):
        try: os.remove(f)
        except: pass

    ydl_opts = {
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': [lang],
        'subtitlesformat': 'vtt',
        'skip_download': True,
        'outtmpl': 'temp_subs',
        'quiet': True,
        'ignoreerrors': True,
        'cookiefile': 'cookies.txt', # Pukka cookies.txt is folder me hona
        'extractor_args': {'youtube': ['player_client=ios,android']} 
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://youtu.be/{video_id}"])
    except:
        return None

    files = glob.glob('temp_subs*.vtt')
    return files[0] if files else None

def parse_vtt(vtt_content):
    segments = []
    current_time = ""
    block_lines = []
    last_block_lines = [] # Pichle block ko yaad rakhne ke liye

    for line in vtt_content.split('\n'):
        line = line.strip()

        # Jab naya timestamp aaye
        if '-->' in line:
            if current_time and block_lines:
                # HTML tags aur kachra saaf karo har line se
                cleaned_block = [html.unescape(re.sub(r'<[^>]+>', '', l)).strip() for l in block_lines if l.strip()]
                
                if cleaned_block:
                    # 🔥 THE MAGIC FIX: Rolling CC Detection
                    # Agar naye block ki pehli line pichle block ki aakhri line se match hoti hai, toh usko uda do!
                    if last_block_lines and (cleaned_block[0] in last_block_lines[-1] or last_block_lines[-1] in cleaned_block[0]):
                        cleaned_block.pop(0) # Purana repeat hua text delete!
                    
                    if cleaned_block:
                        # Bachi hui nayi lines ko jod do
                        text = " ".join(cleaned_block)
                        # Ek aakhri check: Agar exact sentence wapas aara toh ignore karo
                        if not segments or segments[-1]['text'] != text:
                            segments.append({'time': current_time, 'text': text})
                        
                        last_block_lines = cleaned_block
            
            current_time = line.split(' --> ')[0]
            block_lines = []
            
        # Metadata skip karke text lines collect karo
        elif line and 'WEBVTT' not in line and not line.isdigit():
            if not line.startswith('Kind:') and not line.startswith('Language:') and not line.startswith('Style:'):
                block_lines.append(line)

    # Aakhri bache hue block ke liye
    if current_time and block_lines:
        cleaned_block = [html.unescape(re.sub(r'<[^>]+>', '', l)).strip() for l in block_lines if l.strip()]
        if cleaned_block:
            if last_block_lines and (cleaned_block[0] in last_block_lines[-1] or last_block_lines[-1] in cleaned_block[0]):
                cleaned_block.pop(0)
            if cleaned_block:
                text = " ".join(cleaned_block)
                if not segments or segments[-1]['text'] != text:
                    segments.append({'time': current_time, 'text': text})

    return segments

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

# ============================================
# METHOD 2: WHISPER AI
# ============================================

def download_audio(video_id):
    for f in glob.glob('temp_audio*') + glob.glob('*.mp3'):
        try: os.remove(f)
        except: pass

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
        'outtmpl': 'temp_audio',
        'quiet': True,
        'cookiefile': 'cookies.txt',
        'extractor_args': {'youtube': ['player_client=ios,android']}
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://youtu.be/{video_id}"])
    except:
        return None

    return 'temp_audio.mp3' if os.path.exists('temp_audio.mp3') else None

def method_whisper(video_id, lang, model_size):
    audio_path = download_audio(video_id)
    if not audio_path:
        return None

    model = whisper.load_model(model_size)
    lm = {"auto": None, "de": "de", "en": "en", "es": "es", "fr": "fr", "hi": "hi"}.get(lang, None)
    result = model.transcribe(audio_path, language=lm, word_timestamps=True)
    os.remove(audio_path)

    segments = []
    for seg in result.get('segments', []):
        segments.append({
            'time': seconds_to_vtt(seg['start']),
            'text': seg['text'].strip()
        })

    return segments if segments else None

# ============================================
# FORMAT SRT
# ============================================

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

# ============================================
# BUILD SYNCED HTML PLAYER (MOBILE OPTIMIZED)
# ============================================

def build_synced_player(segments, video_id):
    segments_json = json.dumps(segments, ensure_ascii=False)

    html_code = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body, html {{ height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: transparent; }}
.container {{ display: flex; flex-direction: column; height: 100vh; width: 100%; max-width: 600px; margin: 0 auto; background: #1a1a2e; border-radius: 12px; overflow: hidden; }}
.video-panel {{ flex-shrink: 0; width: 100%; background: #000; z-index: 10; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
.video-wrapper {{ position: relative; padding-bottom: 56.25%; height: 0; }}
.video-wrapper iframe {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none; }}
.transcript-panel {{ flex: 1; display: flex; flex-direction: column; overflow: hidden; }}
.header {{ padding: 12px 15px; background: #16213e; color: #e94560; font-weight: bold; font-size: 14px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #0f3460; }}
.progress {{ height: 4px; background: #0f3460; width: 100%; }}
.progress-fill {{ height: 100%; background: #e94560; width: 0%; transition: width 0.3s linear; }}
.transcript-body {{ flex: 1; overflow-y: auto; padding: 15px; scroll-behavior: smooth; }}
.line {{ padding: 15px; margin-bottom: 12px; border-radius: 10px; cursor: pointer; border-left: 4px solid transparent; background: rgba(255,255,255,0.02); transition: all 0.3s ease; }}
.line:active {{ background: rgba(255,255,255,0.05); }}
.line.active {{ background: rgba(233,69,96,0.15); border-left-color: #e94560; transform: scale(1.02); box-shadow: 0 4px 10px rgba(0,0,0,0.2); }}
.ts {{ color: #e94560; font-size: 12px; font-weight: bold; margin-bottom: 6px; display: inline-block; background: rgba(233,69,96,0.1); padding: 2px 8px; border-radius: 12px; }}
.de {{ font-size: 18px; color: #ffffff; font-weight: 500; margin-bottom: 6px; line-height: 1.4; }}
.en {{ font-size: 15px; color: #a0a0b5; font-style: italic; line-height: 1.3; }}
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
# STREAMLIT UI SETUP
# ============================================

st.set_page_config(page_title="Lerne Deutsch - Sync Player", page_icon="🎬", layout="centered")

st.markdown("<h2 style='text-align: center; color: #e94560;'>📱 Mobile Video Sync App</h2>", unsafe_allow_html=True)

# Inputs
url_input = st.text_input("📺 YouTube URL", placeholder="Paste YouTube Link Here...")

col1, col2 = st.columns(2)
with col1:
    method_choice = st.radio("🛠️ Method", ["⚡ YouTube CC", "🎤 Whisper AI"])
with col2:
    language = st.selectbox("🎤 Language", ["de", "en", "auto"], index=0)

if st.button("🚀 Load Sync Player", use_container_width=True):
    if not url_input:
        st.error("❌ Link toh daalo ustad!")
    else:
        video_id = extract_video_id(url_input)
        if not video_id:
            st.error("❌ Invalid URL")
        else:
            with st.status("⏳ Video process hora, thoda sabr karo...", expanded=True) as status:
                
                if "CC" in method_choice:
                    st.write("📥 CC Captions download hore...")
                    segments = method_cc(video_id, language)
                else:
                    st.write("📥 Audio download hora...")
                    st.write("🎤 Whisper AI transcribe karra...")
                    segments = method_whisper(video_id, language, "tiny") # Tiny use karna Streamlit ke liye

                if not segments:
                    status.update(label="❌ Failed to extract subtitles. (JavaScript / Cookie error)", state="error")
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

            # 🔥 YEH NAYA ADD KIYA: Sirf tab UI dikhao jab segments mil gaye ho
            if segments:
                # Display the Synced HTML Player
                st.markdown("---")
                components.html(html_player, height=750, scrolling=False)

                # Display Text Outputs & Download Button
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
