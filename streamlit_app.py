import streamlit as st
import os
import asyncio
import re
import shutil
import json
import time
import importlib
import pro_dubbing_engine
importlib.reload(pro_dubbing_engine)
from pro_dubbing_engine import ProDubbingEngine
import tempfile
import nest_asyncio

# Apply nest_asyncio for Streamlit
nest_asyncio.apply()

st.set_page_config(page_title="Pro Dubbing Engine V2", page_icon="🎙️", layout="wide")

st.title("🎙️ Pro Dubbing Engine - Professional Workflow")
st.markdown("---")

# Initialize Session State
if 'step' not in st.session_state:
    st.session_state.step = 1
if 'script_content' not in st.session_state:
    st.session_state.script_content = ""
if 'translated_script' not in st.session_state:
    st.session_state.translated_script = ""
if 'final_srt' not in st.session_state:
    st.session_state.final_srt = ""
if 'segments' not in st.session_state:
    st.session_state.segments = []
if 'worker_statuses' not in st.session_state:
    st.session_state.worker_statuses = {}
if 'results' not in st.session_state:
    st.session_state.results = None
if 'merged_audio_data' not in st.session_state:
    st.session_state.merged_audio_data = None
if 'generated_srt_content' not in st.session_state:
    st.session_state.generated_srt_content = ""
if 'selected_lang' not in st.session_state:
    st.session_state.selected_lang = "my"
if 'logs' not in st.session_state:
    st.session_state.logs = []

# Function to add logs
def add_log(message):
    timestamp = time.strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{timestamp}] {message}")
    if len(st.session_state.logs) > 50:
        st.session_state.logs.pop(0)

# Try to get API keys from secrets
secret_api_keys = st.secrets.get("GEMINI_API_KEYS", [])
if not secret_api_keys:
    single_key = st.secrets.get("GEMINI_API_KEY", "")
    if single_key:
        secret_api_keys = [single_key]

# Sidebar for settings
with st.sidebar:
    st.header("⚙️ Settings")
    
    if secret_api_keys:
        st.success(f"✅ {len(secret_api_keys)} API Keys loaded")
        api_keys_input = ",".join(secret_api_keys)
    else:
        api_keys_input = st.text_area("Gemini API Keys (Comma separated)")
    
    api_keys = [k.strip() for k in api_keys_input.split(",") if k.strip()]
    
    st.divider()
    st.subheader("📊 Detailed Logs")
    log_container = st.empty()
    
    def refresh_logs():
        log_text = "\n".join(st.session_state.logs[::-1])
        log_container.code(log_text, language="text")

    st.divider()
    st.subheader("👷 Worker Status")
    status_container = st.empty()
    
    def update_status(worker_id, message):
        st.session_state.worker_statuses[worker_id] = message
        status_text = ""
        for wid in sorted(st.session_state.worker_statuses.keys()):
            status_text += f"**Worker {wid}**: {st.session_state.worker_statuses[wid]}\n\n"
        status_container.markdown(status_text)

# Initialize engine
if 'engine' not in st.session_state or not hasattr(st.session_state.engine, 'translate_batch'):
    st.session_state.engine = ProDubbingEngine(api_keys=api_keys if api_keys else [])
engine = st.session_state.engine

if api_keys:
    engine.api_keys = api_keys

# Main UI Logic
if st.session_state.step == 1:
    st.subheader("Step 1: Input & Batch Translation")
    
    col1, col2 = st.columns(2)
    with col1:
        input_type = st.radio("Select Input Type:", ["Text Input", "File Upload (.srt / .txt)"])
        if input_type == "Text Input":
            st.session_state.script_content = st.text_area("Paste your script with timestamps here:", height=300, 
                                                        value=st.session_state.script_content,
                                                        placeholder="[00:00:00] Hello...\n[00:00:02] Welcome...")
        else:
            uploaded_file = st.file_uploader("Upload .srt or .txt file", type=["srt", "txt"])
            if uploaded_file:
                st.session_state.script_content = uploaded_file.read().decode("utf-8")
                add_log(f"File '{uploaded_file.name}' uploaded.")

        lang_options = {
            "Myanmar (Burmese)": "my",
            "English": "en",
            "Japanese": "ja",
            "Korean": "ko",
            "Thai": "th",
            "Vietnamese": "vi"
        }
        selected_lang_name = st.selectbox("Select Output Language:", list(lang_options.keys()), index=0)
        st.session_state.selected_lang = lang_options[selected_lang_name]

        if st.button("🔍 1. Start Translation", use_container_width=True):
            if not st.session_state.script_content:
                st.error("Please provide input text or file.")
            else:
                add_log(f"Starting translation to {selected_lang_name}...")
                start_time = time.time()
                
                timer_placeholder = st.empty()
                with st.spinner("AI is translating..."):
                    lines = [re.sub(r'\[.*?\]', '', l).strip() for l in st.session_state.script_content.split('\n') if l.strip()]
                    clean_text = "\n".join(lines)
                    
                    # Fix: Use asyncio.run with a wrapper to avoid loop issues in Streamlit
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        # Use a separate thread for the timer to avoid blocking
                        import threading
                        is_done = False
                        def update_timer():
                            while not is_done:
                                elapsed = time.time() - start_time
                                timer_placeholder.markdown(f"### ⏱️ Elapsed Time: `{elapsed:.2f}s`")
                                time.sleep(0.1)
                        
                        t = threading.Thread(target=update_timer)
                        t.start()
                        
                        translated = loop.run_until_complete(engine.translate_batch(clean_text, selected_lang_name))
                        is_done = True
                        t.join()
                        
                        st.session_state.translated_script = translated
                        elapsed_final = time.time() - start_time
                        timer_placeholder.success(f"✅ Finished in {elapsed_final:.2f}s")
                        add_log(f"Translation completed.")
                        refresh_logs()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
                        add_log(f"Error during translation: {str(e)}")

    with col2:
        st.write("**Translation Output:**")
        st.session_state.translated_script = st.text_area("Review Translated Text:", 
                                                        value=st.session_state.translated_script, 
                                                        height=450)
        
        if st.button("🚀 2. Finalize & Preserve Timestamps ➡️", use_container_width=True):
            if not st.session_state.translated_script:
                st.error("Please translate first.")
            else:
                add_log("Reconstructing SRT with original timestamps...")
                # Parse original to get timestamps
                original_segments = engine.parse_srt(st.session_state.script_content)
                if not original_segments and "[" in st.session_state.script_content:
                    lines = [l.strip() for l in st.session_state.script_content.split('\n') if l.strip()]
                    for i, line in enumerate(lines):
                        match = re.search(r'\[?(\d{2}:\d{2}:\d{2})\]?', line)
                        if match:
                            start_s = engine._time_to_seconds(match.group(1))
                            end_s = start_s + 3.0 
                            original_segments.append(pro_dubbing_engine.DubbingSegment(start_s, end_s, "en", line, i))

                st.session_state.final_srt = engine.reconstruct_srt_with_translation(original_segments, st.session_state.translated_script)
                st.session_state.segments = engine.parse_srt(st.session_state.final_srt)
                
                add_log(f"SRT Reconstructed.")
                st.session_state.step = 2
                st.rerun()

