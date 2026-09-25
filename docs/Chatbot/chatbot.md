# Chatbot

The chatbot is a feature that allows doctors to ask questions about a patient and recieve relevant information. 

For example, the doctor could ask "What are his recent lab results?" and the chatbot will return the most recent lab results recorded for the opened patient. 

Currently the chatbot is structured more as an information retrieval assistant to provide doctors with information about patients.


## Workflows
The chatbot currently runs each user query through a workflow. Each prompt is classified through an initial LLM call based on a description of each workflow and the provided keywords. The workflow can alternatively be selected through the interface which is by default set to Auto.

### RAG Workflow

The Retrieval Augmented Generation (RAG) architecture gives the LLM patient context to create a better response. This workflow is now exclusive to document-related queries; structured data such as measurements is handled by the Oscar workflow.

The process from querying the chatbot to getting a response flows like:
 1. Query chatbot.
 2. LLM is queried to create a string of keywords based on input and also identify the date relevancy.
 3. Returned keyword string is used to do a vector search on the tool and document embeddings.
 4. The highest scored embeddings are returned and re-ranked to find closest matching chunks (date relevancy is also weighed into new rank).
 5. If any tools have been selected, execute them and save response; tool selection is not restricted by category. 
 6. From the highest scoring to lowest, document chunks are continually added to a follow up prompt until a context max limit is reached.
 7. Send follow up to LLM that contains original User input and the highest scoring patient context. 
 8. LLM returns finally response which gets added to the chatbot log. 

### Oscar Workflow

The Oscar workflow handles patient-specific queries that require structured EMR data, such as measurements, laboratory results, vitals, trends, medications, appointments, demographics, and population lookups. Unlike the RAG workflow, it does not use the vector database at all.

The process from querying the chatbot to getting a response flows like:
 1. Query chatbot.
 2. LLM is queried to classify the question into a data category, measurement types, and mode.
 3. The full tool registry is offered to the LLM, which selects and calls the tools it needs.
 4. Tool results are collected and sent to a follow up LLM call along with the original User input.
 5. LLM returns the final response which gets added to the chatbot log.

### General Workflow

The general workflow is used for tasks that do not require patient-specific data and relying solely on the conversation context. It directly passes the conversation history into the LLM call prompt. This workflow is useful for more general questions to avoid an unnecessary RAG search.


## Usage
To use the chatbot feature, make sure you are connected to the vector database and that the encounter page of the patient you want to ask about is opened in the oscar session. Then, simply input your question and click send (or CTRL + ENTER) to query the chatbot.

## Adding Workflows
More workflows can continuously be added to improve the chatbot's ability to answer questions appropriately. To add a new workflow, define a workflow subclass with the workflow decorator and provide a method `run` following the same method signature.
