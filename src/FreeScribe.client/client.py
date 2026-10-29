"""
This software is released under the AGPL-3.0 license
Copyright (c) 2023-2024 Braedon Hendy

Further updates and packaging added in 2024 through the ClinicianFOCUS initiative, 
a collaboration with Dr. Braedon Hendy and Conestoga College Institute of Applied 
Learning and Technology as part of the CNERG+ applied research project, 
Unburdening Primary Healthcare: An Open-Source AI Clinician Partner Platform". 
Prof. Michael Yingbull (PI), Dr. Braedon Hendy (Partner), 
and Research Students - Software Developer Alex Simko, Pemba Sherpa (F24), and Naitik Patel.

"""

import os
import tkinter as tk
from tkinter import scrolledtext, ttk, filedialog
import requests
import pyperclip
import wave
import threading
import numpy as np
import atexit
import win32con, win32gui

import json
import pyaudio
import tkinter.messagebox as messagebox
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from concurrent.futures import ThreadPoolExecutor
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

try:
    import whisper # python package is named openai-whisper
    WHISPER_AVAILABLE = True
except ImportError:
    whisper = None
    WHISPER_AVAILABLE = False

import scrubadub
import re

try:
    import speech_recognition as sr # python package is named speechrecognition
    SR_AVAILABLE = True
except ImportError:
    sr = None
    SR_AVAILABLE = False
import time
import queue

from UI.MainWindowUI import MainWindowUI
from UI.SettingsWindow import SettingsWindow, SettingsKeys
from UI.PromptsWindow import PromptsWindow
from UI.Widgets.CustomTextBox import CustomTextBox
from UI.Widgets.LabSelectionPanel import LabSelectionPanel
from UI.Widgets.EformPanel import EformPanel
from UI.LoadingWindow import LoadingWindow
from UI.BackgroundTask import BackgroundTask
from UI.Widgets.MicrophoneSelector import MicrophoneState
from Model import  ModelManager
from utils.ip_utils import is_private_ip
from utils.file_utils import get_file_path, get_resource_path
from utils.read_files import file_reader, extract_patient_name, detect_type, extract_patient_notes, extract_plan_section, pdf_image_to_text
from utils.hl7 import *
from utils.lab_processor import generate_lab_hl7
from utils.auto_processing import AutoProcessor
from utils.patient_details import PatientDetailsDB, find_details_from_db
from utils.referral_form_processor import get_referral_labels, get_referral_json
from utils import referral_requisition
from utils.lab_analysis import analyze_plan_for_labs, pick_most_extensive
from utils import med_eform
from utils.note_prompts import with_speaker_rules, TRANSCRIPT_SPEAKER_RULES
import ctypes
import sys
from UI.DebugWindow import DualOutput


from chatbot.OscarChatbot import OscarCB
from UI.Widgets.SourcesWindow import SourcesWindow


dual = DualOutput()
sys.stdout = dual
sys.stderr = dual


chatbot = OscarCB(config_path=r".\configs\config.yaml")
patient_db = PatientDetailsDB(config_path=r".\configs\config.yaml")

atexit.register(chatbot.cleanup)
atexit.register(patient_db.cleanup)

# GUI Setup
root = tk.Tk()
root.title("AI Medical Scribe")
root.geometry("1400x800")


# settings logic
app_settings = SettingsWindow()
ai_prompts = PromptsWindow(default_path=r".\prompts\default_prompts.yaml", target_path=r".\prompts\prompts.yaml")
HL7_PROMPTS = ai_prompts.hl7_prompt_list

oscar = chatbot.oscar 
#  create our ui elements and settings config
if app_settings.editable_settings[SettingsKeys.USE_NEW_UI.value]:
    new_ui = True
    print("New UI selected")
else:
    new_ui = False
    print("Legacy UI selected")
window = MainWindowUI(root, app_settings, ai_prompts)

app_settings.set_main_window(window)

# Cleanup on window close
def on_close():
    chatbot.cleanup()
    patient_db.cleanup()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)


def restart_application():
    print("Restarting app, please wait")
    on_close()
    python = sys.executable
    os.execl(python, python, *sys.argv)

app_settings.set_restart_callback(restart_application)


if app_settings.editable_settings["Use Docker Status Bar"]:
    window.create_docker_status_bar()

NOTE_CREATION = "Note Creation...Please Wait"

user_message = []
response_history = []
current_view = "scribe"
username = "user"
botname = "Assistant"
num_lines_to_keep = 20
uploaded_file_path = None
is_recording = False
is_realtimeactive = False
audio_data = []
frames = []
is_paused = False
is_flashing = False
use_aiscribe = True
is_gpt_button_active = False
auto_process_thread = None
stop_auto_processing = False
auto_processor = None
p = pyaudio.PyAudio()
audio_queue = queue.Queue()
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000

# Application flags
is_audio_processing_realtime_canceled = threading.Event()
is_audio_processing_whole_canceled = threading.Event()

# Constants
DEFAULT_BUTTON_COLOUR = "SystemButtonFace"

#Thread tracking variables
REALTIME_TRANSCRIBE_THREAD_ID = None
GENERATION_THREAD_ID = None

# Global instance of whisper model
stt_local_model = None


def get_prompt(formatted_message):

    sampler_order = app_settings.editable_settings["sampler_order"]
    if isinstance(sampler_order, str):
        sampler_order = json.loads(sampler_order)
    return {
        "prompt": f"{formatted_message}\n",
        "use_story": app_settings.editable_settings["use_story"],
        "use_memory": app_settings.editable_settings["use_memory"],
        "use_authors_note": app_settings.editable_settings["use_authors_note"],
        "use_world_info": app_settings.editable_settings["use_world_info"],
        "max_context_length": int(app_settings.editable_settings["max_context_length"]),
        "max_length": int(app_settings.editable_settings["max_length"]),
        "rep_pen": float(app_settings.editable_settings["rep_pen"]),
        "rep_pen_range": int(app_settings.editable_settings["rep_pen_range"]),
        "rep_pen_slope": float(app_settings.editable_settings["rep_pen_slope"]),
        "temperature": float(app_settings.editable_settings["temperature"]),
        "tfs": float(app_settings.editable_settings["tfs"]),
        "top_a": float(app_settings.editable_settings["top_a"]),
        "top_k": int(app_settings.editable_settings["top_k"]),
        "top_p": float(app_settings.editable_settings["top_p"]),
        "typical": float(app_settings.editable_settings["typical"]),
        "sampler_order": sampler_order,
        "singleline": app_settings.editable_settings["singleline"],
        "frmttriminc": app_settings.editable_settings["frmttriminc"],
        "frmtrmblln": app_settings.editable_settings["frmtrmblln"]
    }

def threaded_toggle_recording():
    thread = threading.Thread(target=toggle_recording)
    thread.start()

def threaded_realtime_text():
    thread = threading.Thread(target=realtime_text)
    thread.start()
    return thread

def threaded_handle_message(formatted_message):
    thread = threading.Thread(target=show_edit_transcription_popup, args=(formatted_message,))
    thread.start()
    return thread

def threaded_send_audio_to_server():
    thread = threading.Thread(target=send_audio_to_server)
    thread.start()
    return thread


def threaded_folder_reading(pdfs):
    def worker():
        global ocr_text
        ocr_text = ""
        #pdfs = [file for file in os.listdir(folder_path) if file.lower().endswith(".pdf")]
        for pdf in pdfs:
            print(pdf)
            try:
                # Read file
                #pdf_path = os.path.join(folder_path, pdf)
                ocr_text += file_reader(pdf)
            except Exception as e:
                print(f"Unable to extract text from {pdf}: {e}")
        
        # Display read text
        user_input.scrolled_text.delete("1.0", tk.END)
        user_input.scrolled_text.insert(tk.END, ocr_text)
        
    thread = threading.Thread(target=worker())
    thread.start()
    return thread

def threaded_file_reading():
    def worker():
        global ocr_text

        # Read file
        ocr_text = file_reader(file_path)
        
        # Display read text
        user_input.scrolled_text.delete("1.0", tk.END)
        user_input.scrolled_text.insert(tk.END, ocr_text)
        
    thread = threading.Thread(target=worker())
    thread.start()
    return thread

def toggle_pause():
    global is_paused
    is_paused = not is_paused

    if is_paused:
        if current_view == "full":
            pause_button.config(text="Resume", bg="red")
        elif current_view == "minimal":
            pause_button.config(text="▶️", bg="red")
    else:
        if current_view == "full":
            pause_button.config(text="Pause", bg=DEFAULT_BUTTON_COLOUR)
        elif current_view == "minimal":
            pause_button.config(text="⏸️", bg=DEFAULT_BUTTON_COLOUR)
    

def record_audio():
    global is_paused, frames, audio_queue

    try:
        stream = p.open(
            format=FORMAT, 
            channels=1, 
            rate=RATE, 
            input=True,
            frames_per_buffer=CHUNK, 
            input_device_index=int(MicrophoneState.SELECTED_MICROPHONE_INDEX))
    except (OSError, IOError) as e:
        print(f"Failed to open audio stream: {e}")
        messagebox.showerror(
            "Microphone Unavailable",
            "We couldn't access your microphone.\n\n"
            "Please check that your microphone is connected and selected correctly "
            "in Whisper Settings, then try again."
        )
        return

    
    current_chunk = []
    silent_duration = 0
    record_duration = 0
    minimum_silent_duration = int(app_settings.editable_settings["Real Time Silence Length"])
    minimum_audio_duration = int(app_settings.editable_settings["Real Time Audio Length"])
    
    while is_recording:
        if not is_paused:
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            # Check for silence
            audio_buffer = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
            if is_silent(audio_buffer, app_settings.editable_settings["Silence cut-off"]):
                silent_duration += CHUNK / RATE
            else:
                current_chunk.append(data)
                silent_duration = 0
            
            record_duration += CHUNK / RATE
            
            # If the current_chunk has at least 5 seconds of audio and 1 second of silence at the end
            if record_duration >= minimum_audio_duration and silent_duration >= minimum_silent_duration:
                if app_settings.editable_settings["Real Time"] and current_chunk:
                    audio_queue.put(b''.join(current_chunk))
                current_chunk = []
                silent_duration = 0
                record_duration = 0

    # Send any remaining audio chunk when recording stops
    if current_chunk:
        audio_queue.put(b''.join(current_chunk))

    stream.stop_stream()
    stream.close()
    audio_queue.put(None)


def is_silent(data, threshold=0.01):
    """Check if audio chunk is silent"""
    data_array = np.array(data)
    max_value = max(abs(data_array))
    return max_value < threshold

def realtime_text():
    global frames, is_realtimeactive, audio_queue
    # Incase the user starts a new recording while this one the older thread is finishing.
    # This is a local flag to prevent the processing of the current audio chunk 
    # if the global flag is reset on new recording
    local_cancel_flag = False 
    if not is_realtimeactive:
        is_realtimeactive = True

        while True:
            #  break if canceled
            if is_audio_processing_realtime_canceled.is_set():
                local_cancel_flag = True
                break

            audio_data = audio_queue.get()
            if audio_data is None:
                break
            if app_settings.editable_settings["Real Time"] == True:
                print("Real Time Audio to Text")
                audio_buffer = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768
                if not is_silent(audio_buffer):
                    if app_settings.editable_settings[SettingsKeys.LOCAL_WHISPER.value] == True:
                        print("Local Real Time Whisper")
                        if stt_local_model is None:
                            update_gui("Local Whisper model not loaded. Please check your settings.")
                            break

                        result = stt_local_model.transcribe(audio_buffer, fp16=False)
                        if not local_cancel_flag and not is_audio_processing_realtime_canceled.is_set():
                            update_gui(result['text'])
                    else:
                        print("Remote Real Time Whisper")
                        if frames:
                            with wave.open(get_resource_path("realtime.wav"), 'wb') as wf:
                                wf.setnchannels(CHANNELS)
                                wf.setsampwidth(p.get_sample_size(FORMAT))
                                wf.setframerate(RATE)
                                wf.writeframes(b''.join(frames))
                            frames = []
                        file_to_send = get_resource_path("realtime.wav")
                        with open(file_to_send, 'rb') as f:
                            files = {'audio': f}

                            headers = {
                                "Authorization": "Bearer "+app_settings.editable_settings[SettingsKeys.WHISPER_SERVER_API_KEY.value]
                            }

                            try:
                                verify = not app_settings.editable_settings["S2T Server Self-Signed Certificates"]
                                response = requests.post(app_settings.editable_settings[SettingsKeys.WHISPER_ENDPOINT.value], headers=headers,files=files, verify=verify)
                                if response.status_code == 200:
                                    text = response.json()['text']
                                    if not local_cancel_flag and not is_audio_processing_realtime_canceled.is_set():
                                        update_gui(text)
                                else:
                                    update_gui(f"Error (HTTP Status {response.status_code}): {response.text}")
                            except Exception as e:
                                update_gui(f"Error: {e}")
                            finally:
                                #Task done clean up file
                                if os.path.exists(file_to_send):
                                    f.close()
                                    os.remove(file_to_send)
                audio_queue.task_done()
    else:
        is_realtimeactive = False

def update_gui(text):
    user_input.scrolled_text.insert(tk.END, text + '\n')
    user_input.scrolled_text.see(tk.END)

def save_audio():
    global frames
    if frames:
        with wave.open(get_resource_path("recording.wav"), 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))
        frames = []  # Clear recorded data

        if app_settings.editable_settings["Real Time"] == True and is_audio_processing_realtime_canceled.is_set() is False:
            send_and_receive()
        elif app_settings.editable_settings["Real Time"] == False and is_audio_processing_whole_canceled.is_set() is False:
            threaded_send_audio_to_server()

