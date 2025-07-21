import sqlite3
import pandas as pd

db_path = r'c:\Users\knigh\Desktop\databaseKiichu\database.db'


try:
    conn = sqlite3.connect(db_path)
    
    # Get total pulls count
    total_pulls = pd.read_sql("SELECT SUM(quantity) FROM user_inventory", conn).iloc[0,0]
    
    # Get variant distribution
    query = """
    SELECT cv.holo_type, cv.signature_type, SUM(ui.quantity) AS count 
    FROM user_inventory ui
    JOIN card_variants cv ON ui.card_variant_id = cv.id
    GROUP BY cv.holo_type, cv.signature_type
    """
    df = pd.read_sql(query, conn)
    df['rate'] = df['count'] / total_pulls
    
    print(f"Total pulls analyzed: {total_pulls}")
    print(df)

except sqlite3.Error as e:
    print(f"Database error: {e}")
finally:
    if conn: conn.close()