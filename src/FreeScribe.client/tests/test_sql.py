import sys
from chatbot.OscarChatbot import OscarCB

print("Initiating")
chatbot = OscarCB(config_path=r".\configs\config.yaml")
print("Established chatbot")
demo_no = input("Enter demo_no: ")
while demo_no != "q":
    print(f"Received demo_no {demo_no}")
    measurement_results = {}
    for measurement_type in ["ecg", "ECHO"]:
        query = f"""
        SELECT *
        FROM measurements
        WHERE demographicNo = {demo_no}
        AND type LIKE '%{measurement_type}%'
        AND dateObserved >= DATE_SUB(CURDATE(), INTERVAL 1 MONTH)
        ORDER BY dateObserved DESC
        """
        print(f"Created query for {measurement_type}")
        results = chatbot.db_conn.query_database(query)
        measurement_results[measurement_type] = results
        print(f"Results: {results}")
    demo_no = input('Enter new demo_no, or "q" to quit: ')
chatbot.cleanup()