def toggle_recording():
    global is_recording, recording_thread, DEFAULT_BUTTON_COLOUR, audio_queue, current_view, REALTIME_TRANSCRIBE_THREAD_ID

    # Reset the cancel flags going into a fresh recording
    if not is_recording:
        is_audio_processing_realtime_canceled.clear()
        is_audio_processing_whole_canceled.clear()

    if is_paused:
        toggle_pause()

    realtime_thread = threaded_realtime_text()

    if not is_recording:
        disable_recording_ui_elements()
        REALTIME_TRANSCRIBE_THREAD_ID = realtime_thread.ident
        user_input.scrolled_text.configure(state='normal')
        user_input.scrolled_text.delete("1.0", tk.END)
        if not app_settings.editable_settings["Real Time"]:
            user_input.scrolled_text.insert(tk.END, "Recording")
        response_display.scrolled_text.configure(state='normal')
        response_display.scrolled_text.delete("1.0", tk.END)
        response_display.scrolled_text.configure(fg='black')
        is_recording = True

        recording_thread = threading.Thread(target=record_audio)
        recording_thread.start()


        if current_view == "full":
            mic_button.config(bg="red", text="Stop\nRecording")
        elif current_view == "minimal":
            #mic_button.config(bg="red", text="⏹️")
            minimal_mic_button.config(bg="red", text="⏹️ Stop")
        else:
            mic_button.config(bg="red", text="⏹️ Stop")
        
        start_flashing()
    else:
        enable_recording_ui_elements()
        is_recording = False
        if recording_thread.is_alive():
            recording_thread.join()  # Ensure the recording thread is terminated
        
        if app_settings.editable_settings["Real Time"] and not is_audio_processing_realtime_canceled.is_set():
            def cancel_realtime_processing(thread_id):
                """Cancels any ongoing audio processing.
                
                Sets the global flag to stop audio processing operations.
                """
                global REALTIME_TRANSCRIBE_THREAD_ID

                try:
                    kill_thread(thread_id)
                except Exception as e:
                    # Log the error message
                    # TODO System logger
                    print(f"An error occurred: {e}")
                finally:
                    REALTIME_TRANSCRIBE_THREAD_ID = None

                #empty the queue
                while not audio_queue.empty():
                    audio_queue.get()
                    audio_queue.task_done()

            loading_window = LoadingWindow(root, "Processing Audio", "Processing Audio. Please wait.", on_cancel=lambda: (cancel_processing(), cancel_realtime_processing(REALTIME_TRANSCRIBE_THREAD_ID)))


            timeout_timer = 0
            while audio_queue.empty() is False and timeout_timer < 180:
                # break because cancel was requested
                if is_audio_processing_realtime_canceled.is_set():
                    break
                
                timeout_timer += 0.1
                time.sleep(0.1)
            
            loading_window.destroy()

            realtime_thread.join()

        save_audio()

        if current_view == "full":
            mic_button.config(bg=DEFAULT_BUTTON_COLOUR, text="Start\nRecording")
        elif current_view == "minimal":
            #mic_button.config(bg=DEFAULT_BUTTON_COLOUR, text="🎤")
            minimal_mic_button.config(bg=DEFAULT_BUTTON_COLOUR, text="⏺  Record")
        else:
            mic_button.config(bg=DEFAULT_BUTTON_COLOUR, text="⏺  Record")

def disable_recording_ui_elements():
    window.disable_settings_menu()
    user_input.scrolled_text.configure(state='disabled')
    send_button.config(state='disabled')
    #toggle_button.config(state='disabled') 
    upload_button.config(state='disabled')
    timestamp_listbox.config(state='disabled')

def enable_recording_ui_elements():
    window.enable_settings_menu()
    user_input.scrolled_text.configure(state='normal')
    send_button.config(state='normal')
    #toggle_button.config(state='normal')
    upload_button.config(state='normal')
    timestamp_listbox.config(state='normal')
    

def cancel_processing():
    """Cancels any ongoing audio processing.
    
    Sets the global flag to stop audio processing operations.
    """
    print("Processing canceled.")

    if app_settings.editable_settings["Real Time"]:
        is_audio_processing_realtime_canceled.set() # Flag to terminate processing
    else:
        is_audio_processing_whole_canceled.set()  # Flag to terminate processing

def clear_application_press():
    if messagebox.askyesno(
        "Clear Transcript and Note",
        "Are you sure you want to clear the transcript and medical note?"
    ):
        """Resets the application state by clearing text fields and recording status."""
        reset_recording_status()  # Reset recording-related variables
        clear_all_text_fields()  # Clear UI text areas

def reset_recording_status():
    """Resets all recording-related variables and stops any active recording.
    
    Handles cleanup of recording state by:
        - Checking if recording is active
        - Canceling any processing
        - Stopping the recording thread
    """
    global is_recording, frames, audio_queue, REALTIME_TRANSCRIBE_THREAD_ID, GENERATION_THREAD_ID
    if is_recording:  # Only reset if currently recording
        cancel_processing()  # Stop any ongoing processing
        threaded_toggle_recording()  # Stop the recording thread

    # kill the generation thread if active
    if REALTIME_TRANSCRIBE_THREAD_ID:
        # Exit the current realtime thread
        try:
            kill_thread(REALTIME_TRANSCRIBE_THREAD_ID)
        except Exception as e:
            # Log the error message
            # TODO System logger
            print(f"An error occurred: {e}")
        finally:
            REALTIME_TRANSCRIBE_THREAD_ID = None

    if GENERATION_THREAD_ID:
        try:
            kill_thread(GENERATION_THREAD_ID)
        except Exception as e:
            # Log the error message
            # TODO System logger
            print(f"An error occurred: {e}")
        finally:
            GENERATION_THREAD_ID = None

def clear_all_text_fields():
    """Clears and resets all text fields in the application UI.
    
    Performs the following:
        - Clears user input field
        - Resets focus
        - Stops any flashing effects
        - Resets response display with default text
    """
    # Enable and clear user input field
    user_input.scrolled_text.configure(state='normal')
    user_input.scrolled_text.delete("1.0", tk.END)
    
    # Reset focus to main window
    user_input.scrolled_text.focus_set()
    root.focus_set()
    
    stop_flashing()  # Stop any UI flashing effects
    
    # Reset response display with default text
    response_display.scrolled_text.configure(state='normal')
    response_display.scrolled_text.delete("1.0", tk.END)
    response_display.scrolled_text.insert(tk.END, "Medical Note")
    response_display.scrolled_text.config(fg='grey')
    
    # Hide and clear lab selection panel
    eform_selection_panel.hide()
    eform_selection_panel._clear_checkboxes()

"""def toggle_aiscribe():
    global use_aiscribe
    use_aiscribe = not use_aiscribe
    toggle_button.config(text="AI Scribe\nON" if use_aiscribe else "AI Scribe\nOFF")"""

def send_audio_to_server():
    """
    Sends an audio file to either a local or remote Whisper server for transcription.

    Global Variables:
    ----------------
    uploaded_file_path : str
        The path to the uploaded audio file. If `None`, the function defaults to
        'recording.wav'.

    Parameters:
    -----------
    None

    Returns:
    --------
    None

    Raises:
    -------
    ValueError
        If the `app_settings.editable_settings[SettingsKeys.LOCAL_WHISPER.value]` flag is not a boolean.
    FileNotFoundError
        If the specified audio file does not exist.
    requests.exceptions.RequestException
        If there is an issue with the HTTP request to the remote server.
    """

    global uploaded_file_path
    current_thread_id = threading.current_thread().ident

    def cancel_whole_audio_process(thread_id):
        global GENERATION_THREAD_ID
        
        is_audio_processing_whole_canceled.clear()

        try:
            kill_thread(thread_id)
        except Exception as e:
            # Log the error message
            #TODO Logging the message to system logger
            print(f"An error occurred: {e}")
        finally:
            GENERATION_THREAD_ID = None

    loading_window = LoadingWindow(root, "Processing Audio", "Processing Audio. Please wait.", on_cancel=lambda: (cancel_processing(), cancel_whole_audio_process(current_thread_id)))

    # Check if SettingsKeys.LOCAL_WHISPER is enabled in the editable settings
    if app_settings.editable_settings[SettingsKeys.LOCAL_WHISPER.value] == True:
        # Inform the user that SettingsKeys.LOCAL_WHISPER.value is being used for transcription
        print(f"Using {SettingsKeys.LOCAL_WHISPER.value} for transcription.")
        # Configure the user input widget to be editable and clear its content
        user_input.scrolled_text.configure(state='normal')
        user_input.scrolled_text.delete("1.0", tk.END)

        # Display a message indicating that audio to text processing is in progress
        user_input.scrolled_text.insert(tk.END, "Audio to Text Processing...Please Wait")
        try:
            # Determine the file to send for transcription
            file_to_send = uploaded_file_path or get_resource_path('recording.wav')
            delete_file = False if uploaded_file_path else True
            uploaded_file_path = None

            # Transcribe the audio file using the loaded model
            result = stt_local_model.transcribe(file_to_send)
            transcribed_text = result["text"]

            # done with file clean up
            if os.path.exists(file_to_send) and delete_file is True:
                os.remove(file_to_send)

            #check if canceled, if so do not update the UI
            if not is_audio_processing_whole_canceled.is_set():
                # Update the user input widget with the transcribed text
                user_input.scrolled_text.configure(state='normal')
                user_input.scrolled_text.delete("1.0", tk.END)
                user_input.scrolled_text.insert(tk.END, transcribed_text)

                # Send the transcribed text and receive a response
                send_and_receive()
        except Exception as e:
            # Log the error message
            # TODO: Add system eventlogger
            print(f"An error occurred: {e}")

            #log error to input window
            user_input.scrolled_text.configure(state='normal')
            user_input.scrolled_text.delete("1.0", tk.END)
            user_input.scrolled_text.insert(tk.END, f"An error occurred: {e}")
            user_input.scrolled_text.configure(state='disabled')
        finally:
            loading_window.destroy()
            
    else:
        # Inform the user that Remote Whisper is being used for transcription
        print("Using Remote Whisper for transcription.")

        # Configure the user input widget to be editable and clear its content
        user_input.scrolled_text.configure(state='normal')
        user_input.scrolled_text.delete("1.0", tk.END)

        # Display a message indicating that audio to text processing is in progress
        user_input.scrolled_text.insert(tk.END, "Audio to Text Processing...Please Wait")

        delete_file = False if uploaded_file_path else True

        # Determine the file to send for transcription
        if uploaded_file_path:
            file_to_send = uploaded_file_path
            uploaded_file_path = None
        else:
            file_to_send = get_resource_path('recording.wav')

        # Open the audio file in binary mode
        with open(file_to_send, 'rb') as f:
            files = {'audio': f}

            # Add the Bearer token to the headers for authentication
            headers = {
                "Authorization": f"Bearer {app_settings.editable_settings[SettingsKeys.WHISPER_SERVER_API_KEY.value]}"
            }

            try:
                verify = not app_settings.editable_settings["S2T Server Self-Signed Certificates"]

                # Send the request without verifying the SSL certificate
                response = requests.post(app_settings.editable_settings[SettingsKeys.WHISPER_ENDPOINT.value], headers=headers, files=files, verify=verify)

                response.raise_for_status()

                # check if canceled, if so do not update the UI
                if not is_audio_processing_whole_canceled.is_set():
                    # Update the UI with the transcribed text
                    transcribed_text = response.json()['text']
                    user_input.scrolled_text.configure(state='normal')
                    user_input.scrolled_text.delete("1.0", tk.END)
                    user_input.scrolled_text.insert(tk.END, transcribed_text)

                    # Send the transcribed text and receive a response
                    send_and_receive()
            except Exception as e:
                # log error message
                #TODO: Implment proper logging to system
                print(f"An error occurred: {e}")
                # Display an error message to the user
                user_input.scrolled_text.configure(state='normal')
                user_input.scrolled_text.delete("1.0", tk.END)
                user_input.scrolled_text.insert(tk.END, f"An error occurred: {e}")
                user_input.scrolled_text.configure(state='disabled')
            finally:
                # done with file clean up
                f.close()
                if os.path.exists(file_to_send) and delete_file:
                    os.remove(file_to_send)
                loading_window.destroy()

def kill_thread(thread_id):
    """
    Terminate a thread with a given thread ID.

    This function forcibly terminates a thread by raising a `SystemExit` exception in its context.
    **Use with caution**, as this method is not safe and can lead to unpredictable behavior, 
    including corruption of shared resources or deadlocks.

    :param thread_id: The ID of the thread to terminate.
    :type thread_id: int
    :raises ValueError: If the thread ID is invalid.
    :raises SystemError: If the operation fails due to an unexpected state.
    """
    # Call the C function `PyThreadState_SetAsyncExc` to asynchronously raise
    # an exception in the target thread's context.
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(thread_id),  # The thread ID to target (converted to `long`).
        ctypes.py_object(SystemExit)  # The exception to raise in the thread.
    )

    # Check the result of the function call.
    if res == 0:
        # If 0 is returned, the thread ID is invalid.
        raise ValueError(f"Invalid thread ID: {thread_id}")
    elif res > 1:
        # If more than one thread was affected, something went wrong.
        # Reset the state to prevent corrupting other threads.
        ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, None)
        raise SystemError("PyThreadState_SetAsyncExc failed")

def send_and_receive():
    global use_aiscribe, user_message
    user_message = user_input.scrolled_text.get("1.0", tk.END).strip()

    if selected_prompt.get() == REFERRAL_REQUISITION_PROMPT:
        display_text(f"\"{REFERRAL_REQUISITION_PROMPT}\" does not generate a note: open the patient's encounter "
                     "page and click Populate to fill the requisition eForm from the referral in the input box.")
        return

    # If user selected OSCAR_FEEDBACK, try to send only patient notes
    try:
        if selected_prompt.get() == "OSCAR_FEEDBACK" and user_message:
            user_message = extract_patient_notes(user_message)
    except Exception:
        pass
    display_text(NOTE_CREATION)
    threaded_handle_message(user_message)

        

def display_text(text):
    response_display.scrolled_text.configure(state='normal')
    response_display.scrolled_text.delete("1.0", tk.END)
    response_display.scrolled_text.insert(tk.END, f"{text}\n")
    response_display.scrolled_text.configure(fg='black')

IS_FIRST_LOG = True
def update_gui_with_response(response_text):
    global response_history, user_message, IS_FIRST_LOG

    if IS_FIRST_LOG:
        timestamp_listbox.delete(0, tk.END)
        timestamp_listbox.config(fg='black')
        IS_FIRST_LOG = False

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    response_history.insert(0, (timestamp, user_message, response_text))

    # Update the timestamp listbox
    timestamp_listbox.delete(0, tk.END)
    for time, _, _ in response_history:
        timestamp_listbox.insert(tk.END, time)

    display_text(response_text)
    pyperclip.copy(response_text)
    user_input.scrolled_text.configure(state='normal')
    stop_flashing()
    
    # Automatically analyze and show lab panel for Scribe prompts
    prompt_type = selected_prompt.get()
    if prompt_type == "Scribe":
        plan_text = extract_plan_section(response_text)
        if plan_text:
            # Shrink response_display to make room for lab panel
            response_display.grid(row=3, column=1, columnspan=7, padx=5, pady=15, sticky='nsew')
            
            # Analyze plan using LLM in a separate thread
            def analyze_and_update():
                try:
                    suggested_labels = analyze_plan_for_labs(plan_text, send_text_to_chatgpt)
                    # Update panel on main thread - always call set_checkboxes (even if empty) to clear previous selections
                    root.after(0, lambda: eform_selection_panel.set_checkboxes(suggested_labels))
                    root.after(0, lambda: eform_selection_panel.show())
                except Exception as e:
                    print(f"Error analyzing plan for labs: {e}")
                    root.after(0, lambda: eform_selection_panel.show())
            
            threading.Thread(target=analyze_and_update, daemon=True).start()
        else:
            # No PLAN found, hide panel and expand response_display (the whole note is not used instead)
            print("[eForm] No PLAN section found in the note (looked for \"PLAN\" and \"Plan:\"); not suggesting lab checkboxes.")
            eform_selection_panel.hide()
            response_display.grid(row=3, column=1, columnspan=9, padx=5, pady=15, sticky='nsew')
    elif prompt_type == "Requisition":
        # Don't hide the eform panel
        pass
    else:
        # Not a Scribe prompt, hide panel and expand response_display
        eform_selection_panel.hide()
        response_display.grid(row=3, column=1, columnspan=9, padx=5, pady=15, sticky='nsew')

