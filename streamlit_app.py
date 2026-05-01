import streamlit as st
import pdfplumber
import re
from datetime import datetime
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="Rate Discrepancy Scanner", page_icon="🔍")
st.title("🔍 Rate Discrepancy Scanner - Find & Fix")

TAX_RATE = 1.134  # 13.4% tax (adjust as needed)

st.markdown("### 📅 Select today's date")
current_date = st.date_input("Current date (for rate comparison)", datetime.now())

uploaded_file = st.file_uploader("📄 Upload Night Audit PDF", type="pdf")

def detect_rate_type_in_comment(comment_text):
    """
    Auto-detect if comment mentions net or ++
    Returns: 'net', 'pp', or None
    """
    comment_lower = comment_text.lower()
    
    # Check for net indicators
    net_patterns = [r'\bnet\b', r'nett', r'after tax', r'inclusive', r'inc\.? tax']
    for pattern in net_patterns:
        if re.search(pattern, comment_lower):
            return 'net'
    
    # Check for ++ indicators
    pp_patterns = [r'\+\+', r'exclusive', r'excl\.? tax', r'before tax', r'plus tax']
    for pattern in pp_patterns:
        if re.search(pattern, comment_lower):
            return 'pp'
    
    return None  # Will determine by comparing values

def determine_rate_type_by_comparison(comment_rate, system_rate):
    """
    If comment doesn't explicitly say net or ++,
    determine by comparing values:
    - If comment_rate > system_rate → likely net
    - If comment_rate ≈ system_rate → likely ++
    """
    if comment_rate > system_rate * 1.05:  # More than 5% higher
        return 'net'
    else:
        return 'pp'

def parse_rate_for_date(text, target_date):
    """
    Find the applicable rate for target_date.
    Returns: (rate_value, rate_source_description)
    """
    
    # Skip monthly rates
    monthly_pattern = r'[\d,]+\s*(?:net)?/?\s*(?:per\s+)?month'
    if re.search(monthly_pattern, text, re.IGNORECASE):
        return None, "SKIP - Monthly rate"
    
    # CASE 1: Date-specific rates
    date_pattern = r'RATE\s*AMOUNTH?\s*->([\d,]+).*?from\s*(\d{2}-[A-Z]{3}-\d{2})\s*to\s*(\d{2}-[A-Z]{3}-\d{2})'
    matches = re.findall(date_pattern, text, re.IGNORECASE)
    
    for rate_str, start_str, end_str in matches:
        rate = float(rate_str.replace(',', ''))
        try:
            start_date = datetime.strptime(start_str, '%d-%b-%y')
            end_date = datetime.strptime(end_str, '%d-%b-%y')
            if start_date <= target_date <= end_date:
                return rate, f"Date-specific: {start_str} to {end_str}"
        except:
            continue
    
    # CASE 2: Flat rate
    flat_pattern = r'RATE\s*AMOUNTH?\s*->([\d,]+)(?:\s|$|\.)'
    flat_match = re.search(flat_pattern, text, re.IGNORECASE)
    if flat_match:
        rate = float(flat_match.group(1).replace(',', ''))
        return rate, "Flat rate"
    
    return None, "No rate found"

def extract_room_actual_rates(text):
    """Extract each room's actual posted rate from system table"""
    rooms = {}
    
    # Pattern: "0403    Zhou, Xinfei ... 2,285,937 VND"
    pattern = r'(\d{3,4})\s+([A-Za-z][^0-9]{5,60}?)\s+\d+\s+\d+\s+\d+\s+\S+\s+\d+(?:,\d{3})*\s+([\d,]+)\s+VND'
    
    matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
    
    for room_num, guest_name, rate_str in matches:
        actual_rate = float(rate_str.replace(',', ''))
        rooms[room_num] = {
            'room': room_num,
            'guest': guest_name.strip()[:35],
            'system_rate': actual_rate
        }
    
    return rooms

def get_comment_section_for_room(text, room_number):
    """Extract the comment section for a specific room"""
    pattern = rf'{room_number}\s+[^\n]+\n(.*?)(?=\n\d{{3,4}}\s+|\Z)'
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(0)
    return text

