"""
Guest Extractor Module
Extracts guest names from PDF and generates email suggestions
Supports both: Night Audit reports AND Arrivals reports
"""
import requests
import streamlit as st
import pdfplumber
import re
import pandas as pd
from io import BytesIO
from datetime import datetime

# Initialize session state for batch selection and API settings
# Add to your existing session state initialization
if 'migadu_email' not in st.session_state:
    st.session_state.migadu_email = ''
if 'batch_selected_indices' not in st.session_state:
    st.session_state.batch_selected_indices = []
if 'batch_selected_guests' not in st.session_state:
    st.session_state.batch_selected_guests = []
if 'show_batch_modal' not in st.session_state:
    st.session_state.show_batch_modal = False
if 'email_domain' not in st.session_state:
    st.session_state.email_domain = 'guest.stay.com'
if 'migadu_api_key' not in st.session_state:
    st.session_state.migadu_api_key = ''
if 'migadu_api_secret' not in st.session_state:
    st.session_state.migadu_api_secret = ''
if 'show_api_settings' not in st.session_state:
    st.session_state.show_api_settings = False

def is_valid_room(room_num):
    """
    Check if room number is valid based on property:
    - Floor 04 to 16
    - Room position 01 to 12
    """
    try:
        room_str = str(room_num).zfill(4)
        room_int = int(room_str)
        floor = room_int // 100
        position = room_int % 100
        
        return (4 <= floor <= 16) and (1 <= position <= 12)
    except:
        return False


def clean_guest_name(name):
    """
    Clean guest name by removing asterisks, extra spaces, and OTA prefixes
    """
    if not name:
        return name
    
    # Remove leading/trailing asterisks
    name = name.lstrip('*').rstrip('*')
    
    # Remove OTA prefixes (T-, C-, S-, B-)
    name = re.sub(r'^[TCSB]-\s*', '', name, flags=re.IGNORECASE)
    
    # Remove any trailing numbers (like confirmation numbers)
    name = re.sub(r'\s+\d+$', '', name)
    
    # Clean up extra spaces
    name = re.sub(r'\s+', ' ', name)
    name = name.strip()
    
    # Remove quotes
    name = name.replace('"', '')
    
    return name


def extract_guests_from_night_audit(text):
    """
    Extract guests from Night Audit report format
    Format: Room number, guest name in table
    """
    guests = []
    
    # Pattern for night audit format
    pattern = r'(\d{3,4})\s+([A-Za-z][^0-9]{10,60}?)(?:\s+\d+){3,}'
    matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
    
    seen_rooms = set()
    
    for room_num, guest_name in matches:
        room_str = room_num.zfill(4)
        
        if not is_valid_room(room_str):
            continue
        if room_str in seen_rooms:
            continue
            
        seen_rooms.add(room_str)
        
        guest_clean = guest_name.strip()
        guest_clean = re.sub(r'\s+', ' ', guest_clean)
        guest_clean = clean_guest_name(guest_clean)
        
        guests.append({
            'room': room_str,
            'guest_name': guest_clean,
            'arrival_date': None,
            'departure_date': None,
            'source': 'Night Audit'
        })
    
    return guests


