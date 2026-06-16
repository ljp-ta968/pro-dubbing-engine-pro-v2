"""
Professional Dubbing Engine - Upgraded Version
Handles SRT, TXT to SRT conversion, timestamp-aware chunking, parallel TTS generation, and duration validation.
Supports multiple voices (Male/Female), parallel workers, and audio merging.
"""

import re
import asyncio
import edge_tts
from typing import List, Dict, Tuple, Optional
import os
import json
import time
import datetime
from google import genai
from google.genai import types
from pydub import AudioSegment
import io
import numpy as np
from concurrent.futures import ThreadPoolExecutor

class DubbingSegment:
    def __init__(self, start: float, end: float, lang: str, text: str, segment_id: int):
        self.start = start
        self.end = end
        self.duration = end - start
        self.lang = lang
        self.text = text
        self.segment_id = segment_id
        self.tts_audio_path = None
        self.tts_duration = None
        self.adjusted_text = text
        self.adjusted_speed = 1.0
        self.status = "pending"
        self.original_tts_duration = None
        self.final_audio_path = None
        self.retries = 0
        self.sentence_id = None # To group segments into sentences

class DubbingSentence:
    def __init__(self, segments: List[DubbingSegment], sentence_id: int):
        self.segments = segments
        self.sentence_id = sentence_id
        self.start = segments[0].start
        self.end = segments[-1].end
        self.duration = self.end - self.start
        self.text = " ".join([s.text for s in segments])
        self.adjusted_text = self.text
        self.tts_audio_path = None
        self.tts_duration = None
        self.retries = 0
        self.status = "pending"

