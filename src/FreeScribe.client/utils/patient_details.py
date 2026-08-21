"""
Patient demographics lookup helpers.

Provides database-backed retrieval of patient details (sex, health card number,
date of birth, name) directly from the Oscar EMR database.
"""

import os

import requests
import yaml

from chatbot.SSHTunnel import OscarDB
from chatbot.SeleniumOscarQuery import SOQ


def load_db_config(config_path=None):
    """
    Load the database connection settings from the chatbot config file.

    Args:
        config_path (str, optional): Path to the config yaml

    Returns:
        dict: A dict with the db connection parameters, or None if the config could not be loaded.
    """
    path = config_path if config_path is not None else None
    if path is None:
        print("No config.yaml found for database connection.")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if config is None:
            return None
        return {
            "query_choice": config.get("query_choice", "oscar"),
            "oscar_login": config.get("OscarLogin", {}),
            "selenium_path": config.get("Selenium", {}).get("geckodriver_path"),
            "ssh": config.get("SSH", {}),
        }
    except Exception as e:
        print(f"Failed to load database config: {e}")
        return None


class PatientDetailsDB:
    """
    Manages a database connection for patient detail lookups.

    Supports both SSH-tunneled MySQL access and Selenium based Query By Example (SOQ).
    """

    def __init__(self, config_path=None):
        self._cfg = load_db_config(config_path)
        self._conn = None

    def connect(self):
        if self._conn is not None:
            return
        if self._cfg is None:
            print("Database config unavailable; cannot connect.")
            return

        choice = self._cfg["query_choice"]
        if choice == "ssh":
            self._conn = self._connect_ssh()
        else:
            self._conn = self._connect_soq()

    def _connect_ssh(self):
        ssh = self._cfg["ssh"]
        oscar_login = self._cfg["oscar_login"]
        try:
            conn = OscarDB(
                ssh_host=ssh["ssh_host"],
                ssh_port=ssh.get("ssh_port", 22),
                ssh_user=ssh["ssh_user"],
                ssh_password=ssh["ssh_passw"],
                db_user=ssh["db_user"],
                db_password=ssh["db_passw"],
                db_name=ssh["db_name"],
                session=requests.session(),
                oscar_url=oscar_login.get("url", ""),
                db_host=ssh.get("db_host", "127.0.0.1"),
                db_port=ssh.get("db_port", 3306),
                local_bind_port=ssh.get("local_bind_port", 3307),
            )
            conn.connect()
            return conn
        except Exception as e:
            print(f"Failed to connect via SSH: {e}")
            return None

    def _connect_soq(self):
        oscar_login = self._cfg["oscar_login"]
        try:
            conn = SOQ(
                oscar_login.get("user"),
                oscar_login.get("passw"),
                oscar_login.get("pin"),
                oscar_login.get("url", ""),
                self._cfg.get("selenium_path"),
                headless=True,
                oscar_version=oscar_login.get("version", 15),
            )
            conn.run()
            return conn
        except Exception as e:
            print(f"Failed to connect via SOQ: {e}")
            return None

    @property
    def connection(self):
        self.connect()
        return self._conn

    def is_connected(self):
        return self.connection is not None

    def query_database(self, sql, params=None):
        conn = self.connection
        if conn is None:
            return None
        try:
            return conn.query_database(sql, params)
        except Exception as e:
            print(f"Database query failed: {e}")
            return None

    def cleanup(self):
        if self._conn is not None:
            try:
                self._conn.cleanup()
            except Exception as e:
                print(f"Failed to cleanup database connection: {e}")
            self._conn = None

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass


def find_details_from_db(db, surname, first_name):
    """
    Look up patient details directly from the Oscar EMR database.

    Searches the demographic table by first and last name and returns the
    fields required to build an HL7 header, matching the return shape of
    ``utils.hl7.find_details``.

    Args:
        db (PatientDetailsDB | OscarDB | SOQ): A database access object with a ``query_database`` method.
        surname (str): The patient's last name.
        first_name (str): The patient's first name.

    Returns:
        tuple: (sex, healthcare_number, dob, name, demographic_no) where dob is formatted 'YYYYMMDD', 
               or None if no match was found or the query failed.
    """
    surname = (surname or "").strip()
    first_name = (first_name or "").strip()
    query = f"""
        SELECT d.demographic_no, d.last_name, d.first_name, d.hin, d.year_of_birth, d.month_of_birth, d.date_of_birth, d.sex FROM demographic
        AS d LEFT JOIN provider AS p ON d.provider_no = p.provider_no 
        WHERE d.last_name = UPPER('{surname.replace("'", "''")}') AND d.first_name = UPPER('{first_name.replace("'", "''")}') LIMIT 1;
    """
    if hasattr(db, "connection") and hasattr(db.connection, "query_database"):
        conn = db.connection
    else:
        conn = db

    if conn is None:
        print("No database connection available for patient lookup.")
        return None

    try:
        results = conn.query_database(query)
    except Exception as e:
        print(f"Patient lookup query failed: {e}")
        return None

    if not results:
        print(f"No patient found for {first_name} {surname}.")
        return None

    row = results[0]
    yob = str(row.get("year_of_birth", ""))
    mob = str(row.get("month_of_birth", "")).zfill(2)
    day = str(row.get("date_of_birth", "")).zfill(2)
    dob = yob + mob + day

    name = f"{row.get('first_name')} {row.get('last_name')}".strip()
    healthcare_number = row.get("hin")
    try:
        healthcare_number = int(healthcare_number)
    except (TypeError, ValueError):
        pass

    return (
        row.get("sex"),
        healthcare_number,
        dob,
        name,
        str(row.get("demographic_no", "")),
    )
