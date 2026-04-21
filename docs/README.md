# AI-Scribe

## Introduction

This is a program that was designed to help empower physicians to alleviate the burden of documentation by utilizing a medical scribe that can transcribe patient-doctor conversation and generate usable notes. Futhermore, additional features have been added to provide more assistance, like HL7 file generation for easy upload of patient information into the Oscar EMR and an AI chatbot that can efficiently retrieve patient information stored in Oscar EMR. 

It utilizes `Koboldcpp`, `Whisper`, `Tesseract`, and `Selenium` for LLM, speech-to-text, OCRing, and Oscar EMR interaction respectivley. `Koboldcpp` and `Whisper` can run on a local server where multiple scribe clients can then access using the `client.py` script. This allows for efficient setup in populating clinic computers with the medical assistant. 


## Modes
The scribe has 4 modes: Scribe, Chatbot, Minimal, and Auto Processing.

### Scribe
The scribe mode is the default mode that is used to record and transcribe patient-doctor encounters and then generate notes. This is also where the PDF upload and manual HL7 generation is done. 

See [scribe](Scribe/scribe.md) for all the scribe mode functionalities.

### Chatbot
The chatbot mode gives access to a chatbot that is setup to assist the doctor in retrieving specific information for the patient. The Chatbot uses a Retrieval Augmented Generation (RAG) architecture along with a vector database to quickly search through document and measurement chunks to provide relevant context about the patient to the LLM to generate a proper response to the User's input. 

See [chatbot](Chatbot/chatbot.md) for the breakdown of the chatbot architecture. \
See [vector-database](Databases/vector-database.md) for creating the vector database and upserting documents and measurements. \
See [tools](Chatbot/tools.md) for creating chatbot tools.

### Minimal
The minimal mode is the scribe mode but with a minimalistic view that only includes the records and pause buttons for conversation transcription only.

### Auto Processing
The auto processing mode is for automatically processing HL7 files. It is set to observe certain folders and when PDF files are dropped into those folders it will automatically create HL7 files for those PDFs. 


## Client Setup

* Clone or copy the Github repository
* You must have Python 3.10.9 installed (you can check your version with `python --version`). If you have a different version installed you can install it here: https://www.python.org/downloads/release/python-3109
* Within the AI-Scribe directory, create a virtual environment for your python packages: `python -m venv venv` 
* Run `.\venv\scripts\activate` to activate your virtual environment.
* Run `pip install -r requirements.txt` to install all required dependencies.
* Install and setup Selenium for Oscar EMR interaction: [selenium-setup](Dependencies/selenium-setup.md)
* Install and setup Tesseract and Poppler for PDF OCRing capabilities: [tesseract-setup](Dependencies/tesseract-setup.md)
* Copy and rename `config_example.yaml` in `..\AI-Scribe\src\FreeScribe.client\configs` to `config.yaml` and fill in the required information.
 - Note1: The SSH credentials are only needed if you plan to SSH to access the Oscar EMR database. If you are fine using Selenium to access the "Query By Example" page and do database quering there, then these do not need to be filled in (just make sure `query_choice` is set to `oscar`). See [oscar-database](Databases/oscar-database.md) for more information on the Oscar EMR database.
 - Note2: The VectorDB credentials are only needed if you want Chatbot capabilities. The scribe funcationalities will work, but you won't have access to the Chatbot unless it is connected to a vector database and has the respective tables. See [chatbot](Chatbot/chatbot.md) for more information on the Chatbot.
* Then, you will need to install software to convert the audio file to be processed. Run this in powershell:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression
scoop install ffmpeg
```
* Finally, run `client.py` and within the client you can access additional settings for your AI and Whipser endpoints.


## Server Setup
This is if you want your machine to run `Koboldcpp` and `Whipser` for LLM and speech-to-text purposes.

* Install Python 3.10.9, clone or copy the Github repository, create a virtual environment, and install the requirements as shown in the client setup.
#### Kobold
* Now you need to download the AI model (it is large). I recommend the `Mistral 7B v0.2` or `Meta Llama 3` models.  These can be found on [HuggingFace.](https://huggingface.co/). Make sure the model is in GGUF format, as that is what Kobold accepts. 
* Install `Koboldcpp` here: https://github.com/LostRuins/koboldcpp/releases
* Launch `koboldcpp.exe`
 - On `Quick Launch` set `Backend` to `Use CUDA` to make use of your GPU (if you have an **NVidia RTX**-based card).
 - Adjust `Context Size` to desired amount (default is usually good).
 - Click `Browse` and navigate and select the model you install (or use `HF Search` to download a model off of huggingface from Kobold).
 - In `Network` tab, enter a port that you have opened and set host to `0.0.0.0` so it listens on all available network interfaces.
 - Click `Launch` to start the server. If you have `Launch Browser` selected it should open a browser that you can use to test the model.
 - If the port you selected in the `Network` tab is opened, then you should be able to connect to it on the client using the endpoint: `http://<your_ip_address>:<port_selected>/v1`

#### Whisper Server
* Run the `server.py` file. This will download the files to help organize the text after converting from audio and will open the whisper server on port 8000. You can access teh whisper server using the endpoint: `http://<your_ip_address>:8000/whisperaudio`


## Additional Information
For more information on how things work, look at the Markdown files in the `docs` folder.
