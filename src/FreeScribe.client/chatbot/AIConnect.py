import requests

class AIConnect():
    def __init__(
        self, 
        endpoint : str, 
        api_key : str = None, 
        headers : list[dict[str, str]] = [],
        temperature : float = 0.1, 
        top_p : float = 0.4, 
        top_k : int = 30, 
        tfs : float = 0.97
    ):
        """
        Initializes a connection to an AI model via the given endpoint and api_key.

        Params
        ------
        endpoint : str
            AI model's endpoint that you want to connect to.

        api_key : str
            API key (model connection may require for verification).

        temperature : float
            Controls model randomness. \\
            Low (0-0.3) -> deterministic, factual. \\
            High (0.7-1.5) -> more creative, more chaotic.

        top_p : float
            Probability mass cutoff. \\
            The model samples only from the smallest set of tokens whose cumulative probability >= top_p. \\
            Smaller values = more deterministic.

        top_k : int
            Limits the number of highest-probability tokens considered. \\
            top_k = 30 -> only top 30 tokens are candidates at each step. \\
            Smaller values = more focused and deterministic.

        tfs : float
            A more advanced sampling technique. \\
            Ranges from 0-1 and filters out tokens that are statistically abnormal for the context.
        """
        self.endpoint = endpoint
        self.api_key = api_key
        self.headers = headers

        self.temperature = temperature    
        self.top_p = top_p
        self.top_k = top_k
        self.tfs = tfs


    def send_message(
            self, 
            content : str, 
            role : str = "user", 
            model : str = None, 
            pre_prompt : str = None, 
            post_prompt : str = None
        
        ):
        """
        Sends a message to AI and returns the AI's response.

        Params
        ------
        content : str
            Users message / content that is to be send to the model.

        role : str
            The role to present this message as (default is 'user').

        model : str
            The model name (not necessary to provide).

        pre_prompt : str
            Additional message that is attached at the start of content.

        post_prompt : str
            Additional message that is attached at the end of content.

        Returns
        -------
        Returns the AI's response to the passed message.
        """
        # Add post/pre prompts if given
        if pre_prompt:
            content = pre_prompt + "\n" + content

        if post_prompt:
            content = content + "\n" + post_prompt

        # Create payload and header
        payload = {
            "model" : model,
            "messages" : [
                {"role" : role, "content" : content}
            ],
            "temperature" : self.temperature,
            "top_p" : self.top_p,
            "top_k" : self.top_k,
            "tfs" : self.tfs,
        }
        headers = {
            "Authorization" : f"Bearer {self.api_key}",
            "Content-Type" : "application/json",
            "accept": "application/json",
        }
        # Add the additional headers
        for header in self.headers:
            headers.update(header)

        # Send message
        response = requests.post(
            f"{self.endpoint}/chat/completions",
            headers=headers,
            json= payload,
            verify=True
        )

        # Extract and return response
        response_data = response.json()
        response_text = (response_data['choices'][0]['message']['content'])
        return response_text
    

        
