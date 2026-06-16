# Pro Dubbing Engine - Workflow Explanation

ဤ `pro-dubbing-engine-pro-cloned` repository သည် အသံသွင်းခြင်း (dubbing) လုပ်ငန်းစဉ်ကို အလိုအလျောက်လုပ်ဆောင်ရန် ဒီဇိုင်းထုတ်ထားသော Streamlit web application တစ်ခုဖြစ်သည်။ ၎င်းသည် စာသား input မှစ၍ အသံဖိုင် ထုတ်လုပ်ခြင်းအထိ အဆင့်ဆင့် လုပ်ဆောင်ပါသည်။

## အဓိက အစိတ်အပိုင်းများ

1.  **`streamlit_app.py`**: ၎င်းသည် user interface (UI) ကို တည်ဆောက်ပြီး user input များကို လက်ခံကာ `ProDubbingEngine` class မှ လုပ်ဆောင်ချက်များကို ခေါ်ယူအသုံးပြုပါသည်။
2.  **`pro_dubbing_engine.py`**: ၎င်းသည် dubbing လုပ်ငန်းစဉ်၏ core logic အားလုံးကို ထိန်းချုပ်ထားသော class ဖြစ်သည်။ SRT parsing, TTS generation, AI text rewriting, audio merging နှင့် parallel processing စသည်တို့ကို ဤဖိုင်တွင် အဓိကထား ရေးသားထားပါသည်။

## Workflow အဆင့်ဆင့်

`Pro Dubbing Engine` ၏ အဓိက workflow အဆင့်ဆင့်ကို အောက်ပါအတိုင်း ဖော်ပြထားပါသည်။

### အဆင့် ၁: Input လက်ခံခြင်း (Input Reception)

*   **Input Type**: User သည် input ကို Text Area မှ တိုက်ရိုက်ထည့်သွင်းနိုင်သည် သို့မဟုတ် `.srt` သို့မဟုတ် `.txt` ဖိုင်ကို upload လုပ်နိုင်သည်။
*   **Timestamp Format**: Input text တွင် `[HH:MM:SS]` ပုံစံ timestamp များ ပါဝင်နိုင်သည်။

### အဆင့် ၂: SRT သို့ ပြောင်းလဲခြင်း (SRT Conversion)

*   **`text_to_srt_with_ai`**: အကယ်၍ input text တွင် SRT format မဟုတ်ဘဲ timestamp များသာ ပါဝင်ပါက၊ `ProDubbingEngine` သည် Google Gemini AI ကို အသုံးပြု၍ ၎င်း text ကို စံ SRT format သို့ ပြောင်းလဲပေးသည်။ ဤအဆင့်တွင် AI သည် စာသားများကို အချိန်နှင့် ကိုက်ညီအောင် စီစဉ်ပေးသည်။
*   **`parse_srt`**: AI မှ ပြောင်းလဲပေးသော SRT သို့မဟုတ် user မှ ပေးပို့သော SRT ဖိုင်ကို `DubbingSegment` objects များအဖြစ် ခွဲခြမ်းစိတ်ဖြာသည်။ `DubbingSegment` တစ်ခုစီတွင် စတင်ချိန်၊ ပြီးဆုံးချိန်၊ စာသားနှင့် ID များ ပါဝင်သည်။

### အဆင့် ၃: စာကြောင်းများအဖြစ် စုစည်းခြင်း (Sentence Grouping)

*   **`group_segments_into_sentences`**: `DubbingSegment` များကို စာကြောင်းအဆုံးသတ် အမှတ်အသားများ (ဥပမာ: `.`, `!`, `?`, `။`, `၊`) အပေါ်မူတည်၍ `DubbingSentence` objects များအဖြစ် စုစည်းသည်။ ၎င်းသည် AI ဖြင့် စာသားပြန်လည်ပြင်ဆင်ရာတွင် စာကြောင်းအလိုက် လုပ်ဆောင်နိုင်ရန် အထောက်အကူပြုသည်။

### အဆင့် ၄: Parallel TTS Generation (Parallel Text-to-Speech Generation)

*   **`process_workflow_parallel`**: ဤသည်မှာ workflow ၏ အဓိက အစိတ်အပိုင်းဖြစ်သည်။
    *   `DubbingSentence` များကို worker အရေအတွက်အလိုက် chunks များအဖြစ် ခွဲခြမ်းသည်။
    *   `asyncio.gather` ကို အသုံးပြု၍ `process_sentence_chunk` function ကို worker များအလိုက် parallel (တစ်ပြိုင်နက်တည်း) လုပ်ဆောင်စေသည်။
    *   `status_callback` ကို အသုံးပြု၍ worker တစ်ခုစီ၏ လက်ရှိအခြေအနေကို UI တွင် ပြသသည်။