def show_response(event):
    global IS_FIRST_LOG

    if IS_FIRST_LOG:
        return

    selection = event.widget.curselection()
    if selection:
        index = selection[0]
        transcript_text = response_history[index][1]
        response_text = response_history[index][2]
        user_input.scrolled_text.configure(state='normal')
        user_input.scrolled_text.config(fg='black')
        user_input.scrolled_text.delete("1.0", tk.END)
        user_input.scrolled_text.insert(tk.END, transcript_text)
        response_display.scrolled_text.configure(state='normal')
        response_display.scrolled_text.delete('1.0', tk.END)
        response_display.scrolled_text.insert('1.0', response_text)
        response_display.scrolled_text.config(fg='black')
        pyperclip.copy(response_text)

def send_text_to_api(edited_text, context_length=None):
    headers = {
        "Authorization": f"Bearer {app_settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
        "accept": "application/json",
    }

    try:
        header_settings = json.loads(app_settings.editable_settings["Model Headers"])
        print(header_settings)
        headers.update(header_settings)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Invalid Model Headers JSON: {e}")

    payload = {}

    try:
        payload = {
            "model": app_settings.editable_settings["Model"].strip(),
            "messages": [
                {"role": "user", "content": edited_text}
            ],
            "temperature": float(app_settings.editable_settings["temperature"]),
            "top_p": float(app_settings.editable_settings["top_p"]),
            "top_k": int(app_settings.editable_settings["top_k"]),
            "tfs": float(app_settings.editable_settings["tfs"]),
        }

        if app_settings.editable_settings["best_of"]:
            payload["best_of"] = int(app_settings.editable_settings["best_of"])

        if context_length is not None:
            payload["max_context_length"] = int(context_length)
            
    except ValueError as e:
        payload = {
            "model": app_settings.editable_settings["Model"].strip(),
            "messages": [
                {"role": "user", "content": edited_text}
            ],
            "temperature": 0.1,
            "top_p": 0.4,
            "top_k": 30,
            "best_of": 6,
            "tfs": 0.97,
        }

        if app_settings.editable_settings["best_of"]:
            payload["best_of"] = int(app_settings.editable_settings["best_of"])

        if context_length is not None:
            payload["max_context_length"] = int(context_length)

        print(f"Error parsing settings: {e}. Using default settings.")

    try:

        if app_settings.editable_settings["Model Endpoint"].endswith('/'):
            app_settings.editable_settings["Model Endpoint"] = app_settings.editable_settings["Model Endpoint"][:-1]

        # Open API Style
        verify = not app_settings.editable_settings["AI Server Self-Signed Certificates"]
        response = requests.post(app_settings.editable_settings["Model Endpoint"]+"/chat/completions", headers=headers, json=payload, verify=verify)
        print(response.text)
        response.raise_for_status()
        response_data = response.json()
        response_text = (response_data['choices'][0]['message']['content'])
        return response_text

        #############################################################
        #                                                           #
        #                   OpenAI API Style                        #
        #           Uncomment to use API Style Selector             #
        #                                                           #
        #############################################################
        
        # if app_settings.API_STYLE == "OpenAI":                    
        # elif app_settings.API_STYLE == "KoboldCpp":
        #     prompt = get_prompt(edited_text)

        #     verify = not app_settings.editable_settings["AI Server Self-Signed Certificates"]
        #     response = requests.post(app_settings.editable_settings["Model Endpoint"] + "/api/v1/generate", json=prompt, verify=verify)

        #     if response.status_code == 200:
        #         results = response.json()['results']
        #         response_text = results[0]['text']
        #         response_text = response_text.replace("  ", " ").strip()
        #         return response_text

    except Exception as e:
        raise e

def send_text_to_localmodel(edited_text):  
    # Send prompt to local model and get response
    if ModelManager.local_model is None:
        ModelManager.setup_model(app_settings=app_settings, root=root)

        timer = 0
        while ModelManager.local_model is None and timer < 30:
            timer += 0.1
            time.sleep(0.1)
        

    return ModelManager.local_model.generate_response(
        edited_text,
        max_tokens=int(app_settings.editable_settings["max_length"]),
        temperature=float(app_settings.editable_settings["temperature"]),
        top_p=float(app_settings.editable_settings["top_p"]),
        repeat_penalty=float(app_settings.editable_settings["rep_pen"]),
    )

    


def send_text_to_chatgpt(edited_text, context_length=None):  
    if app_settings.editable_settings["Use Local LLM"]:
        return send_text_to_localmodel(edited_text)
    else:
        return send_text_to_api(edited_text, context_length)


def get_labs_from_response():
    """Analyze text and open the lab panel with suggested checkboxes."""
    
    # Shrink response_display to make room for lab panel
    response_display.grid(row=3, column=1, columnspan=7, padx=5, pady=15, sticky='nsew')
    
    # Get text from response display (which can be edited)
    response_text = response_display.scrolled_text.get("1.0", tk.END).strip()
    
    if not response_text:
        print("No text in response display to analyze")
        return
    
    # Extract PLAN section
    plan_text = extract_plan_section(response_text)
    
    if not plan_text:
        print("No PLAN section found in response text")
        # Show panel anyway so doctor can manually select
        eform_selection_panel.show()
        return
    
    # Analyze plan using LLM in a separate thread
    def analyze_and_update():
        try:
            suggested_labels = analyze_plan_for_labs(plan_text, send_text_to_chatgpt)
            # Update panel on main thread - always call set_checkboxes (even if empty) to clear previous selections
            root.after(0, lambda: eform_selection_panel.set_checkboxes(suggested_labels))
            root.after(0, lambda: eform_selection_panel.show())
        except Exception as e:
            print(f"Error analyzing plan for labs: {e}")
            # Show panel anyway so doctor can manually select
            root.after(0, lambda: eform_selection_panel.show())
    
    threading.Thread(target=analyze_and_update, daemon=True).start()

def generate_note(formatted_message):
            try:
                prompt_type = selected_prompt.get()
                info = eform_selection_panel.get_patient_info(mute_popup=True)
                sex = ""
                if info:
                    sex = info["sex"].lower().strip()
                    if sex == 'f':
                        sex = 'Female'
                    elif sex == 'm':
                        sex = 'Male'
                print(prompt_type)
                # If note generation is on
                if prompt_type == "Scribe":
                    # If pre-processing is enabled
                    if app_settings.editable_settings["Use Pre-Processing"]:
                        #Generate Facts List
                        list_of_facts = send_text_to_chatgpt(f"{app_settings.editable_settings['Pre-Processing']} {formatted_message}")
                        
                        #Make a note from the facts
                        medical_note = send_text_to_chatgpt(f"{app_settings.AISCRIBE} {list_of_facts} {app_settings.AISCRIBE2}")

                        # If post-processing is enabled check the note over
                        if app_settings.editable_settings["Use Post-Processing"]:
                            post_processed_note = send_text_to_chatgpt(f"{app_settings.editable_settings['Post-Processing']}\nFacts:{list_of_facts}\nNotes:{medical_note}")
                            update_gui_with_response(post_processed_note)
                        else:
                            update_gui_with_response(medical_note)

                    else: # If pre-processing is not enabled thhen just generate the note
                        medical_note = send_text_to_chatgpt(f"{app_settings.AISCRIBE} {formatted_message} {app_settings.AISCRIBE2}")

                        if app_settings.editable_settings["Use Post-Processing"]:
                            post_processed_note = send_text_to_chatgpt(f"{app_settings.editable_settings['Post-Processing']}\nNotes:{medical_note}")
                            update_gui_with_response(post_processed_note)
                        else:
                            update_gui_with_response(medical_note)
                elif prompt_type == "None":
                    ai_response = send_text_to_chatgpt(formatted_message)
                    update_gui_with_response(ai_response)

                elif prompt_type == "Requisition":
                    labels = get_referral_labels()
                    base_prompt = ai_prompts.get("Requisition")
                    ind_prompt = f"{base_prompt}\n\n Available procedures and options and indications\n {json.dumps(labels, indent=2)}"
                    full_prompt = f"{ind_prompt}\n\n Clinical text:\n {formatted_message}"
            #print(full_prompt)
                    """
                    ai_response =
                        {
                            "electrocardiogram": {
                                "indications": "Chest pain of suspected cardiac origin."
                            },
                            "holter monitor": {
                                "indications": "symptom-rhythm correlation",
                                "options": "24 Hours"
                            }
                        }
                        """
                    print("base_prompt:", repr(base_prompt))
                    print(base_prompt)
                    ai_response = send_text_to_chatgpt(full_prompt)
                    print("ai_response:", repr(ai_response))
                    print(ai_response)
                    update_gui_with_response(ai_response)
                    json_response = json.loads(ai_response)
                    eform_selection_panel.set_referral_data(json_response)
                    
                elif prompt_type == "Consult Complete" or prompt_type == "Consult Complete + MH":
                    total_start = time.perf_counter()

                    step_start = time.perf_counter()
                    if not info:
                        print(f"Error: no patient's encounter page is selected")
                        display_text(f"Error: no patient's encounter page is selected")
                        return False
                    
                    demo_no = info["demographic_no"]

                    provider_no_query = f"""
                    SELECT p.provider_no
                    FROM provider AS p
                    LEFT JOIN demographic AS d
                    ON p.provider_no = d.provider_no
                    WHERE demographic_no = {demo_no};
                    """
                    provider_no_results = chatbot.db_conn.query_database(provider_no_query)
                    if provider_no_results:
                        provider_no = provider_no_results[0]["provider_no"]
                        print(f"provider_no: {provider_no}")
                        print(
                            f"[TIMING] provider_no query: "
                            f"{time.perf_counter() - step_start:.2f}s"
                        )
                    else:
                        raise RuntimeError(f"No provider number found for patient {demo_no}")

                    step_start = time.perf_counter()
                    measurement_query = f"""
                    SELECT m.*
                    FROM measurements m
                    JOIN (
                        SELECT type, MAX(dateObserved) AS latest_date
                        FROM measurements
                        WHERE demographicNo = {demo_no}
                        AND (
                            (type IN ('ECG', 'ECHO1', 'ECHO2', 'VA', 'VA2', 'CS', 'CS2', 'CS3')
                            AND providerNo = '{provider_no}')
                            OR type IN (
                                'EST',
                                'SECHO', 'SECHO1',
                                'HOLT', 'HOLT1', 'HOLT2'
                            )
                        )
                        AND dateObserved >= DATE_SUB(CURDATE(), INTERVAL 1 MONTH)
                        GROUP BY type
                    ) latest
                        ON m.type = latest.type
                    AND m.dateObserved = latest.latest_date
                    WHERE m.demographicNo = {demo_no}
                    AND (
                        (m.type IN ('ECG', 'ECHO1', 'ECHO2', 'VA', 'VA2', 'CS', 'CS2', 'CS3')
                        AND m.providerNo = '{provider_no}')
                        OR m.type IN (
                            'EST',
                            'SECHO', 'SECHO1',
                            'HOLT', 'HOLT1', 'HOLT2'
                        )
                    )
                    AND m.dateObserved >= DATE_SUB(CURDATE(), INTERVAL 1 MONTH)
                    ORDER BY m.dateObserved DESC, m.type ASC;
                    """
                    measurement_results = chatbot.db_conn.query_database(measurement_query)
                    print(f"measurement_results: {measurement_results}")
                    print(
                        f"[TIMING] DB: "
                        f"{time.perf_counter() - step_start:.2f}s"
                    )

                    step_start = time.perf_counter()
                    measurements = {
                        result["type"].upper(): result["dataField"]
                        for result in measurement_results
                    }
                    print(f"measurements: {measurements}")
                    ecg_text = str(measurements.get("ECG", ""))
                    echo_text = "".join([
                        str(measurements.get("ECHO1", "")),
                        str(measurements.get("ECHO2", "")),
                        str(measurements.get("VA", "")),
                        str(measurements.get("VA2", "")),
                        str(measurements.get("CS", "")),
                        str(measurements.get("CS2", "")),
                        str(measurements.get("CS3", ""))
                    ])
                    est_text = str(measurements.get("EST", ""))
                    secho_text = "".join([
                        str(measurements.get("SECHO", "")),
                        str(measurements.get("SECHO1", ""))
                    ])
                    holt_text = "".join([
                        str(measurements.get("HOLT", "")),
                        str(measurements.get("HOLT1", "")),
                        str(measurements.get("HOLT2", ""))
                    ])
                    print(f"[TIMING] measurement processing: {time.perf_counter() - step_start:.2f}s")

                    step_start = time.perf_counter()
                    sections = ""
                    completion_advice = ""
                    if prompt_type == "Consult Complete + MH":
                        sections = "- RISK FACTORS\n- PAST CARDIAC HISTORY\n- PAST MEDICAL HISTORY\n"
                    else:
                        sections = ""
                    sections += "- HISTORY OF PRESENT ILLNESS"
                    if ecg_text: 
                        sections += "\n- ECG"
                        print(f"ECG NOTE: {ecg_text}")
                        completion_advice += (
                            "\n\nTo complete the \"ECG\" section, use ONLY the following text. Ensure to write everything in "
                            "full sentences or paragraphs, rather than bullet points. Do NOT include information from other "
                            "sources. Do NOT include information dated older than one month. Include ALL relevant information "
                            "from the text, however do NOT reference the date/time of any observations or say \"the ECG "
                            "revealed...\", simply what the observations actually are. If there is no data, you may omit this "
                            f"section\n\n{ecg_text}"
                        )
                    if echo_text: 
                        sections += "\n- ECHO"
                        print(f"ECHO NOTE: {echo_text}")
                        completion_advice += (
                            "\n\nTo complete the \"ECHO\" section, use ONLY the following text. Ensure to write everything in "
                            "full sentences or paragraphs, rather than bullet points. Do NOT include information from other "
                            "sources. Do NOT include information dated older than one month. Include ALL relevant information "
                            "from the text, however do NOT reference the date/time of any observations or say \"the ECHO "
                            "revealed...\", simply what the observations actually are. If there is no data, you may omit this "
                            f"section.\n\n{echo_text}"
                        )
                    if est_text: 
                        sections += "\n- EST"
                        print(f"EST NOTE: {est_text}")
                        completion_advice += (
                            "\n\nTo complete the \"EST\" section, use ONLY the following text. Ensure to write everything in "
                            "full sentences or paragraphs, rather than bullet points. Do NOT include information from other "
                            "sources. Do NOT include information dated older than one month. Include ALL relevant information "
                            "from the text, however do NOT reference the date/time of any observations or say \"the EST "
                            "revealed...\", simply what the observations actually are. If there is no data, you may omit this "
                            f"section.\n\n{est_text}"
                        )
                    if secho_text: 
                        sections += "\n- SECHO"
                        print(f"SECHO NOTE: {secho_text}")
                        completion_advice += (
                            "\n\nTo complete the \"SECHO\" section, use ONLY the following text. Ensure to write everything in "
                            "full sentences or paragraphs, rather than bullet points. Do NOT include information from other "
                            "sources. Do NOT include information dated older than one month. Include ALL relevant information "
                            "from the text, however do NOT reference the date/time of any observations or say \"the SECHO "
                            "revealed...\", simply what the observations actually are. If there is no data, you may omit this "
                            f"section\n\n{secho_text}"
                        )
                    if holt_text: 
                        sections += "\n- HOLTER"
                        print(f"HOLT NOTE: {holt_text}")
                        completion_advice += (
                            "\n\nTo complete the \"HOLTER\" section, use ONLY the following text. Ensure to write everything in "
                            "full sentences or paragraphs, rather than bullet points. Do NOT include information from other "
                            "sources. Do NOT include information dated older than one month. Include ALL relevant information "
                            "from the text, however do NOT reference the date/time of any observations or say \"the HOLTER "
                            "revealed...\", simply what the observations actually are. If there is no data, you may omit this "
                            f"section\n\n{holt_text}"
                        )
                    sections += "\n- ASSESSMENT\n- PLAN"
                    completion_advice += (
                        '\n\nFor the "PLAN" section, ensure that any information related to medications (e.g. starting, '
                        'stopping, increasing, decreasing, etc.) is output on a single line. Do NOT write confusing output '
                        'that makes it unclear whether a medication has been prescribed or simply recommended. For example, '
                        'do NOT output anything like "I recommended to try increasing the dose of Aspirin. The patient agreed '
                        'to do so."'
                    )

                    master_prompt = f"""
                    You are a board-certified cardiologist writing a concise, professional consultation or follow-up note to a primary care 
                    physician (family doctor) regarding a patient encounter. Synthesize the provided patient conversation transcript into a 
                    standard cardiology note format, including a History of Present Illness (HPI), Assessment, and Plan.
                    

                    Key Instructions:
                    
                    Format: Structure the note clearly with the sections listed below.  Write the summary. Write in full
                    sentences or use numbered points if not writing in full sentences. Do not use any Markdown formatting, bolding, or italics. 
                    Do not use asterisks (*) in the final output. Use plain, flat text.
                    
                    Tone: Maintain a professional, concise, and objective tone suitable for communication between specialists.
                    
                    Tense: Use the past tense consistently (e.g., "I reviewed...", "The patient reported...", "I advised..."). Avoid future tense.
                    
                    Perspective: Write from the perspective of the cardiologist ("I").
                    
                    Audience: Assume the recipient is a primary care physician who needs a clear summary of the cardiology encounter.
                    
                    Content: Focus on cardiology-relevant information. Include pertinent history, exam findings, investigations (ECG, Echo, Labs), 
                    assessment, and management plan.
                    
                    Conciseness: Be efficient and avoid unnecessary detail.
                    
                    Patient Information: Use the patient's name (if provided in the transcript, otherwise use "the patient") and relevant 
                    demographics (age, sex if known).
                    
                    Medication Changes: Clearly state any medication changes made or recommended.
                    
                    Follow-up: Specify any planned follow-up investigations or appointments.
                    

                    Patient Conversation Transcript: [Insert the transcript of the conversation with the patient here]
                    
                    Synthesize the above transcript into the following format.  Do not include any section that is not listed 
                    below, and do not rename/tweak these headings:

                    {sections}
                    

                    Post prompt:
                    
                    FORMATTING REQUIREMENTS: Use plain text only, no markdown, asterisks, bold, or underlining. No headers like 
                    "To:", "From:", "Date:", "Re:", or "Subject:". Separate sections with paragraph breaks. Only include the 
                    sections outlined above in the output."{completion_advice}

                    To complete the remaining sections, use the following information. Ensure to write everything in 
                    paragraphs, rather than bullet points. Do NOT invent new sections that were not listed above.
                    
                    The patient's sex is {sex}.

                    {TRANSCRIPT_SPEAKER_RULES}

                    {formatted_message}

                    Output the complete note.
                    """
                    master_response = send_text_to_chatgpt(master_prompt)
                    print(f"[TIMING] Master LLM: {time.perf_counter() - step_start:.2f}s")

                    step_start = time.perf_counter()
                    update_gui_with_response(master_response)
                    print(f"[TIMING] GUI update: {time.perf_counter() - step_start:.2f}s")

                    print(
                        f"[TIMING] TOTAL Consult Complete: "
                        f"{time.perf_counter() - total_start:.2f}s"
                    )
                
                elif prompt_type in HL7_PROMPTS or prompt_type == "Auto":
                    if not 'file_path' in globals():
                        prompt = ai_prompts.get(prompt_type)
                        ai_response = send_text_to_chatgpt(f"{prompt}\n{formatted_message}")
                        update_gui_with_response(ai_response)
                        return True

                    # Set max context length to 8192
                    context_length = 8192

                    # Extract document type and patient name from file
                    filename = os.path.basename(file_path)
                    try:
                        doc_type = detect_type(filename).upper()
                        first_name, last_name, _ = extract_patient_name(filename)
                        print(f"Document type: {doc_type}")
                        print(f"Patient Name: {first_name} {last_name}")
                    except Exception as e:
                        print(f"An unknown error occurred while trying to extract document type and patient name: {e}")

                    # Generate HL7 Header
                    res = None
                    if first_name and last_name:
                        if app_settings.editable_settings.get("Use Database Patient Lookup", True):
                            res = find_details_from_db(patient_db, last_name, first_name)
                        if not res:
                            res = find_details(app_settings.editable_settings['ReportMasterPath'], last_name, first_name)
                        if res:
                            sex, hin, dob, name, _ = res
                            obs_date = extract_observation_date(ocr_text, doc_type)
                            hl7_header = generate_header(name, hin, dob, sex, obs_date, obs_date)
                        else:
                            print("Unable to generate HL7 header, creating header template that needs to be filled in")
                            hl7_header = generate_header("<PATIENT NAME>", "<HIN>", "<DOB>", "<SEX>", "<MESSAGE DATE>", "<OBSERVATION DATE>")
                        
                    else:
                        print("Unable to generate HL7 header, creating header template that needs to be filled in")
                        hl7_header = generate_header("<PATIENT NAME>", "<HIN>", "<DOB>", "<SEX>", "<MESSAGE DATE>", "<OBSERVATION DATE>")


                    if prompt_type == "Auto":
                        prompt = ai_prompts.get(doc_type)
                        prompt_type = doc_type
                    else: 
                        prompt = ai_prompts.get(prompt_type)

                    if "{prompt_addon}" in prompt:
                        loinc_codes = loinc_code_detector(filename)
                        print("Extra LOINC", loinc_codes)
                        prompt = prompt.format(prompt_addon=extra_loinc_prompt(loinc_codes, EXTRA_LOINC_START_IDX.get(prompt_type, ""), prompt_type))
                    
                    if prompt_type == "LAB":
                        print("Here")
                        ai_response = generate_lab_hl7(formatted_message)
                    else:
                        ai_response = send_text_to_chatgpt(f"{prompt}\n\n{formatted_message}", context_length=context_length)
                    update_gui_with_response(hl7_header + ai_response)

                
                else:
                    prompt = with_speaker_rules(ai_prompts.get(prompt_type))
                    ai_response = send_text_to_chatgpt(f"{prompt}\nPATIENT'S SEX: {sex}\n\n{formatted_message}")
                    update_gui_with_response(ai_response)

                return True
            except Exception as e:
                #Logg
                #TODO: Implement proper logging to system event logger
                print(f"An error occurred: {e}")
                display_text(f"An error occurred: {e}")
                return False

