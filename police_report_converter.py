"""
Police Report to XML/Excel Converter
Extracts guest data from police report PDF and converts to:
- XML for foreign guests (KHAI_BAO_TAM_TRU)
- Excel for Vietnamese guests (DS_KHACH_VIET_NAM_LUU_TRU)
"""

import streamlit as st
import pdfplumber
import re
from datetime import datetime
import pandas as pd
import xml.etree.ElementTree as ET
from xml.dom import minidom
from io import BytesIO
import base64
import json
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils.dataframe import dataframe_to_rows
from gsheets_manager import GuestDatabase

# Country code mapping (2-letter → 3-letter)
COUNTRY_CODE_MAP = {
    'AU': 'AUS',
    'JP': 'JPN', 
    'VN': 'VNM',
    'KR': 'KOR',
    'US': 'USA',
    'GB': 'GBR',
    'FR': 'FRA',
    'DE': 'DEU',
    'IT': 'ITA',
    'ES': 'ESP',
    'CN': 'CHN',
    'SG': 'SGP',
    'MY': 'MYS',
    'TH': 'THA',
    'ID': 'IDN',
    'PH': 'PHL',
    'RU': 'RUS',
    'CA': 'CAN',
    'NZ': 'NZL',
    'IN': 'IND',
    'HK': 'HKG',
    'TW': 'TWN',
    'MO': 'MAC',
    'BR': 'BRA',
    'MX': 'MEX',
    'ZA': 'ZAF',
}

# Default values for Vietnamese guests
DEFAULT_VN_GUEST = {
    'loai_giay_to': '1 - Thẻ CCCD',
    'noi_cu_tru': '2 - Tạm trú',
    'tinh_thanh': '101 - TP. Hà Nội',
    'phuong_xa': '101900167 - Phường Cầu Giấy',
    'dia_chi_chi_tiet': 'Số 5 Duy Tân',
    'ly_do_cu_tru': '1 - Du lịch'
}

# Initialize session state for database connection
if 'db_connected' not in st.session_state:
    st.session_state.db_connected = False
if 'db' not in st.session_state:
    st.session_state.db = None
if 'db_guests' not in st.session_state:
    st.session_state.db_guests = pd.DataFrame()
if 'db_stats' not in st.session_state:
    st.session_state.db_stats = {}
# Initialize session state for guests and export
if 'extracted_guests' not in st.session_state:
    st.session_state.extracted_guests = []
if 'export_guests' not in st.session_state:
    st.session_state.export_guests = []
if 'export_foreign' not in st.session_state:
    st.session_state.export_foreign = []
if 'export_vn' not in st.session_state:
    st.session_state.export_vn = []
if 'switch_to_export' not in st.session_state:
    st.session_state.switch_to_export = False

def display_pdf_preview(pdf_bytes, height=400):
    """Display PDF preview"""
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="{height}" style="border: none;"></iframe>',
        unsafe_allow_html=True
    )

def get_country_name(code_3letter):
    """Get full country name from 3-letter code"""
    country_names = {
        'VNM': 'Viet Nam',
        'AUS': 'Australia',
        'JPN': 'Japan',
        'KOR': 'Korea',
        'USA': 'United States',
        'GBR': 'United Kingdom',
        'FRA': 'France',
        'DEU': 'Germany',
        'ITA': 'Italy',
        'ESP': 'Spain',
        'CHN': 'China',
        'SGP': 'Singapore',
        'MYS': 'Malaysia',
        'THA': 'Thailand',
        'IDN': 'Indonesia',
        'PHL': 'Philippines',
        'RUS': 'Russia',
        'CAN': 'Canada',
        'NZL': 'New Zealand',
        'IND': 'India',
        'TWN': 'Taiwan',
        'BRA': 'Brazil',
        'MEX': 'Mexico',
        'ZAF': 'South Africa'
    }
    return country_names.get(code_3letter, code_3letter)

def connect_to_database():
    """Connect to Google Sheets and load data"""
    try:
        with st.spinner("🔗 Connecting to Google Sheets..."):
            from gsheets_manager import GuestDatabase
            db = GuestDatabase()
            
            if db.conn:
                # Try to get data
                df = db.get_all_guests()
                stats = db.get_statistics()
                
                # Set session state
                st.session_state.db = db
                st.session_state.db_guests = df
                st.session_state.db_stats = stats
                st.session_state.db_connected = True
                
                st.success(f"✅ Connected to Google Sheets! Loaded {stats['total']} guests.")
                return True
            else:
                st.error("❌ Failed to connect to Google Sheets. Please check your configuration.")
                st.session_state.db_connected = False
                return False
    except Exception as e:
        st.error(f"❌ Connection error: {e}")
        st.session_state.db_connected = False
        return False

def disconnect_database():
    """Disconnect from Google Sheets"""
    st.session_state.db = None
    st.session_state.db_guests = pd.DataFrame()
    st.session_state.db_stats = {}
    st.session_state.db_connected = False
    st.success("🔌 Disconnected from Google Sheets")

def display_database_status():
    """Display database connection status in sidebar"""
    with st.sidebar:
        st.markdown("---")
        st.markdown("### 📊 Google Sheets Database")
        
        # Check current status
        is_connected = st.session_state.get('db_connected', False)
        
        # Toggle for enabling/disabling database
        enable_db = st.checkbox(
            "🔗 Enable Google Sheet Data",
            value=is_connected,
            help="Connect to Google Sheets to store and retrieve guest data"
        )
        
        # Handle connection/disconnection
        if enable_db and not is_connected:
            # User wants to connect
            with st.spinner("Connecting..."):
                success = connect_to_database()
                if success:
                    st.rerun()
        elif not enable_db and is_connected:
            # User wants to disconnect
            disconnect_database()
            st.rerun()
        
        # Show status if connected
        if st.session_state.get('db_connected', False):
            stats = st.session_state.get('db_stats', {})
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Guests", stats.get('total', 0))
            with col2:
                st.metric("Active", stats.get('active', 0))
            
            st.caption(f"🔄 Last updated: {datetime.now().strftime('%H:%M:%S')}")
            
            if st.button("🔄 Refresh Data", use_container_width=True):
                connect_to_database()
                st.rerun()
        else:
            st.caption("💡 Toggle above to connect to Google Sheets")