def extract_guests_from_arrivals_report(text):
    """
    Extract guests from Arrivals Report format using text-based extraction
    Keeps all records, shows modal for TRUE duplicates
    """
    guests = []
    
    # Debug counters
    debug_stats = {
        'total_lines_scanned': 0,
        'lines_with_room_numbers': 0,
        'invalid_rooms_filtered': 0,
        'invalid_room_numbers': [],
        'no_name_extracted': 0,
        'name_too_short': 0,
        'successfully_added': 0
    }
    
    lines = text.split('\n')
    total_lines = len(lines)
    
    i = 0
    while i < total_lines:
        line = lines[i].strip()
        debug_stats['total_lines_scanned'] += 1
        
        # Look for a line that starts with a room number (3-4 digits)
        room_match = re.match(r'^(\d{3,4})\s+', line)
        
        if room_match:
            room_num = room_match.group(1)
            room_str = room_num.zfill(4)
            debug_stats['lines_with_room_numbers'] += 1
            
            # Skip invalid rooms
            if not is_valid_room(room_str):
                debug_stats['invalid_rooms_filtered'] += 1
                if room_str not in debug_stats['invalid_room_numbers']:
                    debug_stats['invalid_room_numbers'].append(room_str)
                i += 1
                continue
            
            # Get the part after the room number
            remaining = line[len(room_match.group(0)):].strip()
            
            arrival_date = None
            departure_date = None
            name_part = remaining
            
            # Look for company indicators (C-, T-, S-)
            company_pattern = r'\s+[CTS]-\s*'
            company_match = re.search(company_pattern, remaining, re.IGNORECASE)
            
            if company_match:
                # Name is everything BEFORE the company indicator
                name_part = remaining[:company_match.start()].strip()
                # Look for dates after company indicator
                remaining_after = remaining[company_match.end():].strip()
                date_pattern = r'(\d{2}/\d{2}/\d{2})'
                dates = re.findall(date_pattern, remaining_after)
                if len(dates) >= 2:
                    arrival_date = dates[0]
                    departure_date = dates[1]
                else:
                    # Check next lines
                    for offset in range(1, 4):
                        if i + offset < total_lines:
                            next_line = lines[i + offset].strip()
                            dates = re.findall(date_pattern, next_line)
                            if len(dates) >= 2:
                                arrival_date = dates[0]
                                departure_date = dates[1]
                                break
                            elif len(dates) == 1:
                                if arrival_date is None:
                                    arrival_date = dates[0]
                                elif departure_date is None:
                                    departure_date = dates[0]
            else:
                # No company indicator, look for dates directly
                date_pattern = r'(\d{2}/\d{2}/\d{2})'
                date_match = re.search(date_pattern, remaining)
                
                if date_match:
                    name_part = remaining[:date_match.start()].strip()
                    dates = re.findall(date_pattern, remaining)
                    arrival_date = dates[0] if len(dates) > 0 else None
                    departure_date = dates[1] if len(dates) > 1 else None
                else:
                    # No dates on this line, check next lines
                    for offset in range(1, 4):
                        if i + offset < total_lines:
                            next_line = lines[i + offset].strip()
                            dates = re.findall(date_pattern, next_line)
                            if len(dates) >= 2:
                                arrival_date = dates[0]
                                departure_date = dates[1]
                                break
                            elif len(dates) == 1:
                                if arrival_date is None:
                                    arrival_date = dates[0]
                                elif departure_date is None:
                                    departure_date = dates[0]
            
            # Clean up the name
            guest_name = name_part.strip()
            guest_name = guest_name.lstrip('*')
            guest_name = re.sub(r'\s+\d+$', '', guest_name)
            guest_name = re.sub(r'\s+', ' ', guest_name)
            guest_name = re.sub(r'\s+[CTS]-\s*\S+', '', guest_name, flags=re.IGNORECASE)
            
            # Check if we have a valid name
            if not guest_name or len(guest_name) < 3:
                debug_stats['no_name_extracted'] += 1
                # Still try to add with fallback name if we have dates
                if arrival_date:
                    guests.append({
                        'room': room_str,
                        'guest_name': f"Guest_{room_str}",
                        'arrival_date': arrival_date,
                        'departure_date': departure_date,
                        'source': 'Arrivals Report (Text)',
                        'original_text': name_part[:50]
                    })
                    debug_stats['successfully_added'] += 1
                else:
                    debug_stats['name_too_short'] += 1
            else:
                guests.append({
                    'room': room_str,
                    'guest_name': guest_name[:60],
                    'arrival_date': arrival_date,
                    'departure_date': departure_date,
                    'source': 'Arrivals Report (Text)',
                    'original_text': name_part[:50]
                })
                debug_stats['successfully_added'] += 1
        
        i += 1
    
    # ========== FIND TRUE DUPLICATES ==========
    duplicate_map = {}
    for guest in guests:
        room = guest['room']
        name = guest['guest_name'].lower().strip()
        arrival = guest.get('arrival_date', 'unknown')
        key = f"{room}_{name}_{arrival}"
        
        if key not in duplicate_map:
            duplicate_map[key] = []
        duplicate_map[key].append(guest)
    
    true_duplicates = {k: v for k, v in duplicate_map.items() if len(v) > 1}
    
    # Display debug statistics
    st.write("---")
    st.write("### 📊 Extraction Debug Statistics")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Lines Scanned", debug_stats['total_lines_scanned'])
    with col2:
        st.metric("Lines with Room #", debug_stats['lines_with_room_numbers'])
    with col3:
        st.metric("Invalid Rooms Filtered", debug_stats['invalid_rooms_filtered'])
    with col4:
        st.metric("Successfully Added", debug_stats['successfully_added'])
    
    if debug_stats['invalid_room_numbers']:
        with st.expander(f"🚫 Invalid Room Numbers ({len(debug_stats['invalid_room_numbers'])})"):
            st.write("These room numbers were filtered out (floor must be 04-16, position 01-12):")
            st.write(", ".join(debug_stats['invalid_room_numbers'][:30]))
            if len(debug_stats['invalid_room_numbers']) > 30:
                st.write(f"... and {len(debug_stats['invalid_room_numbers']) - 30} more")
    
    # Show TRUE duplicates modal
    if true_duplicates:
        st.warning(f"🔄 Found {len(true_duplicates)} TRUE duplicate(s) (exact same guest, room, and arrival date)")
        
        if st.button(f"📋 Show {len(true_duplicates)} Duplicate Record(s)", type="primary"):
            st.markdown("---")
            st.subheader("📋 True Duplicate Records")
            st.markdown("These records have the **exact same guest name + room + arrival date** appearing multiple times:")
            
            for key, duplicates in true_duplicates.items():
                parts = key.split('_', 2)
                room_num = parts[0] if len(parts) > 0 else "Unknown"
                guest_name = parts[1] if len(parts) > 1 else "Unknown"
                arrival_date = parts[2] if len(parts) > 2 else "Unknown"
                
                with st.expander(f"🔁 Room {room_num} - {guest_name[:40]} - Arrival {arrival_date} ({len(duplicates)} copies)", expanded=False):
                    dup_data = []
                    for idx, dup in enumerate(duplicates):
                        dup_data.append({
                            "Occurrence": f"Copy {idx + 1}",
                            "Guest Name": dup.get('guest_name', 'N/A')[:50],
                            "Arrival": dup.get('arrival_date', 'N/A'),
                            "Departure": dup.get('departure_date', 'N/A'),
                            "Source": dup.get('source', 'N/A')
                        })
                    st.dataframe(pd.DataFrame(dup_data), use_container_width=True)
                st.markdown("")
    else:
        st.success("✅ No true duplicate records found (all guests are unique)")
    
    st.write(f"📊 Total guests extracted: {len(guests)}")
    st.write("---")
    
    return guests


