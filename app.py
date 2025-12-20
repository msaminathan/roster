import streamlit as st
import mysql.connector
import pandas as pd
from PIL import Image
import io
import binascii
import base64

# Page Config
st.set_page_config(page_title="IITM Class of 1971 Roster", layout="wide")

# Database Connection (Cached)
# Database Connection (No cache)
def get_db_connection():
    try:
        return mysql.connector.connect(
            host='64.68.203.166',
            user='msaminathan_sami',
            password='Thamu$123',
            database='msaminathan_ccdb'
        )
    except mysql.connector.Error as err:
        return None

def load_data():
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    
    # Ensure fresh data by committing (refreshes snapshot in REPEATABLE READ)
    if conn.is_connected():
        conn.commit()
        
    query = "SELECT * FROM graduates"
    try:
        df = pd.read_sql(query, conn)
        return df
    finally:
        conn.close()

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

view_mode = st.sidebar.radio("View Option", ["Grid View", "List View", "Table (Text)", "Table (with Icons)"])

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
                            st.image(p1, caption="1966", use_container_width=True)
                        else:
                            st.text("No Image")
                    with c2:
                        if p2:
                            st.image(p2, caption="Current", use_container_width=True)
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

