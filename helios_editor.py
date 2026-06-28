"""
HeliosEditor - PDF Editor with WebSocket LocalStorage
Uses streamlit-ws-localstorage for reliable localStorage access from iframes
"""

import streamlit as st
import fitz  # PyMuPDF
from io import BytesIO
from datetime import datetime
import uuid
from streamlit_ws_localstorage import injectWebsocketCode
import json
import base64
import pandas as pd


def display_pdf_preview(pdf_bytes, height=500):
    """Display PDF preview using base64"""
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="{height}" style="border: none;"></iframe>',
        unsafe_allow_html=True
    )


def extract_text_with_positions(pdf_bytes, page_num=0):
    """Extract text with exact position data from PDF"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text_blocks = []
    
    if page_num >= len(doc):
        page_num = 0
    
    page = doc[page_num]
    blocks = page.get_text("dict")
    
    for block in blocks.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if text:
                    bbox = span.get("bbox", [0, 0, 0, 0])
                    text_blocks.append({
                        'text': text,
                        'x': bbox[0],
                        'y': bbox[1],
                        'width': bbox[2] - bbox[0],
                        'height': bbox[3] - bbox[1],
                        'font_size': span.get("size", 11),
                        'font': span.get("font", "helv"),
                    })
    
    doc.close()
    return text_blocks


def get_pdf_page_as_image(pdf_bytes, page_num=0, dpi=150):
    """Render a PDF page as an image (base64 encoded)"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    if page_num >= len(doc):
        page_num = 0
    
    page = doc[page_num]
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    
    img_bytes = pix.tobytes("png")
    doc.close()
    
    img_base64 = base64.b64encode(img_bytes).decode('utf-8')
    return img_base64


