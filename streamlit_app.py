import streamlit as st
import pdfplumber
import re
from datetime import datetime
import pandas as pd
import json
from io import BytesIO
import base64
import os
import fitz  # PyMuPDF

st.set_page_config(page_title="Rate Discrepancy Scanner", page_icon="🔍", layout="wide")
st.title("🔍 Rate Discrepancy Scanner - Visual Highlighting")

TAX_RATE = 1.134

# Initialize session state
if 'overrides' not in st.session_state:
    st.session_state.overrides = {}
if 'processed_rooms' not in st.session_state:
    st.session_state.processed_rooms = {}
if 'training_data' not in st.session_state:
    st.session_state.training_data = {}
if 'selected_room' not in st.session_state:
    st.session_state.selected_room = None

# ========== FUNCTIONS ==========

def is_valid_room(room_num):
    """
    Check if room number is valid based on property:
    - Floor 04 to 16
    - Room position 01 to 12
    - Must be 4 digits after normalization
    """
    room_str = str(room_num).zfill(4)
    room_int = int(room_str)
    floor = room_int // 100
    position = room_int % 100
    return (4 <= floor <= 16) and (1 <= position <= 12)


def highlight_pdf_boxes(pdf_bytes, fix_rooms_list, manual_rooms_list):
    """
    Draw colored boxes around room numbers in the PDF
    - RED boxes with "FIX" for rooms that need rate changes
    - YELLOW boxes with "CHECK" for rooms that need manual review
    """
    # Open the PDF from bytes
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    # Convert to strings and normalize (pad to 4 digits for matching)
    fix_room_strings = [str(room_num).zfill(4) for room_num in fix_rooms_list]
    manual_room_strings = [str(room_num).zfill(4) for room_num in manual_rooms_list]
    
    # Also keep original formats for matching
    fix_room_variants = {}
    for room in fix_rooms_list:
        room_str = str(room)
        fix_room_variants[room_str] = True
        fix_room_variants[room_str.zfill(4)] = True
        fix_room_variants[room_str.lstrip('0')] = True
    
    manual_room_variants = {}
    for room in manual_rooms_list:
        room_str = str(room)
        manual_room_variants[room_str] = True
        manual_room_variants[room_str.zfill(4)] = True
        manual_room_variants[room_str.lstrip('0')] = True
    
    all_fix_variants = set(fix_room_variants.keys())
    all_manual_variants = set(manual_room_variants.keys())
    
    # Track highlighted rooms
    highlighted_fix = []
    highlighted_manual = []
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        
        # Get all text on the page
        page_text = page.get_text()
        
        # Find all 3-4 digit numbers that could be room numbers
        import re
        potential_rooms = re.findall(r'\b\d{3,4}\b', page_text)
        
        for potential_room in potential_rooms:
            # FIRST: Validate it's a real room number based on property layout
            if not is_valid_room(potential_room):
                continue
            
            # Skip invalid room numbers
            room_int = int(potential_room)
            if room_int == 0 or room_int > 9999:
                continue
            if potential_room.startswith('20') and len(potential_room) == 4:
                continue  # Skip years like 2026
            
            # Check if this room is in our lists
            is_fix = potential_room in all_fix_variants
            is_manual = potential_room in all_manual_variants
            
            if is_fix or is_manual:
                # Find exact position of this room number
                text_instances = page.search_for(potential_room)
                
                for inst in text_instances:
                    if is_fix and potential_room not in highlighted_fix:
                        # RED for fix
                        annot = page.add_rect_annot(inst)
                        annot.set_colors(stroke=(1, 0, 0))
                        annot.set_border(width=2.5)
                        annot.update()
                        
                        # Add "FIX" label above the box
                        label_rect = fitz.Rect(inst.x0, inst.y0 - 14, inst.x0 + 30, inst.y0)
                        page.draw_rect(label_rect, color=(1, 0, 0), fill=(1, 0, 0))
                        page.insert_text(
                            (inst.x0 + 2, inst.y0 - 3), 
                            "FIX", 
                            fontsize=9, 
                            color=(1, 1, 1),
                            fontname="helv"
                        )
                        highlighted_fix.append(potential_room)
                    
                    elif is_manual and potential_room not in highlighted_manual:
                        # YELLOW for manual check
                        annot = page.add_rect_annot(inst)
                        annot.set_colors(stroke=(1, 1, 0))
                        annot.set_border(width=2.5)
                        annot.update()
                        
                        # Add "CHECK" label above the box
                        label_rect = fitz.Rect(inst.x0, inst.y0 - 14, inst.x0 + 45, inst.y0)
                        page.draw_rect(label_rect, color=(1, 1, 0), fill=(1, 1, 0))
                        page.insert_text(
                            (inst.x0 + 2, inst.y0 - 3), 
                            "CHECK", 
                            fontsize=8, 
                            color=(0, 0, 0),
                            fontname="helv"
                        )
                        highlighted_manual.append(potential_room)
    
    # Save the modified PDF
    output_bytes = doc.tobytes()
    doc.close()
    
    return output_bytes

