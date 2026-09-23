
import logging
import re
import time
import yaml
import requests
import json
from datetime import datetime, timedelta, timezone

from chatbot.SeleniumOscarQuery import SOQ
from chatbot.SSHTunnel import OscarDB
from Oscar import Oscar
from chatbot.Tools.Tool import ToolRegistry, TOOL_REGISTRY, ToolEmbeddings
from chatbot.AIConnect import AIConnect
from chatbot.RAG.VectorSearch import VectorSearch, VectorDB
from chatbot.utils.dailylogger import setup_daily_logger
from chatbot.Workflows.Workflow import WorkflowRegistry, WorkflowContext, WorkflowResult
from chatbot.ChatSession import ChatSession
import chatbot.Workflows

setup_daily_logger(r".\chatbot\logs", 'chatbot.log')

# Total workflow attempts (initial + retries)
MAX_VERIFICATION_ATTEMPTS = 3


class OscarCB:
    def __init__(self, config_path : str, record : bool = True):
        # Load prompts
        with open(r".\prompts\chatbot_prompts.yaml", "r", encoding="utf-8") as f:
            self.prompts = yaml.safe_load(f)

        # Load config file
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        try:
            self.db_conn = None
            self.oscar = None
            self.ai_conn = None
            self.vec_search = None
            self._initialize_connections()
        except Exception as e:
            logging.error(f"Unable to initialize connections: {e}")
            self.cleanup()


        self.curr_demo = None
        # used to feed the LLM context
        self.conversation_history = []
        # used to show the UI
        self.current_conversation = {}
        self.message_no = 0
        self.past_chats: dict[str, ChatSession] = {}
        self.active_chat_id: str | None = None
        self.tools = ToolRegistry(TOOL_REGISTRY)
        self.workflows = WorkflowRegistry.instantiate_all()
    

    def _initialize_oscar(self):
        """
        Initializes connection to Oscar EMR via Selenium.
        """
        try:
            # Oscar credentials
            oscar_login = self.config["OscarLogin"]
            user = oscar_login["user"]
            passw = oscar_login["passw"]
            pin = oscar_login["pin"]
            oscar_url = oscar_login["url"]
            oscar_version = oscar_login["version"]

            # Driver path
            driver_path = self.config["Selenium"]["geckodriver_path"]
        except Exception as e:
            logging.error(f"Failed to read Oscar config: {e}")
            self.oscar = None
            return False

        # Oscar login over Selenium is flaky (slow page loads, the SSL-bypass page
        # appearing late, element-wait races). Retry a few times, cleaning up the
        # half-open browser between attempts so failed tries don't leave orphans.
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            oscar = None
            try:
                oscar = Oscar(
                    user,
                    passw,
                    pin,
                    oscar_url,
                    driver_path,
                    oscar_version=oscar_version
                )
                oscar.run()
                self.oscar = oscar
                logging.info(f"Successfully Initialized Oscar Session (attempt {attempt}/{max_attempts})")
                return True
            except Exception as e:
                logging.error(f"Failed to initialize Oscar Session (attempt {attempt}/{max_attempts}): {e}")
                # Close the half-open browser before retrying so we don't leak a driver.
                if oscar is not None:
                    try:
                        oscar.cleanup()
                    except Exception:
                        pass
                if attempt < max_attempts:
                    time.sleep(3)

        self.oscar = None
        return False
     

    def _initialize_oscar_db(self):
        """
        Initializes connection to Oscar EMR database, either using Selenium or connecting through
        ssh.
        """
        try:
            # Oscar credentials
            oscar_login = self.config["OscarLogin"]
            user = oscar_login["user"]
            passw = oscar_login["passw"]
            pin = oscar_login["pin"]
            oscar_url = oscar_login["url"]
            oscar_version = oscar_login["version"]

            # Query choice (ssh or oscar)
            choice = self.config["query_choice"]

            # Driver path
            driver_path = self.config["Selenium"]["geckodriver_path"]

            # SSH Credentials
            ssh = self.config["SSH"]
            ssh_host = ssh["ssh_host"]
            ssh_port = ssh["ssh_port"]
            ssh_user = ssh["ssh_user"]
            ssh_password = ssh["ssh_passw"]
            db_host = ssh["db_host"]
            db_port = ssh["db_port"]
            local_bind_port = ssh["local_bind_port"]
            db_user = ssh["db_user"]
            db_password = ssh["db_passw"]
            db_name = ssh["db_name"]


            # Initialize Database Connection
            if choice == "ssh":
                session = requests.session()
                self.oscar.pass_cookies(session)
                self.db_conn = OscarDB(
                    ssh_host=ssh_host,
                    ssh_port=ssh_port,
                    ssh_user=ssh_user,
                    ssh_password=ssh_password,
                    db_user=db_user,
                    db_password=db_password,
                    db_name=db_name,
                    session=session,
                    oscar_url=oscar_url,
                    db_host=db_host,
                    db_port=db_port,
                    local_bind_port=local_bind_port
                )
                self.db_conn.connect()
            else:    
                self.db_conn = SOQ(
                    user, 
                    passw, 
                    pin, 
                    oscar_url, 
                    driver_path, 
                    headless=True,
                    oscar_version=oscar_version)
                self.db_conn.run()
            logging.info("Successfully initialized connection to Oscar EMR database.")
            return True
        
        except Exception as e:
            logging.error(f"Failed to initialize connection to Oscar EMR database: {e}")
            self.db_conn = None
            return False


    def _initialize_vector_db(self):
        """
        Initializes connection to the vector database.
        """
        try:
            # Initialize connection to database that holds vector embeddings
            vdb_config = self.config["VectorDB"]
            vec_db = VectorDB(
                host    =vdb_config["host"],
                port    =vdb_config["port"],
                dbname  =vdb_config["dbname"],
                user    =vdb_config["user"],
                password=vdb_config["password"]
            )
            tool_embds = ToolEmbeddings(path=r".\chatbot\Tools\tool_embeddings.jsonl")
            # Warn if any registered tool is missing an embedding (never selectable by vector search).
            tool_embds.verify_registry(TOOL_REGISTRY.keys())
            self.vec_search = VectorSearch(vec_db, tool_embds)
            logging.info("Successfully initialized connection to vector database")
            return True
        except Exception as e:
            logging.error(f"Failed to initialize connection to vector database: {e}")
            self.vec_search = None
            return False


    def _initialize_llm(self):
        """
        Initializes connection to the LLM via provided endpoint in given config file.
        """
        try:
            # AI Connection endpoint
            endpoint = self.config["AIConnection"]["endpoint"]
            api_key = self.config["AIConnection"]["api_key"]
            headers = self.config["AIConnection"].get("headers", {})
            
            # Initialize AI Connection
            self.ai_conn = AIConnect(endpoint, api_key=api_key, headers=headers, top_p=0.25, top_k=20)
            logging.info("Successfully Initialized AI Connection")
            return True
        except Exception as e:
            logging.error(f"Failed to initialize connection to LLM: {e}")
            self.ai_conn = None
            return False
        
        
    def _initialize_connections(self):
        """
        Initializes connections to Oscar EMR, Oscar database, vector database, and LLM.
        """
        res = self._initialize_oscar()
        if not res:
            pass
        res = self._initialize_oscar_db()
        if not res:
            pass
        res = self._initialize_llm()
        if not res:
            pass
        res = self._initialize_vector_db()
        if not res:
            pass


    def cleanup(self):
        """
        Closes opened connections.
        Closes oscar, oscar database, and vector database connections.
        """
        if self.oscar:
            self.oscar.cleanup()

        if self.db_conn:
            self.db_conn.cleanup()

        if self.vec_search:
            self.vec_search.cleanup()

        self.oscar = None
        self.db_conn = None
        self.vec_search = None


    def _generate_rag_string(self, user_input : str):
        """"""


    def _vector_search(self, key_string : str):
        """"""


    def _execute_tools(self, tools : str):
        """"""


    def decide_memory_needed(self, context: WorkflowContext, user_input: str) -> bool:
        """
        Asks the LLM if prior conversation memory is required.
        """
        try:
            prompt = context.prompts.get("memory_gate_prompt").format(user_input=user_input)
            result = context.ai_conn.send_message(prompt)
            # Extract the JSON object from the LLM response
            match = re.search(r"\{.*\}", result, re.DOTALL)
            needed = False
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    needed = bool(parsed.get("needs_memory", False))
                else:
                    # Fall back to a simple textual check of the response
                    needed = "true" in result.lower()
            logging.info(f"Memory gate decision: {needed}")
            return needed
        except Exception as e:
            logging.warning(f"Memory gate decision failed, defaulting to not include memory: {e}")
            return False


    def _build_context(self) -> WorkflowContext:
        return WorkflowContext(
            ai_conn=self.ai_conn,
            db_conn=self.db_conn,
            oscar=self.oscar,
            vec_search=self.vec_search,
            tools=self.tools,
            conversation_history=self.conversation_history,
            curr_demo=self.curr_demo,
            prompts=self.prompts,
        )


    def _verify_answer(self, user_input: str, result: WorkflowResult, context: WorkflowContext) -> dict:
        """
        Asks the LLM to judge whether a workflow response actually answers the
        user's request.

        Fails open (passes=True) on any error so a broken verifier never blocks
        a response. Returns a dict with keys ``passes``, ``retryable`` and
        ``reason``.
        """
        accepted = {"passes": True, "retryable": False, "reason": "verification skipped"}
        try:
            template = context.prompts.get("answer_verification_prompt")
            if not template:
                return accepted

            evidence = ""
            if result.metadata:
                evidence = result.metadata.get("context") or ""

            prompt = template.format(
                user_input=user_input,
                answer=result.response or "",
                context=evidence[:8000],
            )
            raw = context.ai_conn.send_message(prompt)

            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                logging.warning(f"Verification returned no JSON: {raw!r}")
                return accepted

            parsed = json.loads(match.group(0))
            verdict = {
                "passes": bool(parsed.get("passes", True)),
                "retryable": bool(parsed.get("retryable", False)),
                "reason": str(parsed.get("reason", "")),
            }
            logging.info(f"Verification verdict: {verdict}")
            return verdict
        except Exception as e:
            logging.warning(f"Answer verification failed, accepting response: {e}")
            return accepted


    def _run_with_verification(self, user_input: str, workflow_type: str, context: WorkflowContext) -> WorkflowResult:
        """
        Runs the selected workflow and verifies its answer, retrying with
        previously failed tools excluded when verification says a different
        tool could do better.

        Verification is applied to every response produced here, including
        responses that never passed through an LLM (e.g. patient-clarification
        or error messages).
        """
        workflow = self.workflows[workflow_type]
        result = workflow.run(user_input, context)

        for attempt in range(1, MAX_VERIFICATION_ATTEMPTS + 1):
            verdict = self._verify_answer(user_input, result, context)
            if verdict["passes"] or not verdict["retryable"]:
                break
            if attempt == MAX_VERIFICATION_ATTEMPTS:
                logging.info("Verification failed but retry budget exhausted")
                break

            attempted = (result.metadata or {}).get("tools_tried", []) if result.metadata else []
            context.excluded_tools = list(set(context.excluded_tools) | set(attempted))
            context.verification_feedback = verdict["reason"]
            logging.info(
                f"Verification failed (attempt {attempt}/{MAX_VERIFICATION_ATTEMPTS}): "
                f"{verdict['reason']}. Retrying with excluded tools {context.excluded_tools}"
            )
            result = workflow.run(user_input, context)

        return result

    def run(self, user_input, selected_workflow: str | None = None):
        if not user_input.strip(): return None, None, None

        demo_no = self.oscar.get_demographic_no()
        new_chat_result = None
        if self.curr_demo is None:
            self.curr_demo = demo_no
        elif demo_no != self.curr_demo:
            if demo_no is None:
                demo_no = self.curr_demo
            else:
                logging.info(f"Prev: {self.curr_demo} | New: {demo_no}")
                new_chat_result = self.new_chat()
                self.curr_demo = demo_no
        context = self._build_context()
        # Ask the LLM whether prior conversation memory is needed for this input
        context.memory_needed = self.decide_memory_needed(context, user_input)
        # if a forced workflow, no need to run classify
        if selected_workflow and selected_workflow in self.workflows:
            workflow_type = selected_workflow
        else:
            # classify workflow
            workflow_type = WorkflowRegistry.classify(user_input, context)

        # dispatch run call to respective workflow, verifying the answer and
        # retrying with a different tool if it does not hold up
        result = self._run_with_verification(user_input, workflow_type, context)

        # Store conversation
        self.current_conversation[self.message_no] = (user_input, result.response, workflow_type, result.sources)
        self.conversation_history.append(f"User: {user_input}\nChatbot: {result.response}")
        self.message_no += 1

        return workflow_type, result, new_chat_result



    def get_chat_label(self, chat_id : str):
        """
        Returns the display label of a saved chat session by id.
        """
        return self.past_chats[chat_id].label


    def load_chat(self, chat_id : str):
        """
        Loads an existing chat session into the working state, keyed by chat id.
        """
        session = self.past_chats[chat_id]
        self.current_conversation = dict(session.conversation)
        self.conversation_history = list(session.history)
        self.curr_demo = session.demo_no
        self.active_chat_id = chat_id
        self.message_no = len(self.current_conversation)

        return self._append_current_conversation()

    def _append_current_conversation(self):
        """
        Appends the current conversation into one string.
        """
        convo = ""
        for msg_no, (user, ai, workflow_type, sources) in self.current_conversation.items():
            workflow_label = f" [{workflow_type.replace('_', ' ').title()}]" if workflow_type else ""
            convo += f"USER:\n{user}\n\nCHATBOT{workflow_label}:\n{ai}\n\n"

        return convo
    

    def save_chat(self):
        """
        Stores/Saves the current chat session in past_chats, keyed by the chat id.
        Returns the saved chat id, or None if there was nothing to save.
        """
        # if no messages, nothing to save
        if not self.conversation_history:
            return None

        # update the current chat session
        if self.active_chat_id and self.active_chat_id in self.past_chats:
            self.past_chats[self.active_chat_id].update(
                self.curr_demo,
                self.current_conversation,
                self.conversation_history
            )
            return self.active_chat_id

        # create a new chat session
        session = ChatSession(self.curr_demo, self.current_conversation, self.conversation_history)
        self.past_chats[session.id] = session

        return session.id

    def new_chat(self):
        """
        Saves the current chat, returns the chat_id
        """
        result = self.save_chat()
        self.clear()

        return result


    def clear(self):
        """
        Clears conversation history without storing chat.
        """
        self.conversation_history.clear()
        self.current_conversation.clear()
        self.curr_demo = None
        self.active_chat_id = None
        self.message_no = 0

