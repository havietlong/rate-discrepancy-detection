"""
Police Report to XML Converter
Extracts guest data from police report PDF and converts to KHAI_BAO_TAM_TRU XML format
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

def display_pdf_preview(pdf_bytes, height=400):
    """Display PDF preview"""
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="{height}" style="border: none;"></iframe>',
        unsafe_allow_html=True
    )

def extract_guests_from_police_report(pdf_bytes, debug=False):
    """
    Extract guest data from police report PDF
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
            
            # Initialize passport and gender
            passport = None
            gender = None
            
            # Check next 3 lines for passport and gender
            if debug:
                debug_lines.append(f"  Looking ahead 3 lines for passport and gender:")
            
            for offset in range(1, 4):
                if i + offset < len(lines):
                    next_line = lines[i + offset].strip()
                    
                    if debug:
                        debug_lines.append(f"    Line {i+offset}: '{next_line}'")
                    
                    # Check for passport line (contains PAS or RS)
                    if 'PAS' in next_line:
                        passport_match = re.search(r'PAS\s*([A-Z0-9]{6,10})', next_line, re.IGNORECASE)
                        if passport_match:
                            passport = passport_match.group(1)
                            if debug:
                                debug_lines.append(f"    ✅ Found passport: {passport}")
                        else:
                            num_match = re.search(r'PAS\s*([A-Z0-9]{5,10})', next_line, re.IGNORECASE)
                            if num_match:
                                passport = num_match.group(1)
                                if debug:
                                    debug_lines.append(f"    ✅ Found passport (implicit): {passport}")
                    
                    if not passport and 'RS' in next_line:
                        if debug:
                            debug_lines.append(f"    ℹ️ Vietnamese guest (RS) - no passport number")
                    
                    # Look for gender - can be on same line as country description
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
                        # Check for single M or F on its own line
                        gender_single = re.match(r'^\s*([MF])\s*$', next_line)
                        if gender_single:
                            gender = gender_single.group(1)
                            if debug:
                                debug_lines.append(f"    ✅ Found gender (single): {gender}")
                        else:
                            # Look for M or F followed by any text
                            gender_any = re.search(r'\b([MF])\s+\w+', next_line)
                            if gender_any:
                                gender = gender_any.group(1)
                                if debug:
                                    debug_lines.append(f"    ✅ Found gender (with text): {gender}")
            
            if not passport and debug:
                debug_lines.append(f"  ❌ No passport found in next 3 lines")
            if not gender and debug:
                debug_lines.append(f"  ❌ No gender found in next 3 lines")
            
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
                guest_entry = {
                    'room': room_num,
                    'name': guest_name,
                    'arrival_date': arrival_date,
                    'departure_date': departure_date,
                    'nationality': nationality,
                    'passport': passport,
                    'dob': dob,
                    'gender': gender or 'Unknown'
                }
                guests.append(guest_entry)
                guest_counter += 1
                if debug:
                    debug_lines.append(f"  ✅ Added guest #{guest_counter}: {guest_name} (Room {room_num})")
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
        col_d1, col_d2, col_d3, col_d4 = st.columns(4)
        with col_d1:
            st.metric("Total Guests Found", len(guests))
        with col_d2:
            found_passport = sum(1 for g in guests if g.get('passport'))
            st.metric("Has Passport", found_passport)
        with col_d3:
            found_gender = sum(1 for g in guests if g.get('gender') != 'Unknown')
            st.metric("Has Gender", found_gender)
        with col_d4:
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
    """Generate KHAI_BAO_TAM_TRU XML"""
    root = ET.Element("KHAI_BAO_TAM_TRU")
    
    # Add hotel info
    if hotel_name:
        hotel_elem = ET.SubElement(root, "THONG_TIN_KHACH_SAN")
        hotel_elem.text = hotel_name
    
    # Add guest entries
    for i, guest in enumerate(guests, 1):
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


