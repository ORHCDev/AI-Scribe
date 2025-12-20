import yaml
import time
import re
import os
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from utils.hl7 import find_details
from utils.read_files import pdf_image_to_text

class OscarEforms:
    def __init__(self, config_path, headless=False, oscar_report_path=None):
        """
        Initializes a selenium driver that interacts with Oscar EMR, with the intention of opening eForm
        creation windows for searched patients.

        Args
        ----
            config_path: Path to YAML configuration file (Will contain things like Oscar credentials and driver path)
            headless: Boolean option to run selenium driver in headless mode
            oscar_report_path: Path to oscarReportmasterXLS.xls (Used for patient chart number searching)
        
        """
        # Config
        self.config_path = config_path
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        # PDF path for downloading files off of Oscar
        self.temp_pdf_folder = self.config['pdf_folder']
        os.makedirs(self.temp_pdf_folder, exist_ok=True)

        # eForms
        self.default_eforms = {"Auto" : ""}
        try:
            self.eforms = self.default_eforms | self.config['eForms']
        except:
            self.eforms = self.default_eforms
    
        self.oscar_report_path = oscar_report_path

        # Links
        url = self.config['url'].rsplit('/', 1)[0]
        self.eform_lib_link = url + "/eform/efmformslistadd.jsp"
        self.eform_link_template = url + "/eform/efmformadd_data.jsp?fid={formID}&demographic_no={chartNo}&appointment=&parentAjaxId=eforms"
        self.doc_link = url + "/dms/MultiPageDocDisplay.jsp?segmentID={segment_id}&providerNo=130&searchProviderNo=130&status=A" 

        # Windows
        self.home_window = None
        self.search_window = None
        self.encounter_window = None
        self.eform_lib_window = None  

        # Initialize WebDriver
        self.driver = None
        self.wait = None
        self.patient = None
        self.headless = headless
        self.initialize_driver()

        self.appts = {}
        self.session = None
        

    def initialize_driver(self):
        """Initializes selenium driver"""
        try:
            options = FirefoxOptions()
           
            options.set_preference("browser.download.folderList", 2)
            options.set_preference("browser.download.dir", self.temp_pdf_folder)
            options.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/pdf")
            options.set_preference("pdfjs.disabled", True)
            options.set_preference("browser.download.manager.showWhenStarting", False)

            options.add_argument('--ignore-certificate-errors')
            options.add_argument('--ignore-ssl-errors')
            if self.headless:
                options.add_argument("--headless")

            service = Service(self.config['driver_path'])
            self.driver = webdriver.Firefox(service=service, options=options)
            self.wait = WebDriverWait(self.driver, 10)

            self.home_window = self.driver.current_window_handle

        except Exception as e:
            print(f"Failed to initialize WebDriver: {e}")
            self.cleanup()  # Ensure cleanup if initialization fails
            raise


    def run(self):
        """Open Oscar and log in"""
        try:
            self.driver.get(self.config['url'])
            self.driver.minimize_window()
            self.oscar_login()
            print("Oscar session ready.")
            print("Scanning Appointments")
            self.scan_appointments()

            # Request session
            self.session = requests.session()
            cookies = self.driver.get_cookies()
            for cookie in cookies:
                self.session.cookies.set(cookie["name"], cookie["value"])

        except Exception as e:
            print(f"Error in run(): {e}")
            self.cleanup()



    def cleanup(self):
        """Close WebDriver"""
        try:
            if self.driver:
                self.driver.quit()
                print("WebDriver session closed.")
        except Exception as e:
            print(f"Error during cleanup: {e}")
        finally:
            self.driver = None
            self.wait = None



    def oscar_login(self):
        """Login to Oscar using credentials in config."""
        try:
            # Handle privacy/SSL page if present
            try:
                advanced_button = self.wait.until(
                    EC.visibility_of_element_located((By.ID, "details-button"))
                )
                advanced_button.click()
                proceed_link = self.wait.until(
                    EC.visibility_of_element_located((By.ID, "proceed-link"))
                )
                proceed_link.click()
                print("Bypassed privacy error page.")
            except:
                print("No privacy error page encountered.")

            username_input = self.driver.find_element(By.XPATH, "//*[@id='loginText']/form/input[1]")
            password_input = self.driver.find_element(By.XPATH, "//*[@id='loginText']/form/input[2]")
            level_pass = self.driver.find_element(By.XPATH, "//*[@id='loginText']/form/input[4]")

            creds = self.config['oscar_credentials']
            username_input.send_keys(creds['username'])
            password_input.send_keys(creds['password'])
            level_pass.send_keys(creds['pin'])

            sign_in_btn = self.driver.find_element(By.XPATH, "//*[@id='loginText']/form/input[3]")
            sign_in_btn.click()
            print("Successfully submitted login form.")

        except Exception as e:
            print(f"Error during login: {e}")


    def _switch_on_return(func):
        """Decoratoer to switch driver focus to home window when returning"""
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            finally:
                self.switch_to_home()
        return wrapper


    def search_patient(self, first_name, last_name, chartNo=None, open_encounter=True, open_eform_lib=True):
        """
        Searches for patient using demographic number or name.
        Sets self.patient if found.
        """
        print(f"Searching for patient: {first_name} {last_name}, chartNo={chartNo}")
        
        # Check if home window has been closed
        if not self.is_window_opened(self.home_window):
            # Restart
            self.restart()

        # Close patient encounter and eform library windows if opened and clear patient
        if self.is_window_opened(self.encounter_window):
            self.close_window(self.encounter_window)
            self.encounter_window = None

        if self.is_window_opened(self.eform_lib_window):
            self.close_window(self.eform_lib_window) 
            self.eform_lib_window = None

        self.patient = None

        # Click search button
        if not self.is_window_opened(self.search_window):
            try:
                self.driver.switch_to.window(self.home_window)
                search_btn = self.driver.find_element(By.XPATH, "//*[@id='search']")
                search_btn.click()
                
                self.search_window = self.driver.window_handles[-1]
                self.driver.switch_to.window(self.search_window)
                time.sleep(1)
            except Exception as e:
                print(f"Unable to open search window, restarting oscar home window: {e}")
                return self.search_patient(first_name, last_name, chartNo, open_encounter, open_eform_lib)
        
        else:
            self.driver.switch_to.window(self.search_window)
            time.sleep(1)

        self.driver.minimize_window()

        if chartNo:
            # Search by demographic number
            dropdown = Select(self.driver.find_element(By.XPATH, "//*[@class='wideInput']"))
            dropdown.select_by_value("search_demographic_no")

            name_input = self.driver.find_element(By.XPATH, "//*[@class='searchBox']/ul/li[2]/input")
            name_input.send_keys(chartNo)
            time.sleep(1)

        else:
            # Search by patient name: lastname, firstname
            dropdown = Select(self.driver.find_element(By.XPATH, "//*[@class='wideInput']"))
            dropdown.select_by_value("search_name")

            name = f"{last_name}, {first_name}"
            name_input = self.driver.find_element(By.XPATH, "//*[@class='searchBox']/ul/li[2]/input")
            name_input.send_keys(name)
            time.sleep(1)

        # Click search
        search_btn = self.driver.find_element(By.XPATH, "//*[@class='searchBox']/ul/li[3]/input[9]")
        search_btn.click()
        time.sleep(1)


        # Get list of resulting patients
        table = self.driver.find_element(By.XPATH, "//*[@id='searchResults']/table/tbody")
        rows = table.find_elements(By.TAG_NAME, "tr")
        time.sleep(1)

        patient = None
        # No results (single row means only table header is in results, no patients)
        if len(rows) == 1:
            print(f"No patients found for {name}")
            return False

        # Single patient found
        elif len(rows) == 2:
            print("Found single patient")
            patient = rows[1]
            self.patient = patient

            # Open encounter and eform library pages
            if open_encounter: self.open_encounter()
            time.sleep(1)
            if open_eform_lib: self.open_eform_library()
            return True
        
        # Multiple patients found
        else:
            print(f"Multiple results returned: {len(rows)}")
            return False
        
        
    
    def open_encounter(self):
        """
        Opens the patient's encounter page. Requires self.patient.
        """
        if not self.patient:
            print("No patient selected!")
            return
        
        print("Opening encounter page...")
        if not self.is_window_opened(self.encounter_window):
            elink = self.patient.find_element(By.XPATH, "//*[@class='links']/a")
            elink.click()

            self.encounter_window = self.driver.window_handles[-1]
            self.driver.switch_to.window(self.encounter_window)
        else:
            self.driver.switch_to.window(self.encounter_window)

        self.driver.minimize_window()
        time.sleep(1)


        # Dismissing alert
        try:
            WebDriverWait(self.driver, 10).until(EC.alert_is_present())
            alert = self.driver.switch_to.alert
            print("Alert text:", alert.text)
            alert.accept()   # Click "OK"

        except Exception as e:
            # No alert
            print(e)
            pass

        time.sleep(1)
        return True



    def open_eform_library(self):
        """
        Opens eform library window. Requires a patient encounter window to be open
        """
        if not self.is_window_opened(self.encounter_window):
            print("No encounter window opened, reopening encounter window")
            res = self.open_encounter()
            if not res: 
                self.switch_to_home()
                return
        
        print("Opening eForm Library Window")
        try:
            if not self.is_window_opened(self.eform_lib_window):
                eform_btn = self.driver.find_element(By.XPATH, "//*[@id='menuTitleeforms']/h3")
                eform_btn.click()

                self.eform_lib_window = self.driver.window_handles[-1]
                self.driver.switch_to.window(self.eform_lib_window)
            else:
                self.driver.switch_to.window(self.eform_lib_window)

            self.driver.minimize_window()
            time.sleep(1)
            return True
        except Exception as e:
            print(f"An unexpected error occurred when trying to open eForm Library Window: {e}")



    def open_new_eform(self, form_type):
        """
        Opens the specified eForm type. Requires self.eform_lib_window to be open
        """
        if not self.is_window_opened(self.eform_lib_window):
            print("No eForm Library window opened, attempting to open eForm library window")
            self.open_eform_library()
            return

        try:
            eform = self.driver.find_element(By.XPATH, f"//a[normalize-space(text())='{form_type}']")
            eform.click()
            return True
        except Exception as e:
            print(f"Unable to open eForm, make sure '{form_type}' exists: {e}")
            


    def open_eform_from_search(self, form_type):
        """
        Assumes self.patient has been found and will open encounter, eform library, and eform windows
        if not already opened
        """
        if not self.is_window_opened(self.encounter_window):
            self.open_encounter()
        if not self.is_window_opened(self.eform_lib_window):
            self.open_eform_library()
        
        self.open_new_eform(form_type)



    def open_eform_from_link(self, first_name, last_name, form_type, chartNo=None):
        """
        Searches for patient in the oscarReportmasterXLS.xls and gets the patients demographic number.
        Then creates a link using demographic number and form_type to open up the eForm window directly.
        """

        # Make sure on window that exists
        try:
            self.switch_to_last()
        except:
            self.driver.switch_to.window(self.home_window)

        if not self.oscar_report_path:
            print("Need path to oscarReportMaster")
            return

        if not chartNo:
            res = find_details(self.oscar_report_path, last_name, first_name)
            if res:
                _, _, _, _, chartNo = res
            else:
                return

        formID = self.eforms.get(form_type, "")
        if not formID:
            print(f"No form ID for {form_type}")
            return

        link = self.eform_link_template.format(formID=formID, chartNo=chartNo)

        self.driver.execute_script(f"window.open('{link}', '_blank', 'width=800,height=600');")
        return True



    def open_lab_eform_with_checkboxes(self, first_name, last_name, checkbox_names: list[str], plan_text: str = None, chartNo=None):
        """
        Opens 1.2LabCardiacP eform and automatically checks specified checkboxes.
        
        Args:
            first_name: Patient first name
            last_name: Patient last name
            checkbox_names: List of eform checkbox names to check (e.g., ["RenalFunction ", "DyslipidemiaOnStatin"])
            plan_text: Optional PLAN text to populate in the PLAN field
            chartNo: Optional demographic number
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Make sure on window that exists
        try:
            self.switch_to_last()
        except:
            self.driver.switch_to.window(self.home_window)

        form_type = "1.2LabCardiacP"
        formID = self.eforms.get(form_type, "")
        if not formID:
            print(f"No form ID for {form_type}")
            return False
        
        # Get chart number if not provided
        if not chartNo:
            if not self.oscar_report_path:
                print("Need path to oscarReportMaster")
                return False
            res = find_details(self.oscar_report_path, last_name, first_name)
            if res:
                _, _, _, _, chartNo = res
            else:
                print(f"Could not find patient {first_name} {last_name}")
                return False
        
        # Open eform via link
        link = self.eform_link_template.format(formID=formID, chartNo=chartNo)
        self.driver.execute_script(f"window.open('{link}', '_blank', 'width=800,height=600');")
        
        # Switch to new window and wait for load
        self.driver.switch_to.window(self.driver.window_handles[-1])
        time.sleep(2)  # Wait for page to load
        
        try:
            # Wait for form to be present
            self.wait.until(EC.presence_of_element_located((By.NAME, "lab")))
            
            # Optionally populate PLAN field
            if plan_text:
                try:
                    plan_field = self.driver.find_element(By.ID, "PLAN")
                    self.driver.execute_script("arguments[0].value = arguments[1];", plan_field, plan_text)
                except Exception as e:
                    print(f"Could not populate PLAN field: {e}")
            
            # Check each checkbox
            for checkbox_name in checkbox_names:
                try:
                    # Try to find checkbox by name
                    # Some checkboxes are type="checkbox", others are text inputs with name attribute
                    checkbox = self.driver.find_element(By.NAME, checkbox_name)
                    
                    # Check if it's already checked
                    if checkbox.get_attribute("type") == "checkbox":
                        if not checkbox.is_selected():
                            checkbox.click()
                    else:
                        # It's a text input, set value to 'X' to check it
                        current_value = checkbox.get_attribute("value")
                        if current_value != 'X':
                            checkbox.click()  # Click to toggle (the eform uses flip() function)
                    
                    time.sleep(0.2)  # Small delay between checks
                except Exception as e:
                    print(f"Could not check checkbox '{checkbox_name}': {e}\nRetrying...")
                    # Secondary check that normalizes name
                    try:
                        checkbox = self.driver.find_element(
                            By.XPATH,
                            f"//*[@type='checkbox' and normalize-space(@name)='{checkbox_name}']"
                        )
                        # Check if it's already checked
                        if checkbox.get_attribute("type") == "checkbox":
                            if not checkbox.is_selected():
                                checkbox.click()
                        else:
                            # It's a text input, set value to 'X' to check it
                            current_value = checkbox.get_attribute("value")
                            if current_value != 'X':
                                checkbox.click()  # Click to toggle (the eform uses flip() function)
                    except Exception as e:
                        print(f"Could not check checkbox '{checkbox_name}': {e}")
                        # Continue with other checkboxes even if one fails
            
            print(f"Successfully opened lab eform and checked {len(checkbox_names)} checkboxes")
            return True
            
        except Exception as e:
            print(f"Error opening lab eform with checkboxes: {e}")
            return False



    def scan_and_update_eforms(self):
        """
        Opens eForm library in Oscar EMR then scans and saves the all the eForm names
        as a dictionary in the passed config file. Stores eForm name and corresponding form ID.
        """

        # Open and switch to eForm library window
        self.driver.execute_script(f"window.open('{self.eform_lib_link}', '_blank', 'width=800,height=600');")
        self.driver.switch_to.window(self.driver.window_handles[-1])
        
        # Get list of all eForm WebElements
        eforms = self.wait.until(
            EC.presence_of_all_elements_located((By.XPATH, "//*[@id='scrollNumber1']/tbody/tr[2]/td[2]/table/tbody/tr"))
        )
        
        # Extract eForm names
        eform_dict = {}
        for eform in eforms[1:]:
            try:
                # eForm name
                td = eform.find_element(By.XPATH, "./td[1]")
                eform_name = td.text.strip()
                
                # eForm ID
                a = td.find_element(By.XPATH, "./a")
                onclick_value = a.get_attribute("onclick")
                match = re.search(r"fid=(\d+)", onclick_value)
                if match:
                    fid = match.group(1)
                
                eform_dict[eform_name] = fid                
            except:
                pass
            
        # Save list to config file
        self.eforms = self.default_eforms | eform_dict
        self.config["eForms"] = self.eforms
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.config, f, sort_keys=False, allow_unicode=True, indent=2)

        # Close eForm library window
        self.driver.close()
        self.driver.switch_to.window(self.driver.window_handles[-1])


    def find_eforms(self):
        """
        Will read the eforms off a patient's encouter page and return a dictionary where 
        the keys are the eform name and the value is a list of eform ids. Earlier ids in 
        the list are earlier eforms.

        Requires patient's encouter page to be opened.

        Returns
        -------
            A dictionary formatted like:
                'Eform Name' : [list of fdids]

            Formatted as such due to duplicate eform names. Each fdid is unique
            and points to a different eform. If the list contains multiple ids then note
            that the earlier the id is in the list implies that the eform is newer.
        """
        res = self.switch_to_encounter()
        if not res: return
        
        # Expand eForm section
        expand_arrow = self.wait.until(
            EC.element_to_be_clickable((By.ID, "imgeforms5"))
        )
        expand_arrow.click()
        time.sleep(2)

        # Grab all of patients eForm WebElements
        try:
            eforms = self.wait.until(
                EC.presence_of_all_elements_located((By.XPATH, "//*[@id='eformslist']/li"))
            )
        except Exception as e:
            print("Could not find patient's eForms: {e}")
            return 


        # Get fdids from all eforms found
        eform_fdids = {}
        for eform in eforms:
            try:
                # eform name
                a = eform.find_element(By.XPATH, "./span[1]/a")
                eform_name = a.text.strip()

                # eform fdids
                onclick_value = a.get_attribute("onclick")
                match = re.search(r"fdid=(\d+)", onclick_value)
                if match:
                    fdid = match.group(1)

                    # eform already in dictionary, append id to existing list
                    if eform_fdids.get(eform_name):
                        eform_fdids[eform_name].append(fdid)

                    # eform not in dictionary, start new list
                    else:
                        eform_fdids[eform_name] = [fdid]
                    
            except Exception as e:
                print(f"Error when getting eform name and id: {e}")

        # Printing 
        if False:
            for key, val in eform_fdids.items():
                print(f"{key}: {val}")

        return eform_fdids


    def read_0letter(self):
        """
        Will read and return the text from the most recent 0letter eform recorded in the 
        patient's encounter page.

        Returns
        -------
            Extracted text from most recent 0letter eform
        """
        # Get dictionary of eforms and their fdids
        eform_fdids = self.find_eforms()

        # Extract text from 0letter eforms
        text = ""
        for eform, fdids in eform_fdids.items():
            if "0letter" in eform:
                # fdid of most recent 0letter eform
                fdid = fdids[0]
                try:
                    # Find eform by fdid
                    print(f"EFORM: {eform} | FDID: {fdid}")
                    xpath = f"//a[contains(@onclick, 'fdid={fdid}')]"
                    a = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                    
                    # Open 0letter eform 
                    a.click()
                    self.switch_to_last()
                    time.sleep(2)
                    
                    # Find and switch to iframe
                    iframe = self.wait.until(
                        EC.presence_of_element_located((By.XPATH, "//iframe"))
                    )
                    self.driver.switch_to.frame(iframe)
                    
                    # Find and extract text from iframe body (the 0letter text)
                    letter = self.wait.until(
                        EC.presence_of_element_located((By.XPATH, "/html/body"))
                    )
                    text += letter.text.strip()

                    # Switch out of iframe
                    self.driver.switch_to.default_content()
                    
                    # Close 0letter window
                    self.driver.close()
                    try:
                        self.driver.switch_to.window(self.encounter_window)
                    except:
                        self.switch_to_last()
                

                    # End loop
                    break
                except Exception as e:
                    print(f"error: {e}")
        
        return text
        

    def get_doc_type(self, segment_id):
        """Returns document type for a given documents segment ID."""
        url = self.doc_link.format(segment_id=segment_id)
        r = self.session.get(url, verify=False)

        match = re.search(
            r'<option\s+value="([^"]+)"\s+selected>',
            r.text,
            flags=re.IGNORECASE
        )
        return match.group(1) if match else None


    def find_documents(self):
        """
        Will read the documents off a patients encouter page and return a dictionary where 
        the keys are the document name and the value is a list of document ids. Earlier ids in 
        the list are earlier documents.

        Requires patient's encouter page to be opened.

        Returns
        -------
            A dictionary formatted like:
                'Document Name' : [list of segment ids]

            Formatted as such due to duplicate document names. Each segment id is unique
            and points to a different document. If the list contains multiple ids then note
            that the earlier the id is in the list implies that the document is newer.
        """
        res = self.switch_to_encounter()
        if not res: return

        doc_dict = {}
        try:
            # Expand document section
            expand_arrow = self.wait.until(
                EC.element_to_be_clickable((By.ID, "imgdocs5"))
            )
            expand_arrow.click()
            time.sleep(2)

            docs_count = len(self.driver.find_elements(By.XPATH, "//*[@id='docslist']/li"))

            for i in range(1, docs_count+1):
                a = self.wait.until(
                    EC.presence_of_element_located(
                        (By.XPATH, f"(//*[@id='docslist']/li)[{i}]/span[1]/a")
                    )
                )
                # Clean document name
                doc_name_raw = a.text.strip()
                doc_name = re.sub(r'[^A-Za-z0-9]+', ' ', doc_name_raw).strip('_')

                # Document segment ids
                onclick_value = a.get_attribute("onclick")
                match = re.search(r"segmentID=(\d+)", onclick_value)
                if match:
                    segID = match.group(1)
                    doc_type = None
                    
                    try:
                        doc_type = self.get_doc_type(segID)
                    except:
                        pass

                    if doc_type: 
                        doc_name = doc_type
                    else:
                        print(f"No type selected for {doc_name}")

                    if not doc_dict.get(doc_name, ""):
                        doc_dict[doc_name] = [segID]
                    else:
                        doc_dict[doc_name].append(segID)
                else:
                    print(f"No segment ID for {doc_name}")

        except Exception as e:
            print(f"Error: {e}")

        # for key, val in doc_dict.items():
        #    print(f"{key}: {val}")
        return doc_dict


    def extract_text_from_document(self, segID):
        """
        Extracts and returns the text from the given document.
        Requires the patients encounter page to be opened and for the given document id to 
        exist for the patient. 

        Args
        ----
            segID (str): String of numbers that represents a documents ID (i.e. '111111').

        Returns
        -------
            The OCR'd text that is extracted from the document.
        """
        res = self.switch_to_encounter()
        if not res: return
        text = ""

        # Clean up the temporary folder by making sure its empty
        # If can't empty it, make a note of the existing pdfs in it so can determine new
        # pdf added.
        files = [file for file in os.listdir(self.temp_pdf_folder) if file.lower().endswith("pdf")]
        old_pdfs = []
        for file in files:
            try:
                os.remove(os.path.join(self.temp_pdf_folder, file))
            except:
                print(f"Unable to remove {file} from {self.temp_pdf_folder}")
                old_pdfs.append(file) # Pdfs that were unable to be deleted

        # Open document
        try:
            # Expand the documents section to make sure document can be found
            try:
                expand_arrow = self.wait.until(
                    EC.element_to_be_clickable((By.ID, "imgdocs5"))
                )
                expand_arrow.click()
                time.sleep(2)
            except:
                print("Section is already expanded, or unable to expand.")

            # Find eForm by segment ID
            xpath = f"//a[contains(@onclick, 'segmentID={segID}')]"
            a = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            
            # Open Document 
            a.click()
            self.switch_to_last()
            print("Opened Doc")
            time.sleep(1)
            
            # Download doc as PDF
            print_btn = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//*[@type='button' and contains(@value, ' Print ')]"))
            )
            print_btn.click()

            print("Clicked Print")
            time.sleep(1)

            # Close document window
            self.driver.close()
            self.driver.switch_to.window(self.driver.window_handles[-1])
           

            print(f"Old pdfs {old_pdfs}")
            # OCR PDF to extract text and then delete PDF
            pdfs = [file for file in os.listdir(self.temp_pdf_folder) if file.lower().endswith("pdf")]
            for pdf in pdfs:
                pdf_path = os.path.join(self.temp_pdf_folder, pdf)
                if pdf in old_pdfs:
                    # Try to remove agian
                    try:
                        os.remove(pdf_path)
                    except:
                        pass

                # Newly added pdf
                else:
                    # Extract text and remove
                    try:
                        text = pdf_image_to_text(pdf_path)
                        time.sleep(1)
                        os.remove(pdf_path)
                    except Exception as e:
                        print(f"Error trying to read text and remove pdf: {e}")
    
        except Exception as e:
            print(f"An error occurred when downloading and ocring PDF off of Oscar: {e}")


        return text


    def read_documents(self, doc_types):
        """
        Extracts text from the first appearance of the given documents from the patient's encounter page.

        Args
        ----
            doc_types (list): List of document types to extract text from (i.e. ['DC Summary', 'CATH', ...])
        
        Returns
        -------
            A concatonation of the text extracated from the documents. Text will be ordered in the same way the
            document types are given.
        """
        # Dictionary to help find document (as names are not always consistent)
        doc_search_dict = {
            "DC Summary" : [
                "dc summary",
                "discharge",
                "discharge summary", 
                "dc information", 
                "discharge information"
            ],

            "CATH" : [
                "angiogram",
                "catheterization",
                "pci report",
                "interventional",
                "cath report",
                "pci assessment",
                "cath",
            ]
        }
        # Dictionary to keep track of which documents have been found (only want first document for each type)
        doc_found_dict = {d : False for d in doc_types}
        # Dictionary of document names/types with associated list of segment IDs
        doc_id_dict = self.find_documents()
        print(doc_types)
        
        # Add doc_types to search dict
        for d in doc_types:
            if doc_search_dict.get(d):
                doc_search_dict[d].append(d)
            else:
                doc_search_dict[d] = [d]
        print(doc_search_dict)
        # Iterate over document names, find ones that match with given types and use document
        # segment ID to open, download, and extract text from document.
        text = ""
        for doc_name in doc_id_dict.keys():
            for doc_key in doc_search_dict.keys():
                if (not doc_found_dict.get(doc_key, True) and 
                    any([val.lower() in doc_name.lower() for val in doc_search_dict.get(doc_key, [])])):
                    
                    print(f"KEY {doc_key}; NAME {doc_name}; ID {doc_id_dict.get(doc_name, [])[0]}")
                    segIDs = doc_id_dict.get(doc_name)
                    if segIDs:
                        text += f"{doc_key.upper()}\n{self.extract_text_from_document(segIDs[0])}\n\n\n" 
                        doc_found_dict[doc_key] = True
        
        return text


    def read_dcs_and_angiograms(self):
        """
        Extracts the text from a patients DC and Angiogram documents.
        Requires patient encounter page is opened.
        """
        # Switch to encounter page
        res = self.switch_to_encounter()
        if not res: return

        DC = [
            "dc summary",
            "discharge",
            "discharge summary", 
            "dc information", 
            "discharge information"
        ]

        ANG = [
            "angiogram",
            "catheterization",
            "pci report",
            "interventional",
            "cath report",
            "pci assessment",
            "cath",
        ]

        # Get all patient documents
        docs = self.find_documents()

        # Filter to get most recent DC and most recent Angiogram (if exist)
        text = ""
        dc_found = False
        ang_found = False
        for key in docs.keys():
            
            if not dc_found and any([val in key.lower() for val in DC]):
                print(f"KEY: {key}: {docs.get(key, '')}")
                segIDs = docs.get(key, "")
                if segIDs:
                    text += "DC:\n" + self.extract_text_from_document(segIDs[0]) + "\n\n\n" 
                    dc_found = True

            elif not ang_found and any([val in key.lower() for val in ANG]):
                print(f"KEY: {key}: {docs.get(key, '')}")
                segIDs = docs.get(key, "")
                if segIDs:
                    text += "ANGIOGRAM:\n" + self.extract_text_from_document(segIDs[0]) + "\n\n\n" 
                    ang_found = True

        return text

        

    def read_medical_history(self, doc_names):
        """
        Extracts and returns the text from the patients most recent 0letter, angiogram and dc files (if exist).
        Requires patient encounter page to be opened.
        """
        res = self.switch_to_encounter()
        if not res: return
        try:
            letter = self.read_0letter()
            time.sleep(2)
            docs = self.read_documents(doc_names)

            text = "0Letter:\n" + letter + "\n\n\n" + docs
            return text
        except Exception as e:
            print(f"Error occurred when reading medical history: {e}")
            return



    def insert_text_into(self, text : str, box : str):
        """
        Inserts text into one of the four boxes (Social History, Medical History, Ongoing Concerns, or Reminders).

        Args
        ----
        text : str
            Text to be inserted into the box.

        box : Literal["Social", "Medical", "Concerns", "Reminders"]
            Box identify to select which box to insert text into.

        Returns
        -------
            Returns True if text was successfully inserted, False otherwise.
        """
        res = self.switch_to_encounter()
        if not res: return

        # Maps box name to html div location 
        box_map = {
            "Social" : "divR1I1",
            "Medical" : "divR1I2",
            "Concerns" : "divR2I1",
            "Reminders" : "divR2I2"
        }

        box_div = box_map.get(box)
        if not box_div: 
            print(f"Could not find box for {box}. Make sure to use one of: Social, Medical, Concerns, or Reminders for box value.")


        try:
            # Open medical history tab
            self.wait.until(
                EC.element_to_be_clickable((By.XPATH, f"//*[@id='{box_div}']/div[1]/h3/a"))
            ).click()
            
            # Insert text
            tbox = self.wait.until(
                EC.presence_of_element_located((By.XPATH, "//*[@id='noteEditTxt']"))
            )
            tbox.send_keys(text)

            # Save
            self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='frmIssueNotes']/span[1]/input[4]"))
            ).click()
            return True
        
        except Exception as e:
            print(f"Error occurred when inserting and saving medical history: {e}")
            return False
        
        
    def scan_appointments(self):
        """
        Scans the Oscar home page for all patient appointments registered for the day.
        
        Returns
        -------
            Returns a dictionary where the key is the doctor and the value is a list
            a dictionaries where each one represents an appointment. 

            Each appointment dictionary is structured like:
                "Demo#"  : Patient's demographic number
                "Name"   : Patient's name formatted "<lastname>,<firstname>"
                "Type"   : Appointment type
                "Reason" : Appointment reason
                "Notes"  : Appointment notes
                "Time"   : Appointment start time
                "Status" : Appointment's status (i.e. booked, cancelled, rescheduled, etc)

        """
        # Switch to oscar home window
        self.driver.switch_to.window(self.home_window)
        
        # Find all appointment columns
        columns = self.wait.until(
            EC.presence_of_all_elements_located((By.XPATH, "/html/body/table[2]/tbody/tr[2]/td/table/tbody/tr/td"))
        )

        doc_dict = {}
        # For each column get the doctor name and their appointments
        for col in columns:
            try:
                doctor = col.find_element(By.XPATH, "./table/tbody/tr[1]/td/b/b/a[1]").text.strip()
            except:
                print("No doctor, continuing")
                continue

            doc_dict[doctor] = []
            """appts = col.find_elements(By.CLASS_NAME, "appt")
            for appt in appts:
                try:
                    enc = appt.find_element(By.CLASS_NAME, "encounterBtn")
                    onclick_value = enc.get_attribute("onclick")
                    match = re.search(r"demographicNo=(\d+)", onclick_value)
                    if match:
                        demNo = match.group(1)
                        print(demNo)
                        doc_dict[doctor].append(demNo)
                except Exception as e:
                    print(f"Error: {e}")
                    continue"""

            # Iterate over all rows and find appointments
            # Can use above commented out code to get appointments as is cleaner
            # if there is no need for appointment start times
            rows = col.find_elements(By.XPATH, ".//*[@id='providerSchedule']/tbody/tr")
            for row in rows:
                # Check if timeslot has appointment
                try:
                    appt = row.find_element(By.CLASS_NAME, "appt")
                except:
                    continue

                try:
                    # Find encounter element
                    enc = appt.find_element(By.CLASS_NAME, "encounterBtn")
                    # Extract demographic number from encounter link
                    onclick_value = enc.get_attribute("onclick")
                    match = re.search(r"demographicNo=(\d+)", onclick_value)
                    if match:
                        demNo = match.group(1)

                        # Get appointment time slot
                        timeslot = row.find_element(By.XPATH, "./td[1]/a")
                        appt_time = timeslot.text.strip()

                        # get appointment details 
                        details = appt.find_element(By.CLASS_NAME, "apptLink").get_attribute("title")
                        name = ""
                        appt_type = ""
                        reason = ""
                        notes = ""
                        try:
                            split_details = details.split("\n")
                            name =      split_details[0].strip()
                            appt_type = split_details[1].strip()
                            reason =    split_details[2].strip()
                            notes =     split_details[3].strip()
                        except Exception as e:
                            print(f"Unable to get patient details: {e}")
                            

                        # Get appointment status
                        status = appt.find_element(By.CLASS_NAME, "apptStatus").get_attribute("title").strip()
                        # List of status' that if the appointment has will be ignored
                        to_ignore = [
                            "Cancelled",
                            "Completed",
                            "Rescheduled"
                        ]
                        if any([ig in status for ig in to_ignore]):
                            continue

                        # Add appointment dictionary to list
                        patient = {
                            "Demo#" : demNo,
                            "Name" : name,
                            "Type" : appt_type,
                            "Reason" : reason,
                            "Notes" : notes,
                            "Time" : appt_time,
                            "Status" : status,
                        }
                        doc_dict[doctor].append(patient)

                except Exception as e:
                    continue

        # Print dictionary contents
        if False:
            for key, val in doc_dict.items():
                print(f"{25*'='}\n{key}\n{25*'='}")
                for elem in val:
                    print(f"{15*'-'}")
                    for k, v in elem.items():
                        print(f"\t {k:10} : {v}")
                    
                    print(f"{15*'-'}")

        self.appts = doc_dict
        return self.appts



    def get_all_patients(self):
        """
        Get list of all patients from all appointments across all doctors.
        Ensures appointments are scanned if needed.
        
        Returns:
            List of appointment dictionaries with patient information.
            Each dictionary contains: "Demo#", "Name", "Type", "Reason", "Notes", "Time", "Status"
        """
        if not self.appts:
            self.scan_appointments()
        
        all_patients = []
        for doctor, appts in self.appts.items():
            all_patients.extend(appts)
        
        return all_patients



    def switch_to_encounter(self):
        """
        Checks if a patient encounter page is opened. 
        If opened will switch to it, else will attempt to open and switch to it.

        Returns
        -------
        Returns True if able to switch to encounter page, False otherwise.
        """
        # Return if patient's encounter page isn't opened
        if not self.is_window_opened(self.encounter_window):
            # Try to open
            try:
                res = self.open_encounter()
                if not res: return False
            except Exception as e:
                print(f"Unable to open encouter windows: {e}")
                return False
        
        # Switch to encounter window
        self.driver.switch_to.window(self.encounter_window)
        return True


    def switch_to_home(self):
        """
        Checks if Oscar home page is opened.
        If opened will switch to it, else will restart driver and then try and switch.

        Returns
        -------
        Returns True if able to switch to home page, False otherwise        
        """
        # Check if opened
        if self.is_window_opened(self.home_window):
            self.driver.switch_to.window(self.home_window)
            return True
        
        # Home window is not opened, try restarting driver
        else:
            print("Restarting")
            self.restart()
            self.driver.switch_to.window(self.home_window)
            return 


    def is_window_opened(self, window):
        """
        Checks is given window is opened
        """
        if not window: return False
        
        try:
            cur_window = self.driver.current_window_handle
            self.driver.switch_to.window(window)
            self.driver.switch_to.window(cur_window)
            return True
        except:
            return False



    def close_window(self, window):
        """
        Closes the given window. Assumes window is opened.

        If window to be closed is the drivers current window, will switch driver focus
        to last window in window_handles.

        Args
        ----
            window: window to be closed

        Returns
        -------
            Returns True if successfully closed window, False otherwise
        """
        try:
            cur_window = self.driver.current_window_handle
            if cur_window == window:
                self.driver.close()
                # Switch to last window
                self.driver.switch_to.window(self.driver.window_handles[-1])
            else:
                self.driver.switch_to.window(window)
                self.driver.close()
                self.driver.switch_to.window(cur_window)

            return True
        
        except:
            return False
        


    def switch_to_last(self):
        """Switches driver foces to last window in window handles"""
        self.driver.switch_to.window(self.driver.window_handles[-1])


    def restart(self):
        """Re-initializes driver and re-runs (in case someone accidentally closes home window)"""
        self.cleanup()
        self.initialize_driver()
        self.run()