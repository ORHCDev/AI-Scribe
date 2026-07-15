
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import logging
import re
import requests
from bs4 import BeautifulSoup
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import time

class Oscar:
    def __init__(self, user, passw, pin, oscar_url, driver_path, headless=False, oscar_version=15):
        self.user = user
        self.passw = passw
        self.pin = pin
        self.oscar_url = oscar_url
        self.oscar_version=oscar_version
        self.oscar_login_url = self.oscar_url + "index.jsp"
        self.driver_path = driver_path
        self.headless = headless

        self.home_window = None
        self.initialize_driver()

        # Link templates
        self.eform_template = self.oscar_url + "eform/efmshowform_data.jsp?fdid={fdid}&appointment=null&parentAjaxId=eforms"
        self.doc_template = self.oscar_url + "dms/ManageDocument.do?method=display&doc_no={document_no}"
        self.new_eform_template = self.oscar_url + "eform/efmformadd_data.jsp?fid={fid}&demographic_no={demo_no}&appointment=null"
        self.new_blank_eform_template = self.oscar_url + "eform/efmshowform_data.jsp?fid={fid}"
        
        # Session
        self.session = requests.session()
        


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
        self.home_window = self.driver.current_window_handle

        self.pass_cookies(self.session)


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
            if self.oscar_version == 15:
                user_path = "//*[@id='loginText']/form/input[1]"
                passw_path = "//*[@id='loginText']/form/input[2]"
                pin_path = "//*[@id='loginText']/form/input[4]"
                login_btn_path = "//*[@id='loginText']/form/input[3]"
            elif self.oscar_version == 19:
                user_path = '//*[@id="username"]'
                passw_path = '//*[@id="password2"]'
                pin_path = '//*[@id="pin2"]'
                login_btn_path = '/html/body/div/div/div[2]/form/button'

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


            username_input = self.driver.find_element(By.XPATH, user_path)
            password_input = self.driver.find_element(By.XPATH, passw_path)
            level_pass = self.driver.find_element(By.XPATH, pin_path)

            username_input.send_keys(self.user)
            password_input.send_keys(self.passw)
            level_pass.send_keys(self.pin)

            sign_in_btn = self.driver.find_element(By.XPATH, login_btn_path)
            sign_in_btn.click()
            logging.info("Successfully submitted login form.")

        except Exception as e:
            logging.error(f"Error during login: {e}")


    def get_demographic_no(self):
        """
        Iterates over the opened windows. If an encounter window is opened will return the
        demographic number of the patient opened in that window.
        """
        demo_no = None

        for handle in self.driver.window_handles:
            self.driver.switch_to.window(handle)
            url = self.driver.current_url

            match = re.search(r"demographicNo=(\d+)", url)
            if match:
                demo_no = match.group(1)
                return demo_no

        # Switch back to home window
        self.driver.switch_to.window(self.home_window)


    def pass_cookies(self, session : requests.Session):
        """
        Will pass the driver session cookies to the given request session.

        Params
        ------
        session : requests.Session
            Request session that will recieve the saved cookies
        """

        # Pass session cookies
        cookies = self.driver.get_cookies()
        for cookie in cookies:
            session.cookies.set(cookie["name"], cookie["value"])


    def open_doc(self, doc_no):
        """
        Opens document window
        """
        # Url to open document
        doc_url = self.oscar_url + f"dms/ManageDocument.do?method=display&doc_no={doc_no}"

        # Open document windwo
        self.driver.switch_to.new_window("window")
        self.driver.get(doc_url)

        # Switch back to home window
        self.driver.switch_to.window(self.home_window)


    def open_eform(self, fdid, switch_home=True):
        """
        Opens an existing eForm using the form data id.
        """
    
        link = self.eform_template.format(
            fdid=fdid
        )

        self.driver.execute_script(f"window.open('{link}', '_blank', 'width=800,height=600');")
        if switch_home:
            self.driver.switch_to.window(self.home_window)
        return True


    def open_new_eform(self, fid : str | int, checkboxes : list[str]=None):
        """
        Opens a new blank eform for opened patient using the form id.

        Args
        ----
        fid : str | int
            The form id. 

        checkboxes : list(str)
            List of checkbox field names to pre-select when openeing eForm.

        Returns
        -------
        Returns False is no demographic number can be found, True if successfully opens eForm.
        """
        # Get opened patient's demographic number
        demo_no = self.get_demographic_no()
        if demo_no is None:
            print("No encounter page opened; Can't open new eform")
            return False

        # Open eForm
        link = self.new_eform_template.format(
            fid=fid,
            demo_no=demo_no
        )
        self.driver.execute_script(f"window.open('{link}', '_blank', 'width=800,height=600');")
        if checkboxes:
            # Switch to new window
            self.driver.switch_to.window(self.driver.window_handles[-1])
            # Wait for checkboxes to load
            self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, f'input[name="{checkboxes[0]["name"]}"]'))
            )

            # Build and execute JS to check all specified boxes
            js_checks = []
            for field in checkboxes:
                field_name = field["name"]
                field_type = field["type"]
                field_value = field["value"]
                if field_type == "checkbox":
                    js_checks.append(f"""
                        var cb = document.querySelector('input[name="{field_name}"]');
                        if (cb) {{
                            cb.checked = true;
                            if (cb.onclick) {{ try {{ cb.onclick(); }} catch(e) {{}} }}  // fires the add() calls too
                        }}
                    """)
                elif field_type == "text":
                    js_checks.append(f"""
                        var cb = document.querySelector('input[id="{field_name}"]');
                        if (cb) {{
                            cb.value = "{field_value}";
                        }}
                    """)
                    print(f"""
                        var cb = document.querySelector('input[id="{field_name}"]');
                        if (cb) {{
                            cb.value = "{field_value}";
                        }}
                    """)
            # Execute JS
            self.driver.execute_script("\n".join(js_checks))
        self.driver.switch_to.window(self.home_window)

        return True


    def get_document_bytes(self, doc_no):
        """
        Returns the PDF bytes for the given document id.
        """
        link = self.doc_template.format(
            document_no=doc_no
        )
        resp = self.session.get(link, verify=False)

        if resp.status_code == 200:
            return resp.content
        else:
            print("Failed to get PDF bytes")


    def _get_blank_eform_html(self, fid):
        """
        Returns eForm HTML content from a blank eform using form id.
        """

        link = self.new_blank_eform_template.format(
            fid=fid
        )
        resp = self.session.get(link, verify=False)

        if resp.status_code == 200:
            return resp.content
        else:
            print("Failed to get eForm HTML")


    def _get_filled_eform_html(self, fdid):
        """
        Returns eForm HTML content from a filled patient eform using the form data id.
        """

        link = self.eform_template.format(
            fdid=fdid
        )
        resp = self.session.get(link, verify=False)

        if resp.status_code == 200:
            return resp.content
        else:
            print("Failed to get eForm HTML")
        

    def get_0letter_text(self, fdid):
        """
        Extracts and returns 0letter eForm text.
        Requires that passed fdid is the form data id for an 0letter.
        """
        # Get HTML
        html = self._get_filled_eform_html(fdid)
        # Organize HTML
        soup = BeautifulSoup(html, "lxml")
        # Search for text area
        textarea = soup.find("textarea", {"id": "Letter"})

        # Return text if textarea exists
        if textarea and textarea.text.strip():
            return textarea.text.strip()

        textarea = soup.find("textarea", {"name" : "sbx"})

        if not textarea:
            return None

        return textarea.text.strip()

    def insert_text_into_0letter(self, fdid, consult, med_hist=None):
        """
        Will input the given text into the most recent 0letter eform recorded
        in the patient's encounter page.
        """

        def focus_cursor_before(indicator):
            length = len(indicator)
            """Focus cursor to right before given indicator on 0letter note"""
            paras = "const paras = Array.from(document.getElementsByTagName('p'));\n"
            p = f"const p = paras.find(el => el.textContent.includes('{indicator}'));\n"

            script = paras + p + f"""
                if (!p) return;

                if (!p.firstChild) {{
                    p.appendChild(document.createTextNode(''));
                }}

                const range = document.createRange();
                range.setStart(p.firstChild, p.firstChild.length);
                range.collapse(true);

                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
            """
            
            self.driver.execute_script(script)

        def focus_cursor_after_indicator(indicator):
            """Focus cursor right after the given indicator in a 0-letter note"""
            script = f"""
            const paras = Array.from(document.getElementsByTagName('p'));
            const p = paras.find(el => el.textContent.includes('{indicator}'));
            if (!p) return;

            if (!p.firstChild) {{
                p.appendChild(document.createTextNode(''));
            }}

            // Find offset after the indicator text
            const textNode = p.firstChild;
            const offset = textNode.textContent.indexOf('{indicator}') + '{indicator}'.length;

            const range = document.createRange();
            range.setStart(textNode, offset);
            range.collapse(true);

            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            """

            return script

        def focus_curson_at_end():
            """Focus cursor to end of 0letter note"""
            self.driver.execute_script("""
                const body = document.body;

                // Ensure body has something selectable
                if (!body.lastChild) {
                    body.appendChild(document.createElement('p'));
                }

                const range = document.createRange();
                range.selectNodeContents(body);
                range.collapse(false); // false = end of document

                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
            """)
        
        def toggle_off_bold():
            # toggle bold off
            if  self.driver.execute_script("return document.queryCommandState('bold');"):
                print("Toggled")
                self.driver.execute_script("""
                    // Force bold OFF
                    document.execCommand('bold', false, null);

                    // Normalize font weight at caret
                    document.execCommand('removeFormat', false, null);
                """)

        def focus_and_insert(indicator, text):
            focus_cursor_before(indicator)
            body.send_keys(Keys.HOME)
            for i in range(len(indicator) + 1):
                body.send_keys(Keys.ARROW_RIGHT)
            body.send_keys(Keys.ENTER)
            toggle_off_bold()
            body.send_keys(text)
            body.send_keys(Keys.ENTER)
            

        try:
            # Extract text from each section
            hpi_key = "History of Presenting Illness:"
            imp_key = "Impression/Assessment:"
            plan_key = "Plan:"

            # Find starting indices
            i_hpi = consult.find(hpi_key)
            i_imp = consult.find(imp_key)
            i_plan = consult.find(plan_key)
            
            hpi, imp, plan = None, None, None

            # Slice each section by using the start of the next section
            if i_hpi != -1:
                hpi = consult[i_hpi + len(hpi_key) : i_imp].strip()
            if i_imp != -1:
                imp = consult[i_imp + len(imp_key) : i_plan].strip()
            if i_plan != -1:
                plan = consult[i_plan + len(plan_key) : ].strip()

            # Additional check if hpi, imp, or plan are empty
            try:
                # Split consult into chunks
                chuncks = [chunk.strip() for chunk in consult.strip().split("\n\n")]
                # Assign if missing
                if not hpi: hpi = chuncks[0]
                if not imp: imp = chuncks[1]
                if not plan: plan = chuncks[2]
            except Exception as e:
                print(f"Error assigning chuncks: {e}")

            # Open and switch to eForm window
            self.open_eform(fdid, switch_home=False)
            self.driver.switch_to.window(self.driver.window_handles[-1])
            self.driver.maximize_window()
            time.sleep(2)
            
            # Switch to iframe
            self.driver.switch_to.frame("edit")
            # Focus on 0letter body
            body = self.wait.until(
                EC.presence_of_element_located((By.XPATH, "//body"))
            )
            body.click()

            focus_and_insert("HISTORY OF PRESENT ILLNESS", hpi)
            focus_and_insert("ASSESSMENT", imp)
            focus_and_insert("PLAN", plan)

            # Insert medical history if given
            if med_hist:
                focus_and_insert("PAST CARDIAC HISTORY", med_hist)

            # Switch out of iframe
            self.driver.switch_to.default_content()

            # Click submit
            submit_btn = self.wait.until(
                EC.presence_of_element_located((By.XPATH, "/html/body/form/div[2]/table/tbody/tr/td/input[2]"))
            )
            submit_btn.click()

            # Close window and switch to encounter window
            self.driver.close()
            self.driver.switch_to.window(self.home_window)
            
            return
        except Exception as e:
            print(f"error: {e}")
            return


    def get_eform_checkboxes(self, fid):
        """
        Returns a list of dictionaries where each element is a checkbox on the eForm.
        """

        # Get HTML
        html = self._get_blank_eform_html(fid)

        # Organize HTML
        soup = BeautifulSoup(html, "lxml")

        # Find all 'input' elements

        inputs = soup.find_all("input")

        # Filter inputs for checkboxes that aren't tagged with an oscardb flag
        checkboxes = []
        for i in inputs:
            # Get oscardb flag and input type            
            oscardb_flag = i.get("oscardb")
            input_type = i.get("type")

            # Only add if no db flag and is checkbox
            if oscardb_flag is None and input_type == "checkbox":
                
                # Get checkbox full name
                try:
                    full_name = i.next_sibling.strip()
                except:
                    full_name = ""

                cid = i.get("id")
                name = i.get("name")
                # Add to list
                checkboxes.append({
                    "type"      : "checkbox",
                    "id"        : cid or name,
                    "name"      : name or cid,
                    "full_name" : full_name or name,
                    "value"     :   i.get("value"),
                    "onclick"   : i.get("onclick"),  
                })

        return checkboxes




