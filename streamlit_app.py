import streamlit as st
import os
import asyncio
import shutil
import json
import time
from pro_dubbing_engine import ProDubbingEngine
import tempfile
import nest_asyncio

# Apply nest_asyncio for Streamlit
nest_asyncio.apply()

st.set_page_config(page_title="Pro Dubbing Engine V2", page_icon="🎙️", layout="wide")

st.title("🎙️ Pro Dubbing Engine - Optimized Workflow")
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
if 'sentences' not in st.session_state:
    st.session_state.sentences = []
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
if 'timers' not in st.session_state:
    st.session_state.timers = {}

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
        st.success(f"✅ {len(secret_api_keys)} API Keys loaded from Secrets")
        api_keys_input = ",".join(secret_api_keys)
    else:
        api_keys_input = st.text_area("Gemini API Keys (Comma separated)", help="Paste multiple API keys separated by commas for rotation support.")
    
    api_keys = [k.strip() for k in api_keys_input.split(",") if k.strip()]
    
    st.info("💡 Multi-API Support: Using multiple keys helps avoid rate limits.")

    # Sidebar Status Box
    st.divider()
    st.subheader("📊 Worker Status Log")
    status_container = st.empty()
    
    def update_status(worker_id, message):
        st.session_state.worker_statuses[worker_id] = message
        status_text = ""
        for wid in sorted(st.session_state.worker_statuses.keys()):
            status_text += f"**Worker {wid}**: {st.session_state.worker_statuses[wid]}\n\n"
        status_container.markdown(status_text)

# Initialize engine
engine = ProDubbingEngine(api_keys=api_keys if api_keys else [])

# Main UI Logic
if st.session_state.step == 1:
    st.subheader("Step 1: Input & Streaming Translation")
    
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
                st.success(f"File '{uploaded_file.name}' loaded!")

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

        if st.button("🔍 1. Start Streaming Translation", use_container_width=True):
            if not st.session_state.script_content:
                st.error("Please provide input text or file.")
            else:
                st.session_state.translated_script = ""
                placeholder = st.empty()
                
                start_time = time.time()
                with st.spinner("AI is translating in Streaming Mode..."):
                    async def run_streaming():
                        # Extract text without timestamps for translation
                        lines = [re.sub(r'\[.*?\]', '', l).strip() for l in st.session_state.script_content.split('\n') if l.strip()]
                        clean_text = "\n".join(lines)
                        
                        async for chunk in engine.translate_streaming(clean_text, selected_lang_name):
                            st.session_state.translated_script += chunk
                            # Update UI in real-time
                            placeholder.markdown(f"**Live Preview:**\n\n{st.session_state.translated_script}")
                    
                    try:
                        asyncio.run(run_streaming())
                        st.session_state.timers['step1'] = time.time() - start_time
                        st.success(f"✅ Translation completed in {st.session_state.timers['step1']:.2f}s")
                    except Exception as e:
                        st.error(f"AI Error: {str(e)}")

    with col2:
        st.write("**Review & Edit Translation (One line per segment):**")
        st.session_state.translated_script = st.text_area("Final Translated Text:", 
                                                        value=st.session_state.translated_script, 
                                                        height=450)
        
        if st.button("🚀 2. Finalize & Preserve Timestamps ➡️", use_container_width=True):
            if not st.session_state.translated_script:
                st.error("Please translate first.")
            else:
                start_time = time.time()
                # Two-step process: Reconstruct SRT using original timestamps
                # First, parse original to get timestamps
                original_segments = engine.parse_srt(st.session_state.script_content) if "-->" in st.session_state.script_content else []
                if not original_segments:
                    # Fallback for bracket timestamps
                    lines = [l.strip() for l in st.session_state.script_content.split('\n') if l.strip()]
                    for i, line in enumerate(lines):
                        match = re.search(r'\[?(\d{2}:\d{2}:\d{2})\]?', line)
                        if match:
                            start_s = engine._time_to_seconds(match.group(1))
                            # Estimate end time if not available
                            end_s = start_s + 3.0 
                            original_segments.append(engine.DubbingSegment(start_s, end_s, "en", line, i))

                st.session_state.final_srt = engine.reconstruct_srt_with_translation(original_segments, st.session_state.translated_script)
                st.session_state.segments = engine.parse_srt(st.session_state.final_srt)
                st.session_state.timers['step1_reconstruct'] = time.time() - start_time
                st.session_state.step = 2
                st.rerun()

elif st.session_state.step == 2:
    st.subheader("Step 2: Sentence Grouping & Timing Preview")
    
    st.write(f"✅ Reconstructed **{len(st.session_state.segments)}** segments with original timestamps.")
    if 'step1' in st.session_state.timers:
        st.info(f"⏱️ Translation Time: {st.session_state.timers['step1']:.2f}s | Reconstruct Time: {st.session_state.timers['step1_reconstruct']:.2f}s")
    
    with st.expander("Preview Reconstructed SRT (Original Timestamps Preserved)"):
        st.code(st.session_state.final_srt, language="srt")

    if st.button("Group into Sentences ➡️", use_container_width=True):
        start_time = time.time()
        st.session_state.sentences = engine.group_segments_into_sentences(st.session_state.segments)
        st.session_state.timers['step2_grouping'] = time.time() - start_time
        st.session_state.step = 3
        st.rerun()
    
    if st.button("⬅️ Back to Step 1"):
        st.session_state.step = 1
        st.rerun()

elif st.session_state.step == 3:
    st.subheader("Step 3: Professional Dubbing")
    
    st.write(f"✅ Grouped into **{len(st.session_state.sentences)}** sentences.")
    if 'step2_grouping' in st.session_state.timers:
        st.info(f"⏱️ Grouping Time: {st.session_state.timers['step2_grouping']:.2f}s")
    
    col_v, col_w = st.columns(2)
    with col_v:
        selected_gender = st.selectbox("Select Voice Gender:", ["Male", "Female"], index=0)
    with col_w:
        num_chunks = st.slider("Parallel Workers:", 1, 10, 5)

    if st.button("🚀 Start Dubbing Process", use_container_width=True):
        engine.output_language = st.session_state.selected_lang
        engine.voice_gender = selected_gender
        
        start_time = time.time()
        timer_placeholder = st.empty()
        
        with st.spinner("Processing TTS..."):
            async def main_workflow():
                st.session_state.worker_statuses = {i+1: "Idle" for i in range(num_chunks)}
                update_status(0, "")

                with tempfile.TemporaryDirectory() as tmp_dir:
                    def ui_callback(worker_id, msg):
                        update_status(worker_id, msg)

                    results = await engine.process_workflow_parallel(st.session_state.segments, num_chunks, tmp_dir, status_callback=ui_callback)
                    st.session_state.results = results

                    # Merge Audio
                    merged_audio_path = os.path.join(tmp_dir, "dubbed_audio.mp3")
                    if engine.merge_audio_files(st.session_state.segments, merged_audio_path):
                        with open(merged_audio_path, "rb") as f:
                            st.session_state.merged_audio_data = f.read()
                        st.session_state.generated_srt_content = engine.generate_srt_content(st.session_state.segments)
                    
                    st.session_state.timers['step3_total'] = time.time() - start_time

            asyncio.run(main_workflow())
            st.success(f"✅ Completed in {st.session_state.timers['step3_total']:.2f}s")

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
