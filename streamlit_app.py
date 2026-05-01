import streamlit as st
import pdfplumber
import re
from datetime import datetime
import pandas as pd
from io import BytesIO
import base64

st.set_page_config(page_title="Rate Discrepancy Scanner", page_icon="🔍")
st.title("🔍 Rate Discrepancy Scanner - Find & Fix")

uploaded_file = st.file_uploader("📄 Upload Night Audit PDF", type="pdf")

def extract_room_data(text):
    """
    Extract room-by-room data from PDF.
    Returns list of rooms with: room_number, guest_name, actual_rate, comment_rate, is_discrepancy
    """
    rooms = []
    
    # Pattern for table rows (Room No, Name, actual rate)
    # Looking for: "0403    Zhou, Xinfei ... 2,285,937 VND"
    table_pattern = r'(\d{3,4})\s+([A-Za-z][^0-9]{5,40}?)\s+\d+\s+\d+\s+\d+\s+\S+\s+\d+(?:,\d{3})*\s+([\d,]+)\s+VND'
    
    table_matches = re.findall(table_pattern, text, re.IGNORECASE)
    
    # Find all rate schedules from comments
    schedule_pattern = r'RATE\s*AMOUNTH?\s*->([\d,]+).*?from\s*(\d{2}-[A-Z]{3}-\d{2})\s*to\s*(\d{2}-[A-Z]{3}-\d{2})'
    schedules = re.findall(schedule_pattern, text, re.IGNORECASE)
    
    # Calculate average daily rate from comment schedule if multiple periods exist
    comment_daily_rate = None
    if schedules:
        total_amount = 0
        total_nights = 0
        for rate, start, end in schedules:
            rate_val = float(rate.replace(',', ''))
            try:
                start_date = datetime.strptime(start, '%d-%b-%y')
                end_date = datetime.strptime(end, '%d-%b-%y')
                nights = (end_date - start_date).days
                if nights > 0:
                    total_amount += rate_val * nights
                    total_nights += nights
            except:
                pass
        if total_nights > 0:
            comment_daily_rate = total_amount / total_nights
    
    # Match each room with its actual rate
    for room_num, guest_name, actual_rate_str in table_matches:
        actual_rate = float(actual_rate_str.replace(',', ''))
        
        # Try to find comment rate for this specific room
        room_comment_rate = None
        
        # Look for comment section near this room
        room_pattern = rf'{room_num}.*?RATE\s*AMOUNTH?\s*->([\d,]+)'
        room_specific = re.search(room_pattern, text, re.IGNORECASE | re.DOTALL)
        if room_specific:
            room_comment_rate = float(room_specific.group(1).replace(',', ''))
        elif comment_daily_rate:
            room_comment_rate = comment_daily_rate
        
        # Determine discrepancy
        is_discrepancy = False
        difference = 0
        
        if room_comment_rate:
            difference = actual_rate - room_comment_rate
            # Allow 1% tolerance for rounding
            if abs(difference) > (room_comment_rate * 0.01):
                is_discrepancy = True
        
        rooms.append({
            'room': room_num,
            'guest': guest_name.strip(),
            'actual_rate': actual_rate,
            'comment_rate': room_comment_rate if room_comment_rate else 0,
            'difference': difference,
            'discrepancy': is_discrepancy
        })
    
    return rooms

