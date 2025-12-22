import os
import io
import mysql.connector
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Image, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet
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
    except Exception as e:
        print(f"Error building Text PDF: {e}")

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
        return final_filename
    except Exception as e:
        print(f"Error merging PDFs: {e}")
        return None

if __name__ == "__main__":
    generate_consolidated_report()
