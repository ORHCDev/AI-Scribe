import os

class PromptsWindow():
    """
    Manages text-based prompt files and an in-memory cache of their contents.

    The `PromptsWindow` class provides an interface for loading, creating,
    updating, caching, and deleting prompt text files stored in a specified
    directory. Prompts are stored as individual `.txt` files, and their
    contents are also cached in memory for faster access and temporary edits
    during an application session.

    Attributes
    ----------
    prompt_dir: (str) 
        The directory path where prompt `.txt` files are stored.
    cache : dict[str, str]
        An in-memory dictionary storing prompt names as keys and their text
        content as values.

    Methods
    -------
    load_prompts():
        Loads all `.txt` files from the prompt directory into the cache.
    cache_prompt(name, text):
        Updates the in-memory cache for an existing prompt without saving it to disk.
    update_prompt(name, text):
        Writes the updated text to the corresponding `.txt` file and updates the cache.
    create_prompt(name, text):
        Creates a new `.txt` prompt file and adds it to the cache.
    delete_prompt(name):
        Deletes a `.txt` prompt file from disk and removes it from the cache.
    get(prompt):
        Retrieves the text content of a prompt from the cache.
    list_prompts():
        Returns a list of all available prompt names.
    """

    def __init__(self, prompt_dir="prompts"):
        """
        Loads all prompts from prompt dir

        Args
        ----
        prompt_dir : str, optional
            Directory containing prompt .txt files
        """
        self.prompt_dir = prompt_dir
        os.makedirs(self.prompt_dir, exist_ok=True)
        
        # Default prompts, other prompts are loaded in from textfiles in the prompt directory
        self.cache = {}

        self.load_prompts()

    def load_prompts(self):
        """Load available prompt names from the prompt directory."""
        self.cache = {}
        # Get file names without .txt ending
        files = [f for f in os.listdir(self.prompt_dir) if f.endswith(".txt")]

        for file in files:
            path = os.path.join(self.prompt_dir, file)
            with open(path, "r", encoding="utf-8") as f:
                self.cache[file[:-4]] = f.read()    

    def cache_prompt(self, name, text):
        """
        Caches text to given prompt. 
        Changes are not written to prompt file and will only last for current session
        """
        if name in self.cache.keys():
            self.cache[name] = text

    def update_prompt(self, name, text):
        """Writes to given prompt file, updating the prompt to the given text"""
        if name in self.cache.keys():
            # Update file
            with open(os.path.join(self.prompt_dir, f"{name}.txt"), "w", encoding="utf-8") as f:
                f.write(text)
            # Update cache
            self.cache[name] = text

    def create_prompt(self, name, text):
        """Creates a new prompt"""
        if name not in self.cache.keys():
            # Create prompt
            with open(os.path.join(self.prompt_dir, f"{name}.txt"), "w", encoding="utf-8") as f:
                f.write(text)
            # Add to session cache
            self.cache[name] = text

    def delete_prompt(self, name):
        """Deletes the given prompt"""
         # Build full file path
        file_path = os.path.join(self.prompt_dir, f"{name}.txt")

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Prompt '{name}' deleted successfully.")
                return True
            else:
                print(f"Prompt '{name}' does not exist.")
        except Exception as e:
            print(f"Error deleting prompt '{name}': {e}")

        return False

    def get(self, prompt, default=""):
        """Returns the text for the given prompt"""
        return self.cache.get(prompt, default)


    def list_prompts(self):
        """Returns list of prompts"""
        return list(self.cache.keys())