class ProDubbingEngine:
    def __init__(self, api_keys: List[str] = None, output_language: str = "my", voice_gender: str = "Male"):
        self.tolerance = 0.3  # ±0.3 seconds
        self.api_keys = api_keys if api_keys else []
        self.output_language = output_language.lower()
        self.voice_gender = voice_gender
        self.current_key_index = 0
        self.api_lock = asyncio.Lock() # Lock for thread-safe/async-safe rotation
        
        # Rate limiting state: {key: [timestamp1, timestamp2, ...]}
        self.key_usage = {key: [] for key in self.api_keys}
        self.max_rpm = 9 # Conservative limit to avoid rate limiting issues
        
        self._initialize_voice_map()

    async def _get_next_client(self):
        """Rotate through API keys and return a configured GenAI client with rate limit awareness."""
        if not self.api_keys:
            return None, None
        
        while True:
            async with self.api_lock: # Ensure parallel tasks don't pick the same key simultaneously
                attempts = 0
                while attempts < len(self.api_keys):
                    key = self.api_keys[self.current_key_index]
                    self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
                    attempts += 1
                    
                    now = time.time()
                    # Clean up old timestamps (older than 60s)
                    self.key_usage[key] = [t for t in self.key_usage[key] if now - t < 60]
                    
                    if len(self.key_usage[key]) < self.max_rpm:
                        # Key is available
                        self.key_usage[key].append(now)
                        client = genai.Client(api_key=key)
                        return client
            
            # All keys are at limit, wait a bit and loop
            print("All API keys are at rate limit. Waiting 5 seconds...")
            await asyncio.sleep(5)

    def _initialize_voice_map(self):
        # Voice mapping with Male/Female options
        self.voice_map = {
            "my": {"Male": "my-MM-ThihaNeural", "Female": "my-MM-NilarNeural"},
            "en": {"Male": "en-US-GuyNeural", "Female": "en-US-AvaNeural"},
            "ja": {"Male": "ja-JP-KeitaNeural", "Female": "ja-JP-NanamiNeural"},
            "ko": {"Male": "ko-KR-InJoonNeural", "Female": "ko-KR-SunHiNeural"},
            "th": {"Male": "th-TH-NiwatNeural", "Female": "th-TH-PremwadeeNeural"},
            "vi": {"Male": "vi-VN-NamMinhNeural", "Female": "vi-VN-HoaiMyNeural"}
        }

    def _time_to_seconds(self, time_str: str) -> float:
        """Convert HH:MM:SS,ms or MM:SS to seconds"""
        time_str = time_str.replace(',', '.').strip('[] ')
        parts = time_str.split(':')
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(time_str)

    def _seconds_to_time(self, seconds: float) -> str:
        """Convert seconds to HH:MM:SS,ms"""
        td = datetime.timedelta(seconds=seconds)
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds_int = divmod(remainder, 60)
        milliseconds = int((seconds - total_seconds) * 1000)
        return f"{hours:02}:{minutes:02}:{seconds_int:02},{milliseconds:03}"

    def _get_audio_duration(self, audio_path: str) -> float:
        """Get duration of an audio file using pydub."""
        try:
            audio = AudioSegment.from_file(audio_path)
            return len(audio) / 1000.0  # duration in seconds
        except Exception as e:
            print(f"Error getting audio duration for {audio_path}: {e}")
            return 0.0

    def _adjust_audio_speed(self, audio_path: str, target_duration: float, output_path: str) -> bool:
        """Adjust audio speed to match target duration."""
        try:
            audio = AudioSegment.from_file(audio_path)
            current_duration = len(audio) / 1000.0
            if current_duration == 0:
                return False
            
            speed_factor = current_duration / target_duration
            
            # Limit speed adjustment to reasonable range (0.5x to 2.0x)
            speed_factor = max(0.5, min(2.0, speed_factor))
            
            # Apply speed adjustment
            # pydub's speedup is a bit crude, but works for small adjustments
            adjusted_audio = audio.speedup(playback_speed=speed_factor)
            
            # Normalize volume
            adjusted_audio = adjusted_audio.normalize()

            adjusted_audio.export(output_path, format="mp3", bitrate="192k")
            return True
        except Exception as e:
            print(f"Error adjusting audio speed for {audio_path}: {e}")
            return False

    def parse_srt(self, srt_content: str) -> List[DubbingSegment]:
        """Parse SRT content into DubbingSegments"""
        segments = []
        # Support various SRT formats and line endings
        pattern = r'(\d+)\s+(\d{2}:\d{2}:\d{2}[,. ]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[,. ]\d{3})\s+(.*?)(?=\n\n|\r\n\r\n|\n\d+\n|\r\n\d+\r\n|$)'
        matches = re.finditer(pattern, srt_content, re.DOTALL)
        
        for i, match in enumerate(matches):
            start_s = self._time_to_seconds(match.group(2))
            end_s = self._time_to_seconds(match.group(3))
            text = match.group(4).replace('\n', ' ').replace('\r', '').strip()
            
            segments.append(DubbingSegment(
                start=start_s,
                end=end_s,
                lang=self.output_language,
                text=text,
                segment_id=i
            ))
        return segments

    def group_segments_into_sentences(self, segments: List[DubbingSegment]) -> List[DubbingSentence]:
        """Group segments based on sentence-ending punctuation."""
        sentences = []
        current_batch = []
        sentence_id = 1
        
        # Sentence ending markers for various languages
        end_markers = r'[.!?။၊၊]' # Includes Myanmar markers
        
        for seg in segments:
            current_batch.append(seg)
            # Check if the text ends with a sentence marker
            if re.search(end_markers + r'\s*$', seg.text) or seg == segments[-1]:
                sentence = DubbingSentence(current_batch, sentence_id)
                for s in current_batch:
                    s.sentence_id = sentence_id
                sentences.append(sentence)
                current_batch = []
                sentence_id += 1
                
        return sentences

    async def translate_batch(self, text: str, target_lang: str) -> str:
        """Translate text using Gemini in batch mode with Numbered Line System and Retry logic."""
        max_retries = 3
        retry_delay = 2
        
        # Prepare numbered input to force line-by-line translation
        input_lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
        numbered_input = "\n".join([f"L{i+1}: {line}" for i, line in enumerate(input_lines)])
        
        # Dynamic Token Calculation
        # Rule: Word count * 12, clamped between 10,000 and 65,536
        word_count = len(text.split())
        dynamic_tokens = max(10000, min(65536, word_count * 12))
        
        config = types.GenerateContentConfig(
            max_output_tokens=dynamic_tokens,
            temperature=0.7
        )
        
        prompt = f"""You are a professional translator. Translate the following numbered lines into {target_lang}.

### STRICT RULES:
1. Your response MUST start directly with 'L1:' followed by the translation.
2. DO NOT include any introductory text, thinking process, explanations, notes, or concluding remarks.
3. Maintain the exact line markers (L1:, L2:, etc.) for every single line.
4. Do not merge lines. Every input line must have exactly one corresponding output line.
5. Translate all {len(input_lines)} lines without skipping any.
"""
        
        for attempt in range(max_retries):
            client = await self._get_next_client()
            if not client:
                return "Error: No API keys."

            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model='gemini-3.5-flash',
                    contents=f"{prompt}\n\n{numbered_input}",
                    config=config
                )
                translated_raw = response.text.strip()
                
                # Robust Parsing Logic:
                # 1. AI might repeat blocks or add conversational chatter.
                # 2. We split by markers and take only the first relevant line of text for each marker.
                
                output_lines = [f"[Line {i+1} Translation Missing]" for i in range(len(input_lines))]
                
                # Split the raw output by marker patterns (e.g., L1:, L2 -, etc.)
                parts = re.split(r"(L\d+[:\-\.\s]+)", translated_raw)
                
                # parts[0] is text before L1. Subsequent parts are [marker, text, marker, text, ...]
                for i in range(1, len(parts), 2):
                    marker_part = parts[i]
                    text_part = parts[i+1]
                    
                    try:
                        # Extract the line number from the marker (e.g., "L123" -> 123)
                        line_match = re.search(r"\d+", marker_part)
                        if line_match:
                            line_num = int(line_match.group())
                            if 1 <= line_num <= len(input_lines):
                                # Take only the first line of the text part to avoid AI chatter/notes
                                clean_text = text_part.strip().split('\n')[0].strip()
                                # If AI repeats a line, the latest one in the response will be used
                                output_lines[line_num - 1] = clean_text
                    except (ValueError, IndexError):
                        continue
                
                return "\n".join(output_lines)

            except Exception as e:
                error_msg = str(e)
                if "503" in error_msg or "UNAVAILABLE" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        print(f"Server 503 error. Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait_time)
                        continue
                return f"Error: {error_msg}"
        return "Error: Maximum retries reached."

    def reconstruct_srt_with_translation(self, original_segments: List[DubbingSegment], translated_text: str) -> str:
        """Reconstruct SRT using original timestamps and translated text lines."""
        # Split translated text into lines, matching the number of original segments
        translated_lines = [l.strip() for l in translated_text.strip().split('\n') if l.strip()]
        
        srt_out = []
        for i, seg in enumerate(original_segments):
            text = translated_lines[i] if i < len(translated_lines) else seg.text
            start_t = self._seconds_to_time(seg.start)
            end_t = self._seconds_to_time(seg.end)
            # Standard SRT format: Index, Timestamp, Text, followed by a blank line
            srt_block = f"{i+1}\n{start_t} --> {end_t}\n{text}\n"
            srt_out.append(srt_block)
        
        # Join with a single newline because each block already ends with a newline
        return "\n".join(srt_out)

    async def _rewrite_text_with_ai(self, original_text: str, target_duration: float, current_tts_duration: float, lang: str) -> str:
        """Use Gemini AI to rewrite text to better fit target duration with Retry logic."""
        max_retries = 3
        retry_delay = 2

        duration_diff = current_tts_duration - target_duration
        if duration_diff > 0: # TTS is too long, need to shorten text
            prompt = f"""
            The following {lang} text was spoken in {current_tts_duration:.2f} seconds, but it needs to fit into {target_duration:.2f} seconds. 
            Please rewrite the text to be shorter, while retaining its original meaning as much as possible. 
            Do not add any introductory or concluding phrases. Just provide the rewritten text.
            Original text: {original_text}
            Rewritten text:
            """
        else: # TTS is too short, need to lengthen text
            prompt = f"""
            The following {lang} text was spoken in {current_tts_duration:.2f} seconds, but it needs to be {target_duration:.2f} seconds long. 
            Please rewrite the text to be slightly longer, adding natural pauses or descriptive words, while retaining its original meaning as much as possible. 
            Do not add any introductory or concluding phrases. Just provide the rewritten text.
            Original text: {original_text}
            Rewritten text:
            """
        config = types.GenerateContentConfig(
            max_output_tokens=5000, # Fixed size for short rewrites
            temperature=0.7
        )
        for attempt in range(max_retries):
            client = await self._get_next_client()
            if not client:
                return original_text

            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model='gemini-3.5-flash',
                    contents=prompt,
                    config=config
                )
                rewritten_text = response.text.strip()
                # Basic cleanup of potential AI conversational filler
                if rewritten_text.lower().startswith("rewritten text:"):
                    rewritten_text = rewritten_text[len("rewritten text:"):].strip()
                return rewritten_text
            except Exception as e:
                error_msg = str(e)
                if "503" in error_msg or "UNAVAILABLE" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        print(f"Server 503 error in rewrite. Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait_time)
                        continue
                print(f"AI rewrite failed: {error_msg}")
                return original_text
        return original_text

    async def generate_tts_for_sentence(self, sentence: DubbingSentence, output_dir: str, status_callback=None) -> bool:
        """Generate TTS for a full sentence with iterative text rewriting and speed adjustment."""
        target_duration = sentence.duration
        sentence.retries = 0
        max_ai_retries = 3 

        while True:
            try:
                if status_callback:
                    status_callback(sentence.sentence_id, f"Processing (Attempt {sentence.retries + 1})")
                
                lang_voices = self.voice_map.get(self.output_language, self.voice_map["my"])
                voice = lang_voices.get(self.voice_gender, lang_voices["Male"])
                
                temp_output_path = os.path.join(output_dir, f"temp_sent_{sentence.sentence_id}.mp3")
                try:
                    communicate = edge_tts.Communicate(sentence.adjusted_text, voice)
                    await communicate.save(temp_output_path)
                except Exception as e:
                    print(f"Edge-TTS failed: {e}")
                    sentence.retries += 1
                    if sentence.retries >= max_ai_retries:
                        return False
                    await asyncio.sleep(1)
                    continue
                
                tts_duration = self._get_audio_duration(temp_output_path)
                sentence.tts_duration = tts_duration

                if tts_duration > 0 and (abs(tts_duration - target_duration) <= self.tolerance or sentence.retries >= max_ai_retries):
                    final_output_path = os.path.join(output_dir, f"sent_{sentence.sentence_id}.mp3")
                    
                    # Final speed adjustment if still out of tolerance
                    if abs(tts_duration - target_duration) > self.tolerance:
                        self._adjust_audio_speed(temp_output_path, target_duration, final_output_path)
                    else:
                        os.rename(temp_output_path, final_output_path)
                    
                    sentence.tts_audio_path = final_output_path
                    sentence.status = "completed"
                    return True
                
                # If not within tolerance, rewrite and try again
                sentence.adjusted_text = await self._rewrite_text_with_ai(
                    sentence.text, target_duration, tts_duration, self.output_language
                )
                sentence.retries += 1
                
            except Exception as e:
                print(f"Sentence processing error: {e}")
                return False

    async def process_workflow_parallel(self, segments: List[DubbingSegment], num_workers: int, output_dir: str, status_callback=None) -> Dict:
        """Process sentences in parallel."""
        sentences = self.group_segments_into_sentences(segments)
        semaphore = asyncio.Semaphore(num_workers)
        
        async def worker(sentence):
            async with semaphore:
                return await self.generate_tts_for_sentence(sentence, output_dir, status_callback)

        tasks = [worker(s) for s in sentences]
        results = await asyncio.gather(*tasks)
        
        # Distribute sentence results back to segments
        for sentence in sentences:
            if sentence.tts_audio_path:
                for seg in sentence.segments:
                    seg.tts_audio_path = sentence.tts_audio_path
                    seg.status = "completed"
        
        return {
            "total_sentences": len(sentences),
            "completed": sum(1 for r in results if r),
            "segments": [
                {"id": s.segment_id, "start": s.start, "end": s.end, "text": s.text, "status": s.status}
                for s in segments
            ]
        }

    def merge_audio_files(self, segments: List[DubbingSegment], output_path: str) -> bool:
        """Merge individual segment audios into one file with precise timing."""
        try:
            if not segments:
                return False
            
            # Create silence for the total duration
            total_duration_ms = int(segments[-1].end * 1000)
            combined = AudioSegment.silent(duration=total_duration_ms)
            
            processed_sentences = set()
            
            for seg in segments:
                if seg.sentence_id in processed_sentences:
                    continue
                
                if seg.tts_audio_path and os.path.exists(seg.tts_audio_path):
                    audio = AudioSegment.from_file(seg.tts_audio_path)
                    sentence_start_ms = int(seg.start * 1000)
                    combined = combined.overlay(audio, position=sentence_start_ms)
                    processed_sentences.add(seg.sentence_id)
            
            combined.export(output_path, format="mp3", bitrate="192k")
            return True
        except Exception as e:
            print(f"Error merging audio: {e}")
            return False

    def generate_srt_content(self, segments: List[DubbingSegment]) -> str:
        """Generate final SRT content."""
        srt_out = []
        for i, seg in enumerate(segments):
            start_t = self._seconds_to_time(seg.start)
            end_t = self._seconds_to_time(seg.end)
            # Standard SRT format: Index, Timestamp, Text, followed by a blank line
            srt_out.append(f"{i+1}\n{start_t} --> {end_t}\n{seg.text}\n")
        return "\n".join(srt_out)