def extract_guests_from_pdf_table(pdf_bytes):
    """
    Extract guests using pdfplumber's table extraction
    Keeps all records, but shows a modal for TRUE duplicates
    (exact same guest name + room + arrival date)
    """
    guests = []
    
    debug_stats = {
        'pages_processed': 0,
        'tables_found': 0,
        'rows_processed': 0,
        'valid_rooms_found': 0,
        'invalid_rooms_filtered': 0,
        'no_name_extracted': 0,
        'dates_found': 0,
        'invalid_room_numbers': []
    }
    
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages):
            debug_stats['pages_processed'] += 1
            tables = page.extract_tables()
            
            if not tables:
                tables = page.extract_tables({
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines"
                })
            
            debug_stats['tables_found'] += len(tables)
            
            for table in tables:
                for row in table:
                    if not row or len(row) < 2:
                        continue
                    
                    debug_stats['rows_processed'] += 1
                    
                    # Column 0: Room number
                    room_cell = str(row[0]).strip() if row[0] else ""
                    room_match = re.match(r'^[\*\s]*(\d{3,4})[\*\s]*$', room_cell)
                    
                    if room_match:
                        room_num = room_match.group(1)
                        room_str = room_num.zfill(4)
                        
                        if not is_valid_room(room_str):
                            debug_stats['invalid_rooms_filtered'] += 1
                            if room_str not in debug_stats['invalid_room_numbers']:
                                debug_stats['invalid_room_numbers'].append(room_str)
                            continue
                        
                        debug_stats['valid_rooms_found'] += 1
                        
                        # Column 1: Guest Name
                        name_cell = str(row[1]).strip() if len(row) > 1 else ""
                        guest_name = name_cell.lstrip('*').strip()
                        guest_name = re.sub(r'\s+', ' ', guest_name)
                        
                        # Extract dates
                        arrival_date = None
                        departure_date = None
                        date_pattern = r'(\d{2}/\d{2}/\d{2})'
                        
                        for col_idx, cell in enumerate(row):
                            if cell and col_idx >= 3:
                                cell_str = str(cell).strip()
                                dates = re.findall(date_pattern, cell_str)
                                if len(dates) >= 2:
                                    arrival_date = dates[0]
                                    departure_date = dates[1]
                                    debug_stats['dates_found'] += 1
                                    break
                                elif len(dates) == 1:
                                    if arrival_date is None:
                                        arrival_date = dates[0]
                                    elif departure_date is None:
                                        departure_date = dates[0]
                                        debug_stats['dates_found'] += 1
                        
                        # Add to guests (keep ALL records)
                        if guest_name and len(guest_name) > 2:
                            guests.append({
                                'room': room_str,
                                'guest_name': guest_name[:60],
                                'arrival_date': arrival_date,
                                'departure_date': departure_date,
                                'source': f'Page {page_num + 1}'
                            })
                        else:
                            debug_stats['no_name_extracted'] += 1
                            if arrival_date:
                                guests.append({
                                    'room': room_str,
                                    'guest_name': f"Guest_{room_str}",
                                    'arrival_date': arrival_date,
                                    'departure_date': departure_date,
                                    'source': f'Page {page_num + 1}'
                                })
    
    # ========== FIND TRUE DUPLICATES (exact same name + room + arrival date) ==========
    duplicate_map = {}
    for guest in guests:
        # Create a key from normalized values
        room = guest['room']
        name = guest['guest_name'].lower().strip()
        arrival = guest.get('arrival_date', 'unknown')
        key = f"{room}_{name}_{arrival}"
        
        if key not in duplicate_map:
            duplicate_map[key] = []
        duplicate_map[key].append(guest)
    
    # Filter to only actual duplicates (more than 1 occurrence)
    true_duplicates = {k: v for k, v in duplicate_map.items() if len(v) > 1}
    
    # Display debug statistics
    st.write("---")
    st.write("### 📊 Table Extraction Debug Statistics")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Pages Processed", debug_stats['pages_processed'])
    with col2:
        st.metric("Tables Found", debug_stats['tables_found'])
    with col3:
        st.metric("Rows Processed", debug_stats['rows_processed'])
    with col4:
        st.metric("Valid Rooms Found", debug_stats['valid_rooms_found'])
    
    st.write(f"🚫 Invalid rooms filtered: {debug_stats['invalid_rooms_filtered']}")
    st.write(f"❌ No name extracted: {debug_stats['no_name_extracted']}")
    st.write(f"✅ Dates found: {debug_stats['dates_found']}")
    
    if debug_stats['invalid_room_numbers']:
        with st.expander(f"🚫 Invalid Room Numbers ({len(debug_stats['invalid_room_numbers'])})"):
            st.write(", ".join(debug_stats['invalid_room_numbers'][:30]))
    
    # Show TRUE duplicates modal button
    if true_duplicates:
        st.warning(f"🔄 Found {len(true_duplicates)} TRUE duplicate(s) (exact same guest, room, and arrival date)")
        
        if st.button(f"📋 Show {len(true_duplicates)} Duplicate Record(s)", type="primary"):
            st.markdown("---")
            st.subheader("📋 True Duplicate Records")
            st.markdown("These records have the **exact same guest name + room + arrival date** appearing multiple times:")
            
            for key, duplicates in true_duplicates.items():
                # Parse key for display
                parts = key.split('_', 2)
                room_num = parts[0] if len(parts) > 0 else "Unknown"
                guest_name = parts[1] if len(parts) > 1 else "Unknown"
                arrival_date = parts[2] if len(parts) > 2 else "Unknown"
                
                with st.expander(f"🔁 Room {room_num} - {guest_name[:40]} - Arrival {arrival_date} ({len(duplicates)} copies)", expanded=False):
                    dup_data = []
                    for idx, dup in enumerate(duplicates):
                        dup_data.append({
                            "Occurrence": f"Copy {idx + 1}",
                            "Guest Name": dup.get('guest_name', 'N/A')[:50],
                            "Arrival": dup.get('arrival_date', 'N/A'),
                            "Departure": dup.get('departure_date', 'N/A'),
                            "Source": dup.get('source', 'N/A')
                        })
                    st.dataframe(pd.DataFrame(dup_data), use_container_width=True)
                st.markdown("")
    else:
        st.success("✅ No true duplicate records found (all guests are unique)")
    
    st.write(f"📊 Total guests extracted: {len(guests)}")
    st.write("---")
    
    return guests