def compare_with_database(guests):
    """Compare extracted guests with database and show results"""
    if not st.session_state.db_connected:
        st.warning("⚠️ Please enable Google Sheets connection first.")
        return
    
    db = st.session_state.db
    
    with st.spinner("Comparing with database..."):
        new_guests, existing_guests = db.compare_with_extracted(guests)
    
    # Show results - FULL WIDTH (no columns)
    st.markdown("### 📊 Comparison Results")
    
    # Use metrics in a single row with full width
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📄 Total Extracted", len(guests))
    with col2:
        st.metric("✅ Already in Database", len(existing_guests))
    with col3:
        st.metric("🆕 New Guests", len(new_guests))
    
    # Show new guests in full width
    if new_guests:
        st.success(f"🆕 Found {len(new_guests)} new guests not in database")
        
        # Show new guests with full width
        new_df = pd.DataFrame(new_guests)
        st.dataframe(new_df[['room', 'name', 'nationality', 'passport', 'arrival_date', 'departure_date']], 
                     use_container_width=True)
        
        # Buttons for adding and exporting
        col_btn1, col_btn2, col_btn3 = st.columns(3)
        with col_btn1:
            if st.button(f"📥 Add {len(new_guests)} New Guests to Database", use_container_width=True):
                save_to_database(new_guests)
                st.success(f"✅ Added {len(new_guests)} guests to database!")
               
        
        with col_btn2:
            # Separate new guests by type for export
            new_foreign = [g for g in new_guests if g.get('document_type') == 'PAS' or g.get('passport')]
            new_vn = [g for g in new_guests if g.get('document_type') == 'IDC' or g.get('id_card')]
            
            if st.button(f"📤 Export {len(new_guests)} New Guests", use_container_width=True):
                # Store in session state for export tab
                st.session_state.export_guests = new_guests
                st.session_state.export_foreign = new_foreign
                st.session_state.export_vn = new_vn
                st.session_state.switch_to_export = True
                # NO st.rerun() - just show a message
                st.success(f"✅ {len(new_guests)} guests ready for export! Click on the '📥 Export' tab above.")
        
        with col_btn3:
            if st.button("📤 Go to Export Tab", use_container_width=True):
                # Store guests for export
                st.session_state.export_guests = new_guests
                st.session_state.export_foreign = [g for g in new_guests if g.get('document_type') == 'PAS' or g.get('passport')]
                st.session_state.export_vn = [g for g in new_guests if g.get('document_type') == 'IDC' or g.get('id_card')]
                st.session_state.switch_to_export = True
                # NO st.rerun() - just show a message
                st.success("✅ Guests ready for export! Click on the '📥 Export' tab above.")
    else:
        st.info("✅ All guests are already in the database!")
    
    # Show existing guests in full width
    if existing_guests:
        with st.expander(f"📋 {len(existing_guests)} Guests Already in Database"):
            existing_df = pd.DataFrame(existing_guests)
            st.dataframe(existing_df[['room', 'name', 'nationality', 'passport', 'arrival_date', 'departure_date']], 
                         use_container_width=True)

def test_gsheets_connection():
    """Test Google Sheets connection and display diagnostic info"""
    st.subheader("🔧 Google Sheets Connection Test")
    
    # Check if secrets exist
    st.markdown("### 📋 Configuration Check")
    
    try:
        # Check if secrets file exists
        import os
        secrets_path = ".streamlit/secrets.toml"
        if os.path.exists(secrets_path):
            st.success("✅ secrets.toml file found")
        else:
            st.error("❌ secrets.toml file not found at .streamlit/secrets.toml")
    except Exception as e:
        st.error(f"❌ Error checking secrets: {e}")
    
    # Try to connect
    st.markdown("### 🔗 Connection Test")
    
    try:
        from gsheets_manager import GuestDatabase
        import pandas as pd
        
        with st.spinner("Attempting to connect..."):
            db = GuestDatabase()
            
            if db.conn:
                st.success("✅ Successfully connected to Google Sheets!")
                
                # Try to read data
                try:
                    df = db.get_all_guests()
                    st.success(f"✅ Successfully read data! Found {len(df)} rows")
                    
                    # Show data preview
                    st.markdown("### 📊 Data Preview (First 5 rows)")
                    if not df.empty:
                        st.dataframe(df.head(5), use_container_width=True)
                        
                        # Show column info
                        st.markdown("### 📋 Column Info")
                        col_info = pd.DataFrame({
                            'Column': df.columns,
                            'Type': df.dtypes.astype(str),
                            'Non-Null': df.count().values,
                            'Null %': (df.isnull().sum() / len(df) * 100).round(2).values
                        })
                        st.dataframe(col_info, use_container_width=True)
                    else:
                        st.info("📭 The spreadsheet is empty (no data)")
                        
                        # Test writing
                        st.markdown("### ✍️ Write Test")
                        if st.button("Write Test Row"):
                            test_data = {
                                'guest_id': 'TEST001',
                                'name': 'Test Guest',
                                'room': '9999',
                                'arrival_date': '01/01/2024',
                                'departure_date': '02/01/2024',
                                'nationality': 'VN',
                                'document_type': 'IDC',
                                'doc_number': '123456789',
                                'is_active': 'True',
                                'check_in_timestamp': '2024-01-01 10:00:00',
                                'check_out_timestamp': '',
                                'gender': 'M',
                                'passport': '',
                                'id_card': '123456789',
                                'dob': '01/01/1990',
                                'noi_cu_tru': '2 - Tạm trú',
                                'tinh_thanh': '101 - TP. Hà Nội',
                                'phuong_xa': '101900167 - Phường Cầu Giấy',
                                'dia_chi_chi_tiet': 'Số 5 Duy Tân',
                                'ly_do_cu_tru': '1 - Du lịch'
                            }
                            
                            try:
                                # Create a new df with the test data
                                test_df = pd.DataFrame([test_data])
                                
                                # Try to append to existing sheet
                                if not df.empty:
                                    combined = pd.concat([df, test_df], ignore_index=True)
                                    db.conn.write(worksheet=db.worksheet_name, data=combined)
                                    st.success("✅ Test row written successfully!")
                                    
                                    # Read back to verify
                                    verify_df = db.get_all_guests()
                                    st.info(f"📊 Sheet now has {len(verify_df)} rows")
                                    st.dataframe(verify_df.tail(3), use_container_width=True)
                                    
                                    # Clean up - remove test row
                                    if st.button("🗑️ Remove Test Row"):
                                        clean_df = verify_df[verify_df['guest_id'] != 'TEST001']
                                        db.conn.write(worksheet=db.worksheet_name, data=clean_df)
                                        st.success("✅ Test row removed!")
                                        st.rerun()
                                else:
                                    # Sheet is empty, just write test data
                                    db.conn.write(worksheet=db.worksheet_name, data=test_df)
                                    st.success("✅ Test row written to empty sheet!")
                                    
                            except Exception as e:
                                st.error(f"❌ Write test failed: {e}")
                except Exception as e:
                    st.error(f"❌ Failed to read data: {e}")
            else:
                st.error("❌ Failed to connect - db.conn is None")
                st.info("💡 Check your secrets.toml configuration")
                
                # Show what's in secrets (safely)
                st.markdown("### 🔍 Secrets Status")
                try:
                    from streamlit import secrets
                    st.write("Secret keys present:", list(secrets.get('connections', {}).get('gsheets', {}).keys()))
                except:
                    st.warning("Could not read secrets")
                    
    except ImportError as e:
        st.error(f"❌ Import error: {e}")
        st.info("Make sure you have installed: pip install st-gsheets-connection")
    except Exception as e:
        st.error(f"❌ Unexpected error: {e}")
        import traceback
        st.code(traceback.format_exc())

