# TODO
- [ ] Auto selection for eForm checkboxes. Use patient-doctor conversation and maybe the most recent eForm to detect which eForms to open and which checkboxes to autofill.
- [ ] Add document and measurement sources for chunks selected. This will give traceability for which documents and measurements are being used as context. Ideally have '(sources)' at the end of the chatbot response, and on hover it should list documents and measurements used.
- [ ] The PDF upload multiselect doesn't work, will only keep the last PDF selected (switch to use the PDF folder function that already exists if multiple PDFs are selected)
- [ ] Combine config settings with original settings.
- [ ] Remove dependency on Oscar Report Master. Instead query information directly from the database. 
- [ ] (Optional) Upgrade python version.
- [ ] (Optional) Add loading pop-ups to make it more clear things are being processed.
- [ ] (Optional) Add caching for eForm and checkbox scanning so it doesn't have to happen every time app is launched or when eForm is selected.
- [ ] (Optional) Organize `client.py` into a class.

