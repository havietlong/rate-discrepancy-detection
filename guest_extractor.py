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
    Remove company names, OTAs, and other noise from guest names
    Handles: T- (OTA Travel), C- (Corporate), S- (Self/System), B- (B2B)
    Also removes common company suffixes like PTE. LTD, Connectivity, etc.
    """
    if not name:
        return name
    
    # First, split the name if it contains company indicator (T-, C-, S-, B-)
    # Example: "Tsai CHIN LIANG,Albert Connectivity" -> split before "Connectivity"
    
    # Remove any OTA prefix from the beginning (T-, C-, S-, B-)
    name = re.sub(r'^[TCSB]-\s*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+[TCSB]-\s*', ' ', name, flags=re.IGNORECASE)
    
    # Remove common company/OTA suffixes (case insensitive)
    company_suffixes = [
        r'\s+Connectivity$',
        r'\s+PTE\.?\s*LTD\.?$',
        r'\s+PTE$',
        r'\s+LTD\.?$',
        r'\s+COMPANY\s+PTE\.?$',
        r'\s+COMPANY$',
        r'\s+COMPUTER\s+LTD\.?$',
        r'\s+COMPUTER$',
        r'\s+I&S$',
        r'\s+Tour$',
        r'\s+Golf$',
        r'\s+Travel$',
        r'\s+Technologies$',
        r'\s+Services$',
        r'\s+Logistics$',
        r'\s+International$',
        r'\s+Corporation$',
        r'\s+Corp$',
        r'\s+Inc\.?$',
        r'\s+Group$',
        r'\s+Holding$',
        r'\s+Solutions$',
        r'\s+Limited$',
        r'\s+Co\.?$',
        r'\s+Co$',
        r'\s+Reservation$',
        r'\s+Reservations$',
        r'\s+HOTELBEDS$',
        r'\s+AGODA$',
        r'\s+EXPEDIA$',
        r'\s+BOOKING$',
        r'\s+CTRIP$',
        r'\s+TRAVELOCITY$',
    ]
    
    for pattern in company_suffixes:
        name = re.sub(pattern, '', name, flags=re.IGNORECASE)
    
    # Remove any remaining OTA/company indicator anywhere in the string
    name = re.sub(r'\s+[TCSB]-\s*\S+\s*', ' ', name, flags=re.IGNORECASE)
    
    # Clean up extra spaces
    name = re.sub(r'\s+', ' ', name)
    name = name.strip()
    
    # Remove trailing special characters
    name = name.rstrip(',.- ')
    name = name.lstrip('*')
    
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
    Extract guests from Arrivals Report format
    Handles:
    - Asterisks before names (*Chi-Hsi,Ou)
    - Multi-row entries (name, dates, room type on separate lines)
    - Company names on separate lines
    """
    guests = []
    
    lines = text.split('\n')
    total_lines = len(lines)
    
    i = 0
    while i < total_lines:
        line = lines[i].strip()
        
        # Look for a line that starts with a room number (3-4 digits)
        # Allow optional asterisk after the room number
        room_match = re.match(r'^(\d{3,4})\s+[\*\s]*(.+?)(?:\s+\d+)?$', line)
        
        if room_match:
            room_num = room_match.group(1)
            room_str = room_num.zfill(4)
            
            # Skip invalid rooms
            if not is_valid_room(room_str):
                i += 1
                continue
            
            # Get the name part (remove asterisks and clean)
            name_part_raw = room_match.group(2).strip()
            # Remove leading asterisks
            name_part_raw = name_part_raw.lstrip('*')
            # Remove trailing numbers (like conf numbers)
            name_part_raw = re.sub(r'\s+\d+$', '', name_part_raw)
            
            # Initialize tracking variables
            arrival_date = None
            departure_date = None
            guest_name = name_part_raw if name_part_raw else None
            
            # Check next few lines for dates and additional name parts
            date_pattern = r'(\d{2}/\d{2}/\d{2})'
            
            # Look ahead up to 5 lines to find dates
            for offset in range(1, 6):
                if i + offset < total_lines:
                    next_line = lines[i + offset].strip()
                    
                    # Look for dates in this line
                    dates = re.findall(date_pattern, next_line)
                    
                    if len(dates) >= 2:
                        arrival_date = dates[0]
                        departure_date = dates[1]
                        # If we found dates, we can stop looking
                        break
                    elif len(dates) == 1:
                        if arrival_date is None:
                            arrival_date = dates[0]
                        elif departure_date is None:
                            departure_date = dates[0]
                    
                    # Also check if this line might contain additional name parts
                    # (like company names that got split)
                    if not guest_name or guest_name == name_part_raw:
                        # If line contains letters and no dates, might be part of name
                        if re.match(r'^[A-Za-z]', next_line) and not re.search(date_pattern, next_line):
                            # Don't include "C-" or "T-" prefixes as name
                            if not re.match(r'^[CT]-', next_line):
                                # Append to name if it looks like a name continuation
                                if len(next_line) < 50 and not re.match(r'^\d', next_line):
                                    if guest_name:
                                        guest_name = f"{guest_name} {next_line}"
                                    else:
                                        guest_name = next_line
                                    i += 1  # Skip this line since we used it
            
            # Clean up the guest name
            if guest_name:
                # Remove company prefixes
                guest_name = re.sub(r'\s+[CT]-\s*\S+', '', guest_name)
                # Remove quotes
                guest_name = guest_name.replace('"', '')
                # Clean up extra spaces
                guest_name = re.sub(r'\s+', ' ', guest_name)
                guest_name = guest_name.strip()
                
                # Remove any remaining numbers or special chars at end
                guest_name = re.sub(r'\s+\d+$', '', guest_name)
            else:
                guest_name = f"Guest_{room_str}"
            
            # Only add if we have a good name or dates
            if guest_name and guest_name != f"Guest_{room_str}":
                guests.append({
                    'room': room_str,
                    'guest_name': guest_name[:60],
                    'arrival_date': arrival_date,
                    'departure_date': departure_date,
                    'source': 'Arrivals Report'
                })
            elif arrival_date:  # Even without a good name, add if we have dates
                guests.append({
                    'room': room_str,
                    'guest_name': f"Guest_{room_str}",
                    'arrival_date': arrival_date,
                    'departure_date': departure_date,
                    'source': 'Arrivals Report'
                })
        
        i += 1
    
    # Remove duplicates based on room + arrival date + guest name
    seen = set()
    unique_guests = []
    
    for guest in guests:
        arrival = guest.get('arrival_date', 'unknown')
        name = guest.get('guest_name', '')
        key = f"{guest['room']}_{arrival}_{name}"
        
        if key not in seen:
            seen.add(key)
            unique_guests.append(guest)
    
    return unique_guests