def get_recent_cardiac_test_dates():
    test_types = {
        "ECG": "ECG",
        "ECHO1": "Echo",
        "EST": "EST",
        "SECHO": "SEcho",
        "HOLT": "Holter",
    }

    results = {
        display_name: "never"
        for display_name in test_types.values()
    }

    info = eform_selection_panel.get_patient_info(mute_popup=True)
    if not info: return None
    demo_no = info["demographic_no"]

    measurement_query = f"""
        SELECT m.type, MAX(m.dateObserved) AS latest_date
        FROM measurements m
        WHERE m.demographicNo = {demo_no}
          AND m.type IN ('ECG', 'ECHO1', 'EST', 'SECHO', 'HOLT')
          AND m.dateObserved IS NOT NULL
        GROUP BY m.type
    """
    rows = chatbot.db_conn.query_database(measurement_query)

    for row in rows:
        test_type = row["type"]
        latest_date = row["latest_date"]

        if test_type in test_types and latest_date:
            results[test_types[test_type]] = str(latest_date)[:10]

    return results

def show_edit_transcription_popup(formatted_message):
    # Skip PHI scrubbing for OSCAR_FEEDBACK since extract_patient_notes already removes sensitive info
    if selected_prompt.get() == "OSCAR_FEEDBACK":
        # Use unscrubbed message for OSCAR_FEEDBACK
        cleaned_message = formatted_message
    else:
        # scrubadub's email detector also matches "<word> at <x>.<y>", which turns dictated
        # medications such as "Lipitor at h.s." into {{EMAIL}}; only real "@" emails are scrubbed (below).
        scrubber = scrubadub.Scrubber()
        scrubber.remove_detector('email')

        scrubbed_message = scrubber.clean(formatted_message)

        # Additional regex scrubbing
        cleaned_message = scrubbed_message
        re_email = re.compile(r'\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b')  # Email addresses
        re_ohip_plain = re.compile(r'\b\d{10}\b')  # 10 digit OHIP
        re_ohip_dashed = re.compile(r'\b(\d{4})-(\d{3})-(\d{3})(?:[- ]?[A-Za-z]{2})?\b')  # OHIP with dashes
        re_postal = re.compile(r'\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d\b', re.IGNORECASE)  # Canadian postal codes
        re_address = re.compile(r'\b\d+ [A-Z][a-z]+ (Street|St|Avenue|Ave|Road|Rd|Drive|Dr)\b', re.IGNORECASE)  # Street addresses

        scrub_patterns = [
            (re_email, '{{EMAIL}}'),
            (re_ohip_plain, '{{OHIP}}'),
            (re_ohip_dashed, '{{OHIP}}'),
            (re_postal, '{{POSTAL_CODE}}'),
            (re_address, '{{ADDRESS}}'),
        ]

        for regex, replacement in scrub_patterns:
            cleaned_message = regex.sub(replacement, cleaned_message)

    if (app_settings.editable_settings["Use Local LLM"] or is_private_ip(app_settings.editable_settings["Model Endpoint"])) and not app_settings.editable_settings["Show Scrub PHI"]:
        generate_note_thread(cleaned_message)
        return
    
    popup = tk.Toplevel(root)
    popup.title("Send Patient Notes" if selected_prompt.get() == "OSCAR_FEEDBACK" else "Scrub PHI Prior to GPT")
    popup.iconbitmap(get_file_path('assets','logo.ico'))
    text_area = scrolledtext.ScrolledText(popup, height=20, width=80)
    text_area.pack(padx=10, pady=10)
    text_area.insert(tk.END, cleaned_message)

    # Show recent cardiac test dates for complete consult prompts
    if selected_prompt.get() in {"Consult Complete", "Consult Complete + MH"}:
        recent_tests_frame = tk.LabelFrame(popup, text="Recency of Measurements", padx=8, pady=5)
        recent_tests_frame.pack(fill="x", padx=10, pady=(0, 10))

        recent_test_dates = get_recent_cardiac_test_dates()
        if recent_test_dates:
            test_names = ["ECG", "Echo", "EST", "SEcho", "Holter"]
            cutoff_date = datetime.now().date() - timedelta(days=30)
            
            for test in test_names:
                date_text = recent_test_dates.get(test, "never")

                if date_text == "never":
                    text_color = "red"
                else:
                    try:
                        test_date = datetime.strptime(
                            date_text[:10], "%Y-%m-%d"
                        ).date()
                        text_color = "red" if test_date < cutoff_date else "black"
                    except (ValueError, TypeError):
                        text_color = "red"

                tk.Label(
                    recent_tests_frame,
                    text=f"{test}: {date_text}",
                    fg=text_color,
                    anchor="w",
                ).pack(side="left", padx=(0, 12))

    def on_proceed():
        edited_text = text_area.get("1.0", tk.END).strip()
        popup.destroy()
        generate_note_thread(edited_text)        

    proceed_button = tk.Button(popup, text="Send Patient Notes" if selected_prompt.get() == "OSCAR_FEEDBACK" else "Proceed", command=on_proceed)
    proceed_button.pack(side=tk.RIGHT, padx=10, pady=10)

    # Cancel button
    cancel_button = tk.Button(popup, text="Cancel", command=popup.destroy)
    cancel_button.pack(side=tk.LEFT, padx=10, pady=10)



def generate_note_thread(text: str):
    """
    Generate a note from the given text and update the GUI with the response.

    :param text: The text to generate a note from.
    :type text: str
    """
    global GENERATION_THREAD_ID

    thread = threading.Thread(target=generate_note, args=(text,))
    thread.start()

    GENERATION_THREAD_ID = thread.ident

    def cancel_note_generation(thread_id):
        """Cancels any ongoing note generation.
        
        Sets the global flag to stop note generation operations.
        """
        global GENERATION_THREAD_ID

        try:
            kill_thread(thread_id)
        except Exception as e:
            # Log the error message
            # TODO implment system logger
            print(f"An error occurred: {e}")
        finally:
            GENERATION_THREAD_ID = None

    loading_window = LoadingWindow(root, "Generating Note.", "Generating Note. Please wait.", on_cancel=lambda: cancel_note_generation(GENERATION_THREAD_ID))
    

    def check_thread_status(thread, loading_window):
        if thread.is_alive():
            root.after(500, lambda: check_thread_status(thread, loading_window))
        else:
            loading_window.destroy()

    root.after(500, lambda: check_thread_status(thread, loading_window))

def upload_file():
    global uploaded_file_path
    global file_path

    initialdir = app_settings.editable_settings.get("Default Upload Folder", ".")
    if not os.path.exists(initialdir):
        print(f"Default upload folder '{initialdir}' does not exist. Change default folder in settings.")
        initialdir = '.'

    file_paths = filedialog.askopenfilenames(
        filetypes=(("PDF and Text Files", "*.pdf *.txt"),
                   ("Audio files", "*.wav *.mp3"),),
        initialdir=initialdir
    )

    if len(file_paths) > 1:
        threaded_folder_reading(file_paths)

    else:

        file_path = file_paths[0]
        uploaded_file_path = file_paths[0]
        
        ftype = file_path.rsplit(".")[-1]

        if ftype in ["wav", "mp3"]:
            uploaded_file_path = file_path
            threaded_send_audio_to_server()
        elif ftype in ["pdf", "txt"]:
            threaded_file_reading()

        start_flashing()

    

def start_flashing():
    global is_flashing
    is_flashing = True
    flash_circle()

def stop_flashing():
    global is_flashing
    is_flashing = False
    blinking_circle_canvas.itemconfig(circle, fill='white')  # Reset to default color

def flash_circle():
    if is_flashing:
        current_color = blinking_circle_canvas.itemcget(circle, 'fill')
        new_color = 'blue' if current_color != 'blue' else 'black'
        blinking_circle_canvas.itemconfig(circle, fill=new_color)
        root.after(1000, flash_circle)  # Adjust the flashing speed as needed

def send_and_flash():
    start_flashing()
    send_and_receive()



def start_auto_processing_thread():
    """
    Launches the automated processing on a background thread.
    """
    global auto_process_thread, auto_processor
    
    auto_processor = AutoProcessor(app_settings, send_text_to_chatgpt, ai_prompts, append_log, patient_db=patient_db)
    
    auto_process_thread = threading.Thread(
        target=auto_processor.run, 
        daemon=True
    )
    auto_process_thread.start()



