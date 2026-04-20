# Merging
* Need to re-connect the auto processing mode, currently not connected
* Hook up the new chat / clear chat features for the chatbot
* Remove cleanup if failed to initialize chatbot, i.e. if not connected / unable to connect to vector db you should still be able to use scribe features (add warning pop-up on start to alert user if connection failed to initialize)
* Hookup insert consult and insert consult + med history
* Normalize config file

# Cleanup
* Can remove OscaEforms.py and OscarEformsUI.py, also LabEformPanel can also be removed
* Add more documentation to EformPanel and Oscar methods
* Rename lab_panel component to eform_panel

# New Features
* Auto selection for eForm checkboxes. Should use patient-doctor conversation + maybe most recent eForm and maybe other documents of interest
* Add sources to chatbot for tracebility. Have '(sources)' at the end of the AI response and when you hover over it, it should list documents and measurements used in reponse. Can also be used to check that the chatbot is using best info (I.e. using most recent medications entry for recent meds rather than older one)
* Documentation - need to add documentation for many things, like database schema, how to setup local vector db for testing, adding entries, chatbot workflow, new aiscribe, new readmen, new way the chatbot uses tools, ...
* The PDF upload multiselect doesn't work, only pastes text for last selected pdf - will need to redo how files are read (or if more than one just use the PDF folder funtion that already exists)
* Maybe add loading pop-ups for longer processes
* Maybe add caching for eform scanning and checkbox scanning so won't have to scan every time app is opened or eform is selected
* Normalize settings so that the original scribe settings and new config settings can easily be accessed by the User
* Maybe upgrade to later version of python (like 3.12)
* Maybe always provide the chatbot with the current date so it has a point of reference of how recent / long ago certain things are.
* Remove dependency on Oscar report master file, instead query Oscar EMR to get necessary info
* Maybe make client.py into a class to organize it better and remove globals
* eForm auto feature to user patient-doctor transcription to auto detect which forms to open + which checkboxes to check