from sshtunnel import SSHTunnelForwarder
import mysql.connector
import yaml
import logging

class OscarDB:
    def __init__(self, ssh_host, ssh_port, ssh_user, ssh_password,
                 db_user, db_password, db_name, session, oscar_url, db_host='127.0.0.1', db_port=3306, local_bind_port=3307):
        # SSH configuration
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        self.ssh_user = ssh_user
        self.ssh_password = ssh_password

        # Database configuration
        self.db_host = db_host
        self.db_port = db_port
        self.db_user = db_user
        self.db_password = db_password
        self.db_name = db_name

        # Local port for SSH tunnel
        self.local_bind_port = local_bind_port

        # Request session
        self.oscar_url = oscar_url
        self.session = session

        # Internal handles
        self.tunnel = None
        self.conn = None

    def connect(self):
        """Open SSH tunnel and connect to MySQL"""
        self.tunnel = SSHTunnelForwarder(
            (self.ssh_host, self.ssh_port),
            ssh_username=self.ssh_user,
            ssh_password=self.ssh_password,
            allow_agent=False,             # disable ssh-agent
            host_pkey_directories=[],      # disables scanning keys (avoids DSS)
            ssh_private_key=None,          # ensure no private key is loaded
            remote_bind_address=(self.db_host, self.db_port),
            local_bind_address=('127.0.0.1', self.local_bind_port)
        )
        self.tunnel.start()

        self.conn = mysql.connector.connect(
            host='127.0.0.1',
            port=self.local_bind_port,
            user=self.db_user,
            password=self.db_password,
            database=self.db_name
        )

    def query_database(self, sql, params=None):
        """Execute a SQL query and return results as a list of dicts"""
        if not self.conn:
            raise RuntimeError("Database not connected. Call connect() first.")
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute(sql, params or ())
        results = cursor.fetchall()
        cursor.close()
        return results

    def cleanup(self):
        """Close MySQL connection and SSH tunnel"""
        if self.conn:
            self.conn.close()
            self.conn = None
        if self.tunnel:
            self.tunnel.stop()
            self.tunnel = None

    def __del__(self):
        # Automatically close connections if still open
        self.cleanup()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def get_doc_bytes(self, doc_no):
        self.doc_url = self.oscar_url + "dms/ManageDocument.do?method=display&doc_no={document_no}"
        response = self.session.get(self.doc_url.format(document_no=doc_no), verify=False)

        if response.status_code == 200:
            return response.content
        else:
            logging.warning(f"Failed to download pdf bytes for {doc_no}")

