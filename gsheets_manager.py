"""
Google Sheets Manager for Guest Data
Handles CRUD operations with Google Sheets as a database
"""

import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import hashlib

class GuestDatabase:
    """
    Manages guest data in Google Sheets
    Expected format: Header row at row 1, data starting at row 2
    """
    
    def __init__(self):
        """Initialize connection to Google Sheets"""
        try:
            self.conn = st.connection("gsheets", type=GSheetsConnection)
        except Exception as e:
            st.warning(f"⚠️ Google Sheets connection issue: {str(e)[:100]}")
            self.conn = None
    
    def get_all_guests(self):
        """
        Retrieve all guests from the database
        Assumes: Row 1 = Header, Row 2+ = Data
        """
        if not self.conn:
            return pd.DataFrame()
        
        try:
            # Read the worksheet - header is automatically detected at row 1
            df = self.conn.read(header=0)  # header=0 means use first row as header
            
            if df.empty:
                return pd.DataFrame()
            
            # Remove empty rows (where STT is NaN or empty)
            df = df[df['STT'].notna() & (df['STT'] != '') & (df['STT'] != 'nan')]
            
            if df.empty:
                return pd.DataFrame()
            
            # Create standardized DataFrame
            result = pd.DataFrame()
            
            # Map fields to our standard format
            result['name'] = df.get('Họ tên', '')
            result['room'] = df.get('Số phòng', '').astype(str)
            result['arrival_date'] = df.get('Ngày đến', df.get('Ngày đến ', ''))
            result['departure_date'] = df.get('Ngày đi dự kiến', '')
            result['passport'] = df.get('Số hộ chiếu', '')
            result['dob'] = df.get('Ngày sinh', '')
            
            # Map gender
            gender_map = {'Nam': 'M', 'Nữ': 'F', 'M': 'M', 'F': 'F'}
            result['gender'] = df.get('GT', '').map(gender_map).fillna('Unknown')
            
            # Map nationality
            def extract_country_code(nat_str):
                if pd.isna(nat_str) or nat_str == '':
                    return ''
                
                country_codes = {
                    'Tuốc-mê-ni-xtan': 'TM', 'Nhật Bản': 'JP', 'CH Hàn Quốc': 'KR',
                    'Hàn Quốc': 'KR', 'Bồ Đào Nha': 'PT', 'Trung Quốc': 'CN',
                    'Ma-lai-xi-a': 'MY', 'I-ta-li-a': 'IT', 'Căm-pu-chia': 'KH',
                    'Xin-ga-po': 'SG', 'Ấn Độ': 'IN', 'Vương quốc Anh và Bắc Ai len': 'GB',
                    'Thuỵ Điển': 'SE', 'Đông Ti-mo': 'TL', 'CHDCND Lào': 'LA',
                    'In-đô-nê-xi-a': 'ID', 'Fi-ji': 'FJ', 'Mông Cổ': 'MN',
                    'Phi-líp-pin': 'PH', 'Băng-la-đét': 'BD', 'Hoa Kỳ': 'US',
                    'Gru-di-a': 'GE', 'Thái Lan': 'TH', 'Ô-xtrây-li-a': 'AU',
                    'Kê-ni-a': 'KE', 'Trung Quốc (Đài Loan)': 'TW'
                }
                
                nat_str = str(nat_str)
                for country, code in country_codes.items():
                    if country in nat_str:
                        return code
                return ''
            
            result['nationality'] = df.get('QT', '').apply(extract_country_code)
            
            # Document type - all are foreign guests with passport
            result['document_type'] = 'PAS'
            result['id_card'] = ''
            result['doc_number'] = result['passport']
            
            # Add database fields
            result['guest_id'] = result.apply(
                lambda row: self._generate_guest_id_from_row(row), axis=1
            )
            result['is_active'] = 'True'
            result['check_in_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            result['check_out_timestamp'] = ''
            
            # Hotel info (standardized)
            result['noi_cu_tru'] = '2 - Tạm trú'
            result['tinh_thanh'] = '101 - TP. Hà Nội'
            result['phuong_xa'] = '101900167 - Phường Cầu Giấy'
            result['dia_chi_chi_tiet'] = 'Số 5 Duy Tân'
            result['ly_do_cu_tru'] = '1 - Du lịch'
            
            # Clean up - remove rows with empty names
            result = result[result['name'].notna() & (result['name'] != '') & (result['name'] != 'nan')]
            
            return result
            
        except Exception as e:
            st.warning(f"⚠️ Could not read from Google Sheets: {str(e)[:100]}")
            import traceback
            print(traceback.format_exc())
            return pd.DataFrame()

    def _generate_guest_id_from_row(self, row):
        """Generate a unique guest ID from a row"""
        name = row.get('name', '')
        room = row.get('room', '')
        passport = row.get('passport', '')
        
        if passport and passport != '':
            hash_string = f"{passport}_{room}"
        else:
            hash_string = f"{name}_{room}"
        
        hash_obj = hashlib.md5(hash_string.encode())
        return f"G{hash_obj.hexdigest()[:8].upper()}"
    
    def get_active_guests(self):
        """Get all currently active guests (checked in)"""
        df = self.get_all_guests()
        if df.empty:
            return df
        return df[df['is_active'] == 'True']
    
    def search_guests(self, search_term):
        """Search for guests by name, room, or passport"""
        df = self.get_all_guests()
        if df.empty:
            return df
        
        mask = (
            df['name'].str.contains(search_term, case=False, na=False) |
            df['room'].str.contains(search_term, case=False, na=False) |
            df['passport'].str.contains(search_term, case=False, na=False)
        )
        return df[mask]
    
    def get_statistics(self):
        """Get statistics about the current guest database"""
        df = self.get_all_guests()
        if df.empty:
            return {'total': 0, 'active': 0, 'rooms_occupied': 0, 'nationalities': {}}
        
        active_df = df[df['is_active'] == 'True']
        
        stats = {
            'total': len(df),
            'active': len(active_df),
            'rooms_occupied': len(active_df['room'].unique()) if not active_df.empty else 0,
            'nationalities': {}
        }
        
        if not df.empty and 'nationality' in df.columns:
            nat_counts = df['nationality'].value_counts()
            stats['nationalities'] = nat_counts.to_dict()
        
        return stats
    
    def compare_with_extracted(self, extracted_guests):
        """Compare extracted guests with database guests"""
        db_guests = self.get_all_guests()
        
        if db_guests.empty:
            return extracted_guests, []
        
        new_guests = []
        existing_guests = []
        
        for guest in extracted_guests:
            mask = (
                (db_guests['room'] == str(guest.get('room', ''))) & 
                (db_guests['name'].str.upper() == guest.get('name', '').upper())
            )
            
            if mask.any():
                existing_guests.append(guest)
            else:
                if guest.get('passport'):
                    mask_pass = db_guests['passport'] == guest.get('passport')
                    if mask_pass.any():
                        existing_guests.append(guest)
                    else:
                        new_guests.append(guest)
                else:
                    new_guests.append(guest)
        
        return new_guests, existing_guests


def initialize_gsheets_demo():
    """Demo function to show how to use the GuestDatabase class"""
    st.subheader("📊 Google Sheets Database Demo")
    
    db = GuestDatabase()
    stats = db.get_statistics()
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Guests", stats['total'])
    with col2:
        st.metric("Active Guests", stats['active'])
    with col3:
        st.metric("Rooms Occupied", stats['rooms_occupied'])
    
    st.subheader("📋 All Guests")
    df = db.get_all_guests()
    if not df.empty:
        display_cols = ['guest_id', 'name', 'room', 'arrival_date', 'departure_date', 
                       'document_type', 'doc_number', 'is_active']
        available_cols = [col for col in display_cols if col in df.columns]
        st.dataframe(df[available_cols], use_container_width=True, height=400)
    else:
        st.info("No guests in database yet")