*   **`process_sentence_chunk`**: Worker တစ်ခုစီသည် ၎င်းတို့၏ သက်ဆိုင်ရာ sentence chunk အတွင်းရှိ စာကြောင်းများကို တစ်ခုပြီးတစ်ခု လုပ်ဆောင်သည်။
*   **`generate_tts_for_sentence`**: စာကြောင်းတစ်ခုစီအတွက် TTS အသံဖိုင် ထုတ်လုပ်ခြင်းကို ဤ function မှ လုပ်ဆောင်သည်။
    *   **AI Text Rewriting**: `edge_tts` မှ ထုတ်လုပ်လိုက်သော အသံဖိုင်၏ ကြာချိန်သည် မူလ segment ၏ ကြာချိန်နှင့် မကိုက်ညီပါက (သတ်မှတ်ထားသော `tolerance` အတွင်း မရှိပါက) Google Gemini AI ကို အသုံးပြု၍ စာသားကို ပြန်လည်ပြင်ဆင်စေသည်။ ၎င်းသည် အသံဖိုင်၏ ကြာချိန်ကို မူလ segment နှင့် ကိုက်ညီစေရန် ရည်ရွယ်သည်။
    *   **Retry Logic**: AI Text Rewriting သို့မဟုတ် TTS Generation လုပ်ငန်းစဉ်တွင် error တစ်ခုခု ဖြစ်ပေါ်ပါက `max_ai_retries` (၅၀ ကြိမ်) အထိ ပြန်လည်ကြိုးစားသည်။ Error ဖြစ်ပါက retry counter ကို တိုးမြှင့်ပြီး ၂ စက္ကန့်ခန့် စောင့်ဆိုင်းပြီးမှ ပြန်လည်ကြိုးစားသည်။
    *   **Audio Speed Adjustment**: AI ဖြင့် စာသားပြင်ဆင်ပြီးနောက်에도 ကြာချိန် မကိုက်ညီသေးပါက `_adjust_audio_speed` function ကို အသုံးပြု၍ အသံဖိုင်၏ speed ကို ချိန်ညှိပေးသည်။
    *   **Segment Audio Splitting**: စာကြောင်းတစ်ခုအတွက် TTS အသံဖိုင် ထုတ်လုပ်ပြီးပါက ၎င်းကို မူလ `DubbingSegment` များ၏ ကြာချိန်အလိုက် အသံဖိုင်ငယ်များအဖြစ် ပြန်လည်ခွဲခြမ်းစိတ်ဖြာပြီး `tts_audio_path` ကို သတ်မှတ်ပေးသည်။

### အဆင့် ၅: Audio File များ ပေါင်းစည်းခြင်း (Audio Merging)

*   **`merge_audio_files`**: `process_workflow_parallel` ပြီးဆုံးသွားသောအခါ၊ အောင်မြင်စွာ ထုတ်လုပ်ထားသော `DubbingSegment` များ၏ audio file များကို `segment_id` အလိုက် စီစဉ်ပြီး တစ်ခုတည်းသော `dubbed_audio.mp3` အဖြစ် ပေါင်းစည်းသည်။ မူလ segment များ၏ အချိန်ကိုက်ညီမှုအတွက် လိုအပ်ပါက silence (အသံတိတ်) များကို ထည့်သွင်းပေးသည်။

### အဆင့် ၆: SRT Content ထုတ်လုပ်ခြင်း (SRT Content Generation)

*   **`generate_srt_content`**: ပြင်ဆင်ထားသော `DubbingSegment` များမှ အချက်အလက်များကို အသုံးပြု၍ နောက်ဆုံး SRT content ကို ပြန်လည်ထုတ်လုပ်သည်။ ဤအဆင့်တွင် `seg.adjusted_text` ကို အသုံးပြု၍ SRT ဖိုင်ကို တည်ဆောက်သည်။

### အဆင့် ၇: ရလဒ်များ ပြသခြင်းနှင့် Download (Display Results & Download)

*   **UI Update**: Streamlit UI တွင် Total Process Time, Successful Segments အရေအတွက်နှင့် Detailed Segment Status (ဇယားပုံစံ) များကို ပြသသည်။
*   **Download Options**: User သည် ပေါင်းစည်းထားသော Audio File (MP3) ကို တိုက်ရိုက် download လုပ်နိုင်သည် သို့မဟုတ် SRT ဖိုင်နှင့် Audio ဖိုင်ကို သီးခြားစီ download လုပ်နိုင်သည်။

## အဓိက အသုံးပြုထားသော Libraries များ

*   **`streamlit`**: Web UI တည်ဆောက်ရန်။
*   **`asyncio`**: Asynchronous programming နှင့် parallel processing အတွက်။
*   **`edge_tts`**: Text-to-Speech (TTS) အသံဖိုင်များ ထုတ်လုပ်ရန်။
*   **`google.genai`**: Google Gemini AI API ကို အသုံးပြု၍ စာသားပြင်ဆင်ခြင်းနှင့် SRT conversion အတွက်။
*   **`pydub`**: Audio file များကို ကိုင်တွယ်ခြင်း (duration ရယူခြင်း၊ speed ချိန်ညှိခြင်း၊ merge လုပ်ခြင်း) အတွက်။
*   **`re`**: Regular expressions ကို အသုံးပြု၍ စာသားများ ခွဲခြမ်းစိတ်ဖြာရန်။
*   **`tempfile`**: ယာယီဖိုင်များနှင့် directory များ ဖန်တီးရန်။

ဤ workflow သည် စာသား input မှစ၍ AI ၏ အကူအညီဖြင့် အသံဖိုင်နှင့် SRT ဖိုင်များကို အလိုအလျောက် ထုတ်လုပ်ပေးနိုင်သော ပြည့်စုံသည့် dubbing system တစ်ခုကို တည်ဆောက်ထားပါသည်။
