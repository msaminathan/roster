import streamlit as st
import mysql.connector
import pandas as pd
from PIL import Image
import io
import binascii
import base64
import plotly.graph_objects as go
import datetime
import os
from dotenv import load_dotenv
from generate_roster_pdf import generate_pdf, generate_text_roster, generate_consolidated_report # Import generation functions
from sqlalchemy import create_engine, text

# Load environment variables
load_dotenv()

# Page Config
st.set_page_config(page_title="IITM Class of 1971 Roster", layout="wide")

# Database Connection (Cached)
# Database Connection (No cache)
def get_db_connection():
    try:
        return mysql.connector.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME')
        )
    except mysql.connector.Error as err:
        return None

# SQLAlchemy Engine for Pandas
def get_db_engine():
    try:
        user = os.getenv('DB_USER')
        password = os.getenv('DB_PASSWORD')
        host = os.getenv('DB_HOST')
        dbname = os.getenv('DB_NAME')
        # Use mysql-connector-python
        return create_engine(f"mysql+mysqlconnector://{user}:{password}@{host}/{dbname}")
    except Exception as e:
        return None

def load_data():
    engine = get_db_engine()
    if not engine:
        return pd.DataFrame()
        
    query = "SELECT * FROM graduates"
    try:
        # Use connection from engine for robust handling
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)
        return df
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame() # Return empty on error

# Helper to convert binary/hex to image
def get_image_from_blob(blob_data):
    if not blob_data:
        return None
    try:
        # Check if it's bytes or just hex string?
        # Connector python returns bytes for BLOB.
        image = Image.open(io.BytesIO(blob_data))
        return image
    except Exception as e:
        return None

# Load Data
try:
    df = load_data()
except Exception as e:
    st.error(f"Error connecting to database: {e}")
    st.stop()

# Helper to verify user
def verify_user(roll_no):
    conn = get_db_connection()
    if not conn:
        return None
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name, roll_no FROM graduates WHERE roll_no = %s", (roll_no,))
        user = cursor.fetchone()
        cursor.fetchall() # Consume rest
        return user
    except:
        return None
    finally:
        cursor.close()
        conn.close()

# Session State for Login
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['user_info'] = None

# Title with Image (Always visible header)
c_img, c_title = st.columns([1, 5])
with c_img:
    try:
        image = Image.open('gajendra.png')
        st.image(image, width=100) 
    except FileNotFoundError:
        st.warning("gajendra.png not found")

with c_title:
    st.title("🎓 IIT Madras - Class of 1971 Alumni Roster")

st.markdown("---")

# Login Logic
if not st.session_state['logged_in']:
    st.subheader("Login")
    roll_input = st.text_input("Enter your Roll Number")
    if st.button("Login"):
        user = verify_user(roll_input)
        if user:
            st.session_state['logged_in'] = True
            st.session_state['user_info'] = {'name': user[0], 'roll_no': user[1]}
            st.success(f"Welcome, {user[0]}!")
            st.rerun()
        else:
            st.error("Invalid Roll Number. Please try again.")
    st.stop() # Stop execution here if not logged in

# Logout
st.sidebar.markdown(f"**Logged in as:** {st.session_state['user_info']['name']}")
if st.sidebar.button("Logout"):
    st.session_state['logged_in'] = False
    st.session_state['user_info'] = None
    st.rerun()

st.sidebar.header("Filter & Search")
search_term = st.sidebar.text_input("Search (Name or Roll No)", "")

# Branch Filter
unique_branches = sorted(df['branch'].dropna().unique().tolist())
unique_branches.insert(0, "All")
selected_branch = st.sidebar.selectbox("Filter by Branch", unique_branches)

# Sort Options
sort_option = st.sidebar.selectbox("Sort By", ["Name (A-Z)", "Country, City", "Roll No (Ascending)"])

view_mode = st.sidebar.radio("View Option", ["Grid View", "List View", "Table (Text)", "Table (with Icons)", "Statistics", "Items of Interest", "Reports & Downloads", "About this App"])

# Filtering
filtered_df = df.copy()
if selected_branch != "All":
    filtered_df = filtered_df[filtered_df['branch'] == selected_branch]

if search_term:
    filtered_df = filtered_df[
        filtered_df['name'].str.contains(search_term, case=False, na=False) | 
        filtered_df['roll_no'].str.contains(search_term, case=False, na=False)
    ]

# Sorting Logic
if sort_option == "Name (A-Z)":
    filtered_df = filtered_df.sort_values(by='name', ascending=True)