elif st.session_state.step == 2:
    st.subheader("Step 2: Preview & Grouping")
    
    st.write("**Standard SRT Preview (Original Timestamps Preserved):**")
    st.code(st.session_state.final_srt, language="srt")

    if st.button("Confirm & Group into Sentences ➡️", use_container_width=True):
        add_log("Grouping segments into sentences...")
        st.session_state.sentences = engine.group_segments_into_sentences(st.session_state.segments)
        add_log(f"Grouped into {len(st.session_state.sentences)} sentences.")
        st.session_state.step = 3
        st.rerun()
    
    if st.button("⬅️ Back to Step 1"):
        st.session_state.step = 1
        st.rerun()

elif st.session_state.step == 3:
    st.subheader("Step 3: Professional Dubbing")
    
    col_v, col_w = st.columns(2)
    with col_v:
        selected_gender = st.selectbox("Select Voice Gender:", ["Male", "Female"], index=0)
    with col_w:
        num_chunks = st.slider("Parallel Workers:", 1, 10, 5)

    if st.button("🚀 Start Dubbing Process", use_container_width=True):
        engine.output_language = st.session_state.selected_lang
        engine.voice_gender = selected_gender
        
        add_log(f"Starting Dubbing with {num_chunks} workers...")
        start_time = time.time()
        
        timer_placeholder = st.empty()
        with st.spinner("Generating TTS & Merging..."):
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                import threading
                is_done = False
                def update_timer_dub():
                    while not is_done:
                        elapsed = time.time() - start_time
                        timer_placeholder.markdown(f"### ⏱️ Total Elapsed Time: `{elapsed:.2f}s`")
                        time.sleep(0.1)
                
                t = threading.Thread(target=update_timer_dub)
                t.start()

                async def main_workflow():
                    st.session_state.worker_statuses = {i+1: "Idle" for i in range(num_chunks)}
                    update_status(0, "")

                    with tempfile.TemporaryDirectory() as tmp_dir:
                        def ui_callback(worker_id, msg):
                            update_status(worker_id, msg)
                            add_log(f"Worker {worker_id}: {msg}")

                        results = await engine.process_workflow_parallel(st.session_state.segments, num_chunks, tmp_dir, status_callback=ui_callback)
                        st.session_state.results = results

                        add_log("Merging audio files...")
                        merged_audio_path = os.path.join(tmp_dir, "dubbed_audio.mp3")
                        if engine.merge_audio_files(st.session_state.segments, merged_audio_path):
                            with open(merged_audio_path, "rb") as f:
                                st.session_state.merged_audio_data = f.read()
                            st.session_state.generated_srt_content = engine.generate_srt_content(st.session_state.segments)
                            add_log("Audio merging completed.")

                loop.run_until_complete(main_workflow())
                is_done = True
                t.join()
                
                elapsed_final = time.time() - start_time
                timer_placeholder.success(f"✅ Dubbing Completed in {elapsed_final:.2f}s")
                refresh_logs()
            except Exception as e:
                st.error(f"Error: {str(e)}")
                add_log(f"Error during dubbing: {str(e)}")

    if st.button("⬅️ Back to Step 2"):
        st.session_state.step = 2
        st.rerun()

    if st.session_state.merged_audio_data:
        st.divider()
        st.subheader("📥 Download Results")
        col1, col2 = st.columns(2)
        with col1:
            st.audio(st.session_state.merged_audio_data, format="audio/mp3")
            st.download_button("⬇️ Download Audio (MP3)", st.session_state.merged_audio_data, "dubbed_audio.mp3", "audio/mpeg", use_container_width=True)
        with col2:
            st.download_button("⬇️ Download Adjusted SRT", st.session_state.generated_srt_content, "dubbed_subtitles.srt", "text/plain", use_container_width=True)

    if st.button("🔄 Start New Project"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# Initial log refresh
refresh_logs()
