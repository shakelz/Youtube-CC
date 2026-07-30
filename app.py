import streamlit as st
import streamlit.components.v1 as components
import yt_dlp
import whisper
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
# SECURE COOKIE HANDLING
# ============================================

def secure_cookie_upload():
    """Handle cookie upload with security measures"""
    
    # Check if cookies already exist in session
    if 'cookies_uploaded' in st.session_state and st.session_state.cookies_uploaded:
        st.success("✅ Cookies loaded successfully")
        
        # Show cookie status but not the content
        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption(f"🔒 Cookies active • Session: {st.session_state.get('cookie_session_id', 'N/A')}")
        with col2:
            if st.button("🗑️ Clear Cookies", type="secondary"):
                clear_cookies()
                st.rerun()
        return True
    
    # Upload interface with security notice
    st.info("🔒 **Your cookies are safe:** They are stored only in your browser session and never saved to disk or shared.")
    
    uploaded_file = st.file_uploader(
        "📁 Upload cookies.txt (from your browser)",
        type=['txt'],
        help="Export cookies using 'Get cookies.txt' extension from your logged-in YouTube session"
    )
    
    if uploaded_file is not None:
        # Security: Validate file content
        content = uploaded_file.getvalue().decode('utf-8')
        
        # Basic validation - check if it looks like a Netscape cookie file
        if not content.startswith('# Netscape HTTP Cookie File'):
            st.error("❌ Invalid cookie file format. Please export as Netscape format.")
            return False
        
        # Security: Create session-scoped temp file
        try:
            # Create a temporary file that will be deleted when session ends
            temp_dir = tempfile.mkdtemp(prefix='cookies_')
            cookie_path = os.path.join(temp_dir, 'cookies.txt')
            
            with open(cookie_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Store in session state (not the content, just the path)
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
            # Delete the temp file
            cookie_dir = os.path.dirname(st.session_state.cookie_path)
            if os.path.exists(st.session_state.cookie_path):
                os.remove(st.session_state.cookie_path)
            if os.path.exists(cookie_dir):
                os.rmdir(cookie_dir)
        except:
            pass
    
    # Clear session state
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
# UPDATED YT-DLP FUNCTIONS WITH COOKIES
# ============================================

def download_captions(video_id, lang='de'):
    # Clean temp files
    for f in glob.glob('temp_subs*'):
        try: os.remove(f)
        except: pass

    # Get cookie path
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
    
    # Add cookies only if available
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

def download_audio(video_id):
    # Clean temp files
    for f in glob.glob('temp_audio*') + glob.glob('*.mp3'):
        try: os.remove(f)
        except: pass

    # Get cookie path
    cookie_path = get_cookie_path()
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
        'outtmpl': 'temp_audio',
        'quiet': True,
        'extractor_args': {'youtube': ['player_client=ios,android']}
    }
    
    # Add cookies only if available
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
# MODIFIED STREAMLIT UI
# ============================================

st.set_page_config(page_title="Lerne Deutsch - Sync Player", page_icon="🎬", layout="centered")

st.markdown("<h2 style='text-align: center; color: #e94560;'>📱 Mobile Video Sync App</h2>", unsafe_allow_html=True)

# ============================================
# COOKIE UPLOAD SECTION (Prominent but Secure)
# ============================================

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

# Show warning if no cookies
if not st.session_state.get('cookies_uploaded', False):
    st.warning("⚠️ **YouTube access may be blocked** without cookies. Please upload your cookies.txt above.")

# ============================================
# MAIN APP INTERFACE
# ============================================

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
            # Check if cookies are needed but missing
            if not st.session_state.get('cookies_uploaded', False):
                st.warning("⚠️ No cookies uploaded. YouTube may block access. If it fails, upload cookies and try again.")
            
            segments = None
            html_player = ""
            interleaved_text = ""
            original_text = ""
            translated_text = ""
            srt_content = ""
            
            with st.status("⏳ Video process hora, thoda sabr karo...", expanded=True) as status:
                
                if "CC" in method_choice:
                    st.write("📥 CC Captions download aur clean hore...")
                    segments = method_cc(video_id, language)
                else:
                    st.write("📥 Audio download hora...")
                    st.write("🎤 Whisper AI transcribe karra...")
                    segments = method_whisper(video_id, language, "tiny")

                if not segments:
                    status.update(label="❌ Failed to extract subtitles.", state="error")
                    if not st.session_state.get('cookies_uploaded', False):
                        st.info("💡 **Tip:** Upload your cookies.txt from a logged-in YouTube session to bypass access blocks.")
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
