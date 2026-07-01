# test_gsheets.py
import streamlit as st
from gsheets_manager import GuestDatabase

def test():
    print("=" * 50)
    print("Testing Simple Google Sheets Connection")
    print("=" * 50)
    
    db = GuestDatabase()
    
    if db.conn:
        print("✅ Connection successful")
        
        df = db.get_all_guests()
        print(f"✅ Found {len(df)} guests")
        
        if not df.empty:
            print("\n📋 First 5 guests:")
            print(df[['name', 'room', 'passport', 'nationality']].head(5))
            
            stats = db.get_statistics()
            print(f"\n📊 Total: {stats['total']} guests")
        else:
            print("📭 No guests found")
    else:
        print("❌ Connection failed")

if __name__ == "__main__":
    test()