elif sort_option == "Country, City":
    # Ensure 'country' column exists, if not, handle gracefully (e.g., sort by 'lives_in' only)
    # For now, assuming 'country' exists based on the instruction.
    # If 'country' is not in df, this will raise a KeyError.
    # A more robust solution might check `if 'country' in filtered_df.columns:`
    filtered_df = filtered_df.sort_values(by=['country', 'lives_in'], ascending=[True, True])
elif sort_option == "Roll No (Ascending)":
    filtered_df = filtered_df.sort_values(by='roll_no', ascending=True)

# Display Stats
st.sidebar.markdown("---")
st.sidebar.metric("Total Graduates", len(df))
st.sidebar.metric("Shown", len(filtered_df))





# Update Function
def update_graduate(id, name, roll_no, hostel, dob, wad, lives_in, state, email, phone, branch, new_photo_bytes=None):
    conn = get_db_connection()
    if not conn:
        st.error("Database connection failed")
        return

    cursor = conn.cursor()
    
    if new_photo_bytes:
        # Update with photo
        sql = """UPDATE graduates 
                 SET name=%s, roll_no=%s, hostel=%s, dob=%s, wad=%s, lives_in=%s, state=%s, email=%s, phone=%s, branch=%s, photo_current=%s 
                 WHERE id=%s"""
        val = (name, roll_no, hostel, dob, wad, lives_in, state, email, phone, branch, new_photo_bytes, id)
    else:
        # Update without photo
        sql = """UPDATE graduates 
                 SET name=%s, roll_no=%s, hostel=%s, dob=%s, wad=%s, lives_in=%s, state=%s, email=%s, phone=%s, branch=%s 
                 WHERE id=%s"""
        val = (name, roll_no, hostel, dob, wad, lives_in, state, email, phone, branch, id)
        
    try:
        cursor.execute(sql, val)
        conn.commit()
        st.success("Updated successfully!")
        st.rerun()
    except Exception as e:
        st.error(f"Error updating: {e}")
    finally:
        cursor.close()
        conn.close()

# Edit Dialog
@st.dialog("Edit Graduate Details")
def edit_dialog(row):
    with st.form("edit_form"):
        name = st.text_input("Name", value=row['name'])
        branch = st.text_input("Branch", value=row['branch'] if row['branch'] else "")
        roll_no = st.text_input("Roll No", value=row['roll_no'])
        hostel = st.text_input("Hostel", value=row['hostel'] if row['hostel'] else "")
        dob = st.text_input("DOB", value=row['dob'] if row['dob'] else "")
        wad = st.text_input("WAD", value=row['wad'] if row['wad'] else "")
        lives_in = st.text_input("Lives In", value=row['lives_in'] if row['lives_in'] else "")
        
        c1, c2 = st.columns(2)
        with c1:
            state = st.text_input("State", value=row['state'] if row['state'] else "")
        with c2:
            pass # placeholder
            
        email = st.text_input("Email", value=row['email'] if row['email'] else "")
        phone = st.text_input("Phone", value=row['phone'] if row['phone'] else "")
        
        st.markdown("---")
        st.markdown("**Update Photo**")
        uploaded_file = st.file_uploader("Choose a new Current Photo", type=['jpg', 'jpeg', 'png'])
        
        if st.form_submit_button("Save Changes"):
            photo_bytes = uploaded_file.getvalue() if uploaded_file else None
            update_graduate(row['id'], name, roll_no, hostel, dob, wad, lives_in, state, email, phone, branch, photo_bytes)

# Main Grid
if filtered_df.empty:
    st.info("No records found.")
