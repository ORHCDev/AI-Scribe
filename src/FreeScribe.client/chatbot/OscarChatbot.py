
import logging
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

setup_daily_logger(r".\chatbot\logs", 'chatbot.log')


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
        self.conversation_history = []
        self.past_chats = {}
        self.current_conversation = {}
        self.message_no = 0
        self.tools = ToolRegistry(TOOL_REGISTRY)
    

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

            # Initialize Oscar Session
            self.oscar = Oscar(
                user, 
                passw, 
                pin, 
                oscar_url, 
                driver_path,
                oscar_version=oscar_version
            )
            self.oscar.run()
            logging.info("Successfully Initialized Oscar Session")
            return True
        except Exception as e:
            logging.error(f"Failed to initialize Oscar Session: {e}")
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
            
            # Initialize AI Connection
            self.ai_conn = AIConnect(endpoint, top_p=0.25, top_k=20)
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
        """Closes opened connections"""
        if self.oscar:
            self.oscar.cleanup()

        if self.db_conn:
            self.db_conn.cleanup()

        if self.vec_search:
            self.vec_search.cleanup()


    def _generate_rag_string(self, user_input : str):
        """"""


    def _vector_search(self, key_string : str):
        """"""


    def _execute_tools(self, tools : str):
        """"""



    def run(self, user_input):
        """
        
        """

        today = datetime.now()

        # Get AI to generate RAG search string
        rag_prompt = self.prompts.get("date_rag_prompt").format(
            resp_format=self.prompts.get("resp_format"),
            year=today.year,
            month=today.month,
            today=today.date(),
            yesterday=(today - timedelta(days=1)).date(),
            last_week=(today - timedelta(weeks=1)).date(),
            last_month=(today - timedelta(days=30)).date(),
            last_year=(datetime(year=(today.year - 1), month=today.month, day=1)).date(),
            user_input=user_input
        )
        rag_str = self.ai_conn.send_message(rag_prompt)
        rag_str = rag_str.replace("```json", "").replace("```", "").replace("**JSON only**", "").strip()
        rag_json = json.loads(rag_str)

        rstr = rag_json["RAG"]
        date = rag_json["date"]

        #self._write_out(rag_prompt, "#")
        #self._write_out(rag_str, "$")

        
        demo_no = self.oscar.get_demographic_no()
        if self.curr_demo is None:
            self.curr_demo = demo_no
        elif demo_no != self.curr_demo:
            if demo_no is None:
                demo_no = self.curr_demo
            else:
                logging.info(f"Prev: {self.curr_demo} | New: {demo_no}")
                self.curr_demo = demo_no
                self.new_chat()

        # Perform RAG search on tool embeddings and documents
        date_rank = False
        if date == 'old' or date == 'recent':
            date_rank = True
            embeddings = self.vec_search.search(
                query=rag_str,
                patient_id=demo_no,
                top_k=10,
                to_dict=True
            )
        else:
            embeddings = self.vec_search.search(
                query=rag_str,
                patient_id=demo_no,
                top_k=10,
                date=date
            )
        
        tool_embds = embeddings["tools"]
        doc_embds = embeddings["documents"]
        msr_embds = embeddings["measurements"]


        # Combine for reranking
        chunks = []
        
        for t in tool_embds:
            data = {
                "tool_name" : t["tool_name"],
                "text" : t["description"],
                "obs_date" : datetime.now(timezone.utc),
                "args" : t["metadata"]["params"],
                "is_tool" : True
            }
            chunks.append(data)

        for d in doc_embds:
            data = {
                "id" : d["document_id"],
                "type" : d["document_type"],
                "obs_date" : d["observation_date"],
                "text" : d["chunk_text"],
                "is_tool" : False
            }
            chunks.append(data)

        for m in msr_embds:
            data = {
                "id" : m["measurement_ids"],
                "type" : m["measurement_type"],
                "obs_date" : m["observation_date"],
                "text" : m["chunk_text"],
                "is_tool" : False
            }
            chunks.append(data)

        # Re-rank and take top 5 results
        if date_rank:
            reranked = self.vec_search.date_rank(rstr, chunks, text_key="text", date_key="obs_date", recency_method=date, batch_size=8)
        else:
            reranked = self.vec_search.rank(rstr, chunks, batch_size=8)
        top_k = reranked[:10]
        logging.info(f"Top results{top_k}")
        # Extract tools and prompt LLM
        tools = [elem[1] for elem in top_k if elem[1]["is_tool"]]
        
        tool_context = ""
        if tools:
            tool_str = ""
            for t in tools:
                tool_str += f"{t}\n" 
            tool_prompt = self.prompts.get("rag_tool_prompt").format(
                tool_protocol=self.prompts.get("rag_tool_protocol"),
                demo_no=demo_no,
                user_input=user_input,
                tools=tool_str,
            )
        
            tool_resp = self.ai_conn.send_message(tool_prompt)
            
            #self._write_out(tool_prompt, "#")
            #self._write_out(tool_resp, "$")

            # Execute any tools the AI selected and append results as context
            tool_select = tool_resp.replace("```json", "").replace("```", "").replace("**JSON only**", "").strip()
            if tool_select.startswith("["):
                # Load tool
                tool_call = json.loads(tool_select)
                for tool in tool_call:
                    logging.info(f"Calling tool: {tool}")
                    name = tool.get("tool_name")
                    args = tool.get("args")
                    args["db_conn"] = self.db_conn
                    res = self.tools.execute_tool(name, **args)
                    tool_context += f"Tool: {name}\nResults: {res}\n\n"

        MAX_LEN = 15000
        cur_len = len(self.prompts.get("followup")) + len(tool_context)

        # Generate context string
        doc_context = ""
        for elem in top_k:
            if not elem[1]["is_tool"]:
                doc_context += f"Date Observed: {elem[1]['obs_date'].strftime('%Y-%m-%d')}\nDocument ID: {elem[1]['id']}\nContent:{elem[1]['text']}\n\n"
                if len(doc_context) + cur_len > MAX_LEN:
                    break


        # Combine tool and document
        if not tool_context:
            context = f"Document Context:\n{doc_context}"
            logging.info("No tools selected")
        else:
            context = f"Document Context:\n{doc_context}\n\nTool Context:\n{tool_context}"

        #print(f"{'$'*50}\nDOCUMENT CONTEXT:{doc_context}\n{'$'*50}")
        #print(f"{'&'*50}\nTOOL CONTEXT: {tool_context}\n{'&'*50}")

        # Get AI followup response for User question with provided context
        if self.conversation_history:
            history = '\n'.join(self.conversation_history)
            convo_history = f"Conversation History:{history}\nInput:{user_input}\n"
        else:
            convo_history = user_input

        followup_prompt = self.prompts.get("followup").format(
            user_input=convo_history,
            context=context
        )
        logging.info(f"Followup: {followup_prompt}")
        resp = self.ai_conn.send_message(followup_prompt) 
        # self._write_out(followup_prompt, "#")
        # self._write_out(resp, "$")

        # Store current conversation
        self.current_conversation[self.message_no] = (user_input, resp)
        self.message_no += 1

        return resp


    def send_message(self, message):
        """
        Sends given message to LLM and returns response
        """

        if message.strip() == "": return


    def load_chat(self, timestamp : str):
        """
        Loads an existing chat that has been saved using the given timestamp key.
        """
        past_chat = self.past_chats[timestamp]
        self.current_conversation = past_chat["chat"]
        self.conversation_history = past_chat["full_history"]
        self.curr_demo = past_chat["demo_no"]

        return self._append_current_conversation()

    def _append_current_conversation(self):
        """
        Appends the current conversation into one string.
        """
        convo = ""
        for msg_no, msg in self.current_conversation.items():
            for user, ai in msg:
                convo += f"USER:\n{user}\n\nCHATBOT:\n{ai}\n"

        return convo
    

    def _store_chat(self, timestamp : str):
        """
        Stores current chat in dictionary where the key is the given timestamp. 
        """
        self.past_chats[timestamp] = {
            "chat" : self.current_conversation,
            "full_history" : self.conversation_history,
            "demo_no" : self.curr_demo
        }

    def new_chat(self):
        """
        Clears current converstaion history and stores chat. 
        """
        # Store current chat
        timestamp = datetime.now().time().strftime("%H:%M:%S")
        self._store_chat(timestamp)

        # Clear current conversation, stored history, and demo_no
        self.conversation_history.clear()
        self.current_conversation.clear()
        self.curr_demo = None

        return timestamp


    def clear(self):
        """
        Clears conversation history without storing chat.
        """
        self.conversation_history.clear()
        self.current_conversation.clear()
        self.curr_demo = None

