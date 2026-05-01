import streamlit as st
import pdfplumber
import re
from datetime import datetime
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="Rate Discrepancy Scanner", page_icon="🔍")
st.title("🔍 Rate Discrepancy Scanner - Find & Fix")

TAX_RATE = 1.134

st.markdown("### 📅 Select today's date")
current_date = st.date_input("Current date (for rate comparison)", datetime.now())

uploaded_file = st.file_uploader("📄 Upload Night Audit PDF", type="pdf")

def parse_rate_for_date(text, target_date):
    """
    Find the applicable rate for target_date.
    Returns: (rate_value, rate_source_description)
    """
    
    # Skip monthly rates
    if re.search(r'[\d,]+\s*(?:net)?/?\s*(?:per\s+)?month', text, re.IGNORECASE):
        return None, "SKIP - Monthly rate"
    
    # Case 1: Date-specific rates
    date_pattern = r'RATE\s*AMOUNTH?\s*->([\d,]+).*?from\s*(\d{2}-[A-Z]{3}-\d{2})\s*to\s*(\d{2}-[A-Z]{3}-\d{2})'
    matches = re.findall(date_pattern, text, re.IGNORECASE)
    
    for rate_str, start_str, end_str in matches:
        rate = float(rate_str.replace(',', ''))
        try:
            start_date = datetime.strptime(start_str, '%d-%b-%y')
            end_date = datetime.strptime(end_str, '%d-%b-%y')
            if start_date <= target_date <= end_date:
                return rate, f"{start_str} to {end_str}"
        except:
            continue
    
    # Case 2: Flat rate
    flat_pattern = r'RATE\s*AMOUNTH?\s*->([\d,]+)(?:\s|$|\.)'
    flat_match = re.search(flat_pattern, text, re.IGNORECASE)
    if flat_match:
        rate = float(flat_match.group(1).replace(',', ''))
        return rate, "Flat rate"
    
    return None, "No rate found"

def extract_room_actual_rates(text):
    rooms = {}
    
    # Updated pattern to handle more variations
    pattern = r'(\d{3,4})\s+([A-Za-z][^0-9]{5,60}?)\s+.*?([\d,]+)\s+VND'
    matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
    
    for room_num, guest_name, rate_str in matches:
        # Clean up the rate
        rate_str_clean = re.sub(r'[^\d,]', '', rate_str)
        if rate_str_clean:
            try:
                actual_rate = float(rate_str_clean.replace(',', ''))
                rooms[room_num] = {
                    'room': room_num,
                    'guest': guest_name.strip()[:40],
                    'system_rate': actual_rate
                }
            except:
                continue
    
    return rooms

def get_comment_section_for_room(text, room_number):
    pattern = rf'{room_number}\s+[^\n]+\n(.*?)(?=\n\d{{3,4}}\s+|\Z)'
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(0)
    return text