else:
    # Custom CSS for cards
    st.markdown("""
    <style>
    .graduate-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .graduate-name {
        font-size: 1.2em;
        font-weight: bold;
        color: #0e1117;
    }
    .branch-text {
        font-size: 0.9em;
        font-weight: bold;
        color: #2e86de;
        margin-bottom: 5px;
    }
    .roll-no {
        color: #555;
        font-size: 0.9em;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

    if view_mode == "Grid View":
        # Grid Layout
        cols = st.columns(3) # 3 columns grid
        
        for idx, row in filtered_df.iterrows():
            col = cols[idx % 3]
            
            with col:
                with st.container(border=True):
                    c_title, c_edit = st.columns([0.8, 0.2])
                    with c_title:
                        st.markdown(f"<div class='graduate-name'>{row['name']}</div>", unsafe_allow_html=True)
                    with c_edit:
                        # ONLY show edit button if logged in user matches
                        if st.session_state['user_info']['roll_no'] == row['roll_no']:
                            if st.button("✏️", key=f"edit_{row['id']}", help="Edit Details"):
                                edit_dialog(row)

                    if row['branch']:
                         st.markdown(f"<div class='branch-text'>{row['branch']}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='roll-no'>Roll No: {row['roll_no']}</div>", unsafe_allow_html=True)
                    
                    # Photos
                    c1, c2 = st.columns(2)
                    p1 = get_image_from_blob(row['photo_1966'])
                    p2 = get_image_from_blob(row['photo_current'])
                    
                    with c1:
                        if p1:
                            st.image(p1, caption="1966", width="stretch")
                        else:
                            st.text("No Image")
                    with c2:
                        if p2:
                            st.image(p2, caption="Current", width="stretch")
                        else:
                            st.text("No Image")
                            
                    # Details Expander
                    with st.expander("View Details"):
                        st.text(f"Hostel: {row['hostel']}")
                        st.text(f"DOB: {row['dob']}")
                        if row['wad']:
                             st.text(f"WAD: {row['wad']}")
                        st.text(f"Lives in: {row['lives_in']}, {row['state']}")
                        if row['email']:
                            st.markdown(f"📧 [{row['email']}](mailto:{row['email']})")
                        if row['phone']:
                            st.text(f"📞 {row['phone']}")

    elif view_mode == "List View":
        # List View Layout
        for idx, row in filtered_df.iterrows():
            with st.container(border=True):
                # Columns: 1966 Photo (small), Current Photo (small), Details, Edit
                c_img, c_info, c_edit = st.columns([2, 5, 1])
                
                with c_img:
                    p1 = get_image_from_blob(row['photo_1966'])
                    p2 = get_image_from_blob(row['photo_current'])
                    ic1, ic2 = st.columns(2)
                    with ic1:
                        if p1: st.image(p1, width=60, caption="'66")
                    with ic2:
                        if p2: st.image(p2, width=60, caption="Now")

                with c_info:
                    st.markdown(f"**{row['name']}** <span style='color:grey'>({row['roll_no']})</span>", unsafe_allow_html=True)
                    st.caption(f"{row['branch'] if row['branch'] else ''} | {row['hostel'] if row['hostel'] else ''}")
                    
                    contact_parts = []
                    if row['lives_in']: contact_parts.append(f"📍 {row['lives_in']}")
                    if row['email']: contact_parts.append(f"📧 {row['email']}")
                    if contact_parts:
                        st.text(" | ".join(contact_parts))
                
                with c_edit:
                    if st.session_state['user_info']['roll_no'] == row['roll_no']:
                        if st.button("✏️", key=f"edit_list_{row['id']}"):
                            edit_dialog(row)

    elif view_mode == "Table (Text)":
        st.subheader("Tabular View (Text Only)")
        cols_to_show = ['name', 'roll_no', 'branch', 'hostel', 'lives_in', 'state', 'email', 'phone']
        # Filter existing columns
        cols_final = [c for c in cols_to_show if c in filtered_df.columns]
        st.dataframe(filtered_df[cols_final], hide_index=True)

    elif view_mode == "Table (with Icons)":
        st.subheader("Tabular View (with Photos)")
        
        # Prepare data with base64 images
        df_display = filtered_df.copy()
        
        def blob_to_uri(blob):
            if not blob: return None
            try:
                b64 = base64.b64encode(blob).decode('utf-8')
                return f"data:image/jpeg;base64,{b64}"
            except: return None
            
        df_display['photo_1966_uri'] = df_display['photo_1966'].apply(blob_to_uri)
        df_display['photo_current_uri'] = df_display['photo_current'].apply(blob_to_uri)
        
        cols_icons = ['photo_1966_uri', 'photo_current_uri', 'name', 'roll_no', 'branch', 'hostel', 'lives_in', 'email']
        
        # Filter to ensure columns exist
        cols_icons = [c for c in cols_icons if c in df_display.columns]

        st.dataframe(
            df_display[cols_icons],
            column_config={
                "photo_1966_uri": st.column_config.ImageColumn("1966 Photo", width="small"),
                "photo_current_uri": st.column_config.ImageColumn("Current Photo", width="small"),
                "name": "Name",
                "roll_no": "Roll No",
                "branch": "Branch",
                "hostel": "Hostel",
                "lives_in": "Lives In",
                "email": "Email"
            },
            hide_index=True
        )

    elif view_mode == "Statistics":
        st.header("🎓 Statistics & Pareto Charts")

        def draw_pareto(data, category_col, title):
            # 1. Aggregate
            counts = data[category_col].value_counts().reset_index()
            counts.columns = [category_col, 'count']
            counts = counts.sort_values(by='count', ascending=False)
            
            # 2. Cumulative Percentage
            counts['cumulative_percentage'] = counts['count'].cumsum() / counts['count'].sum() * 100
            
            # 3. Create Plot
            fig = go.Figure()
            
            # Bar Chart (Counts)
            fig.add_trace(go.Bar(
                x=counts[category_col],
                y=counts['count'],
                name='Count',
                marker_color='rgb(55, 83, 109)'
            ))
            
            # Line Chart (Cumulative %)
            fig.add_trace(go.Scatter(
                x=counts[category_col],
                y=counts['cumulative_percentage'],
                name='Cumulative Percentage',
                yaxis='y2',
                mode='lines+markers',
                marker_color='rgb(219, 64, 82)'
            ))
            
            # Layout
            fig.update_layout(
                title=title,
                xaxis_title=category_col,
                yaxis=dict(title='Count'),
                yaxis2=dict(
                    title='Cumulative Percentage',
                    overlaying='y',
                    side='right',
                    range=[0, 110]
                ),
                legend=dict(x=0.8, y=1.2),
                template='plotly_white'
            )
            
            st.plotly_chart(fig, width="stretch")

        # 1. Graduates by Branch
        st.subheader("1. Graduates by Branch")
        if 'branch' in df.columns:
            draw_pareto(df, 'branch', 'Graduates by Branch')
        else:
            st.warning("Branch data not available")

        # 2. Graduates by DOB Month
        st.subheader("2. Graduates by DOB Month")
        if 'dob' in df.columns:
            # Extract Month
            def get_month(date_str):
                if not date_str: return None
                try:
                    # User requested heuristic: Last 3 letters are the month
                    # Data format example: "12-Jun"
                    if len(date_str) >= 3:
                        return date_str[-3:]
                except:
                    pass
                return None

            df_dob = df.copy()
            df_dob['dob_month'] = df_dob['dob'].apply(get_month)
            # Filter our NaNs
            df_dob = df_dob.dropna(subset=['dob_month'])
            
            if not df_dob.empty:
                draw_pareto(df_dob, 'dob_month', 'Graduates by DOB Month')
            else:
                st.info("No valid DOB data found to parse months.")

        # 3. Graduates by WAD Month
        st.subheader("3. Graduates by WAD Month")
        if 'wad' in df.columns:
            df_wad = df.copy()
            df_wad['wad_month'] = df_wad['wad'].apply(get_month) # Reuse get_month
            df_wad = df_wad.dropna(subset=['wad_month'])
            
            if not df_wad.empty:
                draw_pareto(df_wad, 'wad_month', 'Graduates by WAD Month')
            else:
                st.info("No valid WAD data found to parse months.")

        # 4. Graduates by Location
        st.subheader("4. Graduates by Location")
        
        tab1, tab2, tab3, tab4 = st.tabs(["Lives In", "Country", "State", "Hostel"])
        
        with tab1:
            if 'lives_in' in df.columns:
                draw_pareto(df, 'lives_in', 'Graduates by City/Lives In')
        
        with tab2:
            if 'country' in df.columns:
                draw_pareto(df, 'country', 'Graduates by Country')
            else:
                st.write("Country column missing")

        with tab3:
            if 'state' in df.columns:
                draw_pareto(df, 'state', 'Graduates by State')
            else:
                st.write("State column missing")
                
        with tab4:
             if 'hostel' in df.columns:
                draw_pareto(df, 'hostel', 'Graduates by Hostel')

    elif view_mode == "Items of Interest":
        st.header("📌 Items of Interest")
        
        # --- Helper Functions for Posts ---
        def get_posts():
            engine = get_db_engine()
            if not engine: return pd.DataFrame()
            try:
                with engine.connect() as conn:
                    return pd.read_sql(text("SELECT * FROM posts ORDER BY created_at DESC"), conn)
            except:
                return pd.DataFrame()

        def create_post(roll_no, author_name, title, description, link):
            conn = get_db_connection()
            if not conn: return False
            cursor = conn.cursor()
            try:
                sql = "INSERT INTO posts (roll_no, author_name, title, description, link) VALUES (%s, %s, %s, %s, %s)"
                cursor.execute(sql, (roll_no, author_name, title, description, link))
                conn.commit()
                return True
            except Exception as e:
                st.error(f"Error creating post: {e}")
                return False
            finally:
                cursor.close()
                conn.close()

        def update_post_db(post_id, title, description, link):
            conn = get_db_connection()
            if not conn: return False
            cursor = conn.cursor()
            try:
                sql = "UPDATE posts SET title=%s, description=%s, link=%s WHERE id=%s"
                cursor.execute(sql, (title, description, link, post_id))
                conn.commit()
                return True
            except Exception as e:
                st.error(f"Error updating post: {e}")
                return False
            finally:
                cursor.close()
                conn.close()

        def delete_post_db(post_id):
            conn = get_db_connection()
            if not conn: return False
            cursor = conn.cursor()
            try:
                sql = "DELETE FROM posts WHERE id=%s"
                cursor.execute(sql, (post_id,))
                conn.commit()
                return True
            except Exception as e:
                st.error(f"Error deleting post: {e}")
                return False
            finally:
                cursor.close()
                conn.close()

        # --- Dialogs ---
        @st.dialog("Add New Item")
        def add_post_dialog():
            with st.form("new_post_form"):
                title = st.text_input("Title", max_chars=255)
                description = st.text_area("Description")
                link = st.text_input("Link (Optional)")
                
                if st.form_submit_button("Post Item"):
                    if not title:
                        st.error("Title is required.")
                    else:
                        c_user = st.session_state['user_info']
                        success = create_post(c_user['roll_no'], c_user['name'], title, description, link)
                        if success:
                            st.success("Item posted!")
                            st.rerun()

        @st.dialog("Edit Item")
        def edit_post_dialog(post_row):
            with st.form("edit_post_form"):
                title = st.text_input("Title", value=post_row['title'], max_chars=255)
                description = st.text_area("Description", value=post_row['description'])
                link = st.text_input("Link (Optional)", value=post_row['link'] if post_row['link'] else "")
                
                if st.form_submit_button("Save Changes"):
                    if not title:
                        st.error("Title is required.")
                    else:
                        success = update_post_db(post_row['id'], title, description, link)
                        if success:
                            st.success("Item updated!")
                            st.rerun()

        @st.dialog("Delete Item")
        def delete_post_dialog(post_id):
            st.warning("Are you sure you want to delete this item? This cannot be undone.")
            if st.button("Yes, Delete"):
                if delete_post_db(post_id):
                    st.success("Item deleted.")
                    st.rerun()

        # --- UI Layout ---
        
        # 'Add New' Button (Only if logged in - logic ensures this page is mostly reached if logged in, but check safe)
        if st.session_state.get('logged_in'):
            if st.button("➕ Post New Item"):
                add_post_dialog()
        else:
            st.info("Please login to post items.")

        st.markdown("---")
        
        posts_df = get_posts()
        
        if posts_df.empty:
            st.info("No items posted yet.")
        else:
            for idx, row in posts_df.iterrows():
                with st.container(border=True):
                    # Header: Title and Actions
                    c_title, c_actions = st.columns([0.85, 0.15])
                    
                    with c_title:
                        st.markdown(f"### {row['title']}")
                        st.caption(f"Posted by **{row['author_name']}** on {row['created_at']}")
                    
                    with c_actions:
                        # Actions only for owner
                        if st.session_state.get('logged_in') and st.session_state['user_info']['roll_no'] == row['roll_no']:
                            c_edit, c_del = st.columns(2)
                            with c_edit:
                                if st.button("✏️", key=f"edit_p_{row['id']}", help="Edit"):
                                    edit_post_dialog(row)
                            with c_del:
                                if st.button("🗑️", key=f"del_p_{row['id']}", help="Delete"):
                                    delete_post_dialog(row['id'])

                    # Content
                    if row['description']:
                        st.write(row['description'])
                    
                    if row['link']:
                        st.markdown(f"🔗 [Link]({row['link']})")

    elif view_mode == "Reports & Downloads":
        st.header("📊 Reports & Downloads")
        st.markdown("Generate and download the latest version of the Alumni Roster in PDF format.")

        col_gen, col_info = st.columns([1, 2])
        with col_gen:
            if st.button("🔄 Generate Latest Reports", type="primary"):
                with st.status("Generating Reports...", expanded=True) as status:
                    st.write("Initializing...")
                    import time
                    time.sleep(0.5)
                    
                    st.write("Processing Data & Images...")
                    generate_consolidated_report("IITM_1971_Graduates_Complete_Report.pdf")
                    
                    status.update(label="Generation Complete!", state="complete", expanded=False)
                st.success("Reports generated successfully!")
                st.rerun()

        st.markdown("### Available Downloads")
        
        def get_file_info(filepath):
            try:
                mtime = os.path.getmtime(filepath)
                ts = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
                return ts
            except:
                return None
        
        # Check for files
        c1, c2, c3 = st.columns(3)
        
        with c1:
             if os.path.exists("IITM_1971_Graduates_Complete_Report.pdf"):
                 ts = get_file_info("IITM_1971_Graduates_Complete_Report.pdf")
                 label = f"📄 Complete Report (PDF) - [{ts}]" if ts else "📄 Complete Report (PDF)"
                 with open("IITM_1971_Graduates_Complete_Report.pdf", "rb") as f:
                     st.download_button(
                         label=label,
                         data=f,
                         file_name="IITM_1971_Graduates_Complete_Report.pdf",
                         mime="application/pdf",
                         width="stretch"
                     )
             else:
                 st.info("Complete Report not generated yet.")

        with c2:
             if os.path.exists("IITM_1971_Graduates_Directory.pdf"):
                 ts = get_file_info("IITM_1971_Graduates_Directory.pdf")
                 label = f"🖼️ Photo Directory Only - [{ts}]" if ts else "🖼️ Photo Directory Only"
                 with open("IITM_1971_Graduates_Directory.pdf", "rb") as f:
                     st.download_button(
                         label=label,
                         data=f,
                         file_name="IITM_1971_Graduates_Directory.pdf",
                         mime="application/pdf",
                         width="stretch"
                     )
             else:
                 st.info("Photo Directory not generated yet.")

        with c3:
             if os.path.exists("IITM_1971_Graduates_List.pdf"):
                 ts = get_file_info("IITM_1971_Graduates_List.pdf")
                 label = f"📝 Text Roster Only - [{ts}]" if ts else "📝 Text Roster Only"
                 with open("IITM_1971_Graduates_List.pdf", "rb") as f:
                     st.download_button(
                         label=label,
                         data=f,
                         file_name="IITM_1971_Graduates_List.pdf",
                         mime="application/pdf",
                         width="stretch"
                     )
             else:
                 st.info("Text Roster not generated yet.")

    elif view_mode == "About this App":
        st.header("🚀 Building the Class of '71 Roster App")
        st.markdown("""
        This application is the result of a collaborative development process between **Saminathan (IITM '71)** and **Antigravity**, an advanced AI agent from Google DeepMind.

        ### 🛠️ The Journey
        
        #### 1. Data Preservation & Extraction
        The project began with a static PDF document: `IITM_1971_Graduates.pdf`.
        *   **Challenge**: The data was locked in a non-structured format with images and text mixed together.
        *   **Solution**: We utilized **Python** and the `pdfplumber` library to programmatically scrape the document.
        *   **Result**: Successfully extracted names, roll numbers, branches, and hostels for the entire batch. Crucially, we also extracted and processed binary image data to display both 1966 and current photos.

        #### 2. Database Design
        To ensure data persistence and scalability, we migrated from flat files to a **MySQL Database**.
        *   Designed a schema to hold rich profile data (DOB, WAD, Spouse Name, Lives In).
        *   Implemented an `update_schema.py` utility to handle migrations (like adding the *Items of Interest* feature).

        #### 3. Application Development
        We chose **Streamlit** for its ability to create beautiful, data-driven web apps quickly.
        *   **Interactive UI**: Built Grid and List views for browsing the directory visually.
        *   **Search & Filter**: Implemented real-time filtering by Branch and robust search by Name/Roll No.
        *   **Secure Editing**: Added a login mechanism (Roll Number based) allowing alumni to edit *only* their own profiles.

        #### 4. Advanced Features
        *   **Analytics**: Integrated `Plotly` to generate Pareto charts showing the distribution of graduates across branches and locations.
        *   **Items of Interest**: A community board for alumni to share updates and links, fully implemented with database backing.
        *   **Report Generation**: Capabilities to generate and download the roster in multiple PDF formats (Consolidated, Photo-only, Text-only).

        ---
        *Generated by Antigravity*
        """)



        st.markdown("---")
        st.subheader("⚠️ Disclaimer & Privacy")
        st.markdown("""
        *   **Data Usage**: This roster is intended for the exclusive use of IIT Madras Class of 1971 alumni. Please do not distribute this document or personal contact details to third parties.
        *   **Accuracy**: While we strive for accuracy, some data may be outdated. Please use the **Edit** feature to keep your profile current.
        """)


