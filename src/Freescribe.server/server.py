# Copyright (c) 2023 Braedon Hendy
# This software is released under the GNU General Public License v3.0

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import whisper
import cgi
import json
import os
import tempfile
import time
import logging
import yaml

from dailylogger import setup_daily_logger

setup_daily_logger(log_dir="logs", log_filename="server.log")
logger = logging.getLogger(__name__)

# Initialize Whisper model
print("Loading Whisper model 'medium'...")
logger.info("Loading Whisper model 'medium'...")
model = whisper.load_model("medium")
print("Whisper model loaded successfully")
logger.info("Whisper model loaded successfully")

with open(r".\configs\config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

WHISPER_API_KEY = config.get("WHISPER_API_KEY")
print("Loaded API key")
logger.info("Loaded API key")

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
                        result = model.transcribe(temp_file_path)
                        elapsed = time.time() - start_time
                        print(f"Transcription completed in {elapsed:.2f}s: {result['text']}")
                        logger.info(
                            "Transcription completed in %.2fs: %s",
                            elapsed,
                            result["text"],
                        )

                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        response_data = json.dumps({"text": result["text"]})
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