def append_log(text, new_line=True):
    """
    Thread-safe way to append text to the textbox from the background thread.
    """
    if new_line: text += "\n"
    auto_process_tbox.after(0, lambda: auto_process_tbox.insert("end", text))
    auto_process_tbox.after(0, lambda: auto_process_tbox.see("end"))


def copy_text(widget):
    text = widget.get("1.0", tk.END)
    pyperclip.copy(text)

def add_placeholder(event, text_widget, placeholder_text="Text box"):
    if text_widget.get("1.0", "end-1c") == "":
        text_widget.insert("1.0", placeholder_text)
        text_widget.config(fg='grey')

def remove_placeholder(event, text_widget, placeholder_text="Text box"):
    if text_widget.get("1.0", "end-1c") == placeholder_text:
        text_widget.delete("1.0", "end")
        text_widget.config(fg='black')

def load_stt_model(event=None):
    thread = threading.Thread(target=_load_stt_model_thread, daemon=True)
    thread.start()

def _load_stt_model_thread():
    global stt_local_model
    
    if not WHISPER_AVAILABLE:
        messagebox.showerror(
            "Whisper Unavailable",
            "The package openai-whisper is not installed.\n\n"
            "Please install the package or use Remote Whisper."
        )
        return
    
    model = app_settings.editable_settings["Whisper Model"].strip()
    # Create a loading window to display the loading message
    stt_loading_window = LoadingWindow(root, "Speech to Text", "Loading Speech to Text. Please wait.")
    print(f"Loading STT model: {model}")
    try:
        # Load the specified Whisper model
        stt_local_model = whisper.load_model(model)
        print("STT model loaded successfully.")
    except Exception as e:
        print(f"Failed to load STT model '{model}': {e}")
        stt_local_model = None
        messagebox.showerror(
            "Speech-to-Text Error",
            "We couldn't load the speech-to-text model.\n\n"
            "Please try again or select a different speech-to-text model in Settings.\n\n"
            "If the problem continues, contact support."
        )
    finally:
        stt_loading_window.destroy()
        print("Closing STT loading window.")


def read_file_text():
    global file_path

    initialdir = app_settings.editable_settings.get("Default Upload Folder", ".")
    # Check if exists
    if not os.path.exists(initialdir):
        print(f"Default upload folder '{initialdir}' does not exist. Change default folder in settings.")
        initialdir = '.'
    
    file_path = filedialog.askopenfilename(
        filetypes=[("PDF and Text Files", "*.pdf *.txt")],
        initialdir=initialdir
    )
    if file_path:
        threaded_file_reading()  # Add this line to process the file immediately


def download_results():
    """
    Downloads AI outputted text as either a .txt file or .hl7 file.
    """
    # If file was uploaded, create default file name based on pdf name
    global file_path
    default_name = ""
    if 'file_path' in globals() and file_path:
        default_name = os.path.basename(file_path)
        # Remove type ending
        default_name = default_name.rsplit('.', 1)[0]

    initialdir = app_settings.editable_settings.get("Default Download Folder", ".")
    # Check if exists
    if not os.path.exists(initialdir):
        print(f"Default download folder '{initialdir}' does not exist. Change default folder in settings.")
        initialdir = '.'    
    
    # User select file path and type (for now only hl7s and txts)
    download_path = filedialog.asksaveasfilename(
        title="Save Downloaded File As",
        defaultextension=".hl7",
        filetypes=[("HL7 Files", "*.hl7"), ("Text Files", "*.txt")],
        initialfile=default_name,
        initialdir=initialdir
    )

    if download_path:
        print("File will be saved as:", download_path)
    else:
        print("No file selected")
        return

    # Get AI response text
    text = response_display.scrolled_text.get("1.0", tk.END).strip()

    # Right text to selected path
    with open(download_path, "w") as f:
        f.write(text)



# How to analyse the plan for eForms: "keyword" (free, instant, can only decide whether to open
# the forms) or "llm" (one extra model call per Insert Consult, more accurate, and also extracts
# the specific medication changes used to pre-fill the medication eForm). Flip to switch.
# The analysis and form-filling logic lives in utils/med_eform.py.
_MED_GATE_MODE = "llm"

_MED_FORM_PREFIX = "0.1Rfx"


def _find_eform_fid(prefix: str):
    """Look up an eForm's fid by exact name, then by name prefix. Returns None if not found."""
    eforms = getattr(eform_selection_panel, "eforms", None) or {}
    if not eforms and hasattr(eform_selection_panel, "_load_eforms"):
        try:
            eforms = eform_selection_panel._load_eforms() or {}
        except Exception as e:
            print(f"Could not load eForms: {e}")
            return None
    fid = eforms.get(prefix)
    if fid is None:
        fid = next((f for name, f in eforms.items() if str(name).startswith(prefix)), None)
    return fid


def _log_eform_decision(name: str, opened: bool, explanation: str | None) -> None:
    """Print whether an eForm opened and the LLM's one-sentence reason for its decision."""
    status = "OPENED" if opened else "NOT OPENED"
    reason = (explanation or "No LLM explanation (keyword mode or LLM fallback).").strip()
    print(f"[eForm] {name}: {status} — {reason}")


def _open_relevant_eforms(consult_text: str = ""):
    plan_text = extract_plan_section(consult_text) or ""
    if not plan_text:
        # Reading the whole note instead used to pick up medications and old results from the HPI /
        # history and open eForms the PLAN never asked for, so without a PLAN nothing is opened.
        print("[eForm] No PLAN section found in the consult (looked for \"PLAN\" and \"Plan:\"); not auto-opening any eForms. Open them manually if needed.")
        for name in ("Medication", "Labs", "Requisition"):
            _log_eform_decision(name, False, "no PLAN section found in the consult")
        return
    scope = plan_text
    decisions = med_eform.analyze_plan_for_eforms(scope, send_text_to_chatgpt, _MED_GATE_MODE)
    print(f"eForm decisions: {decisions}")
    explanations = decisions.get("explanations") or {}

    med_window = None
    labs_window = None
    requisition_window = None

    # Open the meds eform, if necessary
    if decisions["medication"]["open"]: med_window = _open_medication_eform(decisions["medication"]["changes"])
    else: print("No medication change detected in the plan; skipping medication eForm")

    # Open the labs eform, if necessary
    if decisions["labs"] and decisions["lab_period"]: 
        labs_window = _open_labs_eform(decisions["lab_checkboxes"], decisions["lab_period"])
    elif decisions["labs"]: labs_window = _open_labs_eform(decisions["lab_checkboxes"])
    else: print("No labwork requirement detected in the plan; skipping labs eForm")
        
    # Open the requisition eform, if necessary
    if decisions["requisition"]:
        requisition_window = _open_requisition_eform(
            decisions["requisition_period"], 
            decisions["requisition_period_reason"], 
            decisions["requisition_diagnostics"], 
            decisions["holter_period"],
            decisions.get("requisition_indications"),
        )
    else:
        print("No requisition test (ECG, echo, Holter, ...) requested in the plan; skipping requisition eForm")

    # Log each decision and whether the form actually opened, with the model's reason.
    _log_eform_decision("Medication", bool(med_window), explanations.get("medication"))
    _log_eform_decision("Labs", bool(labs_window), explanations.get("labs"))
    _log_eform_decision("Requisition", bool(requisition_window), explanations.get("requisition"))

    # Pop windows to the foreground in the correct order
    driver = oscar.driver
    for handle in (requisition_window, labs_window, med_window):
        if handle: _focus_eform_window(driver, handle)


REQUISITION_GENERATION_PROMPT = "Requisition Generation"


def _most_recent_letter(demo_no):
    """fdid, form name and date of the patient's most recent letter eForm (0letter), or None."""
    if not eform_selection_panel._ensure_db_conn():
        return None
    rows = eform_selection_panel.db_conn.query_database(f"""
        SELECT fdid, form_name, form_date
        FROM eform_data
        WHERE demographic_no = {int(demo_no)}
          AND form_name LIKE '%letter%'
        ORDER BY form_date DESC, fdid DESC
        LIMIT 1;
    """)
    return rows[0] if rows else None


def generate_requisition_from_latest_note():
    """"Requisition Generation" prompt: open the requisition eForm (fid 698) for the patient open in
    Oscar, filled from the PLAN of their most recent letter, with the same rules as after a consult
    upload. Only the requisition form is opened (no medication / lab form); nothing is submitted."""
    def finish(message):
        print(f"[Requisition Generation] {message}")
        display_text(message)

    if oscar is None or oscar.driver is None:
        messagebox.showwarning(REQUISITION_GENERATION_PROMPT, "Oscar is not connected. Click \"Open Oscar\" first.")
        return finish("Oscar is not connected.")
    demo_no = oscar.get_demographic_no()
    if demo_no is None:
        messagebox.showwarning(REQUISITION_GENERATION_PROMPT, "Please open the encounter page of the patient first.")
        return finish("No patient encounter page is open in Oscar.")
    try:
        letter = _most_recent_letter(demo_no)
    except Exception as e:
        return finish(f"Could not look up the patient's letters ({type(e).__name__}): {e}")
    if not letter:
        messagebox.showwarning(REQUISITION_GENERATION_PROMPT, "This patient has no letter in Oscar.")
        return finish("No letter found for this patient.")

    # The most recent letter may be from an earlier visit if today's note is not in Oscar yet.
    patient = _fetch_patient_name(demo_no) or "this patient"
    if not messagebox.askyesno(
            REQUISITION_GENERATION_PROMPT,
            f"Use the most recent letter for {patient}?\n\n{letter['form_name']} - {letter['form_date']}\n\n"
            "Tests requested in its PLAN will be ticked on the requisition eForm."):
        return finish("Cancelled.")

    def worker():
        try:
            text = oscar.get_0letter_text(letter["fdid"])
            plan_text = extract_plan_section(text or "")
            if not plan_text:
                # Same rule as the consult upload: without a PLAN the whole letter is not used instead.
                _log_eform_decision("Requisition", False, "no PLAN section found in the letter")
                return root.after(0, finish, f"No PLAN section found in the letter of {letter['form_date']} "
                                             "(looked for \"PLAN\" and \"Plan:\"); no requisition generated.")
            decisions = med_eform.analyze_plan_for_eforms(plan_text, send_text_to_chatgpt, _MED_GATE_MODE)
            print(f"eForm decisions: {decisions}")
            explanation = (decisions.get("explanations") or {}).get("requisition")
            if not decisions["requisition"]:
                _log_eform_decision("Requisition", False, explanation)
                return root.after(0, finish, f"No requisition test (ECG, echo, Holter, ...) requested in the PLAN of "
                                             f"the letter of {letter['form_date']}; requisition eForm not opened.")
            requisition_window = _open_requisition_eform(
                decisions["requisition_period"],
                decisions["requisition_period_reason"],
                decisions["requisition_diagnostics"],
                decisions["holter_period"],
                decisions.get("requisition_indications"),
            )
            _log_eform_decision("Requisition", bool(requisition_window), explanation)
            if requisition_window:
                _focus_eform_window(oscar.driver, requisition_window)
            tests = ", ".join(decisions["requisition_diagnostics"])
            period = decisions["requisition_period"] or "date from the form's Dater"
            root.after(0, finish, (f"Requisition eForm opened from the letter of {letter['form_date']}.\n\n"
                                   f"Tests: {tests}\nBook for: {period}" if requisition_window
                                   else "The requisition eForm could not be opened; see the console."))
        except Exception as e:
            root.after(0, finish, f"Requisition generation failed ({type(e).__name__}): {e}")

    display_text(f"Reading the PLAN of the letter of {letter['form_date']}...")
    threading.Thread(target=worker, daemon=True).start()


# ── Referral letters -> requisition eForm (fid 716) ──────────────────────────────
# "Referral Requisition" prompt: paste or upload a new patient's referral letter into the input box,
# open the patient's encounter page and click Populate. The requested tests and indications are read
# from the text and the 716 form is opened filled in for the doctor to check and submit (it is never
# submitted here).
REFERRAL_REQUISITION_PROMPT = "Referral Requisition"


def referral_requisition_from_input():
    def finish(message):
        print(f"[{REFERRAL_REQUISITION_PROMPT}] {message}")
        display_text(message)

    text = user_input.scrolled_text.get("1.0", tk.END).strip()
    if not text:
        messagebox.showwarning(REFERRAL_REQUISITION_PROMPT, "Paste or upload the referral letter into the input box first.")
        return finish("No referral text in the input box.")
    if oscar is None or oscar.driver is None:
        messagebox.showwarning(REFERRAL_REQUISITION_PROMPT, "Oscar is not connected. Click \"Open Oscar\" first.")
        return finish("Oscar is not connected.")
    demo_no = oscar.get_demographic_no()
    if demo_no is None:
        messagebox.showwarning(REFERRAL_REQUISITION_PROMPT, "Please open the encounter page of the patient first.")
        return finish("No patient encounter page is open in Oscar.")

    def worker():
        try:
            form_json = get_referral_json()
            raw = send_text_to_chatgpt(referral_requisition.build_referral_prompt(text, form_json))
            result = referral_requisition.parse_referral_response(raw, form_json)
            if not result["tests"]:
                return root.after(0, finish, "No test requested in the referral; requisition eForm not opened.\n\n"
                                             f"{result['explanation']}")
            window, fill = _open_referral_requisition_eform(demo_no, result["fields"])
            if window:
                _focus_eform_window(oscar.driver, window)
            lines = []
            for test in result["tests"]:
                value, from_dropdown = result["indications"].get(test, (None, False))
                lines.append(f"- {test}: {value} ({'dropdown' if from_dropdown else 'free text'})" if value
                             else f"- {test}: no indication")
            missing = f"\n\nNot found on the form: {', '.join(fill['missing'])}" if fill["missing"] else ""
            root.after(0, finish, f"Requisition eForm opened; check it and submit.\n\n" + "\n".join(lines)
                       + missing + (f"\n\n{result['explanation']}" if result["explanation"] else ""))
        except Exception as e:
            root.after(0, finish, f"Referral requisition failed ({type(e).__name__}): {e}")

    display_text("Reading the referral...")
    threading.Thread(target=worker, daemon=True).start()


def _open_referral_requisition_eform(demo_no, fields):
    """Open the 716 eForm for `demo_no` with the same link oscar.open_new_eform uses (Oscar fills the
    patient / doctor details from it), fill `fields`, and return to the main Oscar window.
    Returns (window handle, fill result); the form window stays open, unsaved."""
    driver = oscar.driver
    link = oscar.new_eform_template.format(fid=referral_requisition.REFERRAL_REQUISITION_FID, demo_no=int(demo_no))
    before = set(driver.window_handles)
    driver.execute_script("window.open(arguments[0], '_blank', 'width=800,height=600');", link)
    try:
        WebDriverWait(driver, 10).until(lambda d: len(set(d.window_handles) - before) > 0)
        window = next(h for h in driver.window_handles if h not in before)
        driver.switch_to.window(window)
        WebDriverWait(driver, 20).until(lambda d: d.execute_script(
            "return document.readyState === 'complete' && location.href !== 'about:blank';"))
        return window, driver.execute_script(referral_requisition.FILL_FIELDS_JS, fields)
    finally:
        driver.switch_to.window(oscar.home_window)


