import os
import io
import mysql.connector
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Image, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import matplotlib.pyplot as plt
from pypdf import PdfWriter
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_db_connection():
    try:
        return mysql.connector.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME')
        )
    except mysql.connector.Error as err:
        print(f"Error connecting to DB: {err}")
        return None

def get_image_from_blob(blob, max_width=1.5*inch, max_height=2*inch):
    if not blob:
        return None
    try:
        img_buffer = io.BytesIO(blob)
        pil_img = PILImage.open(img_buffer)
        
        if pil_img.mode != 'RGB':
            pil_img = pil_img.convert('RGB')
            
        # Calculate scaling to fit within box
        # We handle aspect ratio
        img_w, img_h = pil_img.size
        aspect = img_h / float(img_w)
        
        # Determine width/height to fit in max_width x max_height
        # ReportLab Image takes width and height as arguments
        
        # If we fix width
        final_w = max_width
        final_h = max_width * aspect
        
        # If height is too big, scale by height
        if final_h > max_height:
             final_h = max_height
             final_w = final_h / aspect

        out_buffer = io.BytesIO()
        pil_img.save(out_buffer, format='JPEG')
        out_buffer.seek(0)
        
        # Create ReportLab Image
        rl_img = Image(out_buffer, width=final_w, height=final_h)
        return rl_img
    except Exception as e:
        # print(f"Error processing image: {e}") 
        return None

def generate_pdf(filename="IITM_1971_Graduates_Directory.pdf"):
    print("Connecting to database...")
    conn = get_db_connection()
    if not conn:
        print("Failed to connect.")
        return

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM graduates ORDER BY branch, name")
    rows = cursor.fetchall()
    conn.close()
    print(f"Fetched {len(rows)} records.")
    
    # Context to track state across pages
    class PdfContext:
        def __init__(self):
            self.branch_name = ""
            
    context = PdfContext()

    # Flowable to update branch name
    from reportlab.platypus import Flowable
    class SetBranch(Flowable):
        def __init__(self, name):
            Flowable.__init__(self)
            self.name = name
            
        def wrap(self, w, h):
            return (0, 0)
            
        def draw(self):
            # Just update context. Header drawing is deferred to end of page.
            context.branch_name = self.name

    # Page callback
    def on_page(canvas, doc):
        canvas.saveState()
        
        # Footer: Page Number (Center)
        canvas.setFont('Helvetica', 9)
        page_num_text = f"Page {doc.page}"
        canvas.drawCentredString(letter[0]/2, 0.5*inch, page_num_text)
        
        # Footer: Date (Right)
        from datetime import datetime
        date_text = datetime.now().strftime("%Y-%m-%d %H:%M")
        canvas.drawRightString(letter[0] - 0.5*inch, 0.5*inch, date_text)
        
        canvas.restoreState()
        
        # DEFERRED Header Drawing
        def draw_header(page_num):
            if context.branch_name:
                canvas.saveState()
                canvas.setFont('Helvetica-Bold', 12)
                canvas.drawRightString(letter[0] - 0.5*inch, letter[1] - 0.75*inch, context.branch_name)
                canvas.restoreState()
                
        canvas.setPageCallBack(draw_header)


    doc = SimpleDocTemplate(filename, pagesize=letter, # Portrait by default
                            topMargin=1.0*inch, bottomMargin=0.75*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
    elements = []
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    title_style.alignment = 1 # Center
    
    cell_style = styles['Normal']
    cell_style.fontSize = 10
    cell_style.leading = 12

    elements.append(Paragraph("IIT Madras - Class of 1971 Graduates", title_style))
    elements.append(Spacer(1, 0.2*inch))

    # Group by Branch
    from collections import defaultdict
    branches = defaultdict(list)
    for row in rows:
        b_name = row['branch']
        if not b_name:
            b_name = "Unknown Branch"
        branches[b_name].append(row)

    first_branch = True

    for branch_name in sorted(branches.keys()):
        if not first_branch:
             elements.append(PageBreak())
        first_branch = False
        
        # Update context for Header
        elements.append(SetBranch(branch_name))
        
        # Branch Heading on page (Optional section separator)
        # User requested per-graduate detail, but keeping a section header is usually preferred. 
        # I'll leave a small spacer.
        elements.append(Spacer(1, 0.1*inch))
        
        data = []
        # Header Row
        data.append(['Graduate Details', '1966', 'Current'])
        
        for grad in branches[branch_name]:
            # Construct details
            details = []
            name = grad['name'] if grad['name'] else "Unknown"
            roll = grad['roll_no'] if grad['roll_no'] else ""
            
            info_text = f"<b>{name}</b>"
            if roll:
                info_text += f" ({roll})"
            info_text += "<br/>"
            
            # Add Branch to details (Requested Feature)
            info_text += f"<b>Branch:</b> {branch_name}<br/>"
            
            extras = []
            if grad['hostel']: extras.append(f"<b>Hostel:</b> {grad['hostel']}")
            if grad['dob']: extras.append(f"<b>DOB:</b> {grad['dob']}")
            if grad['wad']: extras.append(f"<b>WAD:</b> {grad['wad']}")
            if grad['spouse_name']: extras.append(f"<b>Spouse:</b> {grad['spouse_name']}")
            
            loc_parts = []
            if grad['lives_in']: loc_parts.append(grad['lives_in'])
            if grad['state']: loc_parts.append(grad['state'])
            if grad['country']: loc_parts.append(grad['country'])
            if loc_parts:
                extras.append(f"<b>Lives in:</b> {', '.join(loc_parts)}")
            
            if grad['email']: extras.append(f"<b>Email:</b> {grad['email']}")
            if grad['phone']: extras.append(f"<b>Phone:</b> {grad['phone']}")
            
            info_text += "<br/>".join(extras)
            
            p_details = Paragraph(info_text, cell_style)
            
            img_66 = get_image_from_blob(grad['photo_1966'], max_width=1.2*inch, max_height=1.5*inch)
            img_curr = get_image_from_blob(grad['photo_current'], max_width=1.2*inch, max_height=1.5*inch)
            
            data.append([p_details, img_66, img_curr])

        t = Table(data, colWidths=[5.0*inch, 1.25*inch, 1.25*inch], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.Color(0.9, 0.9, 0.9)),
            ('TEXTCOLOR', (0,0), (-1,0), colors.black),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 10),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.Color(0.97, 0.97, 0.97)]),
        ]))
        
        elements.append(t)

    print("Building PDF...")
    try:
        doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)
        print(f"Successfully generated: {filename}")
        save_report_to_db(filename, "Photo Directory")
    except Exception as e:
        print(f"Error building PDF: {e}")

