

import yaml
import time
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from utils.hl7 import find_details

class OscarEforms:
    def __init__(self, config_path, headless=False, oscar_report_path=None):
        """
        Initializes a selenium driver that interacts with Oscar EMR, with the intention of opening eForm
        creation windows for searched patients.

        Args
        ----
            config_path: Path to YAML configuration file (Will contain things like Oscar credentials and driver path)
            headless: Boolean option to run selenium driver in headless mode
            oscar_report_path: Path to oscarReportmasterXLS.xls (Used for patient demographic number searching)
        
        """
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.oscar_report_path = oscar_report_path
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



    def search_patient(self, first_name, last_name, chartNo=None):
        """
        Searches for patient using demographic number or name.
        Sets self.patient if found.
        """
        print(f"Searching for patient: {first_name} {last_name}, chartNo={chartNo}")
        
        # Close patient encounter and eform library windows if opened and clear patient
        if self.is_window_opened(self.encounter_window):
            self.close_window(self.encounter_window)
            self.encounter_window = None

        if self.is_window_opened(self.eform_lib_window):
            self.close_window(self.eform_lib_window) 
            self.eform_lib_window = None

        self.patient = None

        # Click search button
        if self.search_window not in self.driver.window_handles:
            search_btn = self.driver.find_element(By.XPATH, "//*[@id='search']")
            search_btn.click()
            
            self.search_window = self.driver.window_handles[-1]
            self.driver.switch_to.window(self.search_window)
            time.sleep(1)
        
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
            self.open_encounter()
            time.sleep(1)
            self.open_eform_library()
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
            if not res: return
        
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
        eform_map = {
            "0.1Rfx" : 725,
            "1.2LabCardiac" : 659,
        }

        if not self.oscar_report_path:
            print("Need path to oscarReportMaster")
            return

        if not chartNo:
            res = find_details(self.oscar_report_path, last_name, first_name)
            if res:
                _, _, _, _, chartNo = res
            else:
                return

        formID = eform_map.get(form_type, "")
        if not formID:
            return


        link = f"https://72.137.170.174:8443/oscar/eform/efmformadd_data.jsp?fid={formID}&demographic_no={chartNo}&appointment=&parentAjaxId=eforms"

        self.driver.execute_script(f"window.open('{link}', '_blank', 'width=800,height=600');")
        return True
        

    def is_window_opened(self, window):
        """
        Checks is given window is opened
        """
        if not window: return False
        
        cur_window = self.driver.current_window_handle
        
        try:
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