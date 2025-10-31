

import yaml
import time
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class OscarEforms:
    def __init__(self, config_path, headless=False):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.driver = None
        self.wait = None
        self.patient = None

        # Windows
        self.home_window = None
        self.search_window = None
        self.encounter_window = None
        self.eform_lib_window = None        
        
        # Initialize WebDriver
        try:
            options = FirefoxOptions()
            options.add_argument('--ignore-certificate-errors')
            options.add_argument('--ignore-ssl-errors')
            if headless:
                options.add_argument("--headless")

            service = Service(self.config['driver_path'])
            self.driver = webdriver.Firefox(service=service, options=options)
            self.wait = WebDriverWait(self.driver, 10)

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
        """Login using credentials in config."""
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



    def search_patient(self, first_name, last_name, demNo=None):
        """
        Searches for patient using demographic number or name.
        Sets self.patient if found.
        """
        print(f"Searching for patient: {first_name} {last_name}, demNo={demNo}")
        
        # Click search button
        if not self.search_window:
            search_btn = self.driver.find_element(By.XPATH, "//*[@id='search']")
            search_btn.click()
            
            self.search_window = self.driver.window_handles[-1]
            self.driver.switch_to.window(self.search_window)
            time.sleep(1)
        
        else:
            self.driver.switch_to.window(self.search_window)
            time.sleep(1)

        self.driver.minimize_window()

        if demNo:
            # Search by demographic number
            dropdown = self.driver.find_element(By.XPATH, "//*[@class='wideInput]")
            dropdown.select_by_value("search_demographic_no")

        else:
            # Search by patient name: lastname, firstname
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
        if not self.encounter_window:
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
        if not self.encounter_window:
            print("No encounter window opened, can't open eform library")
            return
        
        print("Opening eForm Library Window")
        try:
            if not self.eform_lib_window:
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
        if not self.eform_lib_window:
            print("No eForm Library window opened, can't open a new eForm")
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
        if not self.encounter_window:
            self.open_encounter()
        if not self.eform_lib_window:
            self.open_eform_library()
        
        self.open_new_eform(form_type)