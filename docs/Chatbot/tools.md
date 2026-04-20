# Introduction
Tools are used alongside the document and measurement chunks to give the LLM access to certain grouped information and give it other capabilities beyond information searching.

For example, there is a tool that retrieves the history of a specific (or set) of lab result(s) and then plots. 

## Adding Tools
Tools can be found in `..\AI-Scribe\FreeScribe.client\chatbot\Tools` and are categorized into differet python files. If the tool you want added correlates with on of the existing categories, then add it there. If the tool belongs to another category, add a new python file called `your_category_name.py` and add this name in the `__init__.py` imports. In your new file, add `from chatbot.Tools.Tool import tool, ToolReturn as tr` as an import. `tool` is used as a decorator that will add the tool to the tool registry. `ToolReturn` is what the tool is expected to return.

Once you have a location for your tool, to add the tool simply call the `tool` decorator above your tool, and make sure your tool returns a `ToolReturn`. Also, the first parameter in all tool calls need to be `db_conn` which is the connection to the Oscar EMR database for querying information (it does not need to be used, just make sure to include it).
```python
@tool(
    category="category_name",
    description=(
        "Description of what the tool does. "
        "This description will become vectorized, so it should be descriptive of what it does"
        "so that during the vector search it will be picked up depending on user input."
    ),
    context="Provided context that may be given to the LLM so that is knows what the returned results are.",
    parameters={
        "param1": "dictionary of parameters needed in the function"
        "param2": "these parameters are told to the LLM so it knows which ones to provide"
        "param3": "Make sure the params are descriptive so the LLM knows what to pass"
    }
)
def your_tool(db_conn, param1, param2, param3):
    """
    Brief description of what tool does
    """

    
    # Usually tools query the database and retrieve specific information that
    # may not be available in the document or measurement chunks
    query = f"""
    SELECT *
    FROM appointment
    WHERE demographic_no = {param1}
      AND appointment_date >= '{param2}'
    """

    res = db_conn.query_database(query) # res is a list of dictionaries
    return tr(
        label="Upcoming Appointments",  # Label to identify what the returned results are 
        send_to_ai=True,                # If true, will send response to AI (this feature is currently not used, will always send to AI)
        query_results=res,              # Results that get send
        save_results=res                # Results to save (this feature is currently not used, but intention was for these results to be saved into LLM memory 
                                        # categorized under the given label to optimize context usage and save key facts in LLM to prevent duplicate calls to same function)
    )
```

Once you have added your tool, it won't be active until the vector embedding has been made. To create these embeddings, call `store_tool_embeddings.py` which will create and store tool embeddings in the `tool_embeddings.jsonl`. You will only need to call this if you add a new tool, change the tool description, or change the tool parameters. You *won't* need to recreate embeddings if you modify the functionality.