if uploaded_file:
    pdf_bytes = uploaded_file.getvalue()
    
    with st.spinner(f"Scanning for discrepancies based on {current_date.strftime('%B %d, %Y')}..."):
        # Extract text from PDF
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            full_text = ""
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    full_text += extracted + "\n"
        
        # Get actual rates from system
        rooms_actual = extract_room_actual_rates(full_text)
        
        target_datetime = datetime(current_date.year, current_date.month, current_date.day)
        
        # Results containers
        discrepancies = []
        skipped_monthly = []
        no_rate_found = []
        
        for room_num, room_data in rooms_actual.items():
            system_rate = room_data['system_rate']
            
            # Get comment section for this room
            comment_section = get_comment_section_for_room(full_text, room_num)
            
            # Find comment rate
            comment_rate, rate_source = parse_rate_for_date(comment_section, target_datetime)
            
            if comment_rate is None:
                if "monthly" in rate_source.lower():
                    skipped_monthly.append({
                        'room': room_num,
                        'guest': room_data['guest'],
                        'system_rate': system_rate,
                    })
                else:
                    no_rate_found.append({
                        'room': room_num,
                        'guest': room_data['guest'],
                        'system_rate': system_rate,
                    })
                continue
            
            # Detect comment rate type
            comment_type = detect_rate_type_in_comment(comment_section)
            
            # If still unknown, determine by comparison
            if comment_type is None:
                comment_type = determine_rate_type_by_comparison(comment_rate, system_rate)
            
            # COMPARISON LOGIC
            is_discrepancy = False
            expected_rate = None
            explanation = ""
            
            if comment_type == 'pp':
                # Comment is ++, should EQUAL system rate
                tolerance = comment_rate * 0.01  # 1% tolerance
                if abs(comment_rate - system_rate) > tolerance:
                    is_discrepancy = True
                    expected_rate = comment_rate
                    explanation = f"Comment says ++ {comment_rate:,.0f} but system shows {system_rate:,.0f} (should be equal)"
                else:
                    explanation = f"✅ ++ rate matches: {comment_rate:,.0f}"
            
            else:  # 'net'
                # Comment is NET, should be HIGHER than system (since net includes tax)
                if comment_rate <= system_rate:
                    is_discrepancy = True
                    expected_rate = comment_rate  # This is net, but system needs to be adjusted?
                    explanation = f"⚠️ Comment NET {comment_rate:,.0f} is NOT higher than system ++ {system_rate:,.0f} (net should include tax)"
                else:
                    # Net is higher - this is normal, but we can still check if it matches expected tax calculation
                    expected_pp = comment_rate / TAX_RATE
                    tolerance = expected_pp * 0.02  # 2% tolerance
                    if abs(expected_pp - system_rate) > tolerance:
                        is_discrepancy = True
                        explanation = f"Comment NET {comment_rate:,.0f} should be ++ {expected_pp:,.0f} after tax, but system shows {system_rate:,.0f}"
                    else:
                        explanation = f"✅ NET rate {comment_rate:,.0f} correctly converts to ++ {system_rate:,.0f}"
            
            if is_discrepancy:
                discrepancies.append({
                    'room': room_num,
                    'guest': room_data['guest'],
                    'system_rate_pp': system_rate,
                    'comment_rate': comment_rate,
                    'comment_type': comment_type.upper(),
                    'rate_source': rate_source,
                    'difference': system_rate - comment_rate if comment_type == 'pp' else system_rate - (comment_rate / TAX_RATE),
                    'explanation': explanation,
                    'action': '🔧 FIX RATE'
                })
        
        # DISPLAY RESULTS
        st.subheader(f"📅 Discrepancies for {current_date.strftime('%B %d, %Y')}")
        
        if discrepancies:
            st.error(f"⚠️ {len(discrepancies)} room(s) need attention")
            
            df = pd.DataFrame(discrepancies)
            df['system_rate_pp'] = df['system_rate_pp'].apply(lambda x: f"{x:,.0f} VND")
            df['comment_rate'] = df['comment_rate'].apply(lambda x: f"{x:,.0f} VND")
            df['difference'] = df['difference'].apply(lambda x: f"{x:+,.0f} VND")
            
            st.dataframe(df[['room', 'guest', 'system_rate_pp', 'comment_rate', 'comment_type', 'explanation', 'action']])
            
            # Simple fix list
            st.markdown("---")
            st.subheader("🔧 Rooms to Fix")
            for d in discrepancies:
                st.markdown(f"- **Room {d['room']}** ({d['guest']}): {d['explanation']}")
            
            fix_list = [str(d['room']) for d in discrepancies]
            st.code(f"Fix these rooms: {', '.join(fix_list)}", language="text")
            
        else:
            st.success("✅ No discrepancies found! All rates are correct.")
        
        # Summary
        if skipped_monthly:
            st.info(f"📆 {len(skipped_monthly)} monthly guest(s) - skipped")
        
        if no_rate_found:
            st.warning(f"❓ {len(no_rate_found)} room(s) with no rate in comments")
        
        st.caption(f"Total: {len(rooms_actual)} rooms | Issues: {len(discrepancies)} | Monthly: {len(skipped_monthly)} | No rate: {len(no_rate_found)}")