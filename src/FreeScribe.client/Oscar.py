
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
    def __init__(self, user, passw, pin, oscar_url, driver_path, headless=False, oscar_version=15, wait_timeout=20):
        self.user = user
        self.passw = passw
        self.pin = pin
        self.oscar_url = oscar_url
        self.oscar_version=oscar_version
        self.oscar_login_url = self.oscar_url + "index.jsp"
        self.driver_path = driver_path
        self.headless = headless
        self.wait_timeout = wait_timeout

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

            # Auto-accept native confirm dialogs (e.g. Oscar's "You have started to
            # edit this note in another window ... continue?", which fires when a
            # stale/orphaned session still holds an edit lock). Without this the
            # default "dismiss and notify" cancels the dialog and raises
            # UnexpectedAlertOpenError, aborting the note write.
            options.unhandled_prompt_behavior = "accept"

            service = Service(self.driver_path)
            self.driver = webdriver.Firefox(service=service, options=options)
            self.wait = WebDriverWait(self.driver, self.wait_timeout)

            # record current process's geckodriver PID for cleaning purposes
            try:
                with open(r".\chatbot\logs\owned_drivers.pids", "a") as _f:
                    _f.write(f"{self.driver.service.process.pid}\n")
            except Exception:
                pass

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

    def get_patient_name(self):
        """
        Iterates over the opened windows. If an encounter window is opened will return the
        name of the patient opened in that window, read directly from the browser page title.
        """
        patient_name = None

        for handle in self.driver.window_handles:
            self.driver.switch_to.window(handle)
            url = self.driver.current_url

            match = re.search(r"demographicNo=(\d+)", url)
            if match:
                try:
                    patient_name = self.driver.title.strip()
                except Exception as e:
                    logging.error(f"Failed to read encounter page title: {e}")
                    patient_name = None
                return patient_name

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

    def insert_text_into_0letter(self, fdid, consult, med_hist=None, ecg_info=None, echo_info=None):
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

            # Insert ECG info if given
            if ecg_info:
                focus_and_insert("ECG", ecg_info)

            # Insert ECHO info if given
            if echo_info:
                focus_and_insert("ECHO", echo_info)

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

    def insert_text_into_0letter_from_headings(self, fdid, full_text, overwrite_existing):
        """
        Will input the given text into the most recent 0letter eform recorded
        in the patient's encounter page, according to the headings present.
        """
        
        HEADINGS = [
            "RISK FACTORS", "PAST CARDIAC HISTORY", "PAST MEDICAL HISTORY", "HISTORY OF PRESENT ILLNESS", "SOCIAL HISTORY",
            "MEDICATIONS", "ALLERGIES", "EXAM", "ECG", "ECHO", "LAB WORK", "ASSESSMENT", "PLAN"
        ]

        def replace_section(heading, text):
            next_headings = HEADINGS[HEADINGS.index(heading) + 1:]

            if not overwrite_existing:
                focus_and_insert(heading, f"{heading}\n{text}")
                return True

            # When overwriting the final section, use the signature as the boundary
            next_headings = HEADINGS[HEADINGS.index(heading) + 1:]
            if not next_headings:
                next_headings = ["Yours Sincerely,"]

            script = """
            const headingText = arguments[0];
            const newText = arguments[1];
            const nextHeadings = arguments[2];
            const overwrite = arguments[3];

            const paras = Array.from(document.getElementsByTagName('p'));

            const headingPara = paras.find(
                p => p.textContent.trim().startsWith(headingText)
            );

            if (!headingPara) {
                return false;
            }

            // Append text only
            if (!overwrite) {
                const range = document.createRange();
                range.selectNodeContents(headingPara);
                range.collapse(false);

                range.insertNode(document.createTextNode(newText));

                return true;
            }

            // Overwrite existing text
            const headingTextContent = headingPara.textContent;
            const colonIndex = headingTextContent.indexOf(":");

            if (colonIndex === -1) {
                return false;
            }

            // Find next heading/signature
            const headingIndex = paras.indexOf(headingPara);

            let nextHeadingPara = null;

            for (let i = headingIndex + 1; i < paras.length; i++) {
                const paragraphText = paras[i].textContent.trim();

                if (
                    nextHeadings.some(
                        h => paragraphText.startsWith(h.trim())
                    )
                ) {
                    nextHeadingPara = paras[i];
                    break;
                }
            }

            // Find colon in current paragraph
            const walker = document.createTreeWalker(
                headingPara,
                NodeFilter.SHOW_TEXT
            );

            let node;
            let currentOffset = 0;
            let startNode = null;
            let startOffset = 0;

            while (node = walker.nextNode()) {
                const colonPosition = node.textContent.indexOf(":");

                if (colonPosition !== -1) {
                    startNode = node;
                    startOffset = colonPosition + 1;
                    break;
                }

                currentOffset += node.textContent.length;
            }

            if (!startNode) {
                return false;
            }

            const range = document.createRange();

            // Start immediately after the colon
            range.setStart(startNode, startOffset);

            // End immediately before the next heading/signature
            if (nextHeadingPara) {
                range.setEndBefore(nextHeadingPara);
            } else {
                // Expected boundary was not found
                range.setEndAfter(headingPara);
            }

            // Remove old section contents
            range.deleteContents();

            // Insert new section contents
            range.insertNode(document.createTextNode(newText));

            return true;
            """

            return self.driver.execute_script(
                script,
                heading,
                text,
                next_headings,
                overwrite_existing
            )

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
            # Preprocessing of text
            HEADING_PATTERN = "|".join(re.escape(h) for h in HEADINGS)

            sections = re.split(
                rf'(?=^(?:{HEADING_PATTERN})\s*$)',
                full_text,
                flags=re.MULTILINE
            )
            sections = [section.strip() for section in sections if section.strip()]

            parsed_sections = {}
            for section in sections:
                heading, separator, content = section.partition("\n")
                stripped_heading = heading.strip()
                stripped_contents = content.strip()
                parsed_sections[stripped_heading] = stripped_contents
                print(f"Processed section {stripped_heading}")
                print(f"Contents: {stripped_contents}")

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

            # Insert present text
            for heading in HEADINGS:
                if heading in parsed_sections:
                    success = replace_section(heading, parsed_sections[heading])
                    if success:
                        print(f"Inserted section {heading}")

            # Click submit
            self.driver.switch_to.default_content()
            submit_btn = self.wait.until(
                EC.presence_of_element_located((By.XPATH, "/html/body/form/div[2]/table/tbody/tr/td/input[2]"))
            )
            submit_btn.click()

            # Close window and switch to encounter window
            self.driver.close()
            self.driver.switch_to.window(self.home_window)
            
            return

        except Exception as e:
            import traceback
            traceback.print_exc()
            

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




