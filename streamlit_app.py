import streamlit as st
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="Rate Discrepancy Scanner", page_icon="🔍")
st.title("🔍 Night Audit Rate Discrepancy Scanner")

st.markdown("""
Upload a PDF containing reservation comments and actual rates.
The scanner will extract both and flag any discrepancies.
""")

uploaded_file = st.file_uploader("📄 Upload Night Audit PDF", type="pdf")

def parse_rate_schedule(text):
    """Extract date-specific rates from comments"""
    pattern = r'RATE\s*AMOUNTH?\s*->([\d,]+).*?from\s*(\d{2}-[A-Z]{3}-\d{2})\s*to\s*(\d{2}-[A-Z]{3}-\d{2})'
    schedule = []
    for rate, start, end in re.findall(pattern, text, re.IGNORECASE):
        try:
            start_date = datetime.strptime(start, '%d-%b-%y')
            end_date = datetime.strptime(end, '%d-%b-%y')
            nights = (end_date - start_date).days
            if nights > 0:
                schedule.append({
                    'rate': float(rate.replace(',', '')),
                    'nights': nights,
                    'period': f"{start} to {end}"
                })
        except:
            continue
    return schedule

def extract_actual_rates(text):
    """Extract actual posted rates from the table section"""
    # Look for patterns like "2,285,937 VND" near room numbers
    pattern = r'(\d+)\s+.*?(\d{1,3}(?:,\d{3})*)\s+VND'
    matches = re.findall(pattern, text)
    return matches

if uploaded_file:
    with st.spinner("Processing PDF..."):
        # Extract text from PDF
        with pdfplumber.open(uploaded_file) as pdf:
            full_text = ""
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    full_text += extracted + "\n"
        
        st.success(f"✅ Processed {len(full_text)} characters")
        
        # Extract rate schedule from comments
        schedule = parse_rate_schedule(full_text)
        
        if schedule:
            total_expected = sum(item['rate'] * item['nights'] for item in schedule)
            
            st.subheader("📊 Rate Schedule Found in Comments")
            st.dataframe(schedule)
            
            st.metric("Expected Total (from comments)", f"{total_expected:,.0f} VND")
        else:
            st.warning("No date-specific rate schedule found in PDF comments")
        
        # Extract actual rates from tables
        actual_rates = extract_actual_rates(full_text)
        if actual_rates:
            st.subheader("🏨 Actual Rates from System")
            # Show first 10 unique rates
            unique_rates = list(set([r[1] for r in actual_rates[:10]]))
            st.write("Sample rates found:", unique_rates)
        else:
            st.info("Could not extract actual rates from table section")
        
        # Show preview of extracted text (for debugging)
        with st.expander("📄 View extracted text preview"):
            st.text(full_text[:1500] + "..." if len(full_text) > 1500 else full_text)

st.markdown("---")
st.caption("Rate Discrepancy Scanner v1.0")