def _open_medication_eform(changes: list[dict] | None = None):
    """Auto-open the medication prescription eForm (0.1Rfx), click its reset button so it starts
    from a clean prescription body, then pre-fill that body with the plan's medication changes.
    Only the prescription body is filled: the current-meds list is written back to the chart on
    submit, so it is left for the clinician to update. Nothing is submitted automatically."""
    fid = _find_eform_fid(_MED_FORM_PREFIX)
    if fid is None:
        print(f"Medication eForm '{_MED_FORM_PREFIX}' not found; skipping auto-open")
        return

    # Remember the windows open before, so we can switch to exactly the new one afterwards
    # without touching the letter window that the consult upload just opened.
    try:
        before = set(oscar.driver.window_handles)
    except Exception:
        before = set()

    try:
        oscar.open_new_eform(fid)
    except Exception as e:
        # Never let the auto-open disturb the consult upload that already succeeded.
        print(f"Could not auto-open medication eForm: {e}")
        return

    # Reset the form so it does not carry stale pre-filled meds, then fill the prescription body.
    try:
        after = oscar.driver.window_handles
        new_windows = [h for h in after if h not in before]
        med_window = new_windows[-1] if new_windows else after[-1]
        oscar.driver.switch_to.window(med_window)
        result = med_eform.prepare_med_form(oscar.driver, oscar.wait, changes)
        print(f"Medication form reset button -> {result['reset']}")
        if result["fill"] is not None:
            print(f"Medication form prescription body -> {result['fill']}: {result['rx_text']!r}")
    except Exception as e:
        print(f"Could not prepare medication form ({type(e).__name__}): {e}")
    finally:
        return med_window


def _open_labs_eform(checkbox_strings: set | None, labwork_period: str = "2w"):
    LABS_FORM_FID = 659
    # None when no checkbox analysis ran (LLM failed / keyword mode) or it found nothing to tick;
    # the form still opens, just without pre-selected checkboxes.
    checkbox_strings = {str(s).strip() for s in (checkbox_strings or []) if str(s).strip()}

    print(f"oscar object: {oscar}")
    print(f"oscar.driver: {getattr(oscar, 'driver', 'None')}")
    print(f"checkbox_strings: {checkbox_strings}")

    try:
        if oscar.driver is None:
            raise RuntimeError("Oscar WebDriver is None; it may have been cleaned up.")

        checkbox_data = oscar.get_eform_checkboxes(LABS_FORM_FID)
        checkbox_vars = {}
        for checkbox in checkbox_data:
            name = checkbox["name"]
            var = name.strip() in checkbox_strings
            checkbox_vars[name] = var
        data_lookup = {cb["name"].strip(): cb for cb in checkbox_data} if checkbox_data else {}
        checkboxes = [data_lookup[k.strip()] for k, v in checkbox_vars.items() if v and k.strip() in data_lookup]

        # Codes the model returned that are not checkboxes on this form are otherwise dropped
        # silently, which looks the same as "no labs in the plan".
        unknown = sorted(checkbox_strings - set(data_lookup))
        if unknown:
            print(f"Lab codes from the LLM not found on eForm {LABS_FORM_FID}: {unknown}")
        if not checkboxes:
            print("No lab checkboxes to tick; opening the labs eForm without pre-selection")
        # Clinician rule: only one checkbox per lab eForm, the most extensive one.
        checkboxes = pick_most_extensive(checkboxes)

        driver = oscar.driver
        before = set(driver.window_handles)
        oscar.open_new_eform(LABS_FORM_FID, checkboxes)

        # Update labwork date element in the window just opened (found by comparing handles, since
        # the medication eForm may have opened just before it), then always return to the main
        # window so later driver calls do not run against the labs eForm.
        try:
            WebDriverWait(driver, 10).until(lambda d: len(set(d.window_handles) - before) > 0)
            labs_window = next(h for h in driver.window_handles if h not in before)
            driver.switch_to.window(labs_window)

            test_date = _offset_from_today(labwork_period).strftime("%Y-%m-%d")
            posttestd = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "Posttestd")))
            posttestd.clear()
            posttestd.send_keys(test_date)

            relative_test_date = _translate_period(labwork_period)
            subject_textbox = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "subject")))
            subject_textbox.clear()
            subject_textbox.send_keys(f"Do in {relative_test_date}.")

            print(f"Updated labwork completion date to {test_date}")
        except Exception as e:
            print(f"Could not update labwork completion date ({type(e).__name__}): {e}")
        finally:
            return labs_window
    except Exception as e:
        print(f"Could not auto-open labs eForm ({type(e).__name__}): {e}")
        return


def _offset_from_today(labwork_period: str) -> date:
    """
    Calculate the requested lab date relative to today.
    Supported periods: d (days), w (weeks), m (months), y (years).
    """
    match = re.fullmatch(r"\s*(\d+)\s*([dwmy])\s*", labwork_period.lower())
    if not match: raise ValueError(f'"{labwork_period}" is not a valid period')

    amount = int(match.group(1))
    unit = match.group(2)
    today = date.today()

    if unit == "d": return today + timedelta(days=amount)
    elif unit == "w": return today + timedelta(weeks=amount)
    elif unit == "m": return today + relativedelta(months=amount)
    elif unit == "y": return today + relativedelta(years=amount)
    else: raise ValueError(f'"{labwork_period}" is not a valid period')


def _translate_period(labwork_period: str) -> str:
    """
    Returns the labwork period as a full string.
    Supported periods: d -> days, w -> weeks, m -> months, y -> years.
    """
    match = re.fullmatch(r"\s*(\d+)\s*([dwmy])\s*", labwork_period.lower())
    if not match: raise ValueError(f'"{labwork_period}" is not a valid period')

    amount = match.group(1)
    unit = match.group(2)
    suffix = "s" if amount != 1 else ""

    if unit == "d": return amount + " day" + suffix
    elif unit == "w": return amount + " week" + suffix
    elif unit == "m": return amount + " month" + suffix
    elif unit == "y": return amount + " year" + suffix
    else: raise ValueError(f'"{labwork_period}" is not a valid period')


def _open_requisition_eform(requisition_period: str, requisition_period_reason: str, data: list, holter_period: str,
                            indications: dict | None = None):
    REQUISITION_FORM_FID = 698

    try:
        driver = oscar.driver
        if driver is None:
            raise RuntimeError("Oscar WebDriver is None; it may have been cleaned up.")
        before = set(driver.window_handles)
        oscar.open_new_eform(REQUISITION_FORM_FID)

        try:
            WebDriverWait(driver, 10).until(lambda d: len(set(d.window_handles) - before) > 0)
            requisition_window = next(h for h in driver.window_handles if h not in before)
            driver.switch_to.window(requisition_window)

            # tick desired checkboxes; one box that cannot be found must not stop the others being ticked
            for checkbox in data:
                if checkbox == "contrastecho" and not "echo" in data:
                    print(f"contrastecho checkbox cannot be ticked due to echo checkbox not being ticked")
                    continue
                try:
                    _tick_requisition_box(driver, checkbox)
                    if checkbox == "holter" and holter_period:
                        _tick_requisition_box(driver, holter_period + 'r' if holter_period.endswith('h') else holter_period + 'k')
                except Exception as e:
                    print(f'Could not tick "{checkbox}" ({type(e).__name__}): {e}')

            # Click the form's own "Dater" button so it fills the Cor Health indications from the
            # patient's meds and previous echo. It also applies the form's rules (e.g. unticks ECG
            # when EST / stress echo is ticked) and sets its own date; the reason and the date
            # below are written afterwards so they still come from the PLAN.
            _click_requisition_dater(driver)

            # Dater unticks ECG when EST / stress echo is ticked, but a Holter always comes with an ECG.
            if "holter" in data and not driver.find_element(By.ID, "ecg").is_selected():
                try:
                    _tick_requisition_box(driver, "ecg")
                except Exception as e:
                    print(f'Could not re-tick "ecg" for the Holter ({type(e).__name__}): {e}')

            # Indications the PLAN gives for each ticked test, as a "— Plan: ..." part after what the box
            # already holds (carried over from the last form, or written by Dater). The previous visit's
            # "— Plan: ..." part is replaced, so the box does not grow at every visit.
            for checkbox in med_eform.REQUISITION_INDICATION_TESTS:
                try:
                    if not driver.find_element(By.ID, checkbox).is_selected():
                        continue
                    indication = driver.find_element(By.ID, f"{checkbox}-input")
                    existing_indication = indication.get_attribute("value") or ""
                    updated_indication = med_eform.merge_indication(existing_indication, (indications or {}).get(checkbox))
                    if updated_indication == existing_indication.strip():
                        continue
                    indication.clear()
                    indication.send_keys(updated_indication)
                    print(f'"{checkbox}" indication: {updated_indication}')
                except Exception as e:
                    print(f'Could not fill the "{checkbox}" indication ({type(e).__name__}): {e}')

            # annotate indication with the reason why the requisition date was changed from the default (1 year)
            if requisition_period_reason:
                for checkbox in data:
                    if checkbox not in ["ecg", "echo", "stecho", "est", "holter"]:
                        continue
                    if not driver.find_element(By.ID, checkbox).is_selected():
                        continue  # unticked by the form's own rules (Dater)
                    indication = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, f"{checkbox}-input")))
                    existing_indication = indication.get_attribute("value").strip()
                    if existing_indication:
                        updated_indication = existing_indication + " — " + requisition_period_reason
                    else:
                        updated_indication = "divergence from typical 1-year timeline: " + requisition_period_reason
                    # replace rather than append, so the existing indication is not typed in twice
                    indication.clear()
                    indication.send_keys(updated_indication)
                    break

            # update "Urgency" date
            URGENCY_ELEMENT_ID = "urgency3"
            urgency_element = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, URGENCY_ELEMENT_ID)))
            if not urgency_element.is_selected():
                urgency_element.click()
            print(f'"Book for" checkbox ticked')

            # no follow-up period in the PLAN: keep the date Dater worked out
            if requisition_period:
                date_input = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "date")))
                date_input.clear()
                date_input.send_keys(_offset_from_today(requisition_period).strftime("%Y-%m-%d"))
        except Exception as e:
            print(f"Failed to edit requisition eForm ({type(e).__name__}): {e}")
        finally:
            return requisition_window
    except Exception as e:
        print(f"Failed to open requisition eForm ({type(e).__name__}): {e}")
        return


def _tick_requisition_box(driver, box_id):
    """Tick one checkbox / radio on the requisition eForm (clicking it, so its onclick runs)."""
    element = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, box_id)))
    if not element.is_selected():
        element.click()
    print(f'"{box_id}" checkbox ticked')


def _click_requisition_dater(driver):
    """Click the requisition eForm's "Dater" button (daterl()), which fills the indications the form
    can work out itself."""
    try:
        result = driver.execute_script(
            "var b = document.querySelector('input[name=\"dater\"]');"
            "if (!b) { return 'Dater button not found'; }"
            "b.click(); return 'clicked';"
        )
        print(f'"Dater" button -> {result}')
    except Exception as e:
        print(f'Could not click "Dater" ({type(e).__name__}): {e}')


def _focus_eform_window(driver, window_handle):
    """Switch to a specific eForm window and request foreground activation."""
    try:
        driver.switch_to.window(window_handle)
        _focus_firefox_window(driver)
    except Exception as e:
        print(f"Could not focus eForm window ({type(e).__name__}): {e}")


def _focus_firefox_window(driver):
    """Best-effort attempt to bring the Firefox window containing the eForm
    to the Windows foreground."""
    try:
        page_title = driver.title.strip()
        candidates = []

        def collect_window(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return

            title = win32gui.GetWindowText(hwnd)
            if not title:
                return

            # Prioritize the window whose title matches the current Selenium page
            if page_title and page_title.lower() in title.lower():
                candidates.insert(0, hwnd)
            elif "firefox" in title.lower():
                candidates.append(hwnd)

        win32gui.EnumWindows(collect_window, None)

        if not candidates:
            print("Could not find a Firefox window to focus.")
            return False

        hwnd = candidates[0]

        # Restore the window if minimized, then request foreground activation.
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)

        print(f"Requested Firefox foreground activation: "
              f"{win32gui.GetWindowText(hwnd)!r}")
        return True

    except Exception as e:
        print(f"Could not focus Firefox ({type(e).__name__}): {e}")
        return False


def upload_consult():
    """Uploads the LLM response to patient consult to most recent 0letter eform,
    then auto-opens the medication (0.1Rfx) eForm fill page."""
    text = response_display.scrolled_text.get("1.0", tk.END).strip()
    fdid = eform_selection_panel.get_most_recent_0letter()
    oscar.insert_text_into_0letter(fdid=fdid, consult=text)
    _open_relevant_eforms(text)

def upload_consult_and_mh():
    """
    Uploads the LLM response to patient consult and response to medical history
    to patient's most recent 0letter eform.
    """

    # Save patient-encounter conversation text
    encounter_convo = user_input.scrolled_text.get("1.0", tk.END).strip()


    # Prompt User for which documents they want scanned
    popup = tk.Toplevel(root)
    popup.title("Select Options")
    popup.transient(root)
    popup.grab_set()
    popup.geometry("800x500")

    # --- Variables ---
    prompts = tk.StringVar(value="Med Hist 2")

    # --- UI ---
    ttk.Label(popup, text="Prompt").pack(pady=(10, 0))
    ttk.Combobox(
        popup,
        textvariable=prompts,
        values=ai_prompts.list_prompts(),
        state="readonly"
    ).pack(padx=10, pady=(0, 10), fill="x")

    docs_container = ttk.Frame(popup)
    docs_container.pack(
        fill="both",
        expand=True,
        padx=10,
        pady=5
    )
    canvas = tk.Canvas(
        docs_container,
        highlightthickness=0
    )
    scrollbar = ttk.Scrollbar(
        docs_container,
        orient="vertical",
        command=canvas.yview
    )
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(
        side="right",
        fill="y"
    )
    canvas.pack(
        side="left",
        fill="both",
        expand=True
    )

    # Frame inside the canvas containing the checkboxes
    docs_frame = ttk.Frame(canvas)
    canvas_window = canvas.create_window(
        (0, 0),
        window=docs_frame,
        anchor="nw"
    )

    def update_scroll_region(event=None):
        canvas.configure(
            scrollregion=canvas.bbox("all")
        )

    def resize_docs_frame(event):
        canvas.itemconfig(
            canvas_window,
            width=event.width
        )

    def on_mousewheel(event):
        canvas.yview_scroll(
            int(-1 * (event.delta / 120)),
            "units"
        )

    docs_frame.bind(
        "<Configure>",
        update_scroll_region
    )
    canvas.bind(
        "<Configure>",
        resize_docs_frame
    )
    canvas.bind_all(
        "<MouseWheel>",
        on_mousewheel
    )

    cols = 2
    defaults = {"DC summary", "CATH"}
    doc_cbs = {}

    for i, doc_type in enumerate(eform_selection_panel.doc_types):
        var = tk.BooleanVar(value=doc_type in defaults)
        doc_cbs[doc_type] = var

        ttk.Checkbutton(
            docs_frame,
            text=doc_type,
            variable=var
        ).grid(
            row=i // cols,
            column=i % cols,
            sticky="w",
            padx=10,
            pady=2
        )

    result = {}

    def on_done():
        result["Prompt"] = prompts.get()
        result["Docs"] = [s for s, v in doc_cbs.items() if v.get()]
        canvas.unbind_all("<MouseWheel>")
        popup.destroy()

    ttk.Button(popup, text="Done", command=on_done).pack(pady=15)

    root.wait_window(popup)
    
    if not result:
        return


    # Prompt User for which prompt they want to choose
    #prompt_dropdown.set(result['Prompt'])
    print(result)
    prompt = ai_prompts.get(result["Prompt"])

    # Read medical history and generate response
    med_hist = eform_selection_panel.load_medical_history(doc_names=result["Docs"], display=False)
    med_hist_resp = chatbot.ai_conn.send_message(content=med_hist, pre_prompt=prompt)

    #generate_note(med_hist_input)
    #med_hist_resp = response_display.scrolled_text.get("1.0", tk.END).strip()

    # Generate consult note with generated medical history
    encounter_convo = "MEDICAL HISTORY:\n" + med_hist_resp + "\n\n" + encounter_convo
    #prompt_dropdown.set("Consult")
    #generate_note(encounter_convo)
    
    prompt = with_speaker_rules(ai_prompts.get("Consult"))
    consult = chatbot.ai_conn.send_message(content=encounter_convo, pre_prompt=prompt)
    #consult = response_display.scrolled_text.get("1.0", tk.END).strip()

    # Insert text into 0letter
    fdid = eform_selection_panel.get_most_recent_0letter()
    oscar.insert_text_into_0letter(fdid, consult, med_hist_resp)
    _open_relevant_eforms(consult)

