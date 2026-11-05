import copy
import os
import shutil
import yaml

CONSULT_COMPLETE_PROMPT = "Consult Complete"
CONSULT_COMPLETE_MASTER_SECTION = "Master Prompt"


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
        self.consult_complete = {}

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
        self._load_consult_complete()


    def _read_default_consult_complete(self):
        """Returns the Consult Complete prompts from the default yaml file, if available."""
        if not os.path.exists(self.default_path):
            return {}
        try:
            with open(self.default_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data.get("Consult_Complete") or {}
        except Exception as e:
            print(f"Unable to read default Consult Complete prompts: {e}")
            return {}


    def _load_consult_complete(self):
        """Loads Consult Complete prompts, filling in any that are missing from the defaults."""
        defaults = self._read_default_consult_complete()
        current = self.data.get("Consult_Complete")
        changed = False

        if not isinstance(current, dict):
            current = {}
            self.data["Consult_Complete"] = current
            changed = True

        if "Master" not in current and "Master" in defaults:
            current["Master"] = defaults["Master"]
            changed = True

        sections = current.get("Sections")
        if not isinstance(sections, dict):
            sections = {}
            current["Sections"] = sections
            changed = True

        for name, text in defaults.get("Sections", {}).items():
            if name not in sections:
                sections[name] = text
                changed = True

        self.consult_complete = current

        if changed:
            self.save_yaml()


    def list_consult_complete_sections(self):
        """Returns the editable Consult Complete section names, with the master prompt first."""
        return [CONSULT_COMPLETE_MASTER_SECTION] + list(self.consult_complete.get("Sections", {}).keys())


    def get_consult_complete_master(self):
        """Returns the Consult Complete master prompt template."""
        return self.consult_complete.get("Master", "") or ""


    def get_consult_complete_section(self, section):
        """Returns the prompt for the given Consult Complete section."""
        if section == CONSULT_COMPLETE_MASTER_SECTION:
            return self.get_consult_complete_master()
        return self.consult_complete.get("Sections", {}).get(section, "") or ""


    def cache_consult_complete_section(self, section, text):
        """Caches a Consult Complete section. Changes only last for the current session."""
        if section == CONSULT_COMPLETE_MASTER_SECTION:
            self.consult_complete["Master"] = text
        else:
            self.consult_complete.setdefault("Sections", {})[section] = text


    def save_consult_complete_section(self, section, text):
        """Saves a Consult Complete section to the yaml file."""
        self.cache_consult_complete_section(section, text)
        self.save_consult_complete()


    def save_consult_complete(self):
        """Saves all Consult Complete prompts to the yaml file."""
        self.data["Consult_Complete"] = self.consult_complete
        self.save_yaml()


    def restore_consult_complete_section(self, section):
        """Restores a Consult Complete section to its default (if it exists)."""
        defaults = self._read_default_consult_complete()
        if section == CONSULT_COMPLETE_MASTER_SECTION:
            if "Master" in defaults:
                self.save_consult_complete_section(section, defaults["Master"])
            else:
                print(f"{section} is not in default Consult Complete prompts")
        elif section in defaults.get("Sections", {}):
            self.save_consult_complete_section(section, defaults["Sections"][section])
        else:
            print(f"{section} is not in default Consult Complete prompts")


    def restore_all_consult_complete(self):
        """Restores all Consult Complete prompts to their defaults."""
        defaults = self._read_default_consult_complete()
        if not defaults:
            return
        self.consult_complete = copy.deepcopy(defaults)
        self.data["Consult_Complete"] = self.consult_complete
        self.save_yaml()


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
