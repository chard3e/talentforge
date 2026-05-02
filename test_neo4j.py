from neo4j import GraphDatabase
from dotenv import load_dotenv
import os

load_dotenv()

# Neo4j bağlantı bilgileri
URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")

def test_connection():
    try:
        driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))
        driver.verify_connectivity()
        print("✅ Neo4j bağlantısı BAŞARILI!")
        
        # Basit bir sorgu testi
        with driver.session() as session:
            result = session.run("RETURN 'Merhaba TalentForge!' AS message")
            record = result.single()
            print("📌 Test sorgusu sonucu:", record["message"])
        
        driver.close()
        
    except Exception as e:
        print("❌ Bağlantı hatası:", e)

if __name__ == "__main__":
    test_connection()