def upload_consult_complete(overwrite):
    text = response_display.scrolled_text.get("1.0", tk.END).strip()
    fdid = eform_selection_panel.get_most_recent_0letter()
    oscar.insert_text_into_0letter_from_headings(fdid, text, overwrite)
    _open_relevant_eforms(text)

def upload_consult_by_type(upload_type, overwrite):
    # With the "Referral Requisition" prompt, Populate fills the requisition from the input box instead.
    if selected_prompt.get() == REFERRAL_REQUISITION_PROMPT: referral_requisition_from_input()
    elif upload_type == "consult": upload_consult()
    elif upload_type == "mh_and_consult": upload_consult_and_mh()
    elif upload_type == "complete_consult": upload_consult_complete(overwrite)
    else: raise ValueError(
        'upload_consult_by_type: upload_type must be one of ["consult", "mh_and_consult", "complete_consult"]'
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  ROOT GRID
# ═══════════════════════════════════════════════════════════════════════════════
# row 0 = mode bar (always visible, fixed height)
# row 1 = active content frame (expands to fill window)
root.grid_rowconfigure(0, weight=0)
root.grid_rowconfigure(1, weight=1)
root.grid_columnconfigure(0, weight=1)


# ═══════════════════════════════════════════════════════════════════════════════
#  MODE BAR 
# ═══════════════════════════════════════════════════════════════════════════════
# Bar at the top of the window that contains buttons to switch between frames
mode_bar = tk.Frame(root)
mode_bar.grid(row=0, column=0, columnspan=14, sticky='ew', padx=0, pady=0)
current_view = "scribe"
scribe_mode_button = tk.Button(
    mode_bar,
    text="📋  Scribe",
    command=lambda: switch_mode("scribe"),
    height=1,
    width=12,
    relief='sunken',    # starts active
)
scribe_mode_button.pack(side='left', padx=(10, 2), pady=4)

chatbot_mode_button = tk.Button(
    mode_bar,
    text="💬  Chatbot",
    command=lambda: switch_mode("chatbot"),
    height=1,
    width=12,
    relief='raised',
)
chatbot_mode_button.pack(side='left', padx=(2, 2), pady=4)

minimal_mode_button = tk.Button(
    mode_bar,
    text="⬡  Minimal",
    command=lambda: switch_mode("minimal"),
    height=1,
    width=12,
    relief='raised',
)
minimal_mode_button.pack(side='left', padx=(2, 2), pady=4)


auto_mode_button = tk.Button(
    mode_bar,
    text="@ Auto Process",
    command=lambda: switch_mode("auto"),
    height=1,
    width=12,
    relief='raised',
)
auto_mode_button.pack(side='left', padx=(2, 10), pady=4)

# ═══════════════════════════════════════════════════════════════════════════════
#  MODE SWITCH LOGIC
# ═══════════════════════════════════════════════════════════════════════════════
_FULL_SIZE   = "1400x800"
_MINIMAL_SIZE = "650x50"    
_AUTO_SIZE = "800x600"

stop_auto_processing = False


def switch_mode(mode: str):
    """Show the requested frame, hide the others, resize window accordingly."""
    global current_view
    scribe_frame.grid_remove()
    chatbot_frame.grid_remove()
    minimal_frame.grid_remove()
    auto_process_frame.grid_remove()

    scribe_mode_button.config(relief='raised')
    chatbot_mode_button.config(relief='raised')
    minimal_mode_button.config(relief='raised')
    auto_mode_button.config(relief='raised')

    _hide_minimal_controls()

    if current_view == "auto":
        if auto_processor:
            auto_processor.stop()
        # Wait for thread to finish gracefully
        if auto_process_thread and auto_process_thread.is_alive():
            auto_process_thread.join(timeout=10)

    if mode == "scribe":
        scribe_frame.grid(row=1, column=0, columnspan=14, sticky='nsew')
        scribe_mode_button.config(relief='sunken')
        root.geometry(_FULL_SIZE)
        current_view = "scribe"

    elif mode == "chatbot":
        chatbot_frame.grid(row=1, column=0, columnspan=14, sticky='nsew')
        chatbot_mode_button.config(relief='sunken')
        root.geometry(_FULL_SIZE)
        current_view = "chatbot"
        _refresh_patient_from_oscar()

    elif mode == "minimal":
        minimal_frame.grid(row=1, column=0, columnspan=14, sticky='nsew')
        minimal_mode_button.config(relief='sunken')
        _show_minimal_controls()
        # Delay resize slightly so the grid has time to settle
        root.after(50, lambda: root.geometry(_MINIMAL_SIZE))
        current_view = "minimal"
    
    elif mode == "auto":
        auto_process_frame.grid(row=1, column=0, columnspan=14, sticky='nsew')
        auto_mode_button.config(relief='sunken')
        root.geometry(_AUTO_SIZE)
        current_view = "auto"
        start_auto_processing_thread()




# ═══════════════════════════════════════════════════════════════════════════════
#  SCRIBE FRAME
# ═══════════════════════════════════════════════════════════════════════════════
scribe_frame = tk.Frame(root)
scribe_frame.grid(row=1, column=0, columnspan=14, sticky='nsew')   # visible at startup

def open_oscar():
    """
    Closes and reopens Selenium Oscar session.
    """
    global oscar
    if chatbot.oscar is not None:
        chatbot.oscar.cleanup()
    chatbot._initialize_oscar()
    # The eForm code uses the module-level `oscar`; rebind it so it doesn't keep the closed session.
    oscar = chatbot.oscar
    eform_selection_panel.oscar = chatbot.oscar

# 14-column spine: cols 0 & 13 = gutters
for c in range(14):
    weight  = 0 if c in (0, 13) else 1
    minsize = 10 if c in (0, 13) else 0
    scribe_frame.grid_columnconfigure(c, weight=weight, minsize=minsize)

scribe_frame.grid_rowconfigure(0, weight=2)   # transcript
scribe_frame.grid_rowconfigure(1, weight=0)   # toolbar row 1
scribe_frame.grid_rowconfigure(2, weight=0)   # toolbar row 2
scribe_frame.grid_rowconfigure(3, weight=3)   # response
scribe_frame.grid_rowconfigure(4, weight=1)   # bottom gutter

# ── Transcript input ──────────────────────────────────────────────────────────
user_input = CustomTextBox(scribe_frame, height=12)
user_input.grid(row=0, column=1, columnspan=8, padx=(5, 2), pady=(12, 4), sticky='nsew')
user_input._id = "input_tbox"

user_input.scrolled_text.insert("1.0", "Transcript of Conversation")
user_input.scrolled_text.config(fg='grey')
user_input.scrolled_text.bind(
    "<FocusIn>",
    lambda e: remove_placeholder(e, user_input.scrolled_text, "Transcript of Conversation"),
)
user_input.scrolled_text.bind(
    "<FocusOut>",
    lambda e: add_placeholder(e, user_input.scrolled_text, "Transcript of Conversation"),
)

# ── Toolbar row 1 ─────────────────────────────────────────────────────────────
mic_button = tk.Button(
    scribe_frame, text="⏺  Record", command=threaded_toggle_recording, height=2, width=10,
)
mic_button.grid(row=1, column=1, pady=(6, 2), sticky='nsew')

pause_button = tk.Button(
    scribe_frame, text="⏸  Pause", command=toggle_pause, height=2, width=10,
)
pause_button.grid(row=2, column=1, pady=(6, 2), sticky='nsew')

send_button = tk.Button(
    scribe_frame, text="Generate Note", command=send_and_flash, height=2, width=13,
)
send_button.grid(row=1, column=2, pady=(6, 2), sticky='nsew')

clear_button = tk.Button(
    scribe_frame, text="Clear", command=clear_application_press, height=2, width=8,
)
clear_button.grid(row=2, column=2, pady=(6, 2), sticky='nsew')

upload_button = tk.Button(
    scribe_frame, text="Upload", command=upload_file, height=2, width=11,
)
upload_button.grid(row=1, column=6, pady=(6, 2), sticky='nsew')

open_oscar_button = tk.Button(
    scribe_frame, text="Open Oscar", command=open_oscar, height=2, width=11,
)
open_oscar_button.grid(row=2, column=6, pady=(6, 2), sticky='nsew')

dropdown_label = tk.Label(scribe_frame, text="Select Prompt", font=("Arial", 8, "bold"))
dropdown_label.grid(row=1, column=4, pady=(8, 0), sticky='sew')

selected_prompt = tk.StringVar(value="Auto")
values = ["Auto", "None", "Scribe"] + ai_prompts.list_prompts() + ["Consult Complete", "Consult Complete + MH",
                                                                   REQUISITION_GENERATION_PROMPT,
                                                                   REFERRAL_REQUISITION_PROMPT]
prompt_dropdown = ttk.Combobox(
    scribe_frame, textvariable=selected_prompt, values=values, state="readonly",
)
prompt_dropdown._id = "prompt_selector"
prompt_dropdown.grid(row=2, column=4, pady=(0, 6), sticky='new')

# "Requisition Generation" is an action, not a note prompt: choosing it runs it straight away and
# puts the previous prompt back, so Generate Note keeps using that one.
_last_note_prompt = selected_prompt.get()


def _on_prompt_selected(_event=None):
    global _last_note_prompt
    if selected_prompt.get() == REQUISITION_GENERATION_PROMPT:
        selected_prompt.set(_last_note_prompt)
        generate_requisition_from_latest_note()
    else:
        _last_note_prompt = selected_prompt.get()


prompt_dropdown.bind("<<ComboboxSelected>>", _on_prompt_selected)

# switch_view_button = tk.Button(
#     scribe_frame, text="Minimize View", command=toggle_minimize_view, height=2, width=12,
# )
# switch_view_button.grid(row=1, column=7, pady=(6, 2), sticky='nsew')

# auto_process_button = tk.Button(
#     scribe_frame, text="Auto Process", command=toggle_auto_process, height=2, width=12,
# )
# auto_process_button.grid(row=2, column=7, pady=(2, 6), sticky='nsew')

blinking_circle_canvas = tk.Canvas(scribe_frame, width=22, height=22, highlightthickness=0)
blinking_circle_canvas.grid(row=1, column=8, rowspan=2, pady=4, sticky='nsew')
circle = blinking_circle_canvas.create_oval(4, 4, 18, 18, fill='white', outline='grey')

# ── Note history sidebar ──────────────────────────────────────────────────────
timestamp_listbox = tk.Listbox(
    scribe_frame,
    height=30,
    selectmode=tk.SINGLE,
    activestyle='dotbox',
    relief='flat',
    highlightthickness=1,
)
timestamp_listbox.grid(
    row=0, column=9, columnspan=2, rowspan=4, padx=(4, 2), pady=12, sticky='nsew',
)
timestamp_listbox.bind('<<ListboxSelect>>', show_response)
timestamp_listbox.insert(tk.END, "Temporary Note History")
timestamp_listbox.config(fg='grey')

# ── Response display ──────────────────────────────────────────────────────────
response_display = CustomTextBox(scribe_frame, height=13, state="normal", new_ui=new_ui)
response_display.grid(
    row=3, column=1, columnspan=8, padx=(5, 2), pady=(4, 12), sticky='nsew',
)
response_display.scrolled_text.insert("1.0", "Medical Note")
response_display.scrolled_text.config(fg='grey')

# ── Lab selection panel ───────────────────────────────────────────────────────
def close_eform_panel():
    eform_selection_panel.hide()
    response_display.grid(
        row=3, column=1, columnspan=8, padx=(5, 2), pady=(4, 12), sticky='nsew',
    )

eform_selection_panel = EformPanel(
    scribe_frame, height=8, close_callback=close_eform_panel, oscar=oscar, db_conn=chatbot.db_conn,
)
eform_selection_panel.grid(row=0, column=11, rowspan=4, padx=(2, 5), pady=12, sticky='nsew')
eform_selection_panel.grid_remove()

# ── Response display callbacks ────────────────────────────────────────────────
if new_ui:
    response_display.set_upload_callback(upload_consult_by_type)
else:
    #response_display.set_med_hist_callback(upload_medical_history)
    response_display.set_consult_callback(upload_consult)
    response_display.set_consult_and_mh_callback(upload_consult_and_mh)
    response_display.set_consult_complete_append_callback(lambda: upload_consult_complete(False))
    response_display.set_consult_complete_overwrite_callback(lambda: upload_consult_complete(True))
response_display.set_get_eforms_callback(get_labs_from_response)
response_display.set_download_callback(download_results)

if app_settings.editable_settings["Enable Scribe Template"]:
    window.create_scribe_template()



# ═══════════════════════════════════════════════════════════════════════════════
#  CHATBOT FRAME
# ═══════════════════════════════════════════════════════════════════════════════
chat_history = []
chat_workflow_choices = ["Auto"] + [name.replace('_', ' ').title() for name in chatbot.workflows]
chat_workflow_index = [0]
chat_current_task = [None]

def _show_saved_chat(saved_id):
    if saved_id is None or saved_id in chat_history:
        return
    chat_history.append(saved_id)
    chat_history_listbox.insert(tk.END, chatbot.get_chat_label(saved_id))

def _reset_chat_log():
    chat_log_display.scrolled_text.config(state='normal')
    chat_log_display.scrolled_text.delete("1.0", tk.END)
    chat_log_display.scrolled_text.insert("1.0", "Chat Log\n\n")
    chat_log_display.scrolled_text.config(fg='grey', state='disabled')

def chatbot_send_message():
    # ongoing task catch
    if chat_current_task[0] is not None and chat_current_task[0].is_running():
        return
    input = chat_user_input.scrolled_text.get("1.0", tk.END).strip()
    if not input or input == "Type a message…":
        return
    chat_user_input.scrolled_text.delete("1.0", tk.END)

    # display user's input message
    chat_log_display.scrolled_text.config(state='normal')
    chat_log_display.scrolled_text.insert(tk.END, f"USER:\n{input}\n\n")
    chat_log_display.scrolled_text.config(state='disabled')
    chat_log_display.scrolled_text.see(tk.END)

    # disable the input box and add placeholder text
    chat_user_input.scrolled_text.insert("1.0", "Chatbot is thinking…")
    chat_user_input.scrolled_text.config(fg='grey', state='disabled')
    chat_send_button.config(state='disabled')

    # get worklow selections
    workflow_select = chat_workflow_button.cget("text")
    # this assumes that the only transformation is removal of spaces and title format
    selected_workflow = None if workflow_select == "Auto" else workflow_select.lower().replace(' ', '_')

    def handle_return(result, error):
        # restore the chat input box
        chat_user_input.scrolled_text.config(fg='black', state='normal')
        chat_user_input.scrolled_text.delete("1.0", tk.END)
        chat_send_button.config(state='normal')
        chat_user_input.scrolled_text.focus_set()
        chat_current_task[0] = None
        chat_user_input.set_cancel_button_active(False)

        if error is not None:
            print(f"Chatbot error: {error}")

            messagebox.showerror(
                "Chatbot Unavailable",
                "The chatbot was unable to produce a response.\n\n"
                "Please try again. If the problem continues, contact support."
            )
            return

        try:
            workflow_type, result, saved_id = result
            # result is WorkflowResult type
            resp = result.response
            sources = result.sources

            if workflow_type is None:
                return

            if saved_id is not None:
                chat_log_display.scrolled_text.config(state='normal')
                chat_log_display.scrolled_text.delete("1.0", tk.END)
                chat_log_display.scrolled_text.config(state='disabled')
                _show_saved_chat(saved_id)
                chat_history_listbox.selection_clear(0, tk.END)
                chat_log_display.scrolled_text.config(state='normal')
                chat_log_display.scrolled_text.insert(tk.END, f"USER:\n{input}\n\n")
                chat_log_display.scrolled_text.config(state='disabled')

            workflow_label = f"[{workflow_type.replace('_', ' ').title()}]"

            chat_log_display.scrolled_text.config(state='normal')
            chat_log_display.scrolled_text.insert(tk.END, f"CHATBOT {workflow_label}:\n{resp}\n")

            if sources:
                src_label = tk.Label(
                    chat_log_display.scrolled_text,
                    text=f"Sources [{len(sources)}]",
                    fg="blue",
                    cursor="hand2",
                    background=chat_log_display.scrolled_text.cget("background")
                )
                chat_log_display.scrolled_text.window_create(tk.END, window=src_label)
                SourcesWindow(root, src_label, sources, chatbot.oscar.open_doc)

            chat_log_display.scrolled_text.insert(tk.END, "\n\n")
            chat_log_display.scrolled_text.config(state='disabled')

            refresh_patient_status()

            # Scroll to the bottom
            # chat_log_display.yview(tk.END)
            chat_log_display.scrolled_text.see(tk.END)

            print("Message sent")

        except Exception as e:
            print(f"Error displaying chatbot response: {e}")

            # Make sure the text widget isn't left in an editable state
            chat_log_display.scrolled_text.config(state='disabled')

            messagebox.showerror(
                "Chatbot Error",
                "The chatbot responded, but we couldn't display the response correctly.\n\n"
                "Please try again. If the problem continues, contact support."
            )

    task = BackgroundTask(
        root, 
        func=chatbot.run, 
        args=(input, selected_workflow),
        on_done = handle_return
    )
    chat_current_task[0] = task
    chat_user_input.set_cancel_button_active(True)
    task.start()

def chatbot_cancel_generation():
    task = chat_current_task[0]

    if task is not None:
        if task.is_running():
            try:
                kill_thread(task.thread_id)
                print("Cancelled chatbot generation")
            except Exception as e:
                print(f"Failed to cancel chatbot generation: {e}")

        task.cancel()

    # send alert in chat logs
    chat_log_display.scrolled_text.config(state='normal')
    chat_log_display.scrolled_text.insert(tk.END, "ALERT:\nprompt cancelled\n")
    chat_log_display.scrolled_text.insert(tk.END, "\n\n")
    chat_log_display.scrolled_text.config(state='disabled')
    chat_log_display.scrolled_text.see(tk.END)
    refresh_patient_status()

    # restore the chat input box
    chat_user_input.scrolled_text.config(fg='black', state='normal')
    chat_user_input.scrolled_text.delete("1.0", tk.END)
    chat_send_button.config(state='normal')
    chat_user_input.scrolled_text.focus_set()
    chat_current_task[0] = None
    chat_user_input.set_cancel_button_active(False)

def chatbot_clear():
    if messagebox.askyesno(
        "Clear Chat",
        "Are you sure you want to clear the chat?"
    ):
        chatbot_cancel_generation()
        print("Cleared Chat")
        chatbot.clear()
        _reset_chat_log()
        chat_history_listbox.selection_clear(0, tk.END)

def chatbot_new_session():
    if not chat_current_task[0] or messagebox.askyesno(
        "New Chat",
        "Are you sure you want to cancel your most recent request?"
    ):
        chatbot_cancel_generation()
        print("Starting New Chat")
        saved_id = chatbot.new_chat()
        _reset_chat_log()
        _show_saved_chat(saved_id)
        chat_history_listbox.selection_clear(0, tk.END)

def chatbot_workflow_toggle():
    # toggle between workflow options
    # update to the next workflow name
    chat_workflow_index[0] = (chat_workflow_index[0] + 1) % len(chat_workflow_choices)
    chat_workflow_button.configure(text=chat_workflow_choices[chat_workflow_index[0]])

def load_chat_history_session(event=None):
    if not chat_history: return

    selection = event.widget.curselection()
    if not selection: return

    # consider chat history label
    if selection[0] - 1 < 0:
        return

    selected_id = chat_history[selection[0] - 1]

    if chatbot.current_conversation:
        saved_id = chatbot.new_chat()
        _show_saved_chat(saved_id)

    text = chatbot.load_chat(selected_id)
    chat_log_display.scrolled_text.config(state='normal')
    chat_log_display.scrolled_text.delete("1.0", tk.END)
    chat_log_display.scrolled_text.insert(tk.END, text)
    chat_log_display.scrolled_text.config(state='disabled')


# ── Patient status (currently viewed patient) ──────────────────────────────
def _refresh_patient_from_oscar():
    # Refresh the patient indicator to reflect the patient currently open in OSCAR
    demo_no = None
    if chatbot.oscar is not None and chatbot.oscar.driver is not None:
        try:
            demo_no = chatbot.oscar.get_demographic_no()
        except Exception as e:
            print(f"Failed to read patient from Oscar: {e}")
            demo_no = None
    refresh_patient_status(demo_no=demo_no)


def _on_ai_scribe_focus(event):
    if current_view == "chatbot":
        _refresh_patient_from_oscar()

root.bind("<FocusIn>", _on_ai_scribe_focus)


def refresh_patient_status(demo_no: str | None = None):
    if patient_status_button is None:
        return
    if demo_no is None:
        demo_no = chatbot.curr_demo
    if not demo_no:
        patient_status_button.config(
            text="No Patient Selected\n(click to select)",
            fg='#8a8a8a',
            relief='raised',
        )
        return
    label = f"Patient (Demo #): {demo_no}"
    try:
        name = _fetch_patient_name(demo_no)
        if name:
            label = f"{name} "
    except Exception as e:
        print(f"Failed to fetch patient name: {e}")
    patient_status_button.config(
        text=label,
        fg='#1f6f2d',
        relief='groove',
        justify='left',
        anchor='w',
        padx=8,
        pady=8,
        wraplength=280,
    )


def _fetch_patient_name(demo_no: str) -> str | None:
    oscar = chatbot.oscar
    if oscar is not None and oscar.driver is not None:
        try:
            name = oscar.get_patient_name()
            if name:
                return _clean_patient_name(name)
        except Exception as e:
            print(f"Failed to read patient name from Oscar: {e}")
    return None


def _clean_patient_name(title: str) -> str | None:
    match = re.match(r"^Encounter\s*-\s*(.+)$", title, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


chatbot_frame = tk.Frame(root)
# Hidden at startup. switch_mode("chatbot") will show it.

for c in range(14):
    weight  = 0 if c in (0, 13) else 1
    minsize = 10 if c in (0, 13) else 0
    chatbot_frame.grid_columnconfigure(c, weight=weight, minsize=minsize)

chatbot_frame.grid_rowconfigure(0, weight=4)   # chat log
chatbot_frame.grid_rowconfigure(1, weight=1)   # user input
chatbot_frame.grid_rowconfigure(2, weight=0)   # buttons
chatbot_frame.grid_rowconfigure(3, weight=0)   # gutter

# ── Chat log ──────────────────────────────────────────────────────────────────
chat_log_display = CustomTextBox(chatbot_frame, height=20, state="disabled")
chat_log_display.grid(
    row=0, column=1, columnspan=8, padx=(5, 2), pady=(12, 4), sticky='nsew',
)
chat_log_display._id = "chat_log_tbox"
_reset_chat_log()

# ── User input ────────────────────────────────────────────────────────────────
chat_user_input = CustomTextBox(chatbot_frame, height=5)
chat_user_input.grid(
    row=1, column=1, columnspan=8, padx=(5, 2), pady=(4, 4), sticky='nsew',
)
chat_user_input._id = "chat_input_tbox"
chat_user_input.scrolled_text.insert("1.0", "Type a message…")
chat_user_input.scrolled_text.config(fg='grey')
chat_user_input.scrolled_text.bind(
    "<FocusIn>",
    lambda e: remove_placeholder(e, chat_user_input.scrolled_text, "Type a message…"),
)
chat_user_input.scrolled_text.bind(
    "<FocusOut>",
    lambda e: add_placeholder(e, chat_user_input.scrolled_text, "Type a message…"),
)
chat_user_input.scrolled_text.bind(
    "<Control-Return>",
    lambda e: chatbot_send_message(),
)

# ── Chatbot button row ────────────────────────────────────────────────────────
chat_send_button = tk.Button(
    chatbot_frame, text="Send", command=chatbot_send_message, height=2, width=12,
)
chat_send_button.grid(row=2, column=1, padx=(5, 2), pady=(2, 10), sticky='nsew')

chat_clear_button = tk.Button(
    chatbot_frame, text="Clear", command=chatbot_clear, height=2, width=10,
)
chat_clear_button.grid(row=2, column=2, padx=(2, 2), pady=(2, 10), sticky='nsew')

chat_new_button = tk.Button(
    chatbot_frame, text="New Chat", command=chatbot_new_session, height=2, width=10,
)
chat_new_button.grid(row=2, column=3, padx=(2, 2), pady=(2, 10), sticky='nsew')

chat_workflow_button = tk.Button(
    chatbot_frame, text="Auto", command=chatbot_workflow_toggle, height=2, width=10,
)
chat_workflow_button.grid(row=2, column=4, padx=(2, 2), pady=(2, 10), sticky='nsew')

chat_user_input.set_cancel_callback(lambda: (
    chatbot_cancel_generation()
    if messagebox.askyesno(
        "Cancel Generation",
        "Are you sure you want to cancel the current prompt?"
    )
    else None
))

# ── Chat history sidebar ──────────────────────────────────────────────────────
chat_history_listbox = tk.Listbox(
    chatbot_frame,
    height=30,
    selectmode=tk.SINGLE,
    activestyle='dotbox',
    relief='flat',
    highlightthickness=1,
)
chat_history_listbox.grid(
    row=0, column=9, columnspan=2, rowspan=3, padx=(4, 2), pady=(12, 4), sticky='nsew',
)
chat_history_listbox.bind('<<ListboxSelect>>', load_chat_history_session)
chat_history_listbox.insert(tk.END, "Chat History")
chat_history_listbox.config(fg='grey')

# Patient indicator 
patient_status_button = tk.Button( # Add functionality to Open OSCAR window on click
    chatbot_frame,
    text="No Patient Selected\n(click to select)",
    fg='#8a8a8a',
    relief='raised',
    justify='left',
    anchor='w',
    padx=8,
    pady=8,
    wraplength=280,
)
patient_status_button.grid(
    row=2, column=9, columnspan=2, padx=(4, 2), pady=(2, 12), sticky='nsew',
)

# Chat session state 
chat_sessions = []
current_chat_messages = []



# ═══════════════════════════════════════════════════════════════════════════════
#  MINIMAL FRAME
# ═══════════════════════════════════════════════════════════════════════════════
# This frame intentionally contains only record and pause buttons
# along with frame switch toggles
minimal_frame = tk.Frame(root)

minimal_separator = tk.Label(mode_bar, text=" │ ", fg='grey')

minimal_mic_button = tk.Button(
    mode_bar,
    text="⏺  Record",
    command=threaded_toggle_recording,
    height=1,
    width=10,
)

minimal_pause_button = tk.Button(
    mode_bar,
    text="⏸  Pause",
    command=toggle_pause,
    height=1,
    width=10,
)

# These three widgets start hidden; switch_mode shows/hides them.
# We keep references so we can pack_forget / pack them cleanly.
def _show_minimal_controls():
    minimal_separator.pack(side='left', padx=(4, 0), pady=4)
    minimal_mic_button.pack(side='left', padx=(2, 2), pady=4)
    minimal_pause_button.pack(side='left', padx=(2, 10), pady=4)

def _hide_minimal_controls():
    minimal_mic_button.pack_forget()
    minimal_pause_button.pack_forget()
    minimal_separator.pack_forget()



# ═══════════════════════════════════════════════════════════════════════════════
#  AUTO PROCESS FRAME
# ═══════════════════════════════════════════════════════════════════════════════
auto_process_frame = tk.Frame(root)

auto_process_tbox = CustomTextBox(auto_process_frame, height=20)
auto_process_tbox.pack(side="left", padx=(2, 2))

auto_process_tbox.delete("1.0", "end")
auto_process_tbox.insert("end", "Starting automated processing...\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  KEYBINDINGS & STARTUP
# ═══════════════════════════════════════════════════════════════════════════════
root.bind('<Alt-p>', lambda event: pause_button.invoke())
root.bind('<Alt-r>', lambda event: mic_button.invoke())

root.minsize(320, 60)    # allow the window to shrink to minimal size

window.load_main_window()
window.update_aiscribe_texts(None)

if app_settings.editable_settings["Use Local LLM"]:
    root.after(100, lambda: ModelManager.setup_model(app_settings=app_settings, root=root))

if app_settings.editable_settings[SettingsKeys.LOCAL_WHISPER.value]:
    print("Using Local Whisper for transcription.")
    root.after(100, load_stt_model)

root.bind("<<LoadSttModel>>", load_stt_model)

try:
    root.mainloop()
finally:
    chatbot.cleanup()
    patient_db.cleanup()

p.terminate()