def get_pdf_dimensions(pdf_bytes, page_num=0):
    """Get PDF page dimensions"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_num]
    rect = page.rect
    doc.close()
    return rect.width, rect.height


def apply_edits_to_pdf(pdf_bytes, edits, page_num=0):
    """Apply text edits to the original PDF"""
    if not edits:
        return pdf_bytes
    
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    if page_num >= len(doc):
        page_num = 0
    
    page = doc[page_num]
    
    for edit in edits:
        try:
            orig_len = len(edit.get('original', ''))
            
            rect = fitz.Rect(
                edit['x'] - 2,
                edit['y'] - 3,
                edit['x'] + (orig_len * (edit.get('font_size', 11) * 0.6)) + 4,
                edit['y'] + edit.get('font_size', 11) + 4
            )
            page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))
            
            page.insert_text(
                (edit['x'], edit['y'] + 2),
                edit.get('new', ''),
                fontsize=edit.get('font_size', 11),
                fontname="helv"
            )
        except Exception as e:
            st.warning(f"Could not apply edit: {str(e)}")
    
    output = doc.tobytes()
    doc.close()
    return output


def generate_editor_html(pdf_bytes, text_blocks, page_num=0):
    """
    Generate HTML with PDF background and editable text overlays
    Uses localStorage for communication (read by WebSocket)
    """
    img_base64 = get_pdf_page_as_image(pdf_bytes, page_num)
    pdf_width, pdf_height = get_pdf_dimensions(pdf_bytes, page_num)
    
    blocks_json = json.dumps(text_blocks)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                background: #f5f5f5;
                font-family: Arial, sans-serif;
                padding: 10px;
            }}
            .container {{
                max-width: 1000px;
                margin: 0 auto;
                background: white;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            .header {{
                padding: 8px 16px;
                background: #f5f5f5;
                border-bottom: 1px solid #ddd;
                display: flex;
                justify-content: space-between;
                font-size: 12px;
                color: #666;
                align-items: center;
                flex-wrap: wrap;
            }}
            .header .left {{ display: flex; align-items: center; gap: 12px; }}
            .pdf-wrapper {{
                position: relative;
                width: 100%;
                background: white;
                overflow: hidden;
            }}
            .pdf-wrapper img {{
                display: block;
                width: 100%;
                height: auto;
                user-select: none;
                pointer-events: none;
            }}
            .text-overlay {{
                position: absolute;
                cursor: text;
                padding: 1px 2px;
                border-radius: 2px;
                white-space: nowrap;
                z-index: 10;
            }}
            .text-overlay:hover {{
                background: rgba(25, 118, 210, 0.08);
            }}
            .text-overlay input {{
                border: none;
                background: rgba(255, 255, 255, 0.85);
                font-size: inherit;
                font-family: inherit;
                color: #000;
                padding: 0 2px;
                width: auto;
                min-width: 20px;
                outline: none;
                border-radius: 2px;
                transition: all 0.2s;
            }}
            .text-overlay input:focus {{
                background: #fff3cd;
                outline: 2px solid #ffc107;
            }}
            .text-overlay input.changed {{
                background: #fff3cd;
            }}
            .status-bar {{
                padding: 6px 16px;
                background: #f5f5f5;
                text-align: center;
                font-size: 12px;
                color: #666;
                border-top: 1px solid #ddd;
                display: flex;
                justify-content: space-between;
                align-items: center;
                flex-wrap: wrap;
            }}
            .btn {{
                padding: 4px 16px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 13px;
                font-weight: bold;
            }}
            .btn-success {{
                background: #2e7d32;
                color: white;
            }}
            .btn-success:hover {{
                background: #1b5e20;
            }}
            .btn-warning {{
                background: #f57c00;
                color: white;
            }}
            .btn-warning:hover {{
                background: #e65100;
            }}
            .edit-hint {{
                display: none;
                position: absolute;
                top: -20px;
                left: 0;
                background: #333;
                color: white;
                font-size: 8px;
                padding: 1px 6px;
                border-radius: 3px;
                white-space: nowrap;
            }}
            .text-overlay:hover .edit-hint {{
                display: block;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="left">
                    <span>📄 Page {page_num + 1}</span>
                    <span>✏️ Click any text to edit</span>
                </div>
                <div>
                    <span id="changeCount" style="margin-right:12px;">0 changes</span>
                    <button class="btn btn-success" onclick="saveEditsToLocalStorage()">💾 Send Edits</button>
                </div>
            </div>
            <div class="pdf-wrapper" id="pdfWrapper">
                <img src="data:image/png;base64,{img_base64}" id="pdfImage" />
                <div id="overlaysContainer"></div>
            </div>
            <div class="status-bar">
                <div class="left">
                    <span id="statusText">💡 Click any text to edit</span>
                </div>
                <div>
                    <button class="btn btn-warning" onclick="resetAll()">🔄 Reset</button>
                    <span style="margin-left:12px; font-size:11px; color:#999;">Press Enter to save, Esc to cancel</span>
                </div>
            </div>
        </div>
        
        <script>
            const textBlocks = {blocks_json};
            let edits = [];
            let currentEdit = null;
            
            const wrapper = document.getElementById('pdfWrapper');
            const img = document.getElementById('pdfImage');
            const container = document.getElementById('overlaysContainer');
            const changeCount = document.getElementById('changeCount');
            const statusText = document.getElementById('statusText');
            
            function getScale() {{
                const displayWidth = wrapper.offsetWidth || 800;
                const pdfWidth = {pdf_width} || 800;
                return displayWidth / pdfWidth;
            }}
            
            function renderOverlays() {{
                const scale = getScale();
                container.innerHTML = '';
                
                textBlocks.forEach(function(block) {{
                    const div = document.createElement('div');
                    div.className = 'text-overlay';
                    div.style.left = (block.x * scale) + 'px';
                    div.style.top = (block.y * scale) + 'px';
                    div.style.fontSize = Math.max((block.font_size * scale), 8) + 'px';
                    div.style.fontFamily = 'Arial, sans-serif';
                    
                    const savedEdit = edits.find(e => e.x === block.x && e.y === block.y);
                    const displayText = savedEdit ? savedEdit.new : block.text;
                    
                    const input = document.createElement('input');
                    input.type = 'text';
                    input.value = displayText;
                    input.dataset.x = block.x;
                    input.dataset.y = block.y;
                    input.dataset.original = block.text;
                    input.dataset.fontSize = block.font_size;
                    
                    if (savedEdit) {{
                        input.classList.add('changed');
                    }}
                    
                    const charWidth = block.font_size * 0.55 * scale;
                    input.style.width = Math.max(displayText.length * charWidth + 10, 30) + 'px';
                    
                    input.addEventListener('focus', function() {{
                        this.style.background = '#fff3cd';
                        this.style.outline = '2px solid #ffc107';
                        this.select();
                    }});
                    
                    input.addEventListener('blur', function() {{
                        this.style.background = 'rgba(255,255,255,0.85)';
                        this.style.outline = 'none';
                        saveEdit(this);
                    }});
                    
                    input.addEventListener('keydown', function(e) {{
                        if (e.key === 'Enter') {{
                            e.preventDefault();
                            this.blur();
                        }}
                        if (e.key === 'Escape') {{
                            this.value = this.dataset.original;
                            this.blur();
                        }}
                    }});
                    
                    div.addEventListener('click', function(e) {{
                        e.stopPropagation();
                        const input = this.querySelector('input');
                        if (input) {{
                            input.focus();
                        }}
                    }});
                    
                    div.appendChild(input);
                    container.appendChild(div);
                }});
                
                updateStatus();
            }}
            
            function saveEdit(input) {{
                const newText = input.value.trim() || input.dataset.original;
                const x = parseFloat(input.dataset.x);
                const y = parseFloat(input.dataset.y);
                const original = input.dataset.original;
                const fontSize = parseFloat(input.dataset.fontSize);
                const scale = getScale();
                
                if (newText !== original) {{
                    const existingIndex = edits.findIndex(e => e.x === x && e.y === y);
                    const editData = {{
                        x: x,
                        y: y,
                        original: original,
                        new: newText,
                        font_size: fontSize
                    }};
                    
                    if (existingIndex >= 0) {{
                        edits[existingIndex] = editData;
                    }} else {{
                        edits.push(editData);
                    }}
                    
                    input.classList.add('changed');
                    const charWidth = fontSize * 0.55 * scale;
                    input.style.width = Math.max(newText.length * charWidth + 10, 30) + 'px';
                }} else {{
                    const existingIndex = edits.findIndex(e => e.x === x && e.y === y);
                    if (existingIndex >= 0) {{
                        edits.splice(existingIndex, 1);
                    }}
                    input.classList.remove('changed');
                }}
                
                updateStatus();
            }}
            
            function saveEditsToLocalStorage() {{
                // Count changes
                let changeCount = 0;
                document.querySelectorAll('.text-overlay input').forEach(function(input) {{
                    if (input.value !== input.dataset.original) {{
                        changeCount++;
                    }}
                }});
                
                if (changeCount === 0) {{
                    statusText.textContent = '✅ No changes to send';
                    statusText.style.color = '#2e7d32';
                    return;
                }}
                
                // Collect all edits
                const newEdits = [];
                document.querySelectorAll('.text-overlay input').forEach(function(input) {{
                    const newText = input.value.trim() || input.dataset.original;
                    if (newText !== input.dataset.original) {{
                        newEdits.push({{
                            x: parseFloat(input.dataset.x),
                            y: parseFloat(input.dataset.y),
                            original: input.dataset.original,
                            new: newText,
                            font_size: parseFloat(input.dataset.fontSize)
                        }});
                    }}
                }});
                
                edits = newEdits;
                
                // Save to localStorage - the WebSocket will pick this up
                try {{
                    localStorage.setItem('helios_edits', JSON.stringify(edits));
                    statusText.textContent = '✅ ' + edits.length + ' edit(s) saved to localStorage!';
                    statusText.style.color = '#2e7d32';
                    updateStatus();
                }} catch (e) {{
                    statusText.textContent = '❌ Error saving to localStorage: ' + e.message;
                    statusText.style.color = '#c62828';
                    console.error('LocalStorage error:', e);
                }}
            }}
            
            function resetAll() {{
                if (confirm('Reset all changes?')) {{
                    edits = [];
                    localStorage.removeItem('helios_edits');
                    renderOverlays();
                    statusText.textContent = '🔄 All changes reset';
                    statusText.style.color = '#f57c00';
                    setTimeout(function() {{
                        statusText.style.color = '#666';
                        updateStatus();
                    }}, 2000);
                }}
            }}
            
            function updateStatus() {{
                if (changeCount) {{
                    changeCount.textContent = edits.length + ' change' + (edits.length !== 1 ? 's' : '');
                }}
                
                if (statusText && !statusText.textContent.includes('saved') && !statusText.textContent.includes('Error')) {{
                    if (edits.length === 0) {{
                        statusText.textContent = '💡 Click any text to edit';
                    }} else {{
                        statusText.textContent = '💾 ' + edits.length + ' change(s). Click "Send Edits" to send.';
                    }}
                }}
            }}
            
            // Handle resize
            let resizeTimeout;
            window.addEventListener('resize', function() {{
                clearTimeout(resizeTimeout);
                resizeTimeout = setTimeout(renderOverlays, 200);
            }});
            
            // Initial render
            if (img.complete) {{
                renderOverlays();
            }} else {{
                img.addEventListener('load', function() {{
                    renderOverlays();
                }});
            }}
            
            setTimeout(renderOverlays, 200);
            console.log('HeliosEditor loaded: ' + textBlocks.length + ' text blocks found');
        </script>
    </body>
    </html>
    """
    
    return html


