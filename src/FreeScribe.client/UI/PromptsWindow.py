import os
import shutil
import yaml

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
        The directory path where prompt .yaml files are stored.
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

    def __init__(self, default_path=r".\prompts\default_prompts.yaml", target_path=r".\prompts\prompts.yaml"):
        """
        Loads all prompts from prompt dir

        Args
        ----
        default_path : str, optional
            Path to default .yaml file
        target_path : str, optional
            Path to target .yaml file 
        """
        self.default_path = default_path
        self.target_path = target_path
        
        # Stored prompts, allows session prompt modification and testing without saving changes
        self.data = {}
        self.cache = {}
        self.hl7_prompt_list = None

        if not os.path.exists(default_path):
            print(f"No default .yaml file to read at {default_path}")

        if not os.path.exists(target_path):
            shutil.copy(default_path, target_path)
            print(f"Created {target_path} from defaults.")

        self.load_prompts()

    def load_prompts(self):
        """Load prompts from target yaml file"""
        with open(self.target_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        self.data = data
        self.cache = data["Prompts"].copy()
        self.hl7_prompt_list = data["HL7_Prompts"]


    def restore_prompt(self, name):
        """Restores given prompt to its default (if exists)"""
        with open(self.default_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if name in data["Prompts"].keys():
                self.save_prompt(name, data["Prompts"][name])
            else:
                print(f"{name} is not in default prompts")


    def restore_all_prompts(self):
        """Restores all prompts to their defaults (if exist)"""
        with open(self.default_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            for name in data["Prompts"].keys():
                self.save_prompt(name, data["Prompts"][name])

    def cache_prompt(self, name, text):
        """
        Caches text to given prompt. 
        Changes are not written to prompt file and will only last for current session
        """
        if name in self.cache.keys():
            self.cache[name] = text


    def save_yaml(self):
        """Writes data to yaml file"""
        with open(self.target_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.data, f, sort_keys=False, allow_unicode=True, indent=2)


    def save_prompt(self, name, text):
        """Save the yaml file for the given prompt with the given text"""
        # Update cache and data
        self.cache[name] = text
        self.data["Prompts"][name] = text
        
        # Update yaml
        self.save_yaml()
        
                
            

    def create_prompt(self, name, text):
        """Creates a new prompt"""
        if name not in self.cache.keys():
            self.data["Prompts"][name] = text
            self.cache[name] = text
            # Create prompt
            self.save_yaml()

            


    def delete_prompt(self, name):
        """Deletes the given prompt"""
        if name in self.cache.keys():
            try:
                del self.data["Prompts"][name]
                del self.cache[name]
                self.save_yaml()
                print(f"{name} prompt was successfully deleted")
                return True
            except Exception as e:
                print(f"Error deleting prompt '{name}': {e}")

        return False

    def get(self, prompt, default=""):
        """Returns the text for the given prompt"""
        return self.cache.get(prompt, default)


    def list_prompts(self):
        """Returns list of prompts"""
        return list(self.cache.keys())