def extract_guests_from_police_report(pdf_bytes, debug=False):
    """
    Extract guest data from police report PDF - supports both Passport and IDC
    """
    if debug:
        st.markdown("### 🔍 Debug Log")
        st.caption("Showing extraction process line by line")
    
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        full_text = ""
        for page in pdf.pages:
            extracted = page.extract_text()
            if extracted:
                full_text += extracted + "\n"
    
    if debug:
        with st.expander("📄 Raw PDF Text", expanded=False):
            st.code(full_text[:3000] + ("\n... (truncated)" if len(full_text) > 3000 else ""), language="text")
    
    lines = full_text.split('\n')
    guests = []
    
    if debug:
        st.markdown("---")
        st.markdown("**Line-by-line scan:**")
        debug_lines = []
    
    i = 0
    guest_counter = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if debug:
            debug_lines.append(f"Line {i}: '{line}'")
        
        # Look for room number pattern (3-4 digits at start of line)
        room_match = re.match(r'^(\d{3,4})\s+', line)
        if room_match:
            room_num = room_match.group(1).zfill(4)
            
            if debug:
                debug_lines.append(f"  ✅ Found room: {room_num}")
            
            # Get the rest of the line after room number
            rest_of_line = line[len(room_match.group(0)):].strip()
            
            if debug:
                debug_lines.append(f"  Rest of line: '{rest_of_line}'")
            
            # Parse the rest of the line
            parts = rest_of_line.split()
            
            if debug:
                debug_lines.append(f"  Parts: {parts}")
            
            # Find date indices
            date_indices = []
            for idx, part in enumerate(parts):
                if re.match(r'\d{2}/\d{2}/\d{2}', part):
                    date_indices.append(idx)
            
            if debug:
                debug_lines.append(f"  Date indices: {date_indices}")
            
            if len(date_indices) >= 2:
                # Name is everything before the first date
                name_parts = parts[:date_indices[0]]
                guest_name = ' '.join(name_parts) if name_parts else ""
                
                # Arrival date
                arrival_date = parts[date_indices[0]] if len(date_indices) > 0 else None
                
                # Departure date
                departure_date = parts[date_indices[1]] if len(date_indices) > 1 else None
                
                # After the second date, look for country and DOB
                remaining = parts[date_indices[1] + 1:]
                
                if debug:
                    debug_lines.append(f"  Name (raw): '{guest_name}'")
                    debug_lines.append(f"  Arrival: {arrival_date}, Departure: {departure_date}")
                    debug_lines.append(f"  Remaining after dates: {remaining}")
                
                # Country and DOB extraction
                nationality = None
                dob = None
                
                # Look for 2-letter country code first
                for j, part in enumerate(remaining):
                    if re.match(r'^[A-Z]{2}$', part) and part in COUNTRY_CODE_MAP:
                        nationality = part
                        if j + 1 < len(remaining):
                            dob_candidate = remaining[j + 1]
                            if re.match(r'\d{2}/\d{2}/\d{2}', dob_candidate):
                                dob = dob_candidate
                        break
                    elif re.match(r'\d{2}/\d{2}/\d{2}', part) and not dob:
                        dob = part
                
                if not nationality and remaining and re.match(r'\d{2}/\d{2}/\d{2}', remaining[0]):
                    dob = remaining[0]
                
                if debug:
                    debug_lines.append(f"  Nationality: {nationality}")
                    debug_lines.append(f"  DOB found: {dob}")
            
            else:
                if debug:
                    debug_lines.append(f"  ❌ Not enough dates found (need at least 2)")
                i += 1
                continue
            
            # ===== CLEAN NAME - Remove ALL commas and extra spaces =====
            guest_name = guest_name.strip()
            # Remove ALL commas from name (e.g., "Nguyen,Trang" -> "Nguyen Trang")
            guest_name = guest_name.replace(',', ' ')
            # Remove any trailing country codes
            name_parts_clean = guest_name.split()
            if name_parts_clean and len(name_parts_clean) > 1:
                # Check if last part is a 2-letter country code
                if re.match(r'^[A-Z]{2}$', name_parts_clean[-1]) and name_parts_clean[-1] in COUNTRY_CODE_MAP:
                    guest_name = ' '.join(name_parts_clean[:-1])
            # Clean up extra spaces
            guest_name = re.sub(r'\s+', ' ', guest_name).strip()
            
            if debug:
                debug_lines.append(f"  Cleaned name: '{guest_name}'")
            
            # Initialize document fields
            passport = None
            id_card_number = None
            document_type = None  # 'PAS' or 'IDC'
            gender = None
            
            # Check next 5 lines for document info
            if debug:
                debug_lines.append(f"  Looking ahead 5 lines for document info:")
            
            for offset in range(1, 6):
                if i + offset < len(lines):
                    next_line = lines[i + offset].strip()
                    
                    if debug:
                        debug_lines.append(f"    Line {i+offset}: '{next_line}'")
                    
                    # Check for IDC (Vietnamese Identity Card)
                    idc_match = re.search(r'\bIDC\s+(\d{9,12})', next_line, re.IGNORECASE)
                    if idc_match:
                        id_card_number = idc_match.group(1)
                        document_type = 'IDC'
                        if debug:
                            debug_lines.append(f"    ✅ Found IDC number: {id_card_number}")
                    else:
                        # Alternative: Check if the line contains "IDC" 
                        idc_parts = next_line.split()
                        for idx, part in enumerate(idc_parts):
                            if part.upper() == 'IDC' and idx + 1 < len(idc_parts):
                                potential_id = idc_parts[idx + 1]
                                if re.match(r'^\d{9,12}$', potential_id):
                                    id_card_number = potential_id
                                    document_type = 'IDC'
                                    if debug:
                                        debug_lines.append(f"    ✅ Found IDC number (alternative): {id_card_number}")
                                    break
                    
                    # Check for PAS (Passport) - only for foreigners
                    if not document_type or document_type != 'IDC':
                        if 'PAS' in next_line:
                            passport_match = re.search(r'PAS\s*([A-Z0-9]{6,10})', next_line, re.IGNORECASE)
                            if passport_match:
                                passport = passport_match.group(1)
                                document_type = 'PAS'
                                if debug:
                                    debug_lines.append(f"    ✅ Found passport: {passport}")
                            else:
                                pas_match = re.search(r'PAS\s+([A-Z0-9]+)', next_line, re.IGNORECASE)
                                if pas_match:
                                    passport = pas_match.group(1)
                                    document_type = 'PAS'
                                    if debug:
                                        debug_lines.append(f"    ✅ Found passport (implicit): {passport}")
                    
                    # Look for gender
                    countries_pattern = '|'.join([
                        'Australia', 'Vietnam', 'Japan', 'Korea', 'USA', 'UK', 'France', 
                        'Germany', 'Italy', 'Spain', 'China', 'Singapore', 'Malaysia', 
                        'Thailand', 'Indonesia', 'Philippines', 'Russia', 'Canada', 
                        'New Zealand', 'India', 'Taiwan', 'Myanmar', 'South Africa',
                        'Brazil', 'Mexico', 'Egypt', 'Israel', 'Saudi Arabia', 'UAE'
                    ])
                    gender_match = re.search(rf'\b([MF])\s+(?:{countries_pattern})', next_line, re.IGNORECASE)
                    if gender_match:
                        gender = gender_match.group(1)
                        if debug:
                            debug_lines.append(f"    ✅ Found gender with country: {gender}")
                    else:
                        gender_single = re.match(r'^\s*([MF])\s*$', next_line)
                        if gender_single:
                            gender = gender_single.group(1)
                            if debug:
                                debug_lines.append(f"    ✅ Found gender (single): {gender}")
                        else:
                            gender_any = re.search(r'\b([MF])\s+\w+', next_line)
                            if gender_any:
                                gender = gender_any.group(1)
                                if debug:
                                    debug_lines.append(f"    ✅ Found gender (with text): {gender}")
                    
                    # If we found both document and gender, stop looking
                    if (document_type and (passport or id_card_number)) and gender:
                        break
            
            if not document_type and debug:
                debug_lines.append(f"  ❌ No document type found (IDC or PAS)")
            if not passport and not id_card_number and debug:
                debug_lines.append(f"  ❌ No document number found")
            if not gender and debug:
                debug_lines.append(f"  ❌ No gender found in next 5 lines")
            
            # Fix DOB year format
            if dob:
                if len(dob.split('/')[-1]) == 2:
                    parts = dob.split('/')
                    year = int(parts[2])
                    if year < 30:
                        parts[2] = f"20{year:02d}"
                    else:
                        parts[2] = f"19{year:02d}"
                    dob = '/'.join(parts)
                    if debug:
                        debug_lines.append(f"  Fixed DOB year: {dob}")
            
            # Only add if we have a valid name
            if guest_name and len(guest_name) > 1:
                # Determine document number for display
                doc_number = id_card_number if document_type == 'IDC' else passport
                
                guest_entry = {
                    'room': room_num,
                    'name': guest_name,
                    'arrival_date': arrival_date,
                    'departure_date': departure_date,
                    'nationality': nationality,
                    'passport': passport,
                    'id_card': id_card_number,
                    'document_type': document_type or 'Unknown',
                    'doc_number': doc_number,  # Unified field
                    'dob': dob,
                    'gender': gender or 'Unknown',
                    # Excel export fields (only used for IDC guests)
                    'loai_giay_to': DEFAULT_VN_GUEST['loai_giay_to'] if document_type == 'IDC' else '4 - Hộ chiếu',
                    'noi_cu_tru': DEFAULT_VN_GUEST['noi_cu_tru'],
                    'tinh_thanh': DEFAULT_VN_GUEST['tinh_thanh'],
                    'phuong_xa': DEFAULT_VN_GUEST['phuong_xa'],
                    'dia_chi_chi_tiet': DEFAULT_VN_GUEST['dia_chi_chi_tiet'],
                    'ly_do_cu_tru': DEFAULT_VN_GUEST['ly_do_cu_tru']
                }
                guests.append(guest_entry)
                guest_counter += 1
                if debug:
                    doc_info = f"IDC: {id_card_number}" if document_type == 'IDC' else f"PAS: {passport}" if passport else "No document"
                    debug_lines.append(f"  ✅ Added guest #{guest_counter}: {guest_name} (Room {room_num})")
                    debug_lines.append(f"     Document: {doc_info}")
                    debug_lines.append(f"     Data: {guest_entry}")
            else:
                if debug:
                    debug_lines.append(f"  ❌ Skipped - name too short: '{guest_name}'")
            
            if debug:
                debug_lines.append("  ---")
        
        i += 1
    
    # Show debug lines
    if debug:
        with st.expander("📋 Full Debug Log", expanded=True):
            st.code("\n".join(debug_lines), language="text")
        
        # Summary statistics
        st.markdown("### 📊 Extraction Summary")
        col_d1, col_d2, col_d3, col_d4, col_d5 = st.columns(5)
        with col_d1:
            st.metric("Total Guests Found", len(guests))
        with col_d2:
            found_passport = sum(1 for g in guests if g.get('passport'))
            st.metric("Has Passport", found_passport)
        with col_d3:
            found_idc = sum(1 for g in guests if g.get('id_card'))
            st.metric("Has ID Card", found_idc)
        with col_d4:
            found_gender = sum(1 for g in guests if g.get('gender') != 'Unknown')
            st.metric("Has Gender", found_gender)
        with col_d5:
            found_dob = sum(1 for g in guests if g.get('dob'))
            st.metric("Has DOB", found_dob)
    
    # Deduplicate by room + name
    seen = set()
    unique_guests = []
    for guest in guests:
        key = f"{guest['room']}_{guest['name']}"
        if key not in seen:
            seen.add(key)
            unique_guests.append(guest)
    
    if debug and len(guests) != len(unique_guests):
        st.warning(f"⚠️ Removed {len(guests) - len(unique_guests)} duplicate(s)")
    
    return unique_guests

