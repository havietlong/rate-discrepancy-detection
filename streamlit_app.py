import streamlit as st
import pdfplumber
import re
from datetime import datetime
import pandas as pd
import json
from io import BytesIO
import os

st.set_page_config(page_title="Rate Discrepancy Scanner", page_icon="🔍", layout="wide")
st.title("🔍 Rate Discrepancy Scanner - Debug & Train")

TAX_RATE = 1.134

# Initialize session state for manual overrides
if 'overrides' not in st.session_state:
    st.session_state.overrides = {}
if 'processed_rooms' not in st.session_state:
    st.session_state.processed_rooms = {}
if 'training_data' not in st.session_state:
    st.session_state.training_data = []

# Sidebar for controls
with st.sidebar:
    st.header("📅 Settings")
    current_date = st.date_input("Today's date", datetime.now())
    
    st.header("⚙️ Tolerance")
    tolerance_percent = st.slider("Rate tolerance (%)", 0.0, 5.0, 1.0, 0.1)
    
    st.header("📊 Training Data")
    if st.button("Export Training Data"):
        if st.session_state.training_data:
            json_str = json.dumps(st.session_state.training_data, indent=2)
            st.download_button("Download JSON", json_str, "training_data.json")
    
    st.header("📁 Upload")
    uploaded_file = st.file_uploader("Upload Night Audit PDF", type="pdf")

def debug_extract_comment_section(text, room_number):
    """Extract and return the exact comment section with boundaries"""
    pattern = rf'({room_number}\s+[^\n]+?\n)(.*?)(?=\n\d{{3,4}}\s+|\Z)'
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    
    if match:
        return {
            'header': match.group(1),
            'comment_body': match.group(2)[:1000],
            'full_section': match.group(0)
        }
    return None

def debug_parse_rates(comment_text, target_date):
    """Return all rates found, not just the best match"""
    results = {
        'all_rates_found': [],
        'selected_rate': None,
        'selected_reason': None,
        'monthly_detected': False,
        'flat_rates': [],
        'date_specific_rates': []
    }
    
    # Check for monthly
    if re.search(r'[\d,]+\s*(?:net)?/?\s*(?:per\s+)?month', comment_text, re.IGNORECASE):
        results['monthly_detected'] = True
        results['selected_rate'] = None
        results['selected_reason'] = "SKIP - Monthly rate (assumed correct)"
        return results
    
    # UPDATED PATTERN: Handles RATE AMOUNT, RATEAMOUNT, RATEAMOUNTCH, etc.
    date_pattern = r'RATE\s*AMOUNT\w*\s*->([\d,]+).*?from\s*(\d{2}-[A-Z]{3}-\d{2})\s*to\s*(\d{2}-[A-Z]{3}-\d{2})'
    matches = re.findall(date_pattern, comment_text, re.IGNORECASE)
    
    st.write(f"DEBUG: Found {len(matches)} date-specific rate matches")  # Temporary debug
    
    for rate_str, start_str, end_str in matches:
        rate = float(rate_str.replace(',', ''))
        try:
            start_date = datetime.strptime(start_str, '%d-%b-%y')
            end_date = datetime.strptime(end_str, '%d-%b-%y')
            nights = (end_date - start_date).days
            
            is_applicable = (start_date <= target_date <= end_date)
            
            results['date_specific_rates'].append({
                'rate': rate,
                'start': start_str,
                'end': end_str,
                'nights': nights,
                'applicable': is_applicable
            })
            
            if is_applicable:
                results['selected_rate'] = rate
                results['selected_reason'] = f"Date-specific: {start_str} to {end_str}"
        except Exception as e:
            st.write(f"DEBUG: Date parse error: {e}")
            continue
    
    # Find flat rates (no date range) - UPDATED pattern
    flat_pattern = r'RATE\s*AMOUNT\w*\s*->([\d,]+)(?:\s|$|\.)'
    flat_matches = re.findall(flat_pattern, comment_text, re.IGNORECASE)
    
    for rate_str in flat_matches:
        rate = float(rate_str.replace(',', ''))
        results['flat_rates'].append(rate)
    
    # If no date-specific rate found, use first flat rate
    if results['selected_rate'] is None and results['flat_rates']:
        results['selected_rate'] = results['flat_rates'][0]
        results['selected_reason'] = "Flat rate (no date range)"
    
    if results['selected_rate'] is None:
        results['selected_reason'] = "No rate found"
    
    return results

