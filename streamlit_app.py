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

st.title("🎙️ Pro Dubbing Engine - Hybrid Workflow")
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

# Main UI Logic
if st.session_state.step == 1:
    st.subheader("Step 1: Input & Translation Preview")
    
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

        if st.button("🔍 1. Preview Translation", use_container_width=True):
            if not st.session_state.script_content:
                st.error("Please provide input text or file.")
            else:
                with st.spinner("AI is translating and formatting..."):
                    async def get_preview():
                        # Await the coroutine to get the client and config
                        client, config = await engine._get_next_client()
                        if not client:
                            raise Exception("No API keys provided.")
                        
                        prompt = f"Translate the following script to {selected_lang_name} while keeping the [HH:MM:SS] timestamps. Return only the translated script."
                        response = await client.models.generate_content(
                            model='gemini-3.5-flash', # Updated to latest model version
                            contents=f"{prompt}\n\n{st.session_state.script_content}",
                            config=config
                        )
                        return response
                    
                    try:
                        response = asyncio.run(get_preview())
                        st.session_state.translated_script = response.text
                    except Exception as e:
                        st.error(f"AI Error: {str(e)}")

    with col2:
        st.write("**Review & Edit Translation:**")
        st.session_state.translated_script = st.text_area("You can manually edit the translation here before generating SRT:", 
                                                        value=st.session_state.translated_script, 
                                                        height=450)
        
        if st.button("🚀 2. Finalize & Generate SRT ➡️", use_container_width=True):
            if not st.session_state.translated_script:
                st.error("Please preview and review translation first.")
            else:
                with st.spinner("Converting to Professional SRT..."):
                    async def convert_srt():
                        # Final conversion to valid SRT format
                        if "[00:" in st.session_state.translated_script and "-->" not in st.session_state.translated_script:
                            return await engine.text_to_srt_with_ai(st.session_state.translated_script)
                        else:
                            return st.session_state.translated_script
                    
                    st.session_state.final_srt = asyncio.run(convert_srt())
                    st.session_state.segments = engine.parse_srt(st.session_state.final_srt)
                    st.session_state.step = 2
                    st.rerun()

elif st.session_state.step == 2:
    st.subheader("Step 2: Sentence Grouping & Preview")
    
    st.write(f"✅ Found **{len(st.session_state.segments)}** segments in SRT.")
    
    with st.expander("Preview Final SRT Content"):
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
    st.subheader("Step 3: Professional Dubbing (One-Click)")
    
    st.write(f"✅ Grouped into **{len(st.session_state.sentences)}** sentences.")
    
    col_v, col_w = st.columns(2)
    with col_v:
        selected_gender = st.selectbox("Select Voice Gender:", ["Male", "Female"], index=0)
    with col_w:
        max_chunks_limit = 10
        num_chunks = st.slider(
            "Select Number of Parallel Workers:", 
            min_value=1, 
            max_value=min(len(st.session_state.sentences), max_chunks_limit), 
            value=min(len(st.session_state.sentences), 5)
        )

    if st.button("🚀 Start Parallel Professional Dubbing", use_container_width=True):
        # Set engine parameters before starting
        engine.output_language = st.session_state.selected_lang
        engine.voice_gender = selected_gender
        
        start_time = time.time()
        timer_placeholder = st.empty()
        
        with st.spinner("Processing TTS and Merging Audio..."):
            async def main_workflow():
                # Reset worker statuses
                st.session_state.worker_statuses = {i+1: "Idle" for i in range(num_chunks)}
                update_status(0, "")

                with tempfile.TemporaryDirectory() as tmp_dir:
                    def ui_callback(worker_id, msg):
                        update_status(worker_id, msg)

                    # Run Parallel TTS
                    task = asyncio.create_task(engine.process_workflow_parallel(st.session_state.segments, num_chunks, tmp_dir, status_callback=ui_callback))
                    
                    while not task.done():
                        elapsed = time.time() - start_time
                        timer_placeholder.markdown(f"### ⏱️ Running Time: {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")
                        await asyncio.sleep(1)
                    
                    results = await task
                    st.session_state.results = results

                    # Merge Audio
                    merged_audio_path = os.path.join(tmp_dir, "dubbed_audio.mp3")
                    if engine.merge_audio_files(st.session_state.segments, merged_audio_path):
                        with open(merged_audio_path, "rb") as f:
                            st.session_state.merged_audio_data = f.read()
                        st.session_state.generated_srt_content = engine.generate_srt_content(st.session_state.segments)
                    
                    elapsed = time.time() - start_time
                    timer_placeholder.markdown(f"### ✅ Total Process Time: {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")

            asyncio.run(main_workflow())
            st.success("✅ Dubbing process completed!")

    if st.button("⬅️ Back to Step 2"):
        st.session_state.step = 2
        st.rerun()

    # Download Section (Visible if results exist)
    if st.session_state.merged_audio_data:
        st.divider()
        st.subheader("📥 Download Results")
        col1, col2 = st.columns(2)
        with col1:
            st.audio(st.session_state.merged_audio_data, format="audio/mp3")
            st.download_button(
                label="⬇️ Download Audio (MP3)",
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