def display_police_report_converter(pdf_bytes):
    """Main function for Police Report to XML Converter with Tabs"""
    st.subheader("📄 Police Report to KHAI_BAO_TAM_TRU XML")
    
    # Debug toggle
    debug_mode = st.checkbox("🔍 Enable Debug Mode", value=False, help="Shows detailed extraction process")
    
    # Show PDF preview
    with st.expander("📄 View Original PDF", expanded=False):
        display_pdf_preview(pdf_bytes, height=400)
    
    
    
    # Extract data
    with st.spinner("Extracting guest data from PDF..."):
        guests = extract_guests_from_police_report(pdf_bytes, debug=debug_mode)
    
    if not guests:
        st.warning("No guest data found in the PDF. Please check the format.")
        return
    
    # ========== THREE TABS ==========
    tab1, tab2, tab3 = st.tabs(["📋 Guest List", "✏️ Edit Guest Data", "🏨 Hotel Overview"])
    
    # ========== TAB 1: Guest List ==========
    with tab1:
        st.subheader("📋 All Extracted Guests")
        st.caption(f"Total: {len(guests)} guests")
        
        # Prepare data for display
        guest_data = []
        for idx, guest in enumerate(guests):
            guest_data.append({
                "#": idx + 1,
                "Room": guest.get('room', ''),
                "Guest Name": guest.get('name', '')[:50],
                "Arrival": guest.get('arrival_date', 'N/A'),
                "Departure": guest.get('departure_date', 'N/A'),
                "Passport": guest.get('passport', 'N/A'),
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
        
        # ===== XML PREVIEW =====
        st.markdown("---")
        st.markdown("### 📄 XML Preview")
        st.caption("Preview of the first 3 guests in XML format")
        
        # Show XML preview for first 3 guests
        preview_guests = guests[:3]
        preview_xml = generate_tam_tru_xml(preview_guests, "Novotel Suites Hanoi", "5 Duy Tan, Cau Giay District, Hanoi, Vietnam")
        st.code(preview_xml, language="xml")
        
        # Download full XML
        if st.button("📥 Download Full XML", use_container_width=True):
            full_xml = generate_tam_tru_xml(guests, "Novotel Suites Hanoi", "5 Duy Tan, Cau Giay District, Hanoi, Vietnam")
            st.download_button(
                label="📥 Download XML",
                data=full_xml,
                file_name=f"KHAI_BAO_TAM_TRU_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml",
                mime="application/xml",
                use_container_width=True
            )
    # ========== TAB 2: Edit Guest Data ==========
    with tab2:
        st.subheader("✏️ Edit Guest Data")
        st.caption("Make corrections to guest information below before generating XML.")
        
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
                    passport = st.text_input(f"Passport {i+1}", value=guest.get('passport', ''))
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
                
                edited_guests.append({
                    'room': room,
                    'name': name,
                    'arrival_date': arrival,
                    'departure_date': departure,
                    'passport': passport,
                    'dob': dob,
                    'nationality': nationality_val,
                    'gender': gender
                })
        
        # Hotel info
        st.markdown("---")
        st.markdown("### 🏨 Hotel Information")
        col_h1, col_h2 = st.columns(2)
        with col_h1:
            hotel_name = st.text_input("Hotel Name", value="Novotel Suites Hanoi")
        with col_h2:
            hotel_address = st.text_input("Hotel Address", value="5 Duy Tan, Cau Giay District, Hanoi, Vietnam")
        
        # Generate XML
        st.markdown("---")
        if st.button("📄 Generate KHAI_BAO_TAM_TRU XML", type="primary", use_container_width=True):
            with st.spinner("Generating XML..."):
                final_guests = edited_guests if edited_guests else guests
                xml_output = generate_tam_tru_xml(final_guests, hotel_name, hotel_address)
                
                st.markdown("### 📄 Generated XML")
                st.code(xml_output, language="xml")
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.download_button(
                        label="📥 Download XML",
                        data=xml_output,
                        file_name=f"KHAI_BAO_TAM_TRU_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml",
                        mime="application/xml",
                        use_container_width=True
                    )
                with col_d2:
                    json_output = json.dumps(final_guests, indent=2, default=str)
                    st.download_button(
                        label="📥 Download JSON",
                        data=json_output,
                        file_name=f"guest_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json",
                        use_container_width=True
                    )
    
    # ========== TAB 3: Hotel Overview ==========
    with tab3:
        display_hotel_overview_tab(guests)

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
    import streamlit as st
    
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