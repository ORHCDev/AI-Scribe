from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cgi
import json
import logging
import os
import tempfile
import threading
import time

import torch
import whisper
import yaml

from dailylogger import setup_daily_logger

setup_daily_logger(log_dir="logs", log_filename="server.log")
logger = logging.getLogger(__name__)

DEFAULT_MAX_UPLOAD_SIZE = 1024 * 1024 * 1024  # 1 GB
DEFAULT_DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"

with open(r".\configs\config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

FFMPEG_DLL_DIR = config.get("FFMPEG_DLL_DIR")
FFMPEG_DLL_HANDLE = None
if os.name == "nt" and FFMPEG_DLL_DIR and os.path.isdir(FFMPEG_DLL_DIR):
    FFMPEG_DLL_HANDLE = os.add_dll_directory(FFMPEG_DLL_DIR)

WHISPER_API_KEY = config.get("WHISPER_API_KEY")
MAX_UPLOAD_SIZE = config.get("MAX_UPLOAD_SIZE", DEFAULT_MAX_UPLOAD_SIZE)
print("Loaded API key")
logger.info("Loaded API key")

WHISPER_MODEL = config.get("WHISPER_MODEL", "medium")
WHISPER_DEVICE = config.get("WHISPER_DEVICE", "auto")
WHISPER_HF_TOKEN = config.get("WHISPER_HF_TOKEN")
DIARIZATION_MODEL = config.get("WHISPER_DIARIZATION_MODEL", DEFAULT_DIARIZATION_MODEL)
DIARIZATION_NUM_SPEAKERS = config.get("DIARIZATION_NUM_SPEAKERS")
DIARIZATION_MIN_SPEAKERS = config.get("DIARIZATION_MIN_SPEAKERS")
DIARIZATION_MAX_SPEAKERS = config.get("DIARIZATION_MAX_SPEAKERS")

# Initialize Whisper model
print(f"Loading Whisper model '{WHISPER_MODEL}' on device '{WHISPER_DEVICE}'...")
logger.info("Loading Whisper model '%s' on device '%s'...", WHISPER_MODEL, WHISPER_DEVICE)
if WHISPER_DEVICE == "auto":
    model = whisper.load_model(WHISPER_MODEL)
else:
    model = whisper.load_model(WHISPER_MODEL, device=WHISPER_DEVICE)
print("Whisper model loaded successfully")
logger.info("Whisper model loaded successfully")

# Initialize pyannote diarization pipeline (falls back to plain
# transcription if loading fails, e.g. missing HuggingFace token).
diarize_pipeline = None
try:
    from pyannote.audio import Pipeline

    print(f"Loading diarization pipeline '{DIARIZATION_MODEL}'...")
    logger.info("Loading diarization pipeline '%s'...", DIARIZATION_MODEL)
    try:
        diarize_pipeline = Pipeline.from_pretrained(
            DIARIZATION_MODEL, use_auth_token=WHISPER_HF_TOKEN)
    except TypeError:
        # newer pyannote.audio renamed use_auth_token to token
        diarize_pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=WHISPER_HF_TOKEN)
    if WHISPER_DEVICE == "auto":
        diarize_pipeline.to(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    else:
        diarize_pipeline.to(torch.device(WHISPER_DEVICE))
    print("Diarization pipeline loaded successfully")
    logger.info("Diarization pipeline loaded successfully")
except Exception as e:
    print(f"Failed to load diarization pipeline, continuing without diarization: {e}")
    logger.exception("Failed to load diarization pipeline, continuing without diarization")
    diarize_pipeline = None

MODEL_LOCK = threading.Lock() # Whisper
DIARIZE_LOCK = threading.Lock() # pyannote

def _overlap_duration(start: float, end: float, other_start: float, other_end: float) -> float:
    return max(0.0, min(end, other_end) - max(start, other_start))

def extract_turns(diarization) -> list[tuple[float, float, str]]:
    annotation = getattr(diarization, "speaker_diarization", diarization)
    turns = [(turn.start, turn.end, label)
             for turn, _, label in annotation.itertracks(yield_label=True)]
    return sorted(turns)

def _diarization_hints() -> dict[str, int]:
    try:
        if DIARIZATION_NUM_SPEAKERS is not None:
            return {"num_speakers": int(DIARIZATION_NUM_SPEAKERS)}
        hints: dict[str, int] = {}
        if DIARIZATION_MIN_SPEAKERS is not None:
            hints["min_speakers"] = int(DIARIZATION_MIN_SPEAKERS)
        if DIARIZATION_MAX_SPEAKERS is not None:
            hints["max_speakers"] = int(DIARIZATION_MAX_SPEAKERS)
        return hints
    except (TypeError, ValueError):
        logger.warning(
            "Ignoring invalid diarization speaker-count config "
            "(DIARIZATION_NUM_SPEAKERS=%r, DIARIZATION_MIN_SPEAKERS=%r, DIARIZATION_MAX_SPEAKERS=%r)",
            DIARIZATION_NUM_SPEAKERS, DIARIZATION_MIN_SPEAKERS, DIARIZATION_MAX_SPEAKERS)
        return {}

def _diarize(audio_path: str) -> list[tuple[float, float, str]]:
    hints = _diarization_hints()
    with DIARIZE_LOCK:
        try:
            return extract_turns(diarize_pipeline(audio_path, **hints))
        except TypeError:
            if not hints:
                raise
            logger.warning("Diarization pipeline rejected speaker-count hints %s; retrying without them", hints)
            return extract_turns(diarize_pipeline(audio_path))

def assign_speakers_to_segments(segments: list[dict], turns: list[tuple[float, float, str]]) -> list[dict]:
    # Label each Whisper segment with its most likely pyannote speaker
    for segment in segments:
        seg_start, seg_end = segment['start'], segment['end']
        words = segment.get('words') or []
        if words:
            units = [(word['start'], word['end']) for word in words]
        else:
            units = [(seg_start, seg_end)]

        scores: dict[str, float] = {}
        for unit_start, unit_end in units:
            for turn_start, turn_end, label in turns:
                overlap = _overlap_duration(unit_start, unit_end, turn_start, turn_end)
                if overlap > 0:
                    scores[label] = scores.get(label, 0.0) + overlap

        if scores:
            segment['speaker'] = max(scores, key=scores.get)
        elif turns:
            midpoint = (seg_start + seg_end) / 2
            segment['speaker'] = min(
                turns, key=lambda turn: abs(midpoint - (turn[0] + turn[1]) / 2))[2]
        else:
            segment['speaker'] = 'SPEAKER_UNKNOWN'
    return segments

def format_segments(segments: list[dict]) -> str:
    if not segments or 'speaker' not in segments[0]:
        return " ".join(segment['text'].strip() for segment in segments)

    lines: list[str] = []
    current_speaker: str | None = None
    current_text: list[str] = []
    for segment in segments:
        text = segment['text'].strip()
        if not text:
            continue
        speaker = segment.get('speaker', 'SPEAKER_UNKNOWN')
        if speaker != current_speaker:
            if current_text:
                lines.append(f"{current_speaker}: {' '.join(current_text)}")
            current_speaker = speaker
            current_text = [text]
        else:
            current_text.append(text)
    if current_text:
        lines.append(f"{current_speaker}: {' '.join(current_text)}")
    return "\n".join(lines)

class RequestHandler(BaseHTTPRequestHandler):
    def handle_one_request(self):
        try:
            super().handle_one_request()
        except ConnectionResetError:
            pass
        except Exception as e:
            print(f"Error handling request: {e}")
            logger.exception("Error handling request: %s", e)

    def do_POST(self):
        client = self.client_address[0] if self.client_address else "unknown"
        print(f"POST {self.path} from {client}")
        logger.info("POST %s from %s", self.path, client)
        try:
            if self.path == '/whisperaudio':
                auth = self.headers.get('Authorization', '')
                if WHISPER_API_KEY and auth != f"Bearer {WHISPER_API_KEY}":
                    logger.warning("Unauthorized request to %s from %s", self.path, client)
                    self.send_error(401, "Unauthorized")
                    return
                try:
                    content_length = int(self.headers.get('Content-Length', 0))
                except (TypeError, ValueError):
                    content_length = 0
                if content_length > MAX_UPLOAD_SIZE:
                    print(f"Request too large ({content_length} bytes) from {client}")
                    logger.warning(
                        "Request too large (%d bytes, max %d) from %s", content_length, MAX_UPLOAD_SIZE, client)
                    self.send_error(413, "Payload too large")
                    return
                ctype, pdict = cgi.parse_header(self.headers.get('content-type'))
                if ctype == 'multipart/form-data':
                    pdict['boundary'] = bytes(pdict['boundary'], "utf-8")
                    fields = cgi.parse_multipart(self.rfile, pdict)
                    audio_data = fields.get('audio')[0]
                    print(f"Received audio upload ({len(audio_data)} bytes) from {client}")
                    logger.info("Received audio upload (%d bytes) from %s", len(audio_data), client)

                    with tempfile.NamedTemporaryFile(delete=False) as temp_audio_file:
                        temp_audio_file.write(audio_data)
                        temp_file_path = temp_audio_file.name

                    try:
                        print("Starting transcription")
                        logger.info("Starting transcription")
                        start_time = time.time()

                        diarization_thread = None
                        diarization_turns: list[tuple[float, float, str]] | None = None

                        def _run_diarization():
                            nonlocal diarization_turns
                            try:
                                diarization_turns = _diarize(temp_file_path)
                            except Exception as e:
                                # Log here so the error is not lost if transcription also fails.
                                print(f"Diarization failed, skipping speaker labels: {e}")
                                logger.error("Diarization failed, skipping speaker labels", exc_info=e)

                        if diarize_pipeline is not None:
                            diarization_thread = threading.Thread(target=_run_diarization, daemon=True)
                            diarization_thread.start()

                        try:
                            with MODEL_LOCK: # handles each request in its own thread
                                result = model.transcribe(
                                    temp_file_path,
                                    word_timestamps=diarize_pipeline is not None,
                                )
                        finally:
                            # Always wait for diarization before the temp file is removed
                            if diarization_thread is not None:
                                diarization_thread.join()

                        if diarization_turns is not None:
                            result['segments'] = assign_speakers_to_segments(result['segments'], diarization_turns)
                        elapsed = time.time() - start_time
                        transcription = format_segments(result['segments'])
                        print(f"Transcription completed in {elapsed:.2f}s: {transcription}")
                        logger.info(
                            "Transcription completed in %.2fs: %s",
                            elapsed,
                            transcription,
                        )

                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        response_data = json.dumps({"text": transcription})
                        self.wfile.write(response_data.encode())
                    finally:
                        os.remove(temp_file_path)
                else:
                    print(f"Invalid content type '{ctype}' from {client}")
                    logger.warning("Invalid content type '%s' from %s", ctype, client)
                    self.send_error(400, "Invalid content type")
            else:
                print(f"Unknown path {self.path} from {client}")
                logger.warning("Unknown path %s from %s", self.path, client)
                self.send_error(404, "File not found")
        except Exception as e:
            print(f"Error processing POST request: {e}")
            logger.exception("Error processing POST request: %s", e)
            try:
                self.send_error(500, "Internal server error")
            except:
                pass

def run(server_class=ThreadingHTTPServer, handler_class=RequestHandler, port=8000):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    httpd.daemon_threads = True
    print(f'Server running at http://localhost:{port}/')
    logger.info("Server running at http://localhost:%d/", port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        logger.info("Server stopped by user (KeyboardInterrupt)")
    except Exception as e:
        print(f"Server error: {e}")
        logger.exception("Server error: %s", e)
        raise

if __name__ == '__main__':
    run()