def format_date_for_xml(date_str):
    """Convert date to dd/mm/yyyy format"""
    if not date_str:
        return None
    
    formats = ['%d/%m/%y', '%d/%m/%Y', '%d-%m-%y', '%d-%m-%Y']
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime('%d/%m/%Y')
        except:
            continue
    
    return date_str

def generate_tam_tru_xml(guests, hotel_name="", hotel_address=""):
    """Generate KHAI_BAO_TAM_TRU XML for foreign guests"""
    root = ET.Element("KHAI_BAO_TAM_TRU")
    
    # Add hotel info
    if hotel_name:
        hotel_elem = ET.SubElement(root, "THONG_TIN_KHACH_SAN")
        hotel_elem.text = hotel_name
    
    # Filter to only foreign guests (PAS holders)
    foreign_guests = [g for g in guests if g.get('document_type') == 'PAS' or g.get('passport')]
    
    # Add guest entries
    for i, guest in enumerate(foreign_guests, 1):
        guest_elem = ET.SubElement(root, "THONG_TIN_KHACH")
        
        # Map nationality to 3-letter code
        nationality_code = guest.get('nationality', '')
        if nationality_code in COUNTRY_CODE_MAP:
            nationality_code = COUNTRY_CODE_MAP[nationality_code]
        
        fields = [
            ('so_thu_tu', str(i)),
            ('ho_ten', guest.get('name', '')),
            ('ngay_sinh', format_date_for_xml(guest.get('dob'))),
            ('ngay_sinh_dung_den', 'D'),
            ('gioi_tinh', guest.get('gender', 'Unknown')),
            ('ma_quoc_tich', nationality_code),
            ('so_ho_chieu', guest.get('passport', '')),
            ('so_phong', guest.get('room', '')),
            ('ngay_den', format_date_for_xml(guest.get('arrival_date'))),
            ('ngay_di_du_kien', format_date_for_xml(guest.get('departure_date'))),
            ('ngay_tra_phong', format_date_for_xml(guest.get('departure_date'))),
        ]
        
        for tag, value in fields:
            if value:
                elem = ET.SubElement(guest_elem, tag)
                elem.text = value
    
    xml_str = ET.tostring(root, encoding='unicode')
    dom = minidom.parseString(xml_str)
    return dom.toprettyxml(indent="  ")

