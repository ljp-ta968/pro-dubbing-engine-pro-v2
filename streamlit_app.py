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

st.title("🎙️ Pro Dubbing Engine - Step-by-Step Workflow")
st.markdown("---")

# Initialize Session State
if 'step' not in st.session_state:
    st.session_state.step = 1
if 'script_content' not in st.session_state:
    st.session_state.script_content = ""
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
    
    st.info("💡 Multi-API Support: Using multiple keys helps avoid rate limits during iterative rewriting.")

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

# Step Tracker UI
step_cols = st.columns(5)
steps = ["1. SRT Prep", "2. Sentence Prep", "3. TTS Generation", "4. Merging", "5. Download"]
for i, s_name in enumerate(steps):
    with step_cols[i]:
        if st.session_state.step == i + 1:
            st.markdown(f"**🔵 {s_name}**")
        elif st.session_state.step > i + 1:
            st.markdown(f"✅ {s_name}")
        else:
            st.markdown(f"⚪ {s_name}")

st.divider()

# Main UI Logic
if st.session_state.step == 1:
    st.subheader("Step 1: SRT Preparation & Language Selection")
    
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

    with col2:
        lang_options = {
            "Myanmar (Burmese)": "my",
            "English": "en",
            "Japanese": "ja",
            "Korean": "ko",
            "Thai": "th",
            "Vietnamese": "vi"
        }
        selected_lang_name = st.selectbox("Select Output Language:", list(lang_options.keys()), index=0)
        engine.output_language = lang_options[selected_lang_name]
        
        selected_gender = st.selectbox("Select Voice Gender:", ["Male", "Female"], index=0)
        engine.voice_gender = selected_gender

        st.info("In this step, the engine will convert your input into a professional SRT format using AI if needed.")
        
        if st.button("Generate SRT ➡️", use_container_width=True):
            if not st.session_state.script_content:
                st.error("Please provide input text or file.")
            else:
                with st.spinner("Converting to SRT..."):
                    async def convert_srt():
                        if "[00:" in st.session_state.script_content and "-->" not in st.session_state.script_content:
                            return await engine.text_to_srt_with_ai(st.session_state.script_content)
                        else:
                            return st.session_state.script_content
                    
                    st.session_state.final_srt = asyncio.run(convert_srt())
                    st.session_state.segments = engine.parse_srt(st.session_state.final_srt)
                    st.session_state.step = 2
                    st.rerun()

elif st.session_state.step == 2:
    st.subheader("Step 2: Sentence Grouping & Preview")
    
    st.write(f"✅ Found **{len(st.session_state.segments)}** segments in SRT.")
    
    with st.expander("Preview SRT Content"):
        st.code(st.session_state.final_srt, language="srt")

    st.info("This step will group short segments into full sentences to improve AI rewriting and natural speech flow.")
    
    if st.button("Group into Sentences ➡️", use_container_width=True):
        st.session_state.sentences = engine.group_segments_into_sentences(st.session_state.segments)
        st.session_state.step = 3
        st.rerun()
    
    if st.button("⬅️ Back to Step 1"):
        st.session_state.step = 1
        st.rerun()

elif st.session_state.step == 3:
    st.subheader("Step 3: Parallel TTS Generation")
    
    st.write(f"✅ Grouped into **{len(st.session_state.sentences)}** sentences.")
    
    max_chunks_limit = 10
    num_chunks = st.slider(
        "Select Number of Parallel Workers:", 
        min_value=1, 
        max_value=min(len(st.session_state.sentences), max_chunks_limit), 
        value=min(len(st.session_state.sentences), 5)
    )

    if st.button("Start TTS Generation 🚀", use_container_width=True):
        start_time = time.time()
        timer_placeholder = st.empty()
        
        with st.spinner("Generating TTS..."):
            async def run_tts():
                # Reset worker statuses
                st.session_state.worker_statuses = {i+1: "Idle" for i in range(num_chunks)}
                
                # We need a temp directory that persists for the next step or we handle it here
                # For step-by-step, we'll use a fixed temp directory or session state to store paths
                temp_dir = tempfile.mkdtemp()
                st.session_state.temp_dir = temp_dir
                
                def ui_callback(worker_id, msg):
                    update_status(worker_id, msg)

                task = asyncio.create_task(engine.process_workflow_parallel(st.session_state.segments, num_chunks, temp_dir, status_callback=ui_callback))
                
                while not task.done():
                    elapsed = time.time() - start_time
                    timer_placeholder.markdown(f"### ⏱️ Running Time: {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")
                    await asyncio.sleep(1)
                
                return await task

            results = asyncio.run(run_tts())
            st.session_state.results = results
            st.session_state.step = 4
            st.rerun()

    if st.button("⬅️ Back to Step 2"):
        st.session_state.step = 2
        st.rerun()

elif st.session_state.step == 4:
    st.subheader("Step 4: Audio Merging")
    
    if st.session_state.results:
        st.write(f"Total Segments: {st.session_state.results['total']} | Successful: {st.session_state.results['successful']}")
    
    st.info("Merging all individual segment audio files into one final MP3 file with proper timing.")
    
    if st.button("Merge Audio 🎵", use_container_width=True):
        with st.spinner("Merging..."):
            merged_audio_path = os.path.join(st.session_state.temp_dir, "dubbed_audio.mp3")
            if engine.merge_audio_files(st.session_state.segments, merged_audio_path):
                with open(merged_audio_path, "rb") as f:
                    st.session_state.merged_audio_data = f.read()
                st.session_state.generated_srt_content = engine.generate_srt_content(st.session_state.segments)
                st.session_state.step = 5
                st.rerun()
            else:
                st.error("❌ Failed to merge audio files. Please check if TTS generation was successful.")

    if st.button("⬅️ Back to Step 3"):
        st.session_state.step = 3
        st.rerun()

elif st.session_state.step == 5:
    st.subheader("Step 5: Download Results")
    
    col1, col2 = st.columns(2)
    with col1:
        st.success("✅ Dubbing process completed successfully!")
        if st.session_state.merged_audio_data:
            st.audio(st.session_state.merged_audio_data, format="audio/mp3")
            st.download_button(
                label="⬇️ Download Final Audio (MP3)",
                data=st.session_state.merged_audio_data,
                file_name="dubbed_audio.mp3",
                mime="audio/mpeg",
                use_container_width=True
            )
    
    with col2:
        if st.session_state.generated_srt_content:
            st.download_button(
                label="⬇️ Download Adjusted SRT",
                data=st.session_state.generated_srt_content,
                file_name="dubbed_subtitles.srt",
                mime="text/plain",
                use_container_width=True
            )
            with st.expander("View Adjusted SRT"):
                st.code(st.session_state.generated_srt_content, language="srt")

    if st.button("🔄 Start New Project"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# Detailed Analytics (Always visible at the bottom if results exist)
if st.session_state.results:
    st.divider()
    st.subheader("📊 Processing Analytics")
    res = st.session_state.results
    
    with st.expander("Detailed Segment Status"):
        st.table(res['segments'])
    
    st.write("**Timeline Visualization**")
    for s in res['segments']:
        status_color = "🟢" if s['status'] in ['tts_generated', 'tts_generated_adjusted'] else "🟡" if 'pending' in s['status'] else "🔴"
        st.text(f"{status_color} [{s['start']:.2f}s - {s['end']:.2f}s] | {s['text'][:100]}...")
