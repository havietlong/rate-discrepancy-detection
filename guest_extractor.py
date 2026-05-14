"""
Guest Extractor Module
Extracts guest names from PDF and generates email suggestions
Supports both: Night Audit reports AND Arrivals reports
"""

import streamlit as st
import pdfplumber
import re
import pandas as pd
from io import BytesIO
from datetime import datetime

# Initialize session state for batch selection and API settings
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
    
    # ========== TAB 2: Batch Export ==========
    with tab2:
        st.subheader("Batch Email Generation")
        
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
        
        if st.button("📧 Generate Emails", type="primary"):
            generate_batch_emails(guests[start_from - 1:end_idx], domain, 'suggestions')
        
        if st.button("🚀 Create Mailboxes (Migadu)"):
            if st.session_state.get('migadu_api_key') and st.session_state.get('migadu_api_secret'):
                generate_batch_emails(guests[start_from - 1:end_idx], domain, 'create_mailboxes')
            else:
                st.error("Configure Migadu API in Settings tab")
    
    # ========== TAB 3: Settings ==========
    with tab3:
        st.subheader("Email Domain")
        domain = st.text_input("Default Domain", st.session_state.get('email_domain', 'guest.stay.com'))
        if st.button("Save Domain"):
            st.session_state.email_domain = domain
            st.success(f"Saved: {domain}")
        
        st.markdown("---")
        st.subheader("Migadu API")
        
        api_key = st.text_input("API Key", type="password", value=st.session_state.get('migadu_api_key', ''))
        api_secret = st.text_input("API Secret", type="password", value=st.session_state.get('migadu_api_secret', ''))
        
        if api_key:
            st.session_state.migadu_api_key = api_key
        if api_secret:
            st.session_state.migadu_api_secret = api_secret
        
        if st.button("Test Connection"):
            if api_key and api_secret and domain:
                with st.spinner("Testing..."):
                    if test_migadu_connection(domain, api_key, api_secret):
                        st.success("✅ Connected!")
                    else:
                        st.error("❌ Failed")
            else:
                st.warning("Enter credentials and domain")
        
        st.markdown("---")
        st.subheader("Data Quality")
        st.caption(f"PDF pages: {st.session_state.get('total_pages', 0)} | Guests: {len(guests)}")
        
        # Duplicate checker with page numbers
        with st.expander("🔍 Find Duplicates"):
            if st.button("Check for Duplicates"):
                dup_map = {}
                for g in guests:
                    # Create key for duplicate detection
                    key = f"{g['room']}_{g['guest_name'].strip()}_{g.get('arrival_date', '')}"
                    if key not in dup_map:
                        dup_map[key] = []
                    dup_map[key].append(g)
                
                duplicates = {k: v for k, v in dup_map.items() if len(v) > 1}
                
                if duplicates:
                    st.warning(f"Found {len(duplicates)} duplicate groups")
                    
                    # Show summary of duplicates
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
def generate_batch_emails(guests, domain, mode='suggestions'):
    """
    Generate emails for a batch of guests
    mode: 'suggestions' (just generate suggestions) or 'create_mailboxes' (actually create via Migadu)
    """
    all_suggestions = []
    domain = domain or st.session_state.get('email_domain', 'guest.stay.com')
    
    for guest in guests:
        suggestions = generate_email_suggestions(guest['guest_name'], guest['room'])
        
        # Use first suggestion as primary email
        primary_email = f"{suggestions[0]}@{domain}" if suggestions else f"guest.{guest['room']}@{domain}"
        
        all_suggestions.append({
            'room': guest['room'],
            'guest_name': guest['guest_name'],
            'arrival_date': guest.get('arrival_date', ''),
            'departure_date': guest.get('departure_date', ''),
            'email': primary_email,
            'suggestions': suggestions[:3]
        })
        
        # If mode is create_mailboxes, call Migadu API
        if mode == 'create_mailboxes':
            create_mailbox_via_migadu(domain, primary_email, guest['guest_name'])
    
    # Display results
    st.markdown("---")
    st.subheader("📧 Email Results")
    
    df_export = pd.DataFrame([{
        'room': item['room'],
        'guest_name': item['guest_name'],
        'email': item['email'],
        'arrival_date': item['arrival_date'],
        'departure_date': item['departure_date']
    } for item in all_suggestions])
    
    st.dataframe(df_export, use_container_width=True)
    
    # Export options
    col_export1, col_export2 = st.columns(2)
    
    with col_export1:
        csv_data = df_export.to_csv(index=False)
        st.download_button(
            label="📥 Download as CSV",
            data=csv_data,
            file_name=f"guest_emails_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    
    with col_export2:
        json_data = df_export.to_json(orient='records', indent=2)
        st.download_button(
            label="📥 Download as JSON",
            data=json_data,
            file_name=f"guest_emails_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json"
        )
    
    if mode == 'create_mailboxes':
        st.success(f"✅ Mailbox creation initiated for {len(all_suggestions)} guests")
    else:
        st.info(f"💡 Suggestions generated for {len(all_suggestions)} guests")


def test_migadu_connection(domain, api_key, api_secret):
    """
    Test connection to Migadu API
    """
    import requests
    
    url = f"https://api.migadu.com/v1/domains/{domain}"
    
    try:
        response = requests.get(
            url,
            auth=(api_key, api_secret),
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return False


def create_mailbox_via_migadu(domain, email, guest_name):
    """
    Create a mailbox via Migadu API
    """
    import requests
    
    api_key = st.session_state.get('migadu_api_key')
    api_secret = st.session_state.get('migadu_api_secret')
    
    if not api_key or not api_secret:
        return False
    
    # Extract local part from email
    local_part = email.split('@')[0]
    
    url = f"https://api.migadu.com/v1/domains/{domain}/mailboxes/{local_part}"
    
    payload = {
        "name": guest_name[:50],
        "local_part": local_part,
        "password": None,  # Will generate random password
        "spam_filter": "tag",
        "spam_aggressiveness": "normal",
        "remove_spam_filters": False
    }
    
    try:
        response = requests.put(
            url,
            auth=(api_key, api_secret),
            json=payload,
            timeout=30
        )
        return response.status_code in [200, 201]
    except Exception as e:
        st.error(f"Failed to create {email}: {str(e)}")
        return False