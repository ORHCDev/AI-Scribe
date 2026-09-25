from chatbot.OscarChatbot import OscarCB

print("Initiating")
chatbot = OscarCB(config_path=r".\configs\config.yaml")
print("Established chatbot")
query = """
SELECT type, COUNT(*) AS count
FROM measurements
WHERE type LIKE '%MEDS%'
GROUP BY type
ORDER BY type
"""
print(f"Created query")
results = chatbot.db_conn.query_database(query)
print(f"Results: {results}")
for result in results:
    print(f"{result['type']}: {result['count']}")
chatbot.cleanup()