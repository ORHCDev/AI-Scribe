
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import logging
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SOQ:
    def __init__(self, user, passw, pin, oscar_url, driver_path, headless=True, oscar_version=15):
        self.user = user
        self.passw = passw
        self.pin = pin
        self.oscar_url = oscar_url
        self.oscar_version=oscar_version
        self.oscar_login_url = self.oscar_url + "index.jsp"
        self.admin_url = self.oscar_url + "administration/"
        self.doc_url = self.oscar_url + "dms/ManageDocument.do?method=display&doc_no={document_no}"
        self.driver_path = driver_path
        self.headless = headless

        self.session = requests.session()
        self.initialize_driver()


    def initialize_driver(self):
        """Initializes selenium driver"""
        try:
            options = FirefoxOptions()
            options.add_argument('--ignore-certificate-errors')
            options.add_argument('--ignore-ssl-errors')
            if self.headless:
                options.add_argument("--headless")

            service = Service(self.driver_path)
            self.driver = webdriver.Firefox(service=service, options=options)
            self.wait = WebDriverWait(self.driver, 10)

        except Exception as e:
            logging.error(f"Failed to initialize WebDriver: {e}")
            self.cleanup()  # Ensure cleanup if initialization fails
            raise

        
    def run(self):
        # Login to Oscar EMR
        self.driver.get(self.oscar_login_url)
        self.oscar_login()

        # Pass session cookies
        cookies = self.driver.get_cookies()
        for cookie in cookies:
            self.session.cookies.set(cookie["name"], cookie["value"])

        # Open admin page and Query By Example
        self.driver.get(self.admin_url)
        self.open_query_by_example()


    def cleanup(self):
        """Close WebDriver"""
        try:
            if self.driver:
                self.driver.quit()
                logging.info("WebDriver session closed.")
        except Exception as e:
            logging.error(f"Error during cleanup: {e}")
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
                logging.info("Bypassed privacy error page.")
            except:
                logging.info("No privacy error page encountered.")

            if self.oscar_version == 15:
                username_input = self.driver.find_element(By.XPATH, "//*[@id='loginText']/form/input[1]")
                password_input = self.driver.find_element(By.XPATH, "//*[@id='loginText']/form/input[2]")
                level_pass = self.driver.find_element(By.XPATH, "//*[@id='loginText']/form/input[4]")
            elif self.oscar_version == 19:
                username_input = self.driver.find_element(By.XPATH, '//*[@id="username"]')
                password_input = self.driver.find_element(By.XPATH, '//*[@id="password2"]')
                level_pass = self.driver.find_element(By.XPATH, '//*[@id="pin2"]')

            username_input.send_keys(self.user)
            password_input.send_keys(self.passw)
            level_pass.send_keys(self.pin)

            sign_in_btn = self.driver.find_element(By.XPATH, "//*[@id='loginText']/form/input[3]")
            sign_in_btn.click()
            logging.info("Successfully submitted login form.")

        except Exception as e:
            logging.error(f"Error during login: {e}")


    def open_query_by_example(self):
        report_dropdown = self.wait.until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="adminNav"]/div/div[10]/a'))
        )
        report_dropdown.click()


        qbe = self.wait.until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="collapseFive"]/div/ul/li[1]/a'))
        )
        qbe.click()

        # ENTER IFRAME
        self.driver.switch_to.frame("myFrame")


    def query_database(self, query):
        # Check query for 'None' and raise error if found
        # The assumption is that SQL queries will not have 'None' as a valid value
        if 'None' in query:
            raise ValueError("A query parameter was not provided.\n Please provide all necessary parameters.")

        tbox = self.wait.until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="scrollNumber1"]/tbody/tr[2]/td[2]/table/tbody/tr[2]/td/textarea'))
        )
        # Clear query
        tbox.send_keys(Keys.CONTROL + "a")
        tbox.send_keys(Keys.DELETE)
        # Send query
        tbox.send_keys(query)

        query_btn = self.wait.until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="scrollNumber1"]/tbody/tr[2]/td[2]/table/tbody/tr[6]/td/input'))
        )
        query_btn.click()

        table = self.wait.until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="scrollNumber1"]/tbody/tr[2]/td[2]/table/tbody/tr[8]/td/table/tbody'))
        )
    
        # Get headers
        headers = [th.text.strip() for th in table.find_elements(By.TAG_NAME, "th")]
        
        # If there are no <th>, use first row as header
        if not headers:
            first_row = table.find_element(By.TAG_NAME, "tr")
            headers = [td.text.strip() for td in first_row.find_elements(By.TAG_NAME, "td")]
        
        # Get all rows
        rows = table.find_elements(By.TAG_NAME, "tr")
        
        table_data = []
        for row in rows[1:]:  # skip header row
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) == 0:
                continue  # skip empty rows
            row_data = {headers[i]: cells[i].text.strip() for i in range(len(cells))}
            table_data.append(row_data)
        
        return table_data
    

    def get_doc_bytes(self, doc_no):
        response = self.session.get(self.doc_url.format(document_no=doc_no), verify=False)

        if response.status_code == 200:
            return response.content
        else:
            logging.warning(f"Failed to download pdf bytes for {doc_no}")