def display_helios_editor(pdf_bytes):
    """
    Main function for HeliosEditor - Uses streamlit-ws-localstorage
    """
    st.subheader("📄 HeliosEditor - PDF Editor")

    # Initialize session state
    if 'helios_edits' not in st.session_state:
        st.session_state.helios_edits = []
    if 'helios_edited_pdf' not in st.session_state:
        st.session_state.helios_edited_pdf = None
    if 'current_page' not in st.session_state:
        st.session_state.current_page = 0
    if 'captured_edits' not in st.session_state:
        st.session_state.captured_edits = None

    # --- Core: Inject WebSocket code for localStorage access ---
    uid = str(uuid.uuid1())
    HOST_PORT = 'wsauthserver.supergroup.ai'
    conn = injectWebsocketCode(hostPort=HOST_PORT, uid=uid)

    # --- Check localStorage for edits ---
    # This runs when the page loads
    try:
        # The component stores data in a specific format
        stored_edits_json = conn.getLocalStorageVal(key='helios_edits')
        if stored_edits_json:
            try:
                stored_edits = json.loads(stored_edits_json)
                if stored_edits and len(stored_edits) > 0:
                    # Only update if we don't already have edits
                    if not st.session_state.helios_edits:
                        st.session_state.helios_edits = stored_edits
                        st.session_state.captured_edits = stored_edits
                        st.success(f"📥 Loaded {len(stored_edits)} edits from localStorage!")
            except Exception as e:
                st.warning(f"Could not parse edits: {e}")
    except Exception as e:
        # The component might not be ready yet
        pass

    # Get number of pages
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    doc.close()

    # Page navigation
    if total_pages > 1:
        st.session_state.current_page = st.slider(
            "Page",
            min_value=0,
            max_value=total_pages - 1,
            value=st.session_state.current_page,
            key="page_slider"
        )
        st.caption(f"Page {st.session_state.current_page + 1} of {total_pages}")
    else:
        st.session_state.current_page = 0

    # Extract text with positions for current page
    with st.spinner("Loading PDF and detecting text positions..."):
        text_blocks = extract_text_with_positions(pdf_bytes, st.session_state.current_page)

    st.caption(f"📝 Found {len(text_blocks)} text blocks on this page. Click any text to edit it.")

    # --- Generate and display the editor iframe ---
    html_content = generate_editor_html(pdf_bytes, text_blocks, st.session_state.current_page)
    html_base64 = base64.b64encode(html_content.encode('utf-8')).decode('utf-8')
    iframe_src = f"data:text/html;base64,{html_base64}"
    st.iframe(iframe_src, height=700)

    # --- Manual Refresh Button to fetch edits from localStorage ---
    st.markdown("---")
    col_refresh1, col_refresh2, col_refresh3 = st.columns([1, 1, 2])
    
    with col_refresh1:
        if st.button("🔄 Refresh Edits from localStorage", use_container_width=True):
            # Try to read from localStorage again
            try:
                stored_edits_json = conn.getLocalStorageVal(key='helios_edits')
                if stored_edits_json:
                    stored_edits = json.loads(stored_edits_json)
                    if stored_edits:
                        st.session_state.helios_edits = stored_edits
                        st.session_state.captured_edits = stored_edits
                        st.success(f"✅ Loaded {len(stored_edits)} edits from localStorage!")
                    else:
                        st.info("No edits found in localStorage")
                else:
                    st.info("No data in localStorage")
            except Exception as e:
                st.error(f"Error reading localStorage: {e}")
            st.rerun()

    with col_refresh2:
        if st.button("🧹 Clear localStorage", use_container_width=True):
            try:
                conn.setLocalStorageVal(key='helios_edits', val='')
                st.session_state.helios_edits = []
                st.success("Cleared localStorage!")
            except Exception as e:
                st.error(f"Error clearing localStorage: {e}")
            st.rerun()

    # --- Controls ---
    st.markdown("---")

    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if st.button("💾 Apply & Generate PDF", type="primary", use_container_width=True):
            edits_to_apply = st.session_state.helios_edits

            if edits_to_apply:
                with st.spinner("Applying edits to PDF..."):
                    edited_pdf = apply_edits_to_pdf(pdf_bytes, edits_to_apply, st.session_state.current_page)
                    st.session_state.helios_edited_pdf = edited_pdf
                    st.success(f"✅ PDF generated with {len(edits_to_apply)} edits!")
                    st.rerun()
            else:
                st.warning("No edits to apply. Edit text and click 'Send Edits' in the editor above, then click 'Refresh Edits'.")

    with col2:
        if st.button("🔄 Reset All", use_container_width=True):
            st.session_state.helios_edits = []
            st.session_state.helios_edited_pdf = None
            try:
                conn.setLocalStorageVal(key='helios_edits', val='')
            except:
                pass
            st.rerun()

    with col3:
        if st.session_state.helios_edited_pdf:
            st.download_button(
                label="📥 Download Edited PDF",
                data=st.session_state.helios_edited_pdf,
                file_name=f"edited_invoice_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                mime="application/pdf",
                use_container_width=True
            )

    # ===== MANUAL EDIT (Always Works) =====
    with st.expander("✏️ Manual Edit (Always Works)", expanded=True):
        st.markdown("Edit text fields below. This method always works.")
        
        if text_blocks:
            edits_to_apply = []
            
            rows = {}
            for block in text_blocks:
                y_key = round(block['y'] / 10) * 10
                if y_key not in rows:
                    rows[y_key] = []
                rows[y_key].append(block)
            
            for y_key in sorted(rows.keys()):
                row_blocks = sorted(rows[y_key], key=lambda b: b['x'])
                cols = st.columns(len(row_blocks))
                
                for i, block in enumerate(row_blocks):
                    with cols[i]:
                        new_text = st.text_input(
                            f"edit_{block['x']}_{block['y']}",
                            value=block['text'],
                            key=f"manual_edit_{block['x']}_{block['y']}",
                            label_visibility="collapsed",
                            placeholder=block['text'][:20]
                        )
                        if new_text != block['text']:
                            edits_to_apply.append({
                                'original': block['text'],
                                'new': new_text,
                                'x': block['x'],
                                'y': block['y'],
                                'font_size': block['font_size']
                            })
            
            if edits_to_apply:
                st.info(f"📝 {len(edits_to_apply)} changes detected")
                if st.button("✅ Apply Manual Edits", type="primary", use_container_width=True):
                    st.session_state.helios_edits = edits_to_apply
                    edited_pdf = apply_edits_to_pdf(pdf_bytes, edits_to_apply, st.session_state.current_page)
                    st.session_state.helios_edited_pdf = edited_pdf
                    st.success(f"✅ Applied {len(edits_to_apply)} manual edits!")
                    st.rerun()
            else:
                st.caption("💡 Make changes above and click 'Apply Manual Edits'")
        else:
            st.info("No text blocks found on this page.")

    # ===== DEBUG PANEL =====
    with st.expander("🔍 Debug Panel", expanded=False):
        st.markdown("### 📊 Debug Information")
        
        col_debug1, col_debug2 = st.columns(2)
        
        with col_debug1:
            st.markdown("**Session State:**")
            st.json({
                "helios_edits": len(st.session_state.helios_edits),
                "captured_edits": "✅ Yes" if st.session_state.captured_edits else "❌ No",
                "edited_pdf": "✅ Yes" if st.session_state.helios_edited_pdf else "❌ No",
                "current_page": st.session_state.current_page
            })
        
        with col_debug2:
            st.markdown("**Edits Details:**")
            if st.session_state.helios_edits:
                st.write(f"📝 {len(st.session_state.helios_edits)} edit(s) stored")
                for i, edit in enumerate(st.session_state.helios_edits[:3]):
                    st.caption(f"Edit {i+1}: '{edit.get('original', 'N/A')}' → '{edit.get('new', 'N/A')}'")
                if len(st.session_state.helios_edits) > 3:
                    st.caption(f"... and {len(st.session_state.helios_edits) - 3} more")
            else:
                st.caption("No edits stored yet")
        
        st.markdown("**Workflow:**")
        st.markdown("""
        1. Edit text in the PDF above
        2. Click **'💾 Send Edits'** in the editor
        3. Click **'🔄 Refresh Edits from localStorage'** below
        4. Click **'💾 Apply & Generate PDF'** to create the final PDF
        """)
    
    # ===== PREVIEW =====
    if st.session_state.helios_edited_pdf:
        st.markdown("---")
        st.markdown("### 📄 Preview - Edited PDF")
        display_pdf_preview(st.session_state.helios_edited_pdf, height=500)
    
    # ===== ORIGINAL PDF =====
    with st.expander("📄 View Original PDF", expanded=False):
        display_pdf_preview(pdf_bytes, height=400)
        st.download_button(
            label="📥 Download Original PDF",
            data=pdf_bytes,
            file_name=f"original_invoice_{datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf"
        )