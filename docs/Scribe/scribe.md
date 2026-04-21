# Scribe
The scribe is the main window of the application and is used to transcribe patient-doctor conversations, generate HL7 files, pull and summarize medical history, and create consulting notes. There is also a prompt manager to create additional prompts if you want to generate other notes. 


## Usage
The primary use of the scribe is to transcribe patient-doctor conversations which can be done by clicking the `Record` button. When clicked, the scribe will be listening and transcribing live conversation to the top text box and you can stop recording by clicking `Stop`. You can then use the connected AI to generate different notes (like SOAP or consult) using one of your saved prompts.

If you are interested in opening eForms, inserting consults, or summarizing medical history for a specific patient, then you must have that patient's encounter page opened. The scribe uses Selenium to interact with Oscar and to open / do certain things for a specific patient it needs to be able to identify the patient you want. This is done by scannig the opened Oscar windows and looking for the patient's demographic number, so if you want access to these features, make sure you open the patient's encounter page. 
- Opening eForms can be done by clicking the `eForms` button in the lower text box. This will open a side panel that has all available eForms loaded into a dropdown, and loads all the checkboxes on the eForm for pre-selection before opening. You can then open the eForm by clicking the `Open` button.
- Loading medical history can be done by opening the eForms section and clicking the `Med Hist` button. This will scan and load the patient's most recent `letter` along with any of the select documents from the `Select Docs` button and input the text into the input box. You can then use this to generate medical history summaries. 
- Inserting consult notes and medical history can be done by clicking the `Insert Consult` and `Insert Consult & MH` respectively. The `Insert Consult` will insert the generated text into the opened patient's most recent letter and save it. `Insert Consult & MH` will generate a medical history summary and consult note, and then insert it into the opened patient's most recent letter. 

The scribe can also be used to create HL7 files using one of the built-in HL7 prompts (like Auto, CN, HOLTER, LAB, ...) and by uploading a PDF file that you want to create an HL7 file for. The generated HL7 can then by downloaded using the download button in the output text box. 