def extract_room_actual_rates(text):
    """
    Extract each room's actual posted rate from the Rate Amt. column (with VND)
    Only includes valid room numbers matching pattern:
    - Floor 04-16, Room 01-12 (e.g., 0401 to 1612)
    """
    rooms = {}
    
    # Pattern: room number, name, then a number with VND (this is the Rate Amt.)
    pattern = r'(\d{3,4})\s+([A-Za-z][^0-9]{10,60}?)\s+.*?(\d{1,3}(?:,\d{3})*)\s+VND'
    
    matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
    
    for room_num, guest_name, rate_str in matches:
        # Pad to 4 digits if needed (e.g., "403" -> "0403")
        room_str = room_num.zfill(4)
        room_int = int(room_str)
        
        # VALID ROOM VALIDATION
        floor = room_int // 100  # First two digits
        position = room_int % 100  # Last two digits
        
        # Valid: floor 4-16, position 1-12
        is_valid_room = (4 <= floor <= 16) and (1 <= position <= 12)
        
        if not is_valid_room:
            continue  # Skip invalid room numbers
        
        # Clean and convert rate
        rate_str_clean = rate_str.replace(',', '')
        try:
            actual_rate = float(rate_str_clean)
            
            # Only add if room not already captured
            if room_str not in rooms:
                rooms[room_str] = {
                    'room': room_str,
                    'guest': guest_name.strip()[:50],
                    'system_rate': actual_rate
                }
        except:
            continue
    
    return rooms

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
        'selected_rate': None,
        'selected_reason': None,
        'monthly_detected': False,
        'flat_rates': [],
        'date_specific_rates': []
    }
    
    # Check for monthly - these will be SKIPPED entirely
    if re.search(r'[\d,]+\s*(?:net)?/?\s*(?:per\s+)?month', comment_text, re.IGNORECASE):
        results['monthly_detected'] = True
        results['selected_rate'] = None
        results['selected_reason'] = "SKIP - Monthly rate (assumed correct)"
        return results
    
    # Date-specific rates
    date_pattern = r'RATE\s*AMOUNT\w*\s*->([\d,]+).*?from\s*(\d{2}-[A-Z]{3}-\d{2})\s*to\s*(\d{2}-[A-Z]{3}-\d{2})'
    matches = re.findall(date_pattern, comment_text, re.IGNORECASE)
    
    for rate_str, start_str, end_str in matches:
        rate = float(rate_str.replace(',', ''))
        try:
            start_date = datetime.strptime(start_str, '%d-%b-%y')
            end_date = datetime.strptime(end_str, '%d-%b-%y')
            
            is_applicable = (start_date <= target_date <= end_date)
            
            results['date_specific_rates'].append({
                'rate': rate,
                'start': start_str,
                'end': end_str,
                'applicable': is_applicable
            })
            
            if is_applicable:
                results['selected_rate'] = rate
                results['selected_reason'] = f"Date-specific: {start_str} to {end_str}"
        except:
            continue
    
    # Flat rates (no date range)
    if results['selected_rate'] is None:
        flat_pattern = r'RATE\s*AMOUNT\w*\s*->([\d,]+)(?:\s|$|\.)'
        flat_matches = re.findall(flat_pattern, comment_text, re.IGNORECASE)
        
        for rate_str in flat_matches:
            rate = float(rate_str.replace(',', ''))
            results['flat_rates'].append(rate)
        
        if results['flat_rates']:
            results['selected_rate'] = results['flat_rates'][0]
            results['selected_reason'] = "Flat rate (no date range)"
    
    if results['selected_rate'] is None:
        results['selected_reason'] = "No rate found"
    
    return results

# ========== SIDEBAR ==========

with st.sidebar:
    st.header("📅 Settings")
    current_date = st.date_input("Today's date", datetime.now())
    
    st.header("⚙️ Tolerance")
    tolerance_percent = st.slider("Rate tolerance (%)", 0.0, 5.0, 1.0, 0.1)
    
    st.header("📁 Upload")
    uploaded_file = st.file_uploader("Upload Night Audit PDF", type="pdf")