def get_month_from_str(date_str):
    if not date_str: return None
    try:
        # Heuristic: Last 3 letters are the month, e.g. "12-Jan"
        if len(date_str) >= 3:
            return date_str[-3:]
    except:
        pass
    return None

def generate_plot_image(data, title, xlabel, ylabel, max_width=6*inch, max_height=4*inch):
    if not data:
        return None
    # data is a dict or Counter: {category: count}
    # Sort by count desc
    sorted_data = dict(sorted(data.items(), key=lambda item: item[1], reverse=True))
    
    categories = list(sorted_data.keys())
    counts = list(sorted_data.values())
    
    plt.figure(figsize=(8, 5))
    plt.bar(categories, counts, color='skyblue')
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100)
    plt.close()
    buf.seek(0)
    
    return Image(buf, width=max_width, height=max_height)

def generate_text_roster(filename="IITM_1971_Graduates_List.pdf"):
    print("Connecting to database for Text Roster...")
    conn = get_db_connection()
    if not conn:
        print("Failed to connect.")
        return

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM graduates ORDER BY branch, name")
    rows = cursor.fetchall()
    conn.close()
    
    # Use Landscape for tabular data to fit more columns
    doc = SimpleDocTemplate(filename, pagesize=landscape(letter),
                            topMargin=0.5*inch, bottomMargin=0.5*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
    
    elements = []
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    title_style.alignment = 1 # Center
    
    elements.append(Paragraph("IIT Madras - Class of 1971 Graduates (Text Only)", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Custom Style for Small Text to prevent wrapping
    from reportlab.lib.styles import ParagraphStyle
    small_style = ParagraphStyle(
        'Small',
        parent=styles['Normal'],
        fontSize=8,
        leading=10
    )
    
    # Page Footer
    def on_page_text(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        date_str = os.getenv('DATE_OVERRIDE') if os.getenv('DATE_OVERRIDE') else current_time
        
        canvas.drawCentredString(landscape(letter)[0]/2, 0.25*inch, f"Page {doc.page} | Generated: {date_str}")
        canvas.restoreState()

    # Table Header
    headers = ['Name', 'Roll No', 'Branch', 'Hostel', 'Lives In', 'Email', 'Phone']
    data = [headers]
    
    # Table Data
    for row in rows:
        name = row['name'] if row['name'] else ""
        roll = row['roll_no'] if row['roll_no'] else ""
        branch = row['branch'] if row['branch'] else ""
        hostel = row['hostel'] if row['hostel'] else ""
        
        lives = []
        if row['lives_in']: lives.append(row['lives_in'])
        if row['state']: lives.append(row['state'])
        if row['country']: lives.append(row['country'])
        location = ", ".join(lives)
        
        email = row['email'] if row['email'] else ""
        phone = row['phone'] if row['phone'] else ""
        
        # Wrapping long text with SMALL STYLE
        p_name = Paragraph(name, small_style)
        p_loc = Paragraph(location, small_style)
        p_email = Paragraph(email, small_style)
        
        data.append([p_name, roll, branch, hostel, p_loc, p_email, phone])
        
    # Table Style
    # Col Widths: Total ~10 inch available
    col_widths = [2.0*inch, 1.0*inch, 1.2*inch, 1.0*inch, 2.0*inch, 1.8*inch, 1.0*inch]
    
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9), # Reduced Header Font
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.beige),
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.lightgrey]),
        ('FONTSIZE', (0,1), (-1,-1), 8), # Reduced Body Font
    ]))
    
    elements.append(t)
    
    # --- Statistics Section ---
    elements.append(PageBreak())
    elements.append(Paragraph("Statistics", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    from collections import Counter
    
    # Calculate Stats
    branches_data = Counter([r['branch'] for r in rows if r['branch']])
    hostels_data = Counter([r['hostel'] for r in rows if r['hostel']])
    countries_data = Counter([r['country'] for r in rows if r['country']])
    states_data = Counter([r['state'] for r in rows if r['state']])
    dob_months_data = Counter([get_month_from_str(r['dob']) for r in rows if get_month_from_str(r['dob'])])
    wad_months_data = Counter([get_month_from_str(r['wad']) for r in rows if get_month_from_str(r['wad'])])

    # Helper to add section
    def add_plot_section(heading, data, x_label):
        elements.append(Paragraph(heading, styles['Heading2']))
        img = generate_plot_image(data, heading, x_label, "Count")
        if img:
            elements.append(img)
        else:
            elements.append(Paragraph("No data available", styles['Normal']))
        elements.append(Spacer(1, 0.2*inch))

    # Branch
    add_plot_section("Graduates by Branch", branches_data, "Branch")
    
    # Hostel
    add_plot_section("Graduates by Hostel", hostels_data, "Hostel")
    elements.append(PageBreak())
    
    # Country
    add_plot_section("Graduates by Country", countries_data, "Country")
    
    # State
    add_plot_section("Graduates by State", states_data, "State")
    elements.append(PageBreak())
    
    # DOB Month
    add_plot_section("Graduates by Birth Month", dob_months_data, "Month")
    
    # WAD Month
    add_plot_section("Graduates by Wedding Anniversary Month", wad_months_data, "Month")
    
    try:
        doc.build(elements, onFirstPage=on_page_text, onLaterPages=on_page_text)
        print(f"Successfully generated: {filename}")
        save_report_to_db(filename, "Text Roster")
    except Exception as e:
        print(f"Error building Text PDF: {e}")

def generate_memoriam_pdf(filename="IITM_1971_In_Memoriam.pdf"):
    print(f"Generating In Memoriam PDF: {filename}")
    conn = get_db_connection()
    if not conn: return
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM memoriam ORDER BY branch, name")
    rows = cursor.fetchall()
    conn.close()
    
    doc = SimpleDocTemplate(filename, pagesize=letter,
                            topMargin=0.5*inch, bottomMargin=0.5*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
    elements = []
    styles = getSampleStyleSheet()
    
    # Header with Images
    # We will use a Table for the header to place Flower L, Title C, Dove R
    header_data = []
    
    # Load decorative images
    flower_img = "memoriam_flower.png"
    dove_img = "memoriam_dove.png"
    
    img_flower = Image(flower_img, width=1.5*inch, height=1.5*inch) if os.path.exists(flower_img) else Paragraph("", styles['Normal'])
    img_dove = Image(dove_img, width=1.5*inch, height=1.5*inch) if os.path.exists(dove_img) else Paragraph("", styles['Normal'])
    
    # Title
    title_style = ParagraphStyle(
        'MemoriamTitle',
        parent=styles['Heading1'],
        fontSize=28,
        alignment=1, # Center
        textColor=colors.darkslategrey,
        fontName='Helvetica-Oblique'
    )
    title_text = Paragraph("In Memoriam<br/><font size=14>Forever in our hearts</font>", title_style)
    
    header_table = Table([[img_flower, title_text, img_dove]], colWidths=[2*inch, 3.5*inch, 2*inch])
    header_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.2*inch))
    
    if not rows:
        elements.append(Paragraph("No records found.", styles['Normal']))
    else:
        # Layout: Tight Table
        # Group by Branch for section headers? User said "tight bt branch ascending". 
        # Usually implies grouping or at least sorting.
        # Let's do a single table for compactness, but maybe add a subheader row for each branch change?
        # Or just a list. Let's do a table where we can have multiple columns if possible, but rows with Photo+Text is classic.
        # To make it "tight", we can reduce padding and maybe put 2 grads per row?
        # Let's try 2 grads per row for compactness if they fit. 
        # Page width ~ 8.5 inch. Margins 0.5+0.5 = 1. Used 7.5.
        # Check col widths. 3.75 inch per cell.
        
        # Preparing data for 2-column grid
        grid_data = []
        current_row = []
        
        # Branch Grouping Logic
        current_branch = None
        
        for row in rows:
            # Check branch change
            b_name = row['branch'] if row['branch'] else "Unknown Branch"
            
            if b_name != current_branch:
                 # If we have a pending row with 1 item, pad it
                if len(current_row) > 0:
                    current_row.append("") # Empty cell
                    grid_data.append(current_row)
                    current_row = []
                
                # Add Branch Header
                current_branch = b_name
                # Span across 2 columns
                # We defer creating Table until end, or we add a special row. 
                # Doing all in one table is tricky with colspans dynamic.
                # Easier: Add a row that says "Branch: X" in bold, spanning?
                # Actually, reportlab table allows span.
                # But treating data as grid is easier.
                
                # Let's just insert a full width row for branch header
                # We'll handle visual span in TableStyle later or just put it in first cell and let it overflow? No.
                # Let's add a special marker tuple?
                grid_data.append([f"BRANCH_HEADER:{b_name}"]) 
                
            # Content Cell
            img = get_image_from_blob(row['photo'], max_width=1.0*inch, max_height=1.2*inch)
            if not img: img = Paragraph("No Photo", styles['Normal'])
            
            name = row['name'] if row['name'] else "Unknown"
            roll = row['roll_no'] if row['roll_no'] else ""
            
            # Tight text
            p_text = f"<b>{name}</b><br/>"
            if roll: p_text += f"{roll}<br/>"
            
            # Inner Table for Cell (Photo Left, Text Right) or Stacked?
            # Side by side in the cell.
            cell_inner = Table([[img, Paragraph(p_text, styles['Normal'])]], colWidths=[1.1*inch, 2.4*inch])
            cell_inner.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ]))
            
            current_row.append(cell_inner)
            
            if len(current_row) == 2:
                grid_data.append(current_row)
                current_row = []
                
        # Flush last row
        if len(current_row) > 0:
            current_row.append("")
            grid_data.append(current_row)
            
        # Transform grid_data to Table data and build styles
        final_data = []
        table_styles = [
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('Grid', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ]
        
        row_idx = 0
        for r_data in grid_data:
            if len(r_data) == 1 and isinstance(r_data[0], str) and r_data[0].startswith("BRANCH_HEADER:"):
                # It's a header
                b_title = r_data[0].split(":", 1)[1]
                final_data.append([Paragraph(b_title, styles['Heading3']), ''])
                # Add Span style
                table_styles.append(('SPAN', (0, row_idx), (1, row_idx)))
                table_styles.append(('BACKGROUND', (0, row_idx), (1, row_idx), colors.aliceblue))
                table_styles.append(('ALIGN', (0, row_idx), (1, row_idx), 'LEFT'))
            else:
                final_data.append(r_data)
            row_idx += 1
            
        t = Table(final_data, colWidths=[3.75*inch, 3.75*inch])
        t.setStyle(TableStyle(table_styles))
        elements.append(t)

    try:
        doc.build(elements)
        print(f"Successfully generated: {filename}")
        save_report_to_db(filename, "In Memoriam")
    except Exception as e:
        print(f"Error building Memoriam PDF: {e}")

def generate_missing_pdf(filename="IITM_1971_Missing_Contacts.pdf"):
    print(f"Generating Missing Contacts PDF: {filename}")
    conn = get_db_connection()
    if not conn: return
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM tracked ORDER BY branch, name")
    rows = cursor.fetchall()
    conn.close()
    
    doc = SimpleDocTemplate(filename, pagesize=letter,
                            topMargin=0.75*inch, bottomMargin=0.75*inch, leftMargin=0.75*inch, rightMargin=0.75*inch)
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = styles['Heading1']
    title_style.alignment = 1
    
    elements.append(Paragraph("Missing Contacts / Yet to Track", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    if not rows:
        elements.append(Paragraph("No records found.", styles['Normal']))
    else:
        # Table Header
        headers = ['Photo', 'Name', 'Branch', 'Roll No']
        data = [headers]
        
        for row in rows:
            # Photo (Small)
            img = get_image_from_blob(row['photo'], max_width=0.8*inch, max_height=1.0*inch)
            
            name = row['name'] if row['name'] else ""
            branch = row['branch'] if row['branch'] else ""
            roll = row['roll_no'] if row['roll_no'] else ""
            
            data.append([img if img else "", name, branch, roll])
            
        t = Table(data, colWidths=[1.0*inch, 2.5*inch, 2.0*inch, 1.5*inch], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ]))
        
        elements.append(t)

    try:
        doc.build(elements)
        print(f"Successfully generated: {filename}")
        save_report_to_db(filename, "Missing Contacts")
    except Exception as e:
        print(f"Error building Missing Contacts PDF: {e}")


def generate_consolidated_report(final_filename="IITM_1971_Graduates_Complete_Report.pdf"):
    print("Generating consolidated report...")
    
    # 1. Generate Individual Reports
    photo_pdf = "IITM_1971_Graduates_Directory.pdf"
    text_pdf = "IITM_1971_Graduates_List.pdf"
    
    generate_pdf(photo_pdf)
    generate_text_roster(text_pdf)
    
    # 2. Merge
    merger = PdfWriter()
    
    try:
        # Append Photo Directory
        with open(photo_pdf, "rb") as f:
            merger.append(f)
            
        # Append Text Roster
        with open(text_pdf, "rb") as f:
            merger.append(f)
            
        # Write Output
        with open(final_filename, "wb") as f_out:
            merger.write(f_out)
            
        print(f"Successfully generated consolidated report: {final_filename}")
        save_report_to_db(final_filename, "Complete Report")
        return final_filename
    except Exception as e:
        print(f"Error merging PDFs: {e}")
        return None

def save_report_to_db(filename, report_custom_name):
    # report_custom_name can be a friendly key, or we can use the filename as unique key
    # Schema says `report_name VARCHAR(255) NOT NULL UNIQUE`.
    # Let's use the filenames as unique keys (e.g. "IITM_1971_Graduates_Directory.pdf") to match app logic.
    # But wait, app logic in previous tool call output showed custom labels but checking for filenames on disk.
    # I'll use filename as the key.
    
    print(f"Saving {filename} to DB...")
    conn = get_db_connection()
    if not conn:
        print("Failed to connect to DB for saving report.")
        return

    try:
        with open(filename, 'rb') as f:
            file_data = f.read()
            
        cursor = conn.cursor()
        # Upsert logic
        sql = """INSERT INTO reports (report_name, file_data) 
                 VALUES (%s, %s) 
                 ON DUPLICATE KEY UPDATE file_data=%s, created_at=NOW()"""
        cursor.execute(sql, (filename, file_data, file_data))
        conn.commit()
        print(f"Saved {filename} to database.")
    except Exception as e:
        print(f"Error saving report to DB: {e}")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    generate_consolidated_report()