def export_to_excel(guests):
    """
    Export Vietnamese guests to the required Excel format
    """
    # Filter to only Vietnamese guests (IDC holders)
    vn_guests = [g for g in guests if g.get('document_type') == 'IDC' or g.get('id_card')]
    
    if not vn_guests:
        return pd.DataFrame()
    
    excel_data = []
    for idx, guest in enumerate(vn_guests, 1):
        # Format date fields
        arrival = guest.get('arrival_date', '')
        departure = guest.get('departure_date', '')
        dob = guest.get('dob', '')
        
        # Convert dates to dd/mm/yyyy format
        for date_field, val in [('arrival', arrival), ('departure', departure), ('dob', dob)]:
            if val:
                for fmt in ['%d/%m/%y', '%d/%m/%Y']:
                    try:
                        dt = datetime.strptime(val, fmt)
                        if date_field == 'dob':
                            dob = dt.strftime('%d/%m/%Y')
                        elif date_field == 'arrival':
                            arrival = dt.strftime('%d/%m/%Y')
                        else:
                            departure = dt.strftime('%d/%m/%Y')
                        break
                    except:
                        pass
        
        # Map gender
        gender_map = {'M': 'M - Nam', 'F': 'F - Nữ'}
        gender = gender_map.get(guest.get('gender', ''), '')
        
        # Map nationality
        nationality = guest.get('nationality', '')
        if nationality in COUNTRY_CODE_MAP:
            nationality = f"{COUNTRY_CODE_MAP[nationality]} - {get_country_name(COUNTRY_CODE_MAP[nationality])}"
        else:
            nationality = f"VNM - Viet Nam"
        
        row = {
            'STT': idx,
            'HỌ TÊN (*)': guest.get('name', ''),
            'NGÀY SINH (*)': dob,
            'GIỚI TÍNH (*)': gender,
            'QUỐC TỊCH (*)': nationality,
            'LOẠI GIẤY TỜ (*)': guest.get('loai_giay_to', DEFAULT_VN_GUEST['loai_giay_to']),
            'TÊN GIẤY TỜ': '',  # Only for "Giấy Tờ Khác"
            'SỐ GIẤY TỜ (*)': guest.get('id_card', ''),
            'SỐ ĐIỆN THOẠI': '',  # Not extracted from PDF
            'NƠI CƯ TRÚ HIỆN NAY': guest.get('noi_cu_tru', DEFAULT_VN_GUEST['noi_cu_tru']),
            'TỈNH/ THÀNH PHỐ': guest.get('tinh_thanh', DEFAULT_VN_GUEST['tinh_thanh']),
            'PHƯỜNG/ XÃ/ ĐẶC KHU': guest.get('phuong_xa', DEFAULT_VN_GUEST['phuong_xa']),
            'ĐỊA CHỈ CHI TIẾT': guest.get('dia_chi_chi_tiet', DEFAULT_VN_GUEST['dia_chi_chi_tiet']),
            'NGÀY ĐẾN (*)': arrival,
            'NGÀY ĐI DỰ KIẾN (*)': departure,
            'SỐ PHÒNG/ KHOA': guest.get('room', ''),
            'LÝ DO CƯ TRÚ (*)': guest.get('ly_do_cu_tru', DEFAULT_VN_GUEST['ly_do_cu_tru']),
            'NHẬP LÝ DO': '',  # Only for "Mục đích khác"
            'GHI CHÚ': ''
        }
        excel_data.append(row)
    
    return pd.DataFrame(excel_data)

def save_to_database(guests):
    """Save extracted guests to the database"""
    if not st.session_state.db_connected:
        st.warning("⚠️ Please enable Google Sheets connection first.")
        return
    
    db = st.session_state.db
    
    # Get existing guests
    existing_df = db.get_all_guests()
    
    new_guests = []
    duplicates = []
    
    for guest in guests:
        # Check if guest already exists (by room and name)
        if not existing_df.empty:
            mask = (existing_df['room'] == guest['room']) & (existing_df['name'] == guest['name'])
            if mask.any():
                # Check if they're already active
                if existing_df[mask]['is_active'].iloc[0] == 'True':
                    duplicates.append(guest)
                    continue
        
        # Prepare guest data for database
        guest_data = {
            'room': guest.get('room', ''),
            'name': guest.get('name', ''),
            'arrival_date': guest.get('arrival_date', ''),
            'departure_date': guest.get('departure_date', ''),
            'nationality': guest.get('nationality', ''),
            'passport': guest.get('passport', ''),
            'id_card': guest.get('id_card', ''),
            'document_type': guest.get('document_type', ''),
            'doc_number': guest.get('doc_number', ''),
            'dob': guest.get('dob', ''),
            'gender': guest.get('gender', ''),
            'noi_cu_tru': guest.get('noi_cu_tru', DEFAULT_VN_GUEST['noi_cu_tru']),
            'tinh_thanh': guest.get('tinh_thanh', DEFAULT_VN_GUEST['tinh_thanh']),
            'phuong_xa': guest.get('phuong_xa', DEFAULT_VN_GUEST['phuong_xa']),
            'dia_chi_chi_tiet': guest.get('dia_chi_chi_tiet', DEFAULT_VN_GUEST['dia_chi_chi_tiet']),
            'ly_do_cu_tru': guest.get('ly_do_cu_tru', DEFAULT_VN_GUEST['ly_do_cu_tru'])
        }
        new_guests.append(guest_data)
    
    if new_guests:
        success_count, failed = db.add_multiple_guests(new_guests)
        # Refresh data
        connect_to_database()
        st.success(f"✅ Added {success_count} new guests to database")
        if duplicates:
            st.info(f"ℹ️ Skipped {len(duplicates)} duplicate guests (already active)")
        if failed:
            st.warning(f"⚠️ Failed to add {len(failed)} guests")
    else:
        st.info("ℹ️ No new guests to add")

def check_export_flag():
    """Check if there are guests waiting to be exported"""
    if st.session_state.get('switch_to_export', False):
        st.session_state.switch_to_export = False
        # Find the export tab and switch to it
        # We'll handle this in the display function
        return True
    return False

