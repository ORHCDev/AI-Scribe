# Chatbot

The chatbot is a feature that allows doctors to ask questions about a patient and recieve relevant information. 

For example, the doctor could ask "What are his recent lab results?" and the chatbot will return the most recent lab results recorded for the opened patient. 

Currently the chatbot is structured more as an information retrieval assistant to provide doctors with information about patients.


## Workflow
The chatbot uses a Retrieval Augmented Generation (RAG) architecture that gives the LLM patient context to create a better response. The retrieved context comes from patient documents and measurements, along with results from tool calls.

The process from querying the chatbot to getting a response flows like:
 1. Query chatbot.
 2. LLM is queried to create a string of keywords based on input and also identify the date relevancy.
 3. Returned keyword string is used to do a vector search on the tool, document, and measurement embeddings.
 4. The highest scored embeddings are returned and re-ranked to find closest matching chunks (date relevancy is also weighed into new rank).
 5. If any tools have been selected, execute them and save response. 
 6. From the highest scoring to lowest, chunks are continually added to a follow up prompt until a context max limit is reached.
 7. Send follow up to LLM that contains original User input and the highest scoring patient context. 
 8. LLM returns finally response which gets added to the chatbot log. 