def extract_room_actual_rates(text):
    """Extract each room's actual posted rate"""
    rooms = {}
    
    # Multiple patterns to handle different formats
    patterns = [
        r'(\d{3,4})\s+([A-Za-z][^0-9]{5,60}?)\s+.*?([\d,]+)\s+VND',
        r'(\d{3,4})\s+([A-Za-z][^,]+?)\s+\d+\s+\d+\s+\d+\s+\S+\s+\d+(?:,\d{3})*\s+([\d,]+)\s+VND',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
        for room_num, guest_name, rate_str in matches:
            rate_str_clean = re.sub(r'[^\d]', '', rate_str)
            if rate_str_clean:
                try:
                    actual_rate = float(rate_str_clean)
                    if room_num not in rooms:  # First match wins
                        rooms[room_num] = {
                            'room': room_num,
                            'guest': guest_name.strip()[:50],
                            'system_rate': actual_rate
                        }
                except:
                    continue
    
    return rooms

if uploaded_file:
    pdf_bytes = uploaded_file.getvalue()
    
    with st.spinner("Processing PDF..."):
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            full_text = ""
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    full_text += extracted + "\n"
        
        rooms_actual = extract_room_actual_rates(full_text)
        target_datetime = datetime(current_date.year, current_date.month, current_date.day)
        
        # Process all rooms
        all_rooms_data = []
        
        for room_num, room_data in rooms_actual.items():
            system_rate = room_data['system_rate']
            comment_section_data = debug_extract_comment_section(full_text, room_num)
            
            if comment_section_data:
                comment_text = comment_section_data['comment_body']
                header_text = comment_section_data['header']
            else:
                comment_text = full_text
                header_text = "No specific comment section found"
            
            # Parse rates with debug info
            parse_result = debug_parse_rates(comment_text, target_datetime)
            
            comment_rate = parse_result['selected_rate']
            
            # Determine status
            status = "unknown"
            decision_reason = ""
            what_to_change = ""
            
            if comment_rate is None:
                if parse_result['monthly_detected']:
                    status = "correct"
                    decision_reason = "Monthly rate - assumed correct"
                else:
                    status = "manual_check"
                    decision_reason = "No rate found in comments"
            else:
                # Simple comparison first
                tolerance = comment_rate * (tolerance_percent / 100)
                
                if abs(comment_rate - system_rate) <= tolerance:
                    status = "correct"
                    decision_reason = f"Rate matches (diff: {abs(comment_rate - system_rate):,.0f} within {tolerance_percent}% tolerance)"
                else:
                    # Check if NET/++ conversion
                    expected_net = system_rate * TAX_RATE
                    if abs(comment_rate - expected_net) <= tolerance:
                        status = "correct"
                        decision_reason = f"NET rate properly converts to ++ (comment {comment_rate:,.0f} ≈ system {system_rate:,.0f} × {TAX_RATE})"
                    else:
                        status = "fix"
                        decision_reason = f"Rate mismatch: comment {comment_rate:,.0f} ≠ system {system_rate:,.0f}"
                        what_to_change = f"Change from {system_rate:,.0f} to {comment_rate:,.0f}"
            
            # Check for manual override from previous session
            override_key = f"{room_num}_{current_date}"
            if override_key in st.session_state.overrides:
                status = st.session_state.overrides[override_key]['status']
                decision_reason = f"MANUAL OVERRIDE: {st.session_state.overrides[override_key]['reason']}"
            
            room_record = {
                'room': room_num,
                'guest': room_data['guest'],
                'system_rate': system_rate,
                'comment_rate': comment_rate,
                'status': status,
                'decision_reason': decision_reason,
                'what_to_change': what_to_change,
                'debug_comment_text': comment_text[:2000],
                'debug_header': header_text[:500],
                'debug_parse_result': parse_result,
                'override_key': override_key
            }
            
            all_rooms_data.append(room_record)
            st.session_state.processed_rooms[room_num] = room_record
    
    # ========== DISPLAY TWO-PANEL INTERFACE ==========
    
    col1, col2 = st.columns([0.4, 0.6])
    
    # LEFT PANEL: Room list
    with col1:
        st.subheader("📋 Rooms")
        
        # Filter options
        filter_option = st.radio("Filter:", ["All", "🔴 Need Fix", "🟡 Manual Check", "🟢 Correct"], horizontal=True)
        
        filtered_rooms = all_rooms_data
        if filter_option == "🔴 Need Fix":
            filtered_rooms = [r for r in all_rooms_data if r['status'] == 'fix']
        elif filter_option == "🟡 Manual Check":
            filtered_rooms = [r for r in all_rooms_data if r['status'] == 'manual_check']
        elif filter_option == "🟢 Correct":
            filtered_rooms = [r for r in all_rooms_data if r['status'] == 'correct']
        
        # Display room buttons
        for room in filtered_rooms:
            if room['status'] == 'fix':
                color = "#ffebee"
                icon = "🔴"
            elif room['status'] == 'manual_check':
                color = "#fff3e0"
                icon = "🟡"
            else:
                color = "#e8f5e9"
                icon = "🟢"
            
            button_label = f"{icon} Room {room['room']} - {room['guest'][:20]}"
            if st.button(button_label, key=f"btn_{room['room']}"):
                st.session_state.selected_room = room['room']
        
        # Summary stats
        st.markdown("---")
        fix_count = len([r for r in all_rooms_data if r['status'] == 'fix'])
        manual_count = len([r for r in all_rooms_data if r['status'] == 'manual_check'])
        correct_count = len([r for r in all_rooms_data if r['status'] == 'correct'])
        
        st.metric("🔴 Need Fix", fix_count)
        st.metric("🟡 Manual Check", manual_count)
        st.metric("🟢 Correct", correct_count)
    
    # RIGHT PANEL: Debug view for selected room
    with col2:
        if 'selected_room' in st.session_state:
            selected_room_num = st.session_state.selected_room
            room_data = next((r for r in all_rooms_data if r['room'] == selected_room_num), None)
            
            if room_data:
                st.subheader(f"🔍 Debug: Room {room_data['room']} - {room_data['guest']}")
                
                # Status badge
                if room_data['status'] == 'fix':
                    st.error(f"🔴 STATUS: NEEDS FIX")
                elif room_data['status'] == 'manual_check':
                    st.warning(f"🟡 STATUS: MANUAL CHECK REQUIRED")
                else:
                    st.success(f"🟢 STATUS: CORRECT")
                
                # Rate comparison
                col_a, col_b = st.columns(2)
                with col_a:
                    st.metric("System Rate (++)", f"{room_data['system_rate']:,.0f} VND")
                with col_b:
                    if room_data['comment_rate']:
                        st.metric("Comment Rate", f"{room_data['comment_rate']:,.0f} VND")
                    else:
                        st.metric("Comment Rate", "NOT FOUND")
                
                # Decision reason
                st.info(f"📝 Decision: {room_data['decision_reason']}")
                
                if room_data['what_to_change']:
                    st.warning(f"🔧 Action: {room_data['what_to_change']}")
                
                # Manual override
                st.markdown("---")
                st.subheader("✏️ Manual Override")
                
                col_override1, col_override2, col_override3 = st.columns(3)
                with col_override1:
                    if st.button("🔴 Mark as NEED FIX"):
                        st.session_state.overrides[room_data['override_key']] = {
                            'status': 'fix',
                            'reason': 'Manually flagged as incorrect'
                        }
                        st.session_state.training_data.append({
                            'room': room_data['room'],
                            'system_rate': room_data['system_rate'],
                            'comment_rate': room_data['comment_rate'],
                            'original_decision': room_data['status'],
                            'corrected_decision': 'fix',
                            'timestamp': str(datetime.now())
                        })
                        st.rerun()
                
                with col_override2:
                    if st.button("🟡 Mark as MANUAL CHECK"):
                        st.session_state.overrides[room_data['override_key']] = {
                            'status': 'manual_check',
                            'reason': 'Manually marked for review'
                        }
                        st.rerun()
                
                with col_override3:
                    if st.button("🟢 Mark as CORRECT"):
                        st.session_state.overrides[room_data['override_key']] = {
                            'status': 'correct',
                            'reason': 'Manually verified as correct'
                        }
                        st.rerun()
                
                # Debug: Raw extracted text
                with st.expander("📄 Raw Extracted Comment Text"):
                    st.code(room_data['debug_comment_text'], language="text")
                
                # Debug: All rates found
                with st.expander("🔍 All Rates Found in Comment"):
                    parse_result = room_data['debug_parse_result']
                    
                    if parse_result['date_specific_rates']:
                        st.write("**Date-specific rates:**")
                        for r in parse_result['date_specific_rates']:
                            applicable = "✅ APPLICABLE" if r['applicable'] else "❌ Not applicable"
                            st.write(f"  {r['rate']:,.0f} VND | {r['start']} to {r['end']} ({r['nights']} nights) - {applicable}")
                    
                    if parse_result['flat_rates']:
                        st.write("**Flat rates found:**")
                        for r in parse_result['flat_rates']:
                            st.write(f"  {r:,.0f} VND")
                    
                    st.write(f"**Selected rate:** {parse_result['selected_rate']:,.0f} VND" if parse_result['selected_rate'] else "**Selected rate:** None")
                    st.write(f"**Reason:** {parse_result['selected_reason']}")
        else:
            st.info("👈 Click on any room from the left panel to see debug information")

# Show training data summary
with st.expander("📊 Training Data Collected"):
    if st.session_state.training_data:
        st.write(f"Collected {len(st.session_state.training_data)} manual corrections")
        st.json(st.session_state.training_data[-5:])  # Show last 5
    else:
        st.write("No training data yet. Use manual overrides to build training set.")