def extract_guests_from_pdf(pdf_bytes):
    """
    Extract guest names and room numbers from PDF
    Auto-detects which format (Night Audit or Arrivals Report)
    """
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        full_text = ""
        total_pages = len(pdf.pages)
        st.write(f"📊 PDF has {total_pages} pages")
        
        for page_num, page in enumerate(pdf.pages):
            extracted = page.extract_text()
            if extracted:
                full_text += extracted + "\n"
    
    # Detect format
    if "Arrivals by Name" in full_text:
        st.info("📋 Detected: Arrivals Report format")
        guests = extract_guests_from_pdf_table(pdf_bytes)
        
        if not guests:
            st.info("Table extraction returned no results, trying text-based extraction...")
            guests = extract_guests_from_arrivals_report(full_text)
        
        st.write(f"📊 Successfully extracted {len(guests)} guests")
        return guests
        
    elif "Rate Amt." in full_text:
        st.info("📋 Detected: Night Audit format")
        guests = extract_guests_from_night_audit(full_text)
        return guests
    
    else:
        st.info("📋 Format not clearly detected, trying both...")
        guests = extract_guests_from_night_audit(full_text)
        if not guests:
            guests = extract_guests_from_arrivals_report(full_text)
        return guests


def generate_email_suggestions(guest_name, room_number):
    """
    Generate dummy email suggestions based on guest name and room number
    """
    # Clean the name first
    guest_name = clean_guest_name(guest_name)
    
    name_parts = guest_name.lower().replace(',', ' ').split()
    
    # Extract first name and last name intelligently
    first_name = ""
    last_name = ""
    
    if len(name_parts) >= 2:
        if ',' in guest_name:
            # Format: "Last, First"
            parts = guest_name.split(',')
            last_name = parts[0].strip().lower()
            first_part = parts[1].strip().lower() if len(parts) > 1 else ""
            first_name = first_part.split()[0] if first_part else ""
        else:
            # Format: "First Last" or "First Middle Last"
            first_name = name_parts[0]
            last_name = name_parts[-1]
    elif len(name_parts) == 1:
        first_name = name_parts[0]
        last_name = name_parts[0]
    
    # Remove special characters
    first_name = re.sub(r'[^a-z]', '', first_name)
    last_name = re.sub(r'[^a-z]', '', last_name)
    room_number_clean = str(room_number).zfill(4)
    
    # Generate email suggestions
    suggestions = []
    
    if first_name and last_name and first_name != last_name:
        suggestions.append(f"{first_name}.{last_name}")
        suggestions.append(f"{first_name}{last_name}")
        suggestions.append(f"{last_name}.{first_name}")
    
    if first_name:
        suggestions.append(f"{first_name}.{room_number_clean}")
    
    if last_name and last_name != first_name:
        suggestions.append(f"{last_name}.{room_number_clean}")
    
    suggestions.append(f"guest.{room_number_clean}")
    suggestions.append(f"room{room_number_clean}")
    suggestions.append(f"{room_number_clean}")
    
    # Remove duplicates and empty strings
    suggestions = [s for s in list(dict.fromkeys(suggestions)) if s]
    
    return suggestions[:10]