# ========== MAIN APP ==========

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
        
        all_rooms_data = []
        
        for room_num, room_data in rooms_actual.items():
            system_rate = room_data['system_rate']
            comment_section_data = debug_extract_comment_section(full_text, room_num)
            
            if comment_section_data:
                comment_text = comment_section_data['comment_body']
            else:
                comment_text = full_text
            
            parse_result = debug_parse_rates(comment_text, target_datetime)
            comment_rate = parse_result['selected_rate']
            
            status = "unknown"
            decision_reason = ""
            what_to_change = ""
            
            if comment_rate is None:
                if parse_result['monthly_detected']:
                    status = "correct"  # Monthly guests are correct - NO HIGHLIGHT
                    decision_reason = "Monthly rate - assumed correct (no action needed)"
                else:
                    status = "manual_check"
                    decision_reason = "No rate found in comments"
            else:
                tolerance = comment_rate * (tolerance_percent / 100)
                
                if abs(comment_rate - system_rate) <= tolerance:
                    status = "correct"
                    decision_reason = f"Rate matches (diff: {abs(comment_rate - system_rate):,.0f})"
                else:
                    expected_net = system_rate * TAX_RATE
                    if abs(comment_rate - expected_net) <= tolerance:
                        status = "correct"
                        decision_reason = f"NET rate properly converts to ++ (comment {comment_rate:,.0f} = system {system_rate:,.0f} × {TAX_RATE})"
                    else:
                        status = "fix"
                        decision_reason = f"Rate mismatch: comment {comment_rate:,.0f} ≠ system {system_rate:,.0f}"
                        what_to_change = f"Change from {system_rate:,.0f} to {comment_rate:,.0f}"
            
            # Check for manual override
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
                'debug_parse_result': parse_result,
                'override_key': override_key
            }
            
            all_rooms_data.append(room_record)
            st.session_state.processed_rooms[room_num] = room_record
    
    # ========== THREE TABS ==========
    
    tab1, tab2, tab3 = st.tabs(["📋 Room List & Debug", "📄 PDF Viewer", "📊 Training Data"])
    
    # TAB 1: Room List & Debug
    with tab1:
        col1, col2 = st.columns([0.4, 0.6])
        
        with col1:
            st.subheader("📋 Rooms")
            
            filter_option = st.radio("Filter:", ["All", "🔴 Need Fix", "🟡 Manual Check", "🟢 Correct"], horizontal=True)
            
            filtered_rooms = all_rooms_data
            if filter_option == "🔴 Need Fix":
                filtered_rooms = [r for r in all_rooms_data if r['status'] == 'fix']
            elif filter_option == "🟡 Manual Check":
                filtered_rooms = [r for r in all_rooms_data if r['status'] == 'manual_check']
            elif filter_option == "🟢 Correct":
                filtered_rooms = [r for r in all_rooms_data if r['status'] == 'correct']
            
            for room in filtered_rooms:
                if room['status'] == 'fix':
                    icon = "🔴"
                elif room['status'] == 'manual_check':
                    icon = "🟡"
                else:
                    icon = "🟢"
                
                button_label = f"{icon} Room {room['room']} - {room['guest'][:20]}"
                if st.button(button_label, key=f"btn_{room['room']}"):
                    st.session_state.selected_room = room['room']
            
            st.markdown("---")
            fix_count = len([r for r in all_rooms_data if r['status'] == 'fix'])
            manual_count = len([r for r in all_rooms_data if r['status'] == 'manual_check'])
            correct_count = len([r for r in all_rooms_data if r['status'] == 'correct'])
            
            st.metric("🔴 Need Fix", fix_count)
            st.metric("🟡 Manual Check", manual_count)
            st.metric("🟢 Correct", correct_count)
        
        with col2:
            if st.session_state.selected_room:
                room_data = next((r for r in all_rooms_data if r['room'] == st.session_state.selected_room), None)
                
                if room_data:
                    st.subheader(f"🔍 Debug: Room {room_data['room']} - {room_data['guest']}")
                    
                    if room_data['status'] == 'fix':
                        st.error("🔴 STATUS: NEEDS FIX")
                    elif room_data['status'] == 'manual_check':
                        st.warning("🟡 STATUS: MANUAL CHECK REQUIRED")
                    else:
                        st.success("🟢 STATUS: CORRECT")
                    
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.metric("System Rate (++)", f"{room_data['system_rate']:,.0f} VND")
                    with col_b:
                        if room_data['comment_rate']:
                            st.metric("Comment Rate", f"{room_data['comment_rate']:,.0f} VND")
                        else:
                            st.metric("Comment Rate", "NOT FOUND")
                    
                    st.info(f"📝 Decision: {room_data['decision_reason']}")
                    
                    if room_data['what_to_change']:
                        st.warning(f"🔧 Action: {room_data['what_to_change']}")
                    
                    st.markdown("---")
                    st.subheader("✏️ Manual Override")
                    
                    col_override1, col_override2, col_override3 = st.columns(3)
                    with col_override1:
                        if st.button("🔴 Mark as NEED FIX"):
                            st.session_state.overrides[room_data['override_key']] = {
                                'status': 'fix',
                                'reason': 'Manually flagged as incorrect'
                            }
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
                    
                    with st.expander("📄 Raw Extracted Comment Text"):
                        st.code(room_data['debug_comment_text'], language="text")
                    
                    with st.expander("🔍 All Rates Found in Comment"):
                        parse_result = room_data['debug_parse_result']
                        
                        if parse_result['date_specific_rates']:
                            st.write("**Date-specific rates:**")
                            for r in parse_result['date_specific_rates']:
                                applicable = "✅ APPLICABLE" if r['applicable'] else "❌ Not applicable"
                                st.write(f"  {r['rate']:,.0f} VND | {r['start']} to {r['end']} - {applicable}")
                        
                        if parse_result['flat_rates']:
                            st.write("**Flat rates found:**")
                            for r in parse_result['flat_rates']:
                                st.write(f"  {r:,.0f} VND")
                        
                        st.write(f"**Selected rate:** {parse_result['selected_rate']:,.0f} VND" if parse_result['selected_rate'] else "**Selected rate:** None")
                        st.write(f"**Reason:** {parse_result['selected_reason']}")
            else:
                st.info("👈 Click on any room from the left panel to see debug information")
    
    # TAB 2: PDF Viewer with Highlighting (PyMuPDF Version)
    with tab2:
        st.subheader("📄 PDF with Automatic Highlighting")
        
        # Get rooms by status - ONLY fix and manual_check get highlighted
        fix_rooms = [r for r in all_rooms_data if r['status'] == 'fix']
        manual_rooms = [r for r in all_rooms_data if r['status'] == 'manual_check']
        
        # Show summary of what will be highlighted
        if fix_rooms:
            st.error(f"🔴 {len(fix_rooms)} room(s) will be highlighted in RED")
            # Normalize to 4-digit display for consistency
            normalized_fix = [str(r['room']).zfill(4) for r in fix_rooms]
            st.markdown(f"**Fix these:** {', '.join(normalized_fix[:15])}")
            if len(fix_rooms) > 15:
                st.caption(f"... and {len(fix_rooms) - 15} more")
        
        if manual_rooms:
            st.warning(f"🟡 {len(manual_rooms)} room(s) will be highlighted in YELLOW")
            normalized_manual = [str(r['room']).zfill(4) for r in manual_rooms]
            st.markdown(f"**Check these:** {', '.join(normalized_manual[:15])}")
        
        if not fix_rooms and not manual_rooms:
            st.success("✅ No discrepancies found — no highlights needed")
        
        st.markdown("---")
        
        # Generate highlighted PDF
        if fix_rooms or manual_rooms:
            with st.spinner("🎨 Drawing highlight boxes on PDF (this may take 10-20 seconds)..."):
                fix_room_numbers = [r['room'] for r in fix_rooms]
                manual_room_numbers = [r['room'] for r in manual_rooms]
                
                try:
                    highlighted_pdf = highlight_pdf_boxes(pdf_bytes, fix_room_numbers, manual_room_numbers)
                    st.success("✅ PDF highlighted successfully!")
                    
                    # Display the highlighted PDF
                    st.pdf(highlighted_pdf, height=700)
                    
                    # Legend
                    st.markdown("""
                    ---
                    **📖 Legend:**
                    - 🔴 **RED BOX** with "FIX" = Room rate needs to be changed
                    - 🟡 **YELLOW BOX** with "CHECK" = Room needs manual review
                    
                    **💡 Tip:** Click on the PDF to zoom in on highlighted areas.
                    """)
                    
                    # Download button for highlighted version
                    st.download_button(
                        label="📥 Download Highlighted PDF (with colored boxes)",
                        data=highlighted_pdf,
                        file_name="highlighted_audit_report.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
                    
                except Exception as e:
                    st.error(f"Highlighting failed: {str(e)}")
                    st.info("Showing original PDF without highlights.")
                    st.pdf(pdf_bytes, height=700)
        else:
            # No highlights needed, just show original
            st.pdf(pdf_bytes, height=700)
            
            st.download_button(
                label="📥 Download PDF",
                data=pdf_bytes,
                file_name="night_audit_report.pdf",
                mime="application/pdf",
                use_container_width=True
            )
    
    # TAB 3: Training Data
    with tab3:
        st.subheader("📊 Training Data Collected")
        
        if st.session_state.training_data:
            st.write(f"Collected {len(st.session_state.training_data)} manual corrections")
            training_list = list(st.session_state.training_data.values())
            if training_list:
                st.json(training_list[-5:])
        else:
            st.info("No training data yet. Use manual override buttons in Tab 1 to build your training set.")