def extract_guests_from_pdf_table(pdf_bytes):
    """
    Extract guests using pdfplumber's table extraction
    Handles OTA/Company prefixes: T-, C-, S-, B-
    """
    guests = []
    
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            
            for table in tables:
                for row in table:
                    if not row or len(row) < 3:
                        continue
                    
                    # Look for room number in first column (col 0)
                    room_cell = str(row[0]).strip() if row[0] else ""
                    
                    # Room number should be 3-4 digits (allow asterisks)
                    room_match = re.match(r'^[\*\s]*(\d{3,4})[\*\s]*$', room_cell)
                    
                    if room_match:
                        room_num = room_match.group(1)
                        room_str = room_num.zfill(4)
                        
                        if not is_valid_room(room_str):
                            continue
                        
                        # Name is in column 1 (col index 1)
                        name_cell = str(row[1]).strip() if len(row) > 1 else ""
                        # Remove leading asterisks
                        guest_name = name_cell.lstrip('*').strip()
                        
                        # Clean the name using the cleaning function
                        guest_name = clean_guest_name(guest_name)
                        
                        # If name is still empty, try column 0 (room col sometimes has name)
                        if not guest_name or len(guest_name) < 3:
                            # Check if room column has additional text
                            room_parts = room_cell.split()
                            if len(room_parts) > 1:
                                potential_name = ' '.join(room_parts[1:])
                                guest_name = clean_guest_name(potential_name)
                        
                        # Dates: Arrival usually in column 3, Departure in column 4
                        arrival_date = None
                        departure_date = None
                        
                        date_pattern = r'(\d{2}/\d{2}/\d{2})'
                        
                        # Search through all columns for dates
                        for col_idx, cell in enumerate(row):
                            if cell:
                                cell_str = str(cell).strip()
                                dates = re.findall(date_pattern, cell_str)
                                if len(dates) >= 2:
                                    arrival_date = dates[0]
                                    departure_date = dates[1]
                                    break
                                elif len(dates) == 1:
                                    if arrival_date is None:
                                        arrival_date = dates[0]
                                    elif departure_date is None:
                                        departure_date = dates[0]
                        
                        # Only add if we have a valid name
                        if guest_name and len(guest_name) > 2:
                            guests.append({
                                'room': room_str,
                                'guest_name': guest_name[:60],
                                'arrival_date': arrival_date,
                                'departure_date': departure_date,
                                'source': f'Page {page_num + 1}'
                            })
                        elif arrival_date:  # Fallback
                            guests.append({
                                'room': room_str,
                                'guest_name': f"Guest_{room_str}",
                                'arrival_date': arrival_date,
                                'departure_date': departure_date,
                                'source': f'Page {page_num + 1}'
                            })
    
    # Remove duplicates based on room + arrival date + guest name
    seen = set()
    unique_guests = []
    
    for guest in guests:
        arrival = guest.get('arrival_date', 'unknown')
        name = guest.get('guest_name', '')
        key = f"{guest['room']}_{arrival}_{name}"
        
        if key not in seen:
            seen.add(key)
            unique_guests.append(guest)
    
    return unique_guests


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