def display_police_report_converter(pdf_bytes):
    """Main function for Police Report to XML/Excel Converter"""
    st.subheader("📄 Police Report to XML/Excel Converter")
    
    # ===== DATABASE CONNECTION SECTION =====
    st.markdown("### 📊 Google Sheets Database")
    
    # Check current connection status
    is_connected = st.session_state.get('db_connected', False)
    
    col_db1, col_db2, col_db3 = st.columns([1, 2, 1])
    with col_db1:
        if not is_connected:
            if st.button("🔗 Connect to Google Sheets", type="primary", use_container_width=True):
                with st.spinner("Connecting..."):
                    success = connect_to_database()
                    if success:
                        st.rerun()
        else:
            if st.button("🔌 Disconnect", use_container_width=True):
                disconnect_database()
                st.rerun()
    
    with col_db2:
        if is_connected:
            stats = st.session_state.get('db_stats', {})
            st.success(f"✅ Connected! Loaded {stats.get('total', 0)} guests")
        else:
            st.info("💡 Click 'Connect to Google Sheets' to load guest data")
    
    with col_db3:
        if is_connected:
            if st.button("🔄 Refresh", use_container_width=True):
                connect_to_database()
                st.rerun()
    
    
    # ===== END DATABASE CONNECTION SECTION =====
    
    # Debug toggle
    debug_mode = st.checkbox("🔍 Enable Debug Mode", value=False, help="Shows detailed extraction process")
    
    # Show PDF preview
    with st.expander("📄 View Original PDF", expanded=False):
        display_pdf_preview(pdf_bytes, height=400)
    
    # Extract data - store in session state
    if 'extracted_guests' not in st.session_state or not st.session_state.extracted_guests:
        with st.spinner("Extracting guest data from PDF..."):
            guests = extract_guests_from_police_report(pdf_bytes, debug=debug_mode)
            st.session_state.extracted_guests = guests
    else:
        guests = st.session_state.extracted_guests
    
    if not guests:
        st.warning("No guest data found in the PDF. Please check the format.")
        return
    
    # ========== FIVE TABS ==========
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 Guest List", 
        "✏️ Edit Guest Data", 
        "🏨 Hotel Overview", 
        "📥 Export",
        "📊 Database"
    ])
    
    # ========== TAB 1: Guest List ==========
    with tab1:
        st.subheader("📋 All Extracted Guests")
        st.caption(f"Total: {len(guests)} guests")
        
        # Prepare data for display
        guest_data = []
        for idx, guest in enumerate(guests):
            doc_type = guest.get('document_type', '')
            doc_number = guest.get('doc_number', '') or guest.get('id_card', '') or guest.get('passport', '')
            
            guest_data.append({
                "#": idx + 1,
                "Room": guest.get('room', ''),
                "Guest Name": guest.get('name', '')[:50],
                "Arrival": guest.get('arrival_date', 'N/A'),
                "Departure": guest.get('departure_date', 'N/A'),
                "Document Type": doc_type if doc_type else 'N/A',
                "Document #": doc_number if doc_number else 'N/A',
                "DOB": guest.get('dob', 'N/A'),
                "Nationality": guest.get('nationality', 'N/A'),
                "Gender": guest.get('gender', 'N/A')
            })
        
        df_guests = pd.DataFrame(guest_data)
        st.dataframe(df_guests, use_container_width=True, height=400)
        
        # Download buttons
        col1, col2 = st.columns(2)
        with col1:
            csv_data = df_guests.to_csv(index=False)
            st.download_button(
                "📥 Download CSV",
                csv_data,
                f"guests_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "text/csv"
            )
        with col2:
            json_data = df_guests.to_json(orient='records', indent=2)
            st.download_button(
                "📥 Download JSON",
                json_data,
                f"guests_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                "application/json"
            )
        
        st.markdown("---")
        st.markdown("### 🔍 Database Comparison")
        
        if st.session_state.db_connected:
            col_comp1, col_comp2 = st.columns(2)
            with col_comp1:
                if st.button("🔍 Compare with Database", use_container_width=True):
                    compare_with_database(guests)
            with col_comp2:
                if st.button("💾 Save All to Database", use_container_width=True):
                    save_to_database(guests)
        else:
            st.info("💡 Enable Google Sheets connection to compare with database.")
    
    # ========== TAB 2: Edit Guest Data ==========
    with tab2:
        st.subheader("✏️ Edit Guest Data")
        st.caption("Make corrections to guest information below before generating XML or Excel.")
        
        edited_guests = []
        for i, guest in enumerate(guests):
            with st.expander(f"Guest #{i+1}: {guest.get('name', 'Unknown')} (Room {guest.get('room', 'N/A')})", expanded=i < 2):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    name = st.text_input(f"Full Name {i+1}", value=guest.get('name', ''))
                    room = st.text_input(f"Room {i+1}", value=guest.get('room', ''))
                    arrival = st.text_input(f"Arrival Date {i+1}", value=guest.get('arrival_date', ''))
                
                with col2:
                    departure = st.text_input(f"Departure Date {i+1}", value=guest.get('departure_date', ''))
                    
                    doc_type = guest.get('document_type', '')
                    if doc_type == 'IDC':
                        doc_label = "ID Card Number"
                        default_doc = guest.get('id_card', '')
                    else:
                        doc_label = "Passport Number"
                        default_doc = guest.get('passport', '')
                    
                    doc_number = st.text_input(f"{doc_label} {i+1}", value=default_doc)
                    dob = st.text_input(f"Date of Birth {i+1}", value=guest.get('dob', ''))
                
                with col3:
                    nationality_val = st.text_input(f"Nationality (2-letter) {i+1}", value=guest.get('nationality', ''))
                    if nationality_val:
                        nationality_val = nationality_val.upper()
                    gender = st.selectbox(
                        f"Gender {i+1}",
                        ["Unknown", "M", "F"],
                        index=0 if guest.get('gender') == 'Unknown' else (1 if guest.get('gender') == 'M' else 2)
                    )
                
                edited_guest = {
                    'room': room,
                    'name': name,
                    'arrival_date': arrival,
                    'departure_date': departure,
                    'passport': doc_number if doc_type != 'IDC' else guest.get('passport', ''),
                    'id_card': doc_number if doc_type == 'IDC' else guest.get('id_card', ''),
                    'document_type': doc_type,
                    'doc_number': doc_number,
                    'dob': dob,
                    'nationality': nationality_val,
                    'gender': gender,
                    'loai_giay_to': DEFAULT_VN_GUEST['loai_giay_to'] if doc_type == 'IDC' else '4 - Hộ chiếu',
                    'noi_cu_tru': guest.get('noi_cu_tru', DEFAULT_VN_GUEST['noi_cu_tru']),
                    'tinh_thanh': guest.get('tinh_thanh', DEFAULT_VN_GUEST['tinh_thanh']),
                    'phuong_xa': guest.get('phuong_xa', DEFAULT_VN_GUEST['phuong_xa']),
                    'dia_chi_chi_tiet': guest.get('dia_chi_chi_tiet', DEFAULT_VN_GUEST['dia_chi_chi_tiet']),
                    'ly_do_cu_tru': guest.get('ly_do_cu_tru', DEFAULT_VN_GUEST['ly_do_cu_tru'])
                }
                edited_guests.append(edited_guest)
    
    # ========== TAB 3: Hotel Overview ==========
    with tab3:
        display_hotel_overview_tab(guests)
    
    # ========== TAB 4: Export ==========
    with tab4:
        st.subheader("📥 Export Options")
        st.caption("Export data based on guest type")
        
        # Check if there are guests waiting to be exported
        export_guests = st.session_state.get('export_guests', [])
        
        if export_guests:
            st.success(f"📤 {len(export_guests)} guests ready for export from comparison!")
            # Use the stored guests
            foreign_guests = st.session_state.get('export_foreign', [])
            vn_guests = st.session_state.get('export_vn', [])
            
            # Show a button to clear the export list
            if st.button("🔄 Clear Export List & Show All Guests", use_container_width=True):
                st.session_state.export_guests = []
                st.session_state.export_foreign = []
                st.session_state.export_vn = []
                st.session_state.switch_to_export = False
                st.rerun()
        else:
            # Use the regular guests
            export_guests = guests
            foreign_guests = [g for g in guests if g.get('document_type') == 'PAS' or g.get('passport')]
            vn_guests = [g for g in guests if g.get('document_type') == 'IDC' or g.get('id_card')]
            
            # Check if switch_to_export flag is set but no export_guests (fallback)
            if st.session_state.get('switch_to_export', False):
                st.session_state.switch_to_export = False
                st.info("💡 Click 'Compare with Database' first, then use the 'Go to Export Tab' button.")
        
        # Clear the flag if it was set
        if st.session_state.get('switch_to_export', False):
            st.session_state.switch_to_export = False
        
        col_exp1, col_exp2 = st.columns(2)
        
        with col_exp1:
            st.markdown("### 🌍 Foreign Guests")
            st.metric("Count", len(foreign_guests))
            
            if foreign_guests:
                st.markdown("#### XML Preview")
                preview_xml = generate_tam_tru_xml(foreign_guests[:3], "Novotel Suites Hanoi", "5 Duy Tan, Cau Giay District, Hanoi, Vietnam")
                st.code(preview_xml, language="xml")
                
                if st.button("📥 Download XML for Foreign Guests", use_container_width=True):
                    full_xml = generate_tam_tru_xml(foreign_guests, "Novotel Suites Hanoi", "5 Duy Tan, Cau Giay District, Hanoi, Vietnam")
                    st.download_button(
                        label="📥 Download XML",
                        data=full_xml,
                        file_name=f"KHAI_BAO_TAM_TRU_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml",
                        mime="application/xml",
                        use_container_width=True
                    )
            else:
                st.info("No foreign guests found")
        
        with col_exp2:
            st.markdown("### 🇻🇳 Vietnamese Guests")
            st.metric("Count", len(vn_guests))
            
            if vn_guests:
                st.markdown("#### Default Values")
                default_noi_cu_tru = st.selectbox(
                    "Nơi cư trú hiện nay",
                    ["1 - Thường trú", "2 - Tạm trú", "3 - Khác"],
                    index=1,
                    key="noi_cu_tru_export"
                )
                default_tinh_thanh = st.selectbox(
                    "Tỉnh/Thành phố",
                    ["101 - TP. Hà Nội", "501 - TP. Đà Nẵng", "701 - TP. Hồ Chí Minh"],
                    index=0,
                    key="tinh_thanh_export"
                )
                default_phuong_xa = st.selectbox(
                    "Phường/Xã",
                    ["101900167 - Phường Cầu Giấy", "101900070 - Phường Hoàn Kiếm", "101900160 - Phường Nghĩa Đô"],
                    index=0,
                    key="phuong_xa_export"
                )
                default_dia_chi = st.text_input("Địa chỉ chi tiết", value="Số 5 Duy Tân", key="dia_chi_export")
                default_ly_do = st.selectbox(
                    "Lý do cư trú",
                    ["1 - Du lịch", "2 - Công tác", "3 - Học tập", "4 - Thăm viếng", "20 - Mục đích khác"],
                    index=0,
                    key="ly_do_export"
                )
                
                export_guests_vn = []
                for guest in vn_guests:
                    guest_copy = guest.copy()
                    guest_copy['noi_cu_tru'] = default_noi_cu_tru
                    guest_copy['tinh_thanh'] = default_tinh_thanh
                    guest_copy['phuong_xa'] = default_phuong_xa
                    guest_copy['dia_chi_chi_tiet'] = default_dia_chi
                    guest_copy['ly_do_cu_tru'] = default_ly_do
                    export_guests_vn.append(guest_copy)
                
                st.markdown("#### Excel Preview")
                df_excel = export_to_excel(export_guests_vn)
                if not df_excel.empty:
                    st.dataframe(df_excel, use_container_width=True, height=300)
                
                if st.button("📥 Download Excel for Vietnamese Guests", type="primary", use_container_width=True):
                    with st.spinner("Generating Excel file..."):
                        output = BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            df_excel.to_excel(writer, sheet_name='DS_KHACH_VIET_NAM_LUU_TRU', index=False)
                            
                            workbook = writer.book
                            worksheet = writer.sheets['DS_KHACH_VIET_NAM_LUU_TRU']
                            
                            for cell in worksheet[1]:
                                cell.font = Font(bold=True)
                                cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
                            
                            for column in worksheet.columns:
                                max_length = 0
                                column_letter = column[0].column_letter
                                for cell in column:
                                    try:
                                        if len(str(cell.value)) > max_length:
                                            max_length = len(str(cell.value))
                                    except:
                                        pass
                                adjusted_width = min(max_length + 2, 30)
                                worksheet.column_dimensions[column_letter].width = adjusted_width
                        
                        st.download_button(
                            label="📥 Download Excel File",
                            data=output.getvalue(),
                            file_name=f"DS_KHACH_LUU_TRU_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )
            else:
                st.info("No Vietnamese guests found")
        
        st.markdown("---")
        st.markdown("### 📊 Summary")
        col_sum1, col_sum2, col_sum3 = st.columns(3)
        with col_sum1:
            st.metric("Total Guests", len(export_guests))
        with col_sum2:
            st.metric("Foreign (XML)", len(foreign_guests))
        with col_sum3:
            st.metric("Vietnamese (Excel)", len(vn_guests))
    
    # ========== TAB 5: Database ==========
    with tab5:
        if st.session_state.db_connected:
            st.subheader("📊 Google Sheets Database")
            
            # Show database stats
            stats = st.session_state.db_stats
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Guests", stats.get('total', 0))
            with col2:
                st.metric("Active Guests", stats.get('active', 0))
            with col3:
                st.metric("Rooms Occupied", stats.get('rooms_occupied', 0))
            with col4:
                st.metric("Last Updated", datetime.now().strftime('%H:%M'))
            
            st.markdown("---")
            
            # Show all guests from database
            st.subheader("📋 Database Guests")
            df = st.session_state.db_guests
            if not df.empty:
                # Select columns to display
                display_cols = ['guest_id', 'name', 'room', 'arrival_date', 'departure_date', 
                               'document_type', 'doc_number', 'is_active']
                available_cols = [col for col in display_cols if col in df.columns]
                st.dataframe(df[available_cols], use_container_width=True, height=400)
                
                # Export database
                st.markdown("---")
                col_exp_db1, col_exp_db2 = st.columns(2)
                with col_exp_db1:
                    csv_data = df.to_csv(index=False)
                    st.download_button(
                        "📥 Download Database CSV",
                        csv_data,
                        f"database_guests_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        "text/csv"
                    )
                with col_exp_db2:
                    if st.button("🔄 Refresh Database", use_container_width=True):
                        connect_to_database()
                        st.rerun()
            else:
                st.info("No data in database")
        else:
            st.info("💡 Enable Google Sheets connection in the sidebar to view database")


def create_floor_map(guests, selected_floor=None):
    """
    Create an interactive floor map showing occupied rooms
    Floors 4-16, Rooms 01-12
    """
    # Create a set of occupied rooms from guests
    occupied_rooms = set()
    for guest in guests:
        room = guest.get('room', '')
        if room and len(room) == 4:
            occupied_rooms.add(room)
    
    # Define all possible rooms
    all_rooms = []
    for floor in range(4, 17):  # 4 to 16
        for room_num in range(1, 13):  # 01 to 12
            room_str = f"{floor:02d}{room_num:02d}"
            all_rooms.append({
                'room': room_str,
                'floor': floor,
                'number': room_num,
                'occupied': room_str in occupied_rooms
            })
    
    # Group by floor
    floors = {}
    for room in all_rooms:
        floor = room['floor']
        if floor not in floors:
            floors[floor] = []
        floors[floor].append(room)
    
    return floors, occupied_rooms

def display_floor_map(floors, occupied_rooms, selected_floor=None):
    """
    Display the floor map with color coding
    """
    # Floor selection buttons
    st.markdown("### 🏢 Select Floor")
    
    # Create floor buttons
    floor_cols = st.columns(8)
    for idx, floor in enumerate(sorted(floors.keys())):
        col_idx = idx % 8
        with floor_cols[col_idx]:
            # Count occupied rooms on this floor
            floor_rooms = floors[floor]
            occupied_count = sum(1 for r in floor_rooms if r['occupied'])
            total_count = len(floor_rooms)
            
            # Determine color based on occupancy
            if occupied_count == total_count:
                color = "🟢"
            elif occupied_count > 0:
                color = "🟡"
            else:
                color = "🔴"
            
            button_label = f"{color} Floor {floor}"
            if st.button(button_label, key=f"floor_{floor}", use_container_width=True):
                st.session_state.selected_floor = floor
                st.rerun()
    
    st.markdown("---")
    
    # Show selected floor details
    if selected_floor and selected_floor in floors:
        st.markdown(f"### 📍 Floor {selected_floor} - Room Layout")
        
        # Show room grid (3 columns x 4 rows for 12 rooms)
        floor_rooms = sorted(floors[selected_floor], key=lambda x: x['number'])
        
        # Create a grid layout
        cols = st.columns(4)  # 4 columns for room numbers 01-12
        
        for idx, room in enumerate(floor_rooms):
            col_idx = idx % 4
            with cols[col_idx]:
                room_num = f"{room['room']}"
                if room['occupied']:
                    st.markdown(f"""
                    <div style="
                        background: #4CAF50; 
                        color: white; 
                        padding: 8px; 
                        margin: 4px; 
                        border-radius: 4px; 
                        text-align: center;
                        font-weight: bold;
                        border: 2px solid #388E3C;
                        font-size: 14px;
                    ">
                        {room_num}
                        <br>
                        <span style="font-size: 10px; font-weight: normal;">🟢 Occupied</span>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div style="
                        background: #f44336; 
                        color: white; 
                        padding: 8px; 
                        margin: 4px; 
                        border-radius: 4px; 
                        text-align: center;
                        font-weight: bold;
                        border: 2px solid #d32f2f;
                        font-size: 14px;
                    ">
                        {room_num}
                        <br>
                        <span style="font-size: 10px; font-weight: normal;">🔴 Available</span>
                    </div>
                    """, unsafe_allow_html=True)
        
        # Show guests on this floor
        st.markdown("---")
        st.markdown(f"**👤 Guests on Floor {selected_floor}:**")
        
        floor_guests = [g for g in st.session_state.guests if g.get('room', '').startswith(f"{selected_floor:02d}")]
        if floor_guests:
            guest_data = []
            for guest in floor_guests:
                guest_data.append({
                    "Room": guest.get('room', ''),
                    "Guest Name": guest.get('name', '')[:30],
                    "Arrival": guest.get('arrival_date', 'N/A'),
                    "Departure": guest.get('departure_date', 'N/A')
                })
            st.dataframe(pd.DataFrame(guest_data), use_container_width=True)
        else:
            st.caption("No guests on this floor")
    
    else:
        st.info("👆 Click a floor above to view room details")

def display_hotel_overview_tab(guests):
    """
    Hotel Overview Tab with Interactive Floor Map
    """
    st.subheader("🏨 Hotel Overview")
    
    # Store guests in session state for floor map
    st.session_state.guests = guests
    
    # Summary statistics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Guests", len(guests))
    with col2:
        total_rooms = len(set(g.get('room') for g in guests))
        st.metric("Total Rooms", total_rooms)
    with col3:
        unique_names = len(set(g.get('name') for g in guests))
        st.metric("Unique Guests", unique_names)
    with col4:
        male_count = sum(1 for g in guests if g.get('gender') == 'M')
        female_count = sum(1 for g in guests if g.get('gender') == 'F')
        st.metric("M/F", f"{male_count}/{female_count}")
    
    st.markdown("---")
    
    # Create floor map
    floors, occupied_rooms = create_floor_map(guests)
    
    # Initialize selected floor in session state
    if 'selected_floor' not in st.session_state:
        st.session_state.selected_floor = None
    
    # Display floor map
    display_floor_map(floors, occupied_rooms, st.session_state.selected_floor)
    
    st.markdown("---")
    
    # Quick statistics
    st.markdown("### 📊 Quick Statistics")
    
    # Occupancy by floor
    floor_stats = []
    for floor in sorted(floors.keys()):
        floor_rooms = floors[floor]
        occupied_count = sum(1 for r in floor_rooms if r['occupied'])
        total_count = len(floor_rooms)
        occupancy_rate = (occupied_count / total_count) * 100
        floor_stats.append({
            "Floor": floor,
            "Occupied": occupied_count,
            "Available": total_count - occupied_count,
            "Occupancy Rate": f"{occupancy_rate:.0f}%"
        })
    
    df_stats = pd.DataFrame(floor_stats)
    st.dataframe(df_stats, use_container_width=True)
    
    # Nationality breakdown
    st.markdown("---")
    st.markdown("### 🌍 Nationality Breakdown")
    nationality_counts = {}
    for guest in guests:
        nat = guest.get('nationality', 'Unknown')
        if nat in COUNTRY_CODE_MAP:
            nat = COUNTRY_CODE_MAP[nat]
        nationality_counts[nat] = nationality_counts.get(nat, 0) + 1
    
    if nationality_counts:
        nat_df = pd.DataFrame([
            {"Nationality": nat, "Count": count}
            for nat, count in sorted(nationality_counts.items(), key=lambda x: x[1], reverse=True)
        ])
        st.dataframe(nat_df, use_container_width=True)
        
        # Simple bar chart
        st.bar_chart(nat_df.set_index("Nationality"))
    
    # Export hotel overview
    st.markdown("---")
    if st.button("📥 Download Hotel Overview", use_container_width=True):
        hotel_data = {
            "hotel_name": "Novotel Suites Hanoi",
            "report_date": datetime.now().strftime('%d/%m/%Y'),
            "total_guests": len(guests),
            "total_rooms": total_rooms,
            "floor_stats": floor_stats,
            "guests": [
                {
                    "room": g.get('room'),
                    "name": g.get('name'),
                    "arrival": g.get('arrival_date'),
                    "departure": g.get('departure_date'),
                    "nationality": COUNTRY_CODE_MAP.get(g.get('nationality', ''), g.get('nationality', ''))
                }
                for g in guests
            ]
        }
        hotel_json = json.dumps(hotel_data, indent=2, default=str)
        st.download_button(
            label="📥 Download Hotel Overview (JSON)",
            data=hotel_json,
            file_name=f"hotel_overview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json"
        )