def highlight_pdf_discrepancies(pdf_bytes, rooms_with_discrepancies):
    """
    Generate HTML that displays PDF with highlighted rows
    Since we can't directly edit PDFs easily in browser,
    we'll create an HTML overlay that highlights the PDF
    """
    
    # Convert PDF to base64 for embedding
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    
    # Get room numbers that have discrepancies
    discrepant_rooms = [r['room'] for r in rooms_with_discrepancies if r['discrepancy']]
    
    # Create HTML with JavaScript to highlight specific text (room numbers)
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Highlighted PDF - Discrepancies in Red</title>
        <style>
            body {{
                margin: 0;
                padding: 20px;
                background: #f0f0f0;
                font-family: Arial, sans-serif;
            }}
            .container {{
                position: relative;
                width: 100%;
                max-width: 1200px;
                margin: 0 auto;
            }}
            .discrepancy-list {{
                background: #fff3cd;
                border: 1px solid #ffc107;
                padding: 15px;
                margin-bottom: 20px;
                border-radius: 5px;
            }}
            .discrepancy-list h3 {{
                margin: 0 0 10px 0;
                color: #856404;
            }}
            .discrepancy-list ul {{
                margin: 0;
            }}
            .discrepancy-list li {{
                color: #dc3545;
                font-weight: bold;
            }}
            .pdf-container {{
                position: relative;
                width: 100%;
                background: white;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }}
            embed, iframe {{
                width: 100%;
                height: 800px;
                border: none;
            }}
            .highlight-instruction {{
                background: #d4edda;
                border: 1px solid #28a745;
                padding: 10px;
                margin-bottom: 15px;
                border-radius: 5px;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="discrepancy-list">
                <h3>⚠️ Rooms with Rate Discrepancies (Fix These):</h3>
                <ul>
                    {''.join([f'<li>Room {r["room"]} - {r["guest"]}: Actual {r["actual_rate"]:,.0f} VND vs Comment {r["comment_rate"]:,.0f} VND (Diff: {r["difference"]:+,.0f})</li>' for r in rooms_with_discrepancies if r["discrepancy"]])}
                </ul>
            </div>
            
            <div class="highlight-instruction">
                <strong>🔍 How to find discrepancies in the PDF:</strong><br>
                Look for these room numbers in the PDF below. They appear in the table rows:
                <strong style="color:#dc3545">{', '.join(discrepant_rooms)}</strong>
            </div>
            
            <div class="pdf-container">
                <embed src="data:application/pdf;base64,{base64_pdf}#toolbar=1&navpanes=1&scrollbar=1" 
                       type="application/pdf"
                       width="100%"
                       height="800px" />
            </div>
        </div>
        
        <script>
            // Try to highlight text in PDF viewer (works in some browsers)
            console.log("PDF loaded. Search for room numbers: {', '.join(discrepant_rooms)}");
            // Note: Native PDF highlighting requires PDF.js integration
            // For now, use browser's Find feature (Ctrl+F)
        </script>
    </body>
    </html>
    """
    
    return html_content

if uploaded_file:
    # Read the PDF file
    pdf_bytes = uploaded_file.getvalue()
    
    with st.spinner("Scanning for discrepancies..."):
        # Extract text from PDF
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            full_text = ""
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    full_text += extracted + "\n"
        
        # Extract room data and find discrepancies
        rooms = extract_room_data(full_text)
        
        if rooms:
            # Convert to DataFrame for display
            df = pd.DataFrame(rooms)
            
            # Show summary
            discrepancy_count = df['discrepancy'].sum()
            
            st.subheader("📊 Discrepancy Summary")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Rooms", len(rooms))
            with col2:
                st.metric("Rooms with Issues", discrepancy_count)
            with col3:
                if discrepancy_count > 0:
                    st.metric("⚠️ Fix Needed", "YES", delta_color="off")
            
            # Show table of discrepancies
            if discrepancy_count > 0:
                st.error(f"⚠️ Found {discrepancy_count} room(s) with rate discrepancies")
                discrepant_df = df[df['discrepancy'] == True][['room', 'guest', 'actual_rate', 'comment_rate', 'difference']]
                st.dataframe(discrepant_df)
                
                # Generate HTML with PDF highlighting
                st.subheader("📄 PDF with Highlighted Discrepancies")
                st.markdown("**Look for the red-highlighted room numbers in the table rows below:**")
                
                html_content = highlight_pdf_discrepancies(pdf_bytes, rooms)
                
                # Display the HTML
                st.components.v1.html(html_content, height=1000, scrolling=True)
                
                # Download option
                st.download_button(
                    label="📥 Download Highlighted PDF Report (HTML)",
                    data=html_content,
                    file_name="discrepancy_report.html",
                    mime="text/html"
                )
                
            else:
                st.success("✅ No discrepancies found! All rates match.")
                # Show PDF anyway
                base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
                st.markdown(f'<embed src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600px" />', 
                           unsafe_allow_html=True)
        else:
            st.warning("Could not extract room data from PDF. Please check the format.")