if uploaded_file:
    pdf_bytes = uploaded_file.getvalue()
    
    with st.spinner(f"Scanning for {current_date.strftime('%B %d, %Y')}..."):
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            full_text = ""
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    full_text += extracted + "\n"
        
        rooms_actual = extract_room_actual_rates(full_text)
        target_datetime = datetime(current_date.year, current_date.month, current_date.day)
        
        # Three result categories
        fix_these = []      # Red - need to change rate
        manual_check = []   # Yellow - need manual investigation
        correct = []        # Green - no action needed
        
        for room_num, room_data in rooms_actual.items():
            system_rate = room_data['system_rate']
            comment_section = get_comment_section_for_room(full_text, room_num)
            comment_rate, rate_source = parse_rate_for_date(comment_section, target_datetime)
            
            # Case: No comment rate found
            if comment_rate is None:
                if "monthly" in rate_source.lower():
                    correct.append({
                        'room': room_num,
                        'guest': room_data['guest'],
                        'system_rate': system_rate,
                        'comment_rate': 'Monthly rate',
                        'action': '✅ NO ACTION (Monthly)'
                    })
                else:
                    manual_check.append({
                        'room': room_num,
                        'guest': room_data['guest'],
                        'system_rate': system_rate,
                        'comment_rate': 'NOT FOUND',
                        'reason': 'No rate found in comments',
                        'action': '🔍 MANUAL CHECK'
                    })
                continue
            
            # SIMPLE COMPARISON - No net/++ detection, just direct comparison
            # Because in your example, comment rate should match system rate directly
            
            tolerance = comment_rate * 0.01  # 1% tolerance for rounding
            
            if abs(comment_rate - system_rate) <= tolerance:
                correct.append({
                    'room': room_num,
                    'guest': room_data['guest'],
                    'system_rate': system_rate,
                    'comment_rate': comment_rate,
                    'rate_period': rate_source,
                    'action': '✅ CORRECT'
                })
            else:
                # Check if comment might be NET (higher than system)
                # NET rate should be about 13.4% higher than system
                expected_net = system_rate * TAX_RATE
                
                if abs(comment_rate - expected_net) <= tolerance:
                    # Comment is NET, system is ++ - this is actually correct
                    correct.append({
                        'room': room_num,
                        'guest': room_data['guest'],
                        'system_rate': system_rate,
                        'comment_rate': comment_rate,
                        'rate_period': rate_source,
                        'action': '✅ CORRECT (NET vs ++)'
                    })
                else:
                    # Real discrepancy
                    fix_these.append({
                        'room': room_num,
                        'guest': room_data['guest'],
                        'system_rate': system_rate,
                        'comment_rate': comment_rate,
                        'rate_period': rate_source,
                        'what_to_change': f"Change from {system_rate:,.0f} to {comment_rate:,.0f}",
                        'reason': f"Comment rate {comment_rate:,.0f} does not match system rate {system_rate:,.0f}"
                    })
        
        # ========== DISPLAY RESULTS ==========
        
        st.markdown("---")
        
        # SECTION 1: FIX THESE (RED)
        if fix_these:
            st.error(f"🔴 {len(fix_these)} ROOM(S) NEED RATE CHANGE")
            st.markdown("**Go to your PMS and change these rooms now:**")
            
            for item in fix_these:
                st.markdown(f"""
                <div style='background-color:#ffebee; padding:12px; border-radius:8px; margin:8px 0; border-left:4px solid #d32f2f;'>
                <b>🏨 Room {item['room']}</b> - {item['guest']}<br>
                📍 Current system rate: <b>{item['system_rate']:,.0f} VND</b><br>
                ✏️ Comment rate: {item['comment_rate']:,.0f} VND ({item['rate_period']})<br>
                🔧 <b>Action: {item['what_to_change']}</b><br>
                📝 Reason: {item['reason']}
                </div>
                """, unsafe_allow_html=True)
            
            # Copy-paste list
            fix_room_numbers = [str(item['room']) for item in fix_these]
            st.code(f"Rooms to fix (copy this): {', '.join(fix_room_numbers)}", language="text")
        
        # SECTION 2: MANUAL CHECK (YELLOW)
        if manual_check:
            st.warning(f"🟡 {len(manual_check)} ROOM(S) NEED MANUAL CHECK")
            
            df_manual = pd.DataFrame(manual_check)
            df_manual['system_rate'] = df_manual['system_rate'].apply(lambda x: f"{x:,.0f} VND")
            st.dataframe(df_manual[['room', 'guest', 'system_rate', 'reason', 'action']])
        
        # SECTION 3: CORRECT (GREEN)
        if correct:
            with st.expander(f"🟢 {len(correct)} CORRECT ROOMS (no action needed)"):
                df_correct = pd.DataFrame(correct)
                df_correct['system_rate'] = df_correct['system_rate'].apply(lambda x: f"{x:,.0f} VND")
                df_correct['comment_rate'] = df_correct['comment_rate'].apply(lambda x: f"{x:,.0f} VND" if isinstance(x, (int, float)) else x)
                st.dataframe(df_correct[['room', 'guest', 'system_rate', 'comment_rate', 'action']])
        
        # FINAL SUMMARY
        st.markdown("---")
        st.subheader("📋 Summary")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🔴 Need Fix", len(fix_these))
        with col2:
            st.metric("🟡 Manual Check", len(manual_check))
        with col3:
            st.metric("🟢 Correct", len(correct))