def detect_pdf_format(pdf_bytes):
    """Quick detection of PDF format"""
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        first_page_text = pdf.pages[0].extract_text() or ""
        
        if "Arrivals by Name" in first_page_text:
            return "Arrivals Report"
        elif "Rate Amt." in first_page_text:
            return "Night Audit"
        else:
            return "Unknown"

def get_migadu_domain_info(domain, api_email, api_secret):
    """
    Fetch domain information from Migadu API
    """
    import requests
    
    url = f"https://api.migadu.com/v1/domains/{domain}"
    
    try:
        response = requests.get(
            url,
            auth=(api_email, api_secret),
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Status {response.status_code}: {response.text[:200]}")
            return None
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return None

def test_migadu_connection(domain, api_email, api_secret):
    """
    Test connection to Migadu API
    - api_email: Your Migadu account email address (username)
    - api_secret: Your API key secret
    """
    import requests
    
    url = f"https://api.migadu.com/v1/domains/{domain}"
    
    try:
        response = requests.get(
            url,
            auth=(api_email, api_secret),
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 200:
            return True
        else:
            return False
            
    except Exception:
        return False

def extract_guests_from_arrivals_report_silent(text):
    """
    Silent version - no debug output, just returns guests
    """
    guests = []
    lines = text.split('\n')
    total_lines = len(lines)
    
    i = 0
    while i < total_lines:
        line = lines[i].strip()
        room_match = re.match(r'^(\d{3,4})\s+', line)
        
        if room_match:
            room_num = room_match.group(1)
            room_str = room_num.zfill(4)
            
            if not is_valid_room(room_str):
                i += 1
                continue
            
            remaining = line[len(room_match.group(0)):].strip()
            
            arrival_date = None
            departure_date = None
            name_part = remaining
            
            company_pattern = r'\s+[CTS]-\s*'
            company_match = re.search(company_pattern, remaining, re.IGNORECASE)
            date_pattern = r'(\d{2}/\d{2}/\d{2})'
            
            if company_match:
                name_part = remaining[:company_match.start()].strip()
                remaining_after = remaining[company_match.end():].strip()
                dates = re.findall(date_pattern, remaining_after)
                if len(dates) >= 2:
                    arrival_date = dates[0]
                    departure_date = dates[1]
                else:
                    for offset in range(1, 4):
                        if i + offset < total_lines:
                            next_line = lines[i + offset].strip()
                            dates = re.findall(date_pattern, next_line)
                            if len(dates) >= 2:
                                arrival_date = dates[0]
                                departure_date = dates[1]
                                break
                            elif len(dates) == 1:
                                if arrival_date is None:
                                    arrival_date = dates[0]
                                elif departure_date is None:
                                    departure_date = dates[0]
            else:
                date_match = re.search(date_pattern, remaining)
                if date_match:
                    name_part = remaining[:date_match.start()].strip()
                    dates = re.findall(date_pattern, remaining)
                    arrival_date = dates[0] if len(dates) > 0 else None
                    departure_date = dates[1] if len(dates) > 1 else None
                else:
                    for offset in range(1, 4):
                        if i + offset < total_lines:
                            next_line = lines[i + offset].strip()
                            dates = re.findall(date_pattern, next_line)
                            if len(dates) >= 2:
                                arrival_date = dates[0]
                                departure_date = dates[1]
                                break
                            elif len(dates) == 1:
                                if arrival_date is None:
                                    arrival_date = dates[0]
                                elif departure_date is None:
                                    departure_date = dates[0]
            
            guest_name = name_part.strip()
            guest_name = guest_name.lstrip('*')
            guest_name = re.sub(r'\s+\d+$', '', guest_name)
            guest_name = re.sub(r'\s+', ' ', guest_name)
            guest_name = re.sub(r'\s+[CTS]-\s*\S+', '', guest_name, flags=re.IGNORECASE)
            
            if not guest_name or len(guest_name) < 3:
                if arrival_date:
                    guests.append({
                        'room': room_str,
                        'guest_name': f"Guest_{room_str}",
                        'arrival_date': arrival_date,
                        'departure_date': departure_date,
                        'source': 'Arrivals Report'
                    })
            else:
                guests.append({
                    'room': room_str,
                    'guest_name': guest_name[:60],
                    'arrival_date': arrival_date,
                    'departure_date': departure_date,
                    'source': 'Arrivals Report'
                })
        
        i += 1
    
    return guests

def verify_domain(domain):
    """
    Simple domain verification using DNS lookup
    """
    import socket
    
    try:
        # Basic DNS resolution
        socket.gethostbyname(domain)
        return True, "Domain resolves"
    except socket.gaierror:
        return False, "Domain does not resolve"
    
def generate_batch_emails(guests, domain, mode='create_mailboxes'):
    """
    Generate emails for a batch of guests and create mailboxes via Migadu
    """
    all_guest_data = []
    domain = domain or st.session_state.get('email_domain', 'guest.stay.com')
    
    # Track success/failure for mailbox creation
    success_count = 0
    fail_count = 0
    failed_emails = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, guest in enumerate(guests):
        # Clean guest name and extract parts
        full_name = clean_guest_name(guest['guest_name'])
        
        # Parse first and last name
        first_name = ""
        last_name = ""
        
        if ',' in full_name:
            # Format: "Last, First"
            parts = full_name.split(',')
            last_name = parts[0].strip()
            first_name = parts[1].strip() if len(parts) > 1 else ""
        else:
            # Format: "First Last"
            name_parts = full_name.split()
            if len(name_parts) >= 2:
                first_name = name_parts[0]
                last_name = name_parts[-1]
            elif len(name_parts) == 1:
                first_name = name_parts[0]
                last_name = name_parts[0]
        
        # Generate email local_part based on guest name
        local_part = generate_local_part(guest['guest_name'], guest['room'])
        primary_email = f"{local_part}@{domain}"
        
        # Store all data
        guest_record = {
            'room': guest['room'],
            'full_name': full_name,
            'first_name': first_name,
            'last_name': last_name,
            'email': primary_email,
            'local_part': local_part,
            'password': 'Abc@123456',
            'arrival_date': guest.get('arrival_date', ''),
            'departure_date': guest.get('departure_date', '')
        }
        all_guest_data.append(guest_record)
        
        # Create mailbox via Migadu API
        status_text.text(f"Creating mailbox for {full_name[:30]}... ({i+1}/{len(guests)})")
        
        result = create_mailbox_via_migadu(
            domain, 
            local_part, 
            full_name,
            st.session_state.get('migadu_email', ''),
            st.session_state.get('migadu_api_secret', '')
        )
        
        if result:
            success_count += 1
        else:
            fail_count += 1
            failed_emails.append(primary_email)
        
        progress_bar.progress((i + 1) / len(guests))
    
    progress_bar.empty()
    status_text.empty()
    
    # Display results
    st.markdown("---")
    st.subheader("📧 Email Creation Results")
    
    # Create full DataFrame
    df_export = pd.DataFrame([{
        'Room': item['room'],
        'Full Name': item['full_name'],
        'First Name': item['first_name'],
        'Last Name': item['last_name'],
        'Email': item['email'],
        'Password': item['password'],
        'Arrival Date': item['arrival_date'],
        'Departure Date': item['departure_date']
    } for item in all_guest_data])
    
    # Display the full table (spanning full width)
    st.dataframe(df_export, use_container_width=True)
    
    # Show summary for mailbox creation
    if success_count > 0:
        st.success(f"✅ Created {success_count} mailboxes successfully!")
    if fail_count > 0:
        st.error(f"❌ Failed to create {fail_count} mailboxes")
        with st.expander("View failed emails"):
            for email in failed_emails:
                st.write(f"- {email}")
    
    # Export options
    st.markdown("---")
    st.subheader("💾 Export Data")
    
    col_export1, col_export2 = st.columns(2)
    
    with col_export1:
        # CSV export
        csv_data = df_export.to_csv(index=False)
        st.download_button(
            label="📥 Download as CSV",
            data=csv_data,
            file_name=f"guest_emails_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with col_export2:
        # Excel export
        try:
            import io
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False, sheet_name='Guest Emails')
            excel_data = output.getvalue()
            
            st.download_button(
                label="📥 Download as Excel",
                data=excel_data,
                file_name=f"guest_emails_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        except ImportError:
            st.warning("Excel export requires openpyxl. Install with: pip install openpyxl")
            # Fallback to CSV only
            st.info("Excel export not available. Please install openpyxl or use CSV.")
    
    st.info(f"💡 Password for all mailboxes: **Abc@123456**")

def generate_local_part(guest_name, room_number):
    """
    Generate random local part for email based on guest name
    Examples:
    - An,Chang Ho -> an.chang.ho123 or an-chang-ho456 or anchangho789
    - Andrew Vincent,Boyce -> andrew.boyce123 or andrew-boyce456
    - With dash: dwightcrawford.robinson-94
    - Without dash: dwightcrawford.robinson94
    """
    import random
    
    # Clean the guest name
    name = clean_guest_name(guest_name)
    name_lower = name.lower()
    
    # Parse the name properly
    name_parts = []
    
    # Handle "Last, First Middle" format
    if ',' in name_lower:
        parts = name_lower.split(',')
        last_name = parts[0].strip()
        first_middle = parts[1].strip() if len(parts) > 1 else ""
        
        # Add last name
        if last_name:
            name_parts.append(last_name)
        
        # Split first and middle names
        if first_middle:
            first_parts = first_middle.split()
            name_parts.extend(first_parts)
    else:
        # Standard "First Last" format
        name_parts = name_lower.split()
    
    # Remove empty parts and clean (only keep letters)
    name_parts = [re.sub(r'[^a-z]', '', p) for p in name_parts if p]
    
    # If no valid parts, use room number
    if not name_parts:
        name_parts = [f"guest{room_number}"]
    
    # Generate unique random suffix (10-999)
    random_suffix = random.randint(10, 999)
    
    # Randomly choose format (0-4)
    # 0: dots with dash (e.g., an.chang-123)
    # 1: dots with dash (multiple dots) (e.g., an.chang.ho-456)
    # 2: hyphens with dash (e.g., an-chang-789)
    # 3: no separators with dash (e.g., anchang-234)
    # 4: no separators without dash (e.g., anchang567)
    format_choice = random.randint(0, 4)
    
    if format_choice == 0:
        # Format: first.last-suffix (with dash)
        if len(name_parts) >= 2:
            base = f"{name_parts[0]}.{name_parts[-1]}"
        else:
            base = name_parts[0]
        local_part = f"{base}-{random_suffix}"
    
    elif format_choice == 1:
        # Format: first.last.last-suffix (with dash, multiple dots)
        if len(name_parts) >= 2:
            base = '.'.join(name_parts[:2])
        else:
            base = name_parts[0]
        local_part = f"{base}-{random_suffix}"
    
    elif format_choice == 2:
        # Format: first-last-suffix (hyphens with dash)
        if len(name_parts) >= 2:
            base = '-'.join(name_parts[:2])
        else:
            base = name_parts[0]
        local_part = f"{base}-{random_suffix}"
    
    elif format_choice == 3:
        # Format: firstlast-suffix (no separators, but with dash)
        base = ''.join(name_parts[:2]) if len(name_parts) >= 2 else name_parts[0]
        local_part = f"{base}-{random_suffix}"
    
    else:
        # Format: firstlastsuffix (no separators, NO dash)
        base = ''.join(name_parts[:2]) if len(name_parts) >= 2 else name_parts[0]
        local_part = f"{base}{random_suffix}"
    
    # Ensure local_part is valid (only lowercase letters, numbers, dots, hyphens)
    local_part = re.sub(r'[^a-z0-9.-]', '', local_part)
    # Remove leading/trailing dots or hyphens
    local_part = local_part.strip('.-')
    # Limit to 40 characters
    local_part = local_part[:40]
    
    return local_part

def create_mailbox_via_migadu(domain, local_part, guest_name, api_email, api_secret):
    """
    Create a mailbox via Migadu API
    Uses POST method to create mailbox with password
    """
    import requests
    
    url = f"https://api.migadu.com/v1/domains/{domain}/mailboxes"
    
    # Clean local_part (ensure it's valid)
    local_part = re.sub(r'[^a-z0-9.-]', '', local_part.lower())
    local_part = local_part.strip('.-')
    
    # Default password (as requested)
    password = "Abc@123456"
    
    # Create mailbox name from guest name (clean it)
    mailbox_name = guest_name.strip()
    # Remove special characters from name for display
    mailbox_name = re.sub(r'[^\w\s]', ' ', mailbox_name)
    mailbox_name = re.sub(r'\s+', ' ', mailbox_name).strip()
    mailbox_name = mailbox_name[:50]
    
    payload = {
        "name": mailbox_name,
        "local_part": local_part,
        "password": password
    }
    
    try:
        response = requests.post(
            url,
            auth=(api_email, api_secret),
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            return True
        else:
            return False
            
    except Exception as e:
        return False

def display_guest_extractor(pdf_bytes):
    """
    Main function for Guest Extractor - CLEAN VERSION with working duplicate display
    """
    st.subheader("📇 Guest Name Extractor")
    
    # Get page count first
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        total_pages = len(pdf.pages)
    
    # Show simple status
    st.info(f"📄 PDF: {total_pages} pages | Format: Arrivals Report")
    
    # Cache extraction (use silent text extraction - the working one)
    cache_key = f"extracted_guests_{hash(pdf_bytes)}"
    if cache_key not in st.session_state:
        with st.spinner(f"Extracting guests from {total_pages} pages..."):
            with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
                full_text = ""
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted:
                        full_text += extracted + "\n"
            
            # Use SILENT version (no debug output)
            guests = extract_guests_from_arrivals_report_silent(full_text)
            st.session_state[cache_key] = guests
            st.session_state['total_pages'] = total_pages
    
    guests = st.session_state[cache_key]
    
    if not guests:
        st.warning("No guests found. Please check the PDF format.")
        return
    
    st.success(f"✅ {len(guests)} guests extracted")
    
    # Create tabs
    tab1, tab2, tab3 = st.tabs(["📋 Guest List", "📦 Batch Export", "⚙️ Settings"])
    
    
    # ========== TAB 1: Guest List ==========
    with tab1:
        st.subheader("All Extracted Guests")
        
        # Data Quality section moved here
        st.caption(f"📊 PDF pages: {st.session_state.get('total_pages', 0)} | Guests: {len(guests)}")
        
        # Prepare data for display
        guest_data = []
        for idx, guest in enumerate(guests):
            guest_data.append({
                "#": idx + 1,
                "Room": guest['room'],
                "Guest Name": guest['guest_name'][:50],
                "Arrival": guest.get('arrival_date', 'N/A'),
                "Departure": guest.get('departure_date', 'N/A'),
                "Source": guest.get('source', 'N/A')
            })
        
        df_guests = pd.DataFrame(guest_data)
        st.dataframe(df_guests, use_container_width=True, height=500)
        
        col1, col2 = st.columns(2)
        with col1:
            st.download_button("📥 CSV", df_guests.to_csv(index=False), f"guests_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", "text/csv")
        with col2:
            st.download_button("📥 JSON", df_guests.to_json(orient='records', indent=2), f"guests_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", "application/json")
        
        # Duplicate checker moved here
        st.markdown("---")
        with st.expander("🔍 Find Duplicates"):
            if st.button("Check for Duplicates"):
                dup_map = {}
                for g in guests:
                    key = f"{g['room']}_{g['guest_name'].strip()}_{g.get('arrival_date', '')}"
                    if key not in dup_map:
                        dup_map[key] = []
                    dup_map[key].append(g)
                
                duplicates = {k: v for k, v in dup_map.items() if len(v) > 1}
                
                if duplicates:
                    st.warning(f"Found {len(duplicates)} duplicate groups")
                    
                    dup_summary = []
                    for key, dups in duplicates.items():
                        parts = key.split('_', 2)
                        room = parts[0]
                        name = parts[1][:35]
                        dup_summary.append({"Room": room, "Guest": name, "Copies": len(dups)})
                    st.dataframe(pd.DataFrame(dup_summary), use_container_width=True)
                    
                    st.markdown("---")
                    st.markdown("### Detailed Duplicate Records")
                    
                    for key, dups in duplicates.items():
                        parts = key.split('_', 2)
                        room = parts[0]
                        name = parts[1][:40]
                        arrival = parts[2] if len(parts) > 2 else "Unknown"
                        
                        with st.expander(f"🔁 Room {room} - {name} - Arrival {arrival} ({len(dups)} copies)"):
                            dup_data = []
                            for i, d in enumerate(dups):
                                dup_data.append({
                                    "Copy": i + 1,
                                    "Guest Name": d['guest_name'],
                                    "Arrival": d.get('arrival_date', 'N/A'),
                                    "Departure": d.get('departure_date', 'N/A'),
                                    "Source": d.get('source', 'N/A')
                                })
                            st.dataframe(pd.DataFrame(dup_data), use_container_width=True)
                else:
                    st.success("No duplicates found")
    
    # ========== TAB 2: Batch Export ==========
    with tab2:
        st.subheader("Batch Email Creation")
        
        col1, col2 = st.columns(2)
        with col1:
            batch_size = st.number_input("Records", 1, len(guests), min(50, len(guests)), 10)
        with col2:
            start_from = st.number_input("Start from", 1, len(guests), 1, 1)
        
        end_idx = min(start_from + batch_size - 1, len(guests))
        st.info(f"Records #{start_from} to #{end_idx} ({batch_size} records)")
        
        # Preview
        preview = []
        for idx in range(start_from - 1, end_idx):
            g = guests[idx]
            preview.append({"#": idx + 1, "Room": g['room'], "Guest": g['guest_name'][:35]})
        st.dataframe(pd.DataFrame(preview), use_container_width=True)
        
        domain = st.text_input("Email Domain", st.session_state.get('email_domain', 'guest.stay.com'))
        
        # Only keep the Create Mailboxes button
        if st.button("🚀 Create Mailboxes (Migadu)", type="primary", use_container_width=True):
            if st.session_state.get('migadu_email') and st.session_state.get('migadu_api_secret'):
                generate_batch_emails(guests[start_from - 1:end_idx], domain, 'create_mailboxes')
            else:
                st.error("Configure Migadu API in Settings tab")
    
    # ========== TAB 3: Settings ==========
    with tab3:
        st.subheader("Email Domain")
        
        col_domain1, col_domain2 = st.columns([3, 1])
        with col_domain1:
            domain = st.text_input("Default Domain", st.session_state.get('email_domain', 'guest.stay.com'))
        with col_domain2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🌐 Verify Domain", use_container_width=True):
                if domain:
                    with st.spinner(f"Verifying {domain}..."):
                        import socket
                        try:
                            socket.gethostbyname(domain)
                            st.success(f"✅ Domain {domain} resolves")
                        except socket.gaierror:
                            st.error(f"❌ Cannot resolve domain {domain}")
                else:
                    st.warning("Please enter a domain first")
        
        if st.button("💾 Save Domain", use_container_width=True):
            st.session_state.email_domain = domain
            st.success(f"Domain saved: {domain}")
        
        st.markdown("---")
        st.subheader("Migadu API")
        st.caption("You need your Migadu account email and API secret from My Account > API Keys")
        
        col_api1, col_api2 = st.columns(2)
        with col_api1:
            api_email = st.text_input(
                "Migadu Account Email", 
                value=st.session_state.get('migadu_email', ''),
                type="default",
                help="Your Migadu login email address"
            )
            st.session_state.migadu_email = api_email
        
        with col_api2:
            api_secret = st.text_input(
                "API Secret", 
                value=st.session_state.get('migadu_api_secret', ''),
                type="password",
                help="Your API key secret from Migadu"
            )
            st.session_state.migadu_api_secret = api_secret
        
        if st.button("🔌 Test API Connection", use_container_width=True):
            if api_email and api_secret and domain:
                with st.spinner("Testing Migadu API connection..."):
                    test_result = test_migadu_connection(domain, api_email, api_secret)
                    if test_result:
                        st.success("✅ Migadu API connected!")
                    else:
                        st.error("❌ API connection failed")
            else:
                st.warning("Enter email, API secret, and domain first")