def display_guest_extractor(pdf_bytes):
    """
    Main function for Guest Extractor mode
    """
    st.subheader("📇 Guest Name Extractor")
    
    # Detect format
    format_type = detect_pdf_format(pdf_bytes)
    st.info(f"📄 Detected PDF format: **{format_type}**")
    
    with st.spinner("Extracting guest names from PDF..."):
        guests = extract_guests_from_pdf(pdf_bytes)
    
    if not guests:
        st.warning("No guests found in PDF. Please check the file format.")
        st.markdown("""
        **Supported formats:**
        - Night Audit report (with Rate Amt. column)
        - Arrivals report (with Arr. Date/Dep. Date)
        """)
        return
    
    st.success(f"✅ Found {len(guests)} guests")
    
    # Display guests in a table
    guest_data = []
    for guest in guests:
        guest_data.append({
            "Room": guest['room'],
            "Guest Name": guest['guest_name'][:50],
            "Arrival": guest.get('arrival_date', 'N/A'),
            "Departure": guest.get('departure_date', 'N/A'),
            "Source": guest.get('source', 'N/A')
        })
    
    df_guests = pd.DataFrame(guest_data)
    st.dataframe(df_guests, use_container_width=True)

    # Debug expander to see raw data
    with st.expander("🔍 Debug: View Raw Extracted Text (first 2000 chars)"):
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            raw_text = ""
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    raw_text += extracted + "\n"
        st.code(raw_text[:2000], language="text")
    
    # Email creation section
    st.markdown("---")
    st.subheader("📧 Generate Dummy Emails")
    
    # Domain input
    col_domain1, col_domain2 = st.columns([2, 1])
    with col_domain1:
        domain = st.text_input("Email Domain", value="guest.stay.com", 
                               help="Domain to use for email addresses")
    with col_domain2:
        st.markdown("---")
        st.caption(f"Example: `name@{domain}`")
    
    # Select which guests to generate emails for
    st.markdown("**Select guests to generate emails for:**")
    
    select_all = st.checkbox("Select All Guests")
    
    # Use columns for better layout
    selected_guests = []
    cols = st.columns(4)
    for i, guest in enumerate(guests):
        col_idx = i % 4
        with cols[col_idx]:
            checked = st.checkbox(f"{guest['room']}", key=f"guest_{i}", value=select_all)
            if checked:
                selected_guests.append(guest)
    
    if selected_guests:
        st.markdown(f"**{len(selected_guests)} guests selected**")
        
        if st.button("📧 Generate Email Suggestions", type="primary"):
            st.markdown("---")
            st.subheader("📧 Email Suggestions")
            
            all_suggestions = []
            
            for guest in selected_guests:
                suggestions = generate_email_suggestions(guest['guest_name'], guest['room'])
                
                with st.expander(f"Room {guest['room']} - {guest['guest_name'][:40]}", expanded=False):
                    st.markdown(f"**Arrival:** {guest.get('arrival_date', 'N/A')} | **Departure:** {guest.get('departure_date', 'N/A')}")
                    st.markdown("**Email suggestions:**")
                    for suggestion in suggestions[:5]:
                        full_email = f"{suggestion}@{domain}"
                        st.markdown(f"- `{full_email}`")
                        all_suggestions.append({
                            'room': guest['room'],
                            'guest_name': guest['guest_name'],
                            'arrival_date': guest.get('arrival_date', ''),
                            'departure_date': guest.get('departure_date', ''),
                            'email': full_email
                        })
            
            # Export options
            st.markdown("---")
            st.subheader("💾 Export Data")
            
            df_export = pd.DataFrame(all_suggestions)
            
            col_export1, col_export2 = st.columns(2)
            
            with col_export1:
                csv_data = df_export.to_csv(index=False)
                st.download_button(
                    label="📥 Download as CSV",
                    data=csv_data,
                    file_name=f"guest_emails_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            
            with col_export2:
                json_data = df_export.to_json(orient='records', indent=2)
                st.download_button(
                    label="📥 Download as JSON",
                    data=json_data,
                    file_name=f"guest_emails_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json",
                    use_container_width=True
                )
            
            # Preview JSON
            with st.expander("📋 Preview JSON (for API integration)"):
                st.code(json_data, language="json")
    
    else:
        st.info("Select at least one guest to generate emails.")