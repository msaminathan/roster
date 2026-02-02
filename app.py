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
from generate_roster_pdf import generate_pdf, generate_text_roster, generate_consolidated_report, generate_memoriam_pdf, generate_missing_pdf
from sqlalchemy import create_engine, text
import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster
import time

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

@st.cache_data(ttl=3600)
def get_all_location_data():
    engine = get_db_engine()
    if not engine: return pd.DataFrame()
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT * FROM location"), conn)
    except Exception as e:
        # Avoid showing st.error directly in cached function if possible, or just print
        print(f"Error fetching location data: {e}")
        return pd.DataFrame()

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

# Helper to resize image for map
def resize_image_for_map(image_bytes, max_wh=100):
    if not image_bytes: return None
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Convert to RGB if mode is RGBA or P to avoid JPEG saving issues
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        img.thumbnail((max_wh, max_wh))
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=70) # Lower quality for thumbnail
        return buffered.getvalue()
    except:
        return None

# Load Data
try:
    df = load_data()
except Exception as e:
    st.error(f"Error connecting to database: {e}")
    st.stop()

@st.cache_data(ttl=3600)
def get_report_from_db(report_name):
    conn = get_db_connection()
    if not conn: return None, None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT file_data, created_at FROM reports WHERE report_name = %s", (report_name,))
        row = cursor.fetchone()
        if row:
            return row[0], row[1] # blob, timestamp
        return None, None
    except Exception as e:
        return None, None
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

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

# Helper to log login
def log_login(roll_no, name):
    conn = get_db_connection()
    if not conn: return None
    cursor = conn.cursor()
    try:
        current_time = datetime.datetime.now()
        login_date = current_time.strftime('%Y-%m-%d')
        login_time = current_time.strftime('%H:%M:%S')
        
        sql = "INSERT INTO user_logs (roll_no, name, login_date, login_time) VALUES (%s, %s, %s, %s)"
        cursor.execute(sql, (roll_no, name, login_date, login_time))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        print(f"Error logging login: {e}")
        return None
    finally:
        cursor.close()
        conn.close()

# Helper to log logout
def log_logout(log_id):
    if not log_id: return
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor()
    try:
        current_time = datetime.datetime.now()
        logout_time = current_time.strftime('%H:%M:%S')
        
        sql = "UPDATE user_logs SET logout_time = %s WHERE id = %s"
        cursor.execute(sql, (logout_time, log_id))
        conn.commit()
    except Exception as e:
        print(f"Error logging logout: {e}")
    finally:
        cursor.close()
        conn.close()

# Helper to check for today's events
def check_today_events(df):
    today = datetime.datetime.now()
    current_day = today.day
    current_month_name = today.strftime("%b") # e.g., "Jan", "Feb"
    
    events = []
    
    # Map for inconsistent month abbreviations if necessary (e.g. Sept vs Sep)
    # Assuming standard 3-letter months based on "ddd-mmm" description and "12-Jun" example.
    
    for _, row in df.iterrows():
        # Check DOB
        if row['dob']:
            try:
                # Expected formats: "12-Jun", "7-May"
                parts = row['dob'].split('-')
                if len(parts) == 2:
                    d = int(parts[0])
                    m = parts[1]
                    if d == current_day and m == current_month_name:
                        events.append({
                            'name': row['name'],
                            'type': 'Birthday',
                            'date': row['dob'],
                            'photo_1966': row['photo_1966'],
                            'photo_current': row['photo_current']
                        })
            except:
                pass # Ignore parse errors

        # Check WAD
        if row['wad']:
            try:
                parts = row['wad'].split('-')
                if len(parts) == 2:
                    d = int(parts[0])
                    m = parts[1]
                    if d == current_day and m == current_month_name:
                        events.append({
                            'name': row['name'],
                            'type': 'Wedding Anniversary',
                            'date': row['wad'],
                            'photo_1966': row['photo_1966'],
                            'photo_current': row['photo_current']
                        })
            except:
                pass
                
    return events

# Popup Dialog
@st.dialog("🎉 Special Occasions Today!")
def show_event_popup(events):
    for event in events:
        st.subheader(f"Happy {event['type']} ({event['date']}), {event['name']}!")
        
        # Photos
        c1, c2 = st.columns(2)
        p1 = get_image_from_blob(event['photo_1966'])
        p2 = get_image_from_blob(event['photo_current'])
        
        with c1:
            if p1:
                st.image(p1, caption="1966", width=150)
            else:
                st.info("No 1966 Photo")
        with c2:
            if p2:
                st.image(p2, caption="Current", width=150)
            else:
                st.info("No Current Photo")
                
        st.markdown(f"**Wishing you a wonderful day filled with joy and happiness!**")
        st.divider()

# Update Function
# Update Function
def update_graduate(id, name, roll_no, hostel, dob, wad, spouse_name, lives_in, state, country, email, phone, branch, new_photo_bytes=None):
    conn = get_db_connection()
    if not conn:
        st.error("Database connection failed")
        return

    cursor = conn.cursor(dictionary=True) # Use dictionary cursor for easier access
    
    # 1. Fetch CURRENT data to check for address changes
    current_data = {}
    try:
        cursor.execute("SELECT lives_in, state, country FROM graduates WHERE id = %s", (id,))
        current_data = cursor.fetchone()
    except Exception as e:
        print(f"Error fetching current data: {e}")

    # 2. Update Graduates Table
    if new_photo_bytes:
        # Update with photo
        sql = """UPDATE graduates 
                 SET name=%s, roll_no=%s, hostel=%s, dob=%s, wad=%s, spouse_name=%s, lives_in=%s, state=%s, country=%s, email=%s, phone=%s, branch=%s, photo_current=%s 
                 WHERE id=%s"""
        val = (name, roll_no, hostel, dob, wad, spouse_name, lives_in, state, country, email, phone, branch, new_photo_bytes, id)
    else:
        # Update without photo
        sql = """UPDATE graduates 
                 SET name=%s, roll_no=%s, hostel=%s, dob=%s, wad=%s, spouse_name=%s, lives_in=%s, state=%s, country=%s, email=%s, phone=%s, branch=%s 
                 WHERE id=%s"""
        val = (name, roll_no, hostel, dob, wad, spouse_name, lives_in, state, country, email, phone, branch, id)
        
    try:
        cursor.execute(sql, val)
        conn.commit()
        
        # 3. Geo-Location & Location Table Sync
        try:
            # 3a. Check if address text changed
            address_text_changed = True
            if current_data:
                old_lives_in = current_data.get('lives_in') or ""
                old_state = current_data.get('state') or ""
                old_country = current_data.get('country') or ""
                
                new_lives_in = lives_in or ""
                new_state = state or ""
                new_country = country or ""
                
                if (old_lives_in == new_lives_in) and (old_state == new_state) and (old_country == new_country):
                    address_text_changed = False
            
            # 3b. Check if 'location' table has valid entry
            # We need to ensure we have lat/long. If not, even if text didn't change, we must geocode.
            loc_exists_and_valid = False
            try:
                cursor.execute("SELECT latitude, longitude FROM location WHERE roll_no = %s", (roll_no,))
                loc_row = cursor.fetchone()
                if loc_row and loc_row.get('latitude') is not None and loc_row.get('longitude') is not None:
                     loc_exists_and_valid = True
            except:
                pass # Assume not valid if error

            # Decision Logic
            is_address_cleared = not (lives_in or state or country)

            if is_address_cleared:
                # Case: Address cleared -> Remove from location table
                cursor.execute("DELETE FROM location WHERE roll_no = %s", (roll_no,))
                conn.commit()

            elif not address_text_changed and loc_exists_and_valid:
                # Case: Address UNCHANGED AND Location VALID -> Update Name/Branch only (No Geocoding)
                sql_update_meta = """
                    UPDATE location 
                    SET name = %s, branch = %s
                    WHERE roll_no = %s
                """
                cursor.execute(sql_update_meta, (name, branch, roll_no))
                conn.commit()
                
            else:
                # Case: Address CHANGED OR Location INVALID/MISSING -> Geocode and Full Update
                from geopy.geocoders import Nominatim
                geolocator = Nominatim(user_agent="iitm_graduates_locator_app_update")
                
                query_parts = []
                if lives_in: query_parts.append(lives_in)
                if state: query_parts.append(state)
                if country: query_parts.append(country)
                
                address_query = ", ".join(query_parts)
                
                lat = None
                lon = None
                
                try:
                    location = geolocator.geocode(address_query, timeout=5)
                    if location:
                        lat = location.latitude
                        lon = location.longitude
                except:
                    pass 
                    
                # Upsert
                # Note: 'loc_exists_and_valid' might be False because row doesn't exist OR lat is null.
                # ON DUPLICATE KEY UPDATE handles both existing row (fix lat/long) and new row.
                sql_loc = """
                    INSERT INTO location (roll_no, branch, name, lives_in, state, country, latitude, longitude)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        branch = VALUES(branch),
                        name = VALUES(name),
                        lives_in = VALUES(lives_in),
                        state = VALUES(state),
                        country = VALUES(country),
                        latitude = VALUES(latitude),
                        longitude = VALUES(longitude)
                """
                cursor.execute(sql_loc, (roll_no, branch, name, lives_in, state, country, lat, lon))
                conn.commit()
                
        except Exception as geo_e:
             print(f"Location sync failed: {geo_e}") # Non-blocking error
        
        st.success("Updated successfully!")
        st.rerun()
    except Exception as e:
        st.error(f"Error updating: {e}")
    finally:
        cursor.close()
        conn.close()

# Helper removed: save_changes_from_editor (Replaced by per-row Edit Dialog)

# Helper to highlight user row
def highlight_user(row):
    try:
        if st.session_state['user_info']['roll_no'] == row['roll_no']:
            return ['background-color: lightyellow'] * len(row)
        else:
            return [''] * len(row)
    except:
        return [''] * len(row)

# Edit Dialog
@st.dialog("Edit My Details")
def edit_dialog(row):
    with st.form("edit_form"):
        # Row 1
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Name", value=row['name'])
        with c2:
            roll_no = st.text_input("Roll No", value=row['roll_no'])
            
        # Row 2
        c3, c4 = st.columns(2)
        with c3:
            branch = st.text_input("Branch", value=row['branch'] if row['branch'] else "")
        with c4:
             hostel = st.text_input("Hostel", value=row['hostel'] if row['hostel'] else "")

        # Row 3
        c5, c6 = st.columns(2)
        with c5:
             dob = st.text_input("DOB", value=row['dob'] if row['dob'] else "")
        with c6:
             wad = st.text_input("WAD", value=row['wad'] if row['wad'] else "")

        # Row 4
        c7, c8 = st.columns(2)
        with c7:
             spouse_name = st.text_input("Spouse Name", value=row['spouse_name'] if row.get('spouse_name') else "")
        with c8:
             lives_in = st.text_input("Lives In (City)", value=row['lives_in'] if row['lives_in'] else "")

        # Row 5
        c9, c10 = st.columns(2)
        with c9:
            state = st.text_input("State", value=row['state'] if row['state'] else "")
        with c10:
            country = st.text_input("Country", value=row['country'] if row.get('country') else "") # Added Country

        # Row 6
        c11, c12 = st.columns(2)
        with c11:
            email = st.text_input("Email", value=row['email'] if row['email'] else "")
        with c12:
            phone = st.text_input("Phone", value=row['phone'] if row['phone'] else "")
        
        st.markdown("---")
        st.markdown("**Update Photo**")
        uploaded_file = st.file_uploader("Choose a new Current Photo", type=['jpg', 'jpeg', 'png'])
        
        if st.form_submit_button("Save Changes"):
            st.session_state['table_key'] += 1 # Force reset of filtered table views
            photo_bytes = uploaded_file.getvalue() if uploaded_file else None
            update_graduate(int(row['id']), name, roll_no, hostel, dob, wad, spouse_name, lives_in, state, country, email, phone, branch, photo_bytes)

# Session State for Login
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['user_info'] = None
    st.session_state['log_id'] = None
if 'show_popup' not in st.session_state:
    st.session_state['show_popup'] = False

# Handle Redirect
if st.session_state.get('redirect_to_grid'):
    st.session_state['view_mode_selection'] = 'Grid View'
    del st.session_state['redirect_to_grid']
if 'table_key' not in st.session_state:
    st.session_state['table_key'] = 0

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
            
            # Log login
            log_id = log_login(user[1], user[0])
            st.session_state['log_id'] = log_id
            
            st.session_state['show_popup'] = True # Trigger popup on first load
            st.success(f"Welcome, {user[0]}!")
            st.rerun()
        else:
            st.error("Invalid Roll Number. Please try again.")
    st.stop() # Stop execution here if not logged in

# Logout
st.sidebar.markdown(f"**Logged in as:** {st.session_state['user_info']['name']}")
if st.sidebar.button("Edit My Profile", type="primary"):
    if not df.empty and st.session_state.get('user_info'):
        user_roll = st.session_state['user_info']['roll_no']
        user_rows = df[df['roll_no'] == user_roll]
        if not user_rows.empty:
            edit_dialog(user_rows.iloc[0])
        else:
             st.error("User details not found.")

if st.sidebar.button("Logout"):
    # Log logout
    if 'log_id' in st.session_state:
        log_logout(st.session_state['log_id'])

    st.session_state['logged_in'] = False
    st.session_state['user_info'] = None
    st.session_state['show_popup'] = False
    st.session_state['log_id'] = None
    st.rerun()

# Check Events Popup
if st.session_state['show_popup']:
    events = check_today_events(df)
    if events:
        show_event_popup(events)
    # Disable popup after showing once
    st.session_state['show_popup'] = False

st.sidebar.header("Filter & Search")
search_term = st.sidebar.text_input("Search (Name or Roll No)", "")

# Branch Filter
unique_branches = sorted(df['branch'].dropna().unique().tolist())
unique_branches.insert(0, "All")
selected_branch = st.sidebar.selectbox("Filter by Branch", unique_branches)

# Sort Options
sort_option = st.sidebar.selectbox("Sort By", ["Name (A-Z)", "Country, City", "Roll No (Ascending)"])

view_mode = st.sidebar.radio("View Option", ["Grid View", "List View", "Table (Text)", "Table (with Icons)", "Statistics", "Global Map", "Items of Interest", "Missing Contacts", "In Memoriam", "Reunion Photo Album", "Reports & Downloads", "About this App"], key="view_mode_selection")

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
# Display Stats
st.sidebar.markdown("---")

# Fetch counts for sidebar
def get_table_count(table_name):
    conn = get_db_connection()
    if not conn: return 0
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cursor.fetchone()[0]
    except:
        return 0
    finally:
        cursor.close()
        conn.close()

# Only fetch if not already done (optimization? No, need fresh counts occasionally, but let's simple fetch)
grad_count = len(df)
memoriam_count = get_table_count("memoriam")
tracked_count = get_table_count("tracked")
grand_total = grad_count + memoriam_count + tracked_count

# Custom Stats Table
# Calculate Total Shown
total_shown = 0
show_total_shown = False
if view_mode in ["Grid View", "List View", "Table (Text)", "Table (with Icons)"]:
    total_shown = len(filtered_df)
    show_total_shown = True
elif view_mode == "Missing Contacts":
    total_shown = tracked_count
    show_total_shown = True
elif view_mode == "In Memoriam":
    total_shown = memoriam_count
    show_total_shown = True

total_shown_row = ""
if show_total_shown:
    total_shown_row = f"""
<tr style="background-color: #f0f2f6;">
<td style="padding: 5px; font-weight: bold;">Total Shown</td>
<td style="padding: 5px; text-align: right; font-weight: bold;">{total_shown}</td>
</tr>"""

# Custom Stats Table
# Custom Stats Table
st.sidebar.markdown(f"""
<div style="font-family: sans-serif; font-size: 0.9em;">
<table style="width:100%; border-collapse: collapse; color: #333;">
<tr style="border-bottom: 1px solid #ddd;">
<td style="padding: 5px; font-weight: bold;">Category</td>
<td style="padding: 5px; text-align: right; font-weight: bold;">Count</td>
</tr>
<tr>
<td style="padding: 5px;">🎓 Graduates</td>
<td style="padding: 5px; text-align: right;">{grad_count}</td>
</tr>
<tr>
<td style="padding: 5px;">🌹 In Memoriam</td>
<td style="padding: 5px; text-align: right;">{memoriam_count}</td>
</tr>
<tr>
<td style="padding: 5px;">🔍 Yet to Track</td>
<td style="padding: 5px; text-align: right;">{tracked_count}</td>
</tr>
<tr style="border-top: 2px solid #555; background-color: #f0f2f6;">
<td style="padding: 5px; font-weight: bold;">Grand Total</td>
<td style="padding: 5px; text-align: right; font-weight: bold;">{grand_total}</td>
</tr>
{total_shown_row}
</table>
</div>
<br>
""", unsafe_allow_html=True)






# Main Grid
if filtered_df.empty:
    st.info("No records found.")
else:
    # Custom CSS for cards
    st.markdown("""
    <style>
    .graduate-card {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 10px;
        margin-bottom: 10px;
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
        st.info("Note: You can edit only your own details by clicking the edit icon (✏️) on your card.")
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
                        st.text(f"WAD: {row['wad'] if row['wad'] else '-'}")
                        st.text(f"Spouse: {row.get('spouse_name') if row.get('spouse_name') else '-'}")
                        st.text(f"Lives in: {row['lives_in']}, {row['state']}")
                        if row['email']:
                            st.markdown(f"📧 [{row['email']}](mailto:{row['email']})")
                        if row['phone']:
                            st.text(f"📞 {row['phone']}")

    elif view_mode == "List View":
        st.info("Note: You can edit only your own details by clicking the edit icon (✏️) in your row.")
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
        st.info("Note: You can edit only your own row, marked by the edit symbol (✏️). Please select the checkbox for your row to edit.")
        
        # Cols to show
        cols_to_show = ['id', 'name', 'roll_no', 'branch', 'hostel', 'lives_in', 'state', 'email', 'phone']
        cols_final = [c for c in cols_to_show if c in filtered_df.columns]
        
        # Create Dataframe for display
        df_view = filtered_df[cols_final].copy()
        
        # Add visual "Edit" column conditionally
        current_user_roll = st.session_state['user_info']['roll_no']
        df_view.insert(0, "Edit", df_view['roll_no'].apply(lambda x: "✏️" if x == current_user_roll else ""))
        
        # Apply Styling
        # Note: We need 'roll_no' in the dataframe to check user
        # 'roll_no' is already in cols_final
        
        styled_df = df_view.style.apply(highlight_user, axis=1)

        event = st.dataframe(
            styled_df,
            hide_index=True,
            column_config={
                "id": None, # Hide ID
                "Edit": st.column_config.Column("Edit", width="small", help="Click row to edit")
            },
            on_select="rerun",
            selection_mode="single-row",
            key=f"text_df_{st.session_state['table_key']}"
        )
        
        # Handle Selection
        if len(event.selection.rows) > 0:
            selected_row_index = event.selection.rows[0]
            # Get the exact row from the *displayed* dataframe (df_view)
            # df_view has same index as styled_df if we didn't reset index? 
            # filtered_df might have gaps in index. 
            # st.dataframe preserves index or resets? 
            # "The selection.rows property contains a list of the integers of the selected rows." - These act as positional indices (0-based) relative to the displayed data.
            # So we use iloc on df_view.
            
            selected_row = df_view.iloc[selected_row_index]
            
            # Fetch full row using ID for editing
            full_row = filtered_df[filtered_df['id'] == selected_row['id']].iloc[0]

            # Verify User
            current_user_roll = st.session_state['user_info']['roll_no']
            if current_user_roll == full_row['roll_no']:
                 edit_dialog(full_row)
            else:
                 st.warning(f"You can only edit your own details (Roll No: {current_user_roll}).")

    elif view_mode == "Table (with Icons)":
        st.subheader("Tabular View (with Photos)")
        st.info("Note: You can edit only your own row, marked by the edit symbol (✏️). Please select the checkbox for your row to edit.")
        
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
        
        # Include ID
        cols_icons = ['id', 'photo_1966_uri', 'photo_current_uri', 'name', 'roll_no', 'branch', 'hostel', 'lives_in', 'email']
        
        # Filter to ensure columns exist
        cols_icons = [c for c in cols_icons if c in df_display.columns]

        if 'roll_no' not in cols_icons: 
            # Should be there, but just in case
            pass 
            
        df_view_icons = df_display[cols_icons].copy()
        
        # Add visual "Edit" column conditionally
        current_user_roll = st.session_state['user_info']['roll_no']
        df_view_icons.insert(0, "Edit", df_view_icons['roll_no'].apply(lambda x: "✏️" if x == current_user_roll else ""))
        
        styled_df_icons = df_view_icons.style.apply(highlight_user, axis=1)
        
        event_icons = st.dataframe(
            styled_df_icons,
            column_config={
                "id": None,
                "Edit": st.column_config.Column("Edit", width="small", help="Click row to edit"),
                "photo_1966_uri": st.column_config.ImageColumn("1966 Photo", width="small"),
                "photo_current_uri": st.column_config.ImageColumn("Current Photo", width="small"),
                "name": "Name",
                "roll_no": "Roll No",
                "branch": "Branch",
                "hostel": "Hostel",
                "lives_in": "Lives In",
                "email": "Email"
            },
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"icon_df_{st.session_state['table_key']}"
        )

        if len(event_icons.selection.rows) > 0:
            selected_row_index_icons = event_icons.selection.rows[0]
            selected_row_icons = df_view_icons.iloc[selected_row_index_icons]
            
            full_row = filtered_df[filtered_df['id'] == selected_row_icons['id']].iloc[0]
            
            current_user_roll = st.session_state['user_info']['roll_no']
            
            if current_user_roll == full_row['roll_no']:
                 edit_dialog(full_row)
            else:
                 st.warning(f"You can only edit your own details (Roll No: {current_user_roll}).")

    elif view_mode == "Global Map":
        # Use placeholder for dynamic header based on selection
        header_ph = st.empty()

        import random # Import locally to avoid massive file diff just for top-level import

        # Hostel Coordinates (Refined Zones)
        # Himalaya Zone (Central): Godavari, Narmada, Saraswati, Tapti, Pampa
        # Ganga Zone (South-East): Ganga, Jamuna, Mandakini, Alakananda
        # Stadium/North Zone: Cauvery, Krishna, Mahanadi, Tamiraparani, Brahmaputra
        # Ladies: Sarayu/Sharavati (Located distinctly)
        
        @st.cache_data(ttl=3600)
        def get_hostel_coordinates_from_db():
            conn = get_db_connection()
            coords = {}
            if not conn:
                return coords
            
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT hostel_name, latitude, longitude FROM hostel_coordinates")
                rows = cursor.fetchall()
                for row in rows:
                    # Assuming schema: hostel_name, latitude, longitude
                    # row[0] is name, row[1] is lat, row[2] is lon
                    # Convert Decimals to float if necessary, though Folium handles floats best
                    h_name = row[0].strip()
                    lat = float(row[1])
                    lon = float(row[2])
                    coords[h_name] = [lat, lon]
            except Exception as e:
                print(f"Error fetching hostel coordinates: {e}")
            finally:
                cursor.close()
                conn.close()
            return coords

        HOSTEL_COORDINATES = get_hostel_coordinates_from_db()
        
        # View Toggle
        map_view_type = st.radio("Map View Mode:", ["By Residency (Global)", "By Hostel (Campus)"], horizontal=True)

        if map_view_type == "By Residency (Global)":
            header_ph.header(f"🌍 Global Alumni Map - {selected_branch}")
            st.markdown("Map shows locations of graduates based on their 'Lives In', 'State', and 'Country'. Overlapping markers are clustered; click to expand.")
            
            # 1. Fetch Location Data (Cached)
            loc_df = get_all_location_data()

                
            if not loc_df.empty and not filtered_df.empty:
                # 2. Merge with Filtered Graduates
                # filtered_df has the current filters applied (Branch, Search)
                # We merge on roll_no
                map_data = pd.merge(filtered_df, loc_df[['roll_no', 'latitude', 'longitude']], on='roll_no', how='inner')
                
                # Filter out invalid lat/lon
                map_data = map_data.dropna(subset=['latitude', 'longitude'])
                
                if map_data.empty:
                     st.warning("No location data found for the selected graduates.")
                else:
                    # Layout: Map (Left), Controls (Right)
                     col_map, col_controls = st.columns([4, 1])
                     
                     selected_user_loc = None
                     zoom_level = 2
                     center_coords = [20, 0]

                     with col_controls:
                         st.subheader("Find Graduate")
                         # Prepare list for dropdown
                         # Sort by name
                         map_data_sorted = map_data.sort_values(by='name')
                         options = map_data_sorted['name'].tolist()
                         options.insert(0, "Select a Name...")
                         
                         target_name = st.selectbox("Select Name to Locate", options)
                         
                         if target_name != "Select a Name...":
                             user_row = map_data_sorted[map_data_sorted['name'] == target_name].iloc[0]
                             st.info(f"Locating {target_name}...")
                             st.write(f"**Lives in:** {user_row['lives_in']}, {user_row['state']}, {user_row['country']}")
                             
                             # Set map center and zoom
                             center_coords = [user_row['latitude'], user_row['longitude']]
                             zoom_level = 10
                             selected_user_loc = user_row
                     
                     with col_map:
                         st.write(f"Showing **{len(map_data)}** graduates on the map.")
                         
                         # 3. Create Map (Simple Version)
                         m = folium.Map(location=center_coords, zoom_start=zoom_level, tiles='OpenStreetMap')
                         
                         
                         # Cluster
                         marker_cluster = MarkerCluster(
                             spiderfyOnMaxZoom=True,
                             spiderfyDistanceMultiplier=2,
                             zoomToBoundsOnClick=True
                         ).add_to(m)
                         
                         for _, row in map_data.iterrows():
                             # Popup Content
                             # Image
                             img_uri = ""
                             if row['photo_current']:
                                 try:
                                     # Optimize: Resize image for thumbnail in popup
                                     resized_bytes = resize_image_for_map(row['photo_current'], 100)
                                     if resized_bytes:
                                         b64 = base64.b64encode(resized_bytes).decode('utf-8')
                                         img_uri = f'<img src="data:image/jpeg;base64,{b64}" width="100px" style="border-radius: 5px; margin-bottom: 5px;"><br>'
                                 except: pass
                             
                             lives_in_str = f"{row['lives_in']}, {row['state']}" if row['lives_in'] else row['state']
                             
                             popup_html = f"""
                             <div style="font-family: sans-serif; width: 200px;">
                                {img_uri}
                                <b style="font-size: 14px;">{row['name']}</b><br>
                                <span style="color: #666; font-size: 12px;">{row['roll_no']}</span><br>
                                <span style="color: #2e86de; font-weight: bold;">Branch: {row['branch']}</span><br>
                                <span style="font-size: 12px;">Hostel: {row['hostel']}</span><br>
                                <span style="font-size: 12px;">📍 {lives_in_str}</span>
                             </div>
                             """
                             
                             # Special handling for selected user to ensure visibility and popup
                             is_selected = False
                             if selected_user_loc is not None and row['roll_no'] == selected_user_loc['roll_no']:
                                 is_selected = True
                                 
                             # Create Marker
                             marker = folium.CircleMarker(
                                location=[row['latitude'], row['longitude']],
                                radius=6 if not is_selected else 9, # Larger if selected
                                color='#e74c3c' if not is_selected else '#27ae60', # Green if selected
                                fill=True,
                                fill_color='#e74c3c' if not is_selected else '#27ae60',
                                fill_opacity=0.8,
                                popup=folium.Popup(popup_html, max_width=250, show=is_selected) # Auto open if selected
                             )
                             
                             if is_selected:
                                 # Add directly to map to behave as "overlay" and ensure popup opens unclustered
                                 marker.add_to(m)
                             else:
                                 marker.add_to(marker_cluster)
                             
                         # Render Map
                         # Using width=None allows the map to fill the column width responsive
                         st_folium(m, width=1000, height=600, key=f"map_global_{selected_branch}")
                     
            else:
                if loc_df.empty:
                    st.warning("Location data not loaded from database.")
                else:
                    st.info("No graduates found for current filter.")

        elif map_view_type == "By Hostel (Campus)":
            st.markdown("Map shows graduates clustered by their Hostel. Click clusters to spiral view.")
            
            # Prepare Hostel Data
            # Start with filtered_df
            hostel_df = filtered_df.copy()
            
            # Filter valid hostels
            # Check if hostel is in our coordinates map or generic
            # Only keep rows where hostel is present
            hostel_df = hostel_df.dropna(subset=['hostel'])
            hostel_df = hostel_df[hostel_df['hostel'] != ""]
            
            # Get list of unique hostels for dropdown
            unique_hostels = sorted(hostel_df['hostel'].unique().tolist())
            # User Request: Remove "All Hostels" to prevent flickering/performance issues
            # unique_hostels.insert(0, "All Hostels") 
            
            # Layout
            col_map_h, col_controls_h = st.columns([4, 1])
            
            selected_hostel_filter = unique_hostels[0] if unique_hostels else None
            
            with col_controls_h:
                st.subheader("Filter Hostel")
                if unique_hostels:
                    selected_hostel_filter = st.selectbox("Select Hostel", unique_hostels)
                else:
                    st.write("No hostels data available.")
                
            # Update Header with Selection
            if selected_hostel_filter:
                if selected_branch != "All":
                    header_ph.header(f"🌍 Global Alumni Map - {selected_hostel_filter} - {selected_branch}")
                else:
                    header_ph.header(f"🌍 Global Alumni Map - {selected_hostel_filter}")

            # Apply Filter
            # Always filter by the specific hostel
            if selected_hostel_filter:
                hostel_df = hostel_df[hostel_df['hostel'] == selected_hostel_filter]

            if hostel_df.empty:
                st.info("No graduates found for this hostel selection.")
            else:
                with col_map_h:
                    # Center on specific hostel zone if possible, or campus center
                    # We can pick the coordinate of the selected hostel to center map
                    center_h = [12.9915, 80.2336]
                    if selected_hostel_filter and selected_hostel_filter in HOSTEL_COORDINATES:
                        center_h = HOSTEL_COORDINATES[selected_hostel_filter]

                    m_hostel = folium.Map(location=center_h, zoom_start=16, tiles='OpenStreetMap')
                    
                    # Cluster
                    # We want the spiral effect, so we use MarkerCluster with specific options
                    # disableClusteringAtZoom can be set high so it always spiderfies or clusters
                    
                    marker_cluster_h = MarkerCluster(
                        spiderfyOnMaxZoom=True,
                         spiderfyDistanceMultiplier=2,
                         zoomToBoundsOnClick=True # Enable zoom interactions, let spiderfy take over at max zoom
                    ).add_to(m_hostel)
                    
                    for _, row in hostel_df.iterrows():
                        h_name = row['hostel']
                        
                        # Get coords
                        # Strip whitespace and title case just in case
                        h_key = h_name.strip() if h_name else ""
                        
                        # Fallback coords if not in list (center of campus + small jitter?)
                        base_coords = HOSTEL_COORDINATES.get(h_key, [12.9915, 80.2336])
                        
                        # Add Jitter (Approx +/- 5-10 meters)
                        # Use deterministic seed based on Roll No to prevent flickering on reruns
                        # 0.0001 deg ~ 11m
                        rng = random.Random(row['roll_no']) 
                        lat_jitter = rng.uniform(-0.0001, 0.0001)
                        lon_jitter = rng.uniform(-0.0001, 0.0001)
                        
                        coords = [base_coords[0] + lat_jitter, base_coords[1] + lon_jitter]
                        
                        # Popup
                        img_uri = ""
                        if row['photo_current']:
                             try:
                                 resized_bytes = resize_image_for_map(row['photo_current'], 100)
                                 if resized_bytes:
                                     b64 = base64.b64encode(resized_bytes).decode('utf-8')
                                     img_uri = f'<img src="data:image/jpeg;base64,{b64}" width="100px" style="border-radius: 5px; margin-bottom: 5px;"><br>'
                             except: pass
                        
                        popup_html = f"""
                         <div style="font-family: sans-serif; width: 200px;">
                            {img_uri}
                            <b style="font-size: 14px;">{row['name']}</b><br>
                            <span style="color: #666; font-size: 12px;">{row['roll_no']}</span><br>
                            <span style="color: #e67e22; font-weight: bold;">Hostel: {h_name}</span><br>
                            <span style="color: #2e86de; font-weight: bold;">Branch: {row['branch']}</span>
                         </div>
                         """
                        
                        folium.Marker(
                            location=coords,
                            popup=folium.Popup(popup_html, max_width=250),
                            icon=folium.Icon(color='blue', icon='user', prefix='fa')
                        ).add_to(marker_cluster_h)

                    st_folium(m_hostel, width=1000, height=600, key=f"map_hostel_{selected_hostel_filter}", returned_objects=[])

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

        def create_post(roll_no, author_name, title, description, link, photo):
            conn = get_db_connection()
            if not conn: return False
            cursor = conn.cursor()
            try:
                sql = "INSERT INTO posts (roll_no, author_name, title, description, link, photo) VALUES (%s, %s, %s, %s, %s, %s)"
                cursor.execute(sql, (roll_no, author_name, title, description, link, photo))
                conn.commit()
                return True
            except Exception as e:
                st.error(f"Error creating post: {e}")
                return False
            finally:
                cursor.close()
                conn.close()

        def update_post_db(post_id, title, description, link, photo):
            post_id = int(post_id)
            conn = get_db_connection()
            if not conn: return False
            cursor = conn.cursor()
            try:
                if photo is not None:
                    sql = "UPDATE posts SET title=%s, description=%s, link=%s, photo=%s WHERE id=%s"
                    cursor.execute(sql, (title, description, link, photo, post_id))
                else:
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
            post_id = int(post_id)
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
                photo_file = st.file_uploader("Upload Photo (Optional)", type=['jpg', 'jpeg', 'png'])
                
                if st.form_submit_button("Post Item"):
                    if not title:
                        st.error("Title is required.")
                    else:
                        photo_bytes = None
                        if photo_file:
                            photo_bytes = photo_file.getvalue()

                        c_user = st.session_state['user_info']
                        success = create_post(c_user['roll_no'], c_user['name'], title, description, link, photo_bytes)
                        if success:
                            st.success("Item posted!")
                            st.rerun()

        @st.dialog("Edit Item")
        def edit_post_dialog(post_row):
            with st.form("edit_post_form"):
                title = st.text_input("Title", value=post_row['title'], max_chars=255)
                description = st.text_area("Description", value=post_row['description'])
                link = st.text_input("Link (Optional)", value=post_row['link'] if post_row['link'] else "")
                
                st.markdown("Current Photo:")
                if post_row['photo']:
                     st.image(get_image_from_blob(post_row['photo']), width=100)
                else:
                    st.text("No photo uploaded")

                photo_file = st.file_uploader("Change Photo (Optional)", type=['jpg', 'jpeg', 'png'])
                
                if st.form_submit_button("Save Changes"):
                    if not title:
                        st.error("Title is required.")
                    else:
                        photo_bytes = None
                        if photo_file:
                            photo_bytes = photo_file.getvalue()
                            
                        success = update_post_db(post_row['id'], title, description, link, photo_bytes)
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
            # Display as Expandable List
            for _, row in posts_df.iterrows():
                # Expander Header
                expander_title = f"{row['title']} | {row['author_name']} ({row['created_at']})"
                
                with st.expander(expander_title):
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
                    
                    if row['photo']:
                        img = get_image_from_blob(row['photo'])
                        if img:
                            st.image(img, caption=row['title']) # Display at original size

                    if row['link']:
                        st.markdown(f"🔗 [Link]({row['link']})")


    elif view_mode == "Missing Contacts":
        st.markdown("<h1 style='text-align: center; color: #d35400;'>🔍 Help Us Find 🔍</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; font-style: italic; color: #777;'>We would love to renew contact with these batchmates.</p>", unsafe_allow_html=True)
        st.markdown("---")

        def get_tracked_data():
            conn = get_db_connection()
            if not conn: return []
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute("SELECT * FROM tracked ORDER BY name")
                return cursor.fetchall()
            except:
                return []
            finally:
                cursor.close()
                conn.close()

        tracked_data = get_tracked_data()

        if not tracked_data:
            st.info("No records found.")
        else:
            cols = st.columns(3)
            
            st.markdown("""
            <style>
            .tracked-card {
                background-color: #fff8e1; /* Light amber */
                padding: 20px;
                border-radius: 15px;
                border: 1px solid #ffe082;
                margin-bottom: 20px;
                text-align: center;
                box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            }
            .tracked-name {
                font-size: 1.25em;
                font-weight: bold;
                color: #e67e22;
                margin-top: 10px;
            }
            .tracked-details {
                color: #555;
                font-size: 0.9em;
                margin-top: 5px;
            }
            </style>
            """, unsafe_allow_html=True)

            for idx, row in enumerate(tracked_data):
                col = cols[idx % 3]
                with col:
                    st.markdown('<div class="tracked-card">', unsafe_allow_html=True)
                    
                    if row['photo']:
                        photo = get_image_from_blob(row['photo'])
                        if photo:
                            st.image(photo, width=130)
                        else:
                            st.text("No Photo")
                    else:
                        # Placeholder for text-only
                        st.markdown("<div style='font-size:3em;'>👤</div>", unsafe_allow_html=True)
                    
                    st.markdown(f"""
                        <div class="tracked-name">{row['name']}</div>
                        <div class="tracked-details">
                            <b>{row['branch']}</b><br>
                            Roll No: {row['roll_no']}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

    elif view_mode == "In Memoriam":
        st.markdown("<h1 style='text-align: center; color: #555;'>🌹 In Loving Memory 🌹</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; font-style: italic; color: #777;'>Remembering our batchmates who are no longer with us.</p>", unsafe_allow_html=True)
        st.markdown("---")

        def get_memoriam_data():
            conn = get_db_connection()
            if not conn: return []
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute("SELECT * FROM memoriam ORDER BY name")
                return cursor.fetchall()
            except:
                return []
            finally:
                cursor.close()
                conn.close()

        mem_data = get_memoriam_data()
        
        if not mem_data:
            st.info("No records found.")
        else:
            # Grid Layout
            cols = st.columns(3)
            
            # Custom CSS for memoriam cards
            st.markdown("""
            <style>
            .memoriam-card {
                background-color: #fff0f5; /* Lavender Blush key */
                padding: 20px;
                border-radius: 15px;
                border: 1px solid #eebbcc;
                margin-bottom: 20px;
                text-align: center;
                box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            }
            .mem-name {
                font-size: 1.3em;
                font-weight: bold;
                color: #4a4a4a;
                margin-top: 10px;
            }
            .mem-details {
                color: #666;
                font-size: 0.95em;
                margin-top: 5px;
            }
            .flower-icon {
                font-size: 1.2em;
            }
            </style>
            """, unsafe_allow_html=True)

            for idx, row in enumerate(mem_data):
                col = cols[idx % 3]
                with col:
                    with st.container():
                        # We use a container to apply the visual style implicitly via the card logic or directly elements
                        # Since st.markdown(unsafe_allow_html) for div wrapping is tricky with st.image
                        # We will use st.card-like structure
                        
                        # Render the card start
                        st.markdown('<div class="memoriam-card">', unsafe_allow_html=True)
                        
                        # Image
                        photo = get_image_from_blob(row['photo'])
                        if photo:
                            st.image(photo, width=150) # Centered by default in Streamlit column if we don't use 'width' too specific or column width
                        else:
                            st.text("No Photo")
                        
                        st.markdown(f"""
                            <div class="mem-name">{row['name']} <span class="flower-icon">🕊️</span></div>
                            <div class="mem-details">
                                <b>{row['branch']}</b><br>
                                Roll No: {row['roll_no']}
                            </div>
                            <div style="margin-top:10px; font-size:1.5em;">💐</div>
                        </div>
                        """, unsafe_allow_html=True)

    elif view_mode == "Reunion Photo Album":
        st.header("📸 Reunion Photo Album")
        st.info("📝 Note: Viewers can edit the description by clicking the pencil icon (✏️) on any photo card. Feel free to include names, memories, and stories!")
        st.markdown("Share your memories with the batch! Upload photos (max 5MB).")
        st.markdown("---")

        # Initialize Session State for Pagination
        if 'album_page' not in st.session_state:
            st.session_state['album_page'] = 0

        # Helper to sync pagination across all widgets
        def set_page(page_index):
            st.session_state['album_page'] = page_index
            st.session_state['page_select_top'] = page_index + 1
            st.session_state['page_select_bot'] = page_index + 1

        # Handle Force Reset (e.g. after upload)
        if st.session_state.get('force_page_zero'):
            set_page(0)
            del st.session_state['force_page_zero']

        # Database Helpers for Album
        def get_photos_paginated(limit, offset):
            conn = get_db_connection()
            if not conn: return []
            cursor = conn.cursor(dictionary=True)
            try:
                # Use LIMIT and OFFSET on 'photos' table
                # Map columns: image_data -> photo, filename, description, upload_date -> created_at
                cursor.execute("SELECT id, image_data as photo, filename, description, upload_date as created_at FROM photos ORDER BY upload_date DESC LIMIT %s OFFSET %s", (limit, offset))
                rows = cursor.fetchall()
                # Add default values for missing columns to avoid UI errors
                for row in rows:
                    if 'uploader_name' not in row: row['uploader_name'] = 'Batchmate'
                    if 'roll_no' not in row: row['roll_no'] = None
                    # Set caption for backward compatibility if needed, but we'll use filename/description logic
                    row['caption'] = row['description'] if row['description'] else row['filename']
                return rows
            except: return []
            finally: 
                cursor.close()
                conn.close()

        def get_total_photo_count():
            conn = get_db_connection()
            if not conn: return 0
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM photos")
                return cursor.fetchone()[0]
            except: return 0
            finally:
                cursor.close()
                conn.close()

        def save_album_photo(roll_no, uploader_name, photo_bytes, caption):
            conn = get_db_connection()
            if not conn: return False
            cursor = conn.cursor()
            try:
                # Insert into photos table
                # caption -> filename (or generate one)
                filename = caption if caption else f"upload_{int(time.time())}.jpg"
                sql = "INSERT INTO photos (filename, image_data, upload_date) VALUES (%s, %s, NOW())"
                cursor.execute(sql, (filename, photo_bytes))
                conn.commit()
                return True
            except Exception as e:
                st.error(f"Error saving photo: {e}")
                return False
            finally:
                cursor.close()
                conn.close()

        def delete_album_photo(photo_id):
            conn = get_db_connection()
            if not conn: return False
            cursor = conn.cursor()
            try:
                sql = "DELETE FROM photos WHERE id = %s"
                cursor.execute(sql, (photo_id,))
                conn.commit()
                return True
            except: return False
            finally:
                cursor.close()
                conn.close()
        
        def update_photo_description(photo_id, description):
            conn = get_db_connection()
            if not conn: return False
            cursor = conn.cursor()
            try:
                sql = "UPDATE photos SET description = %s WHERE id = %s"
                cursor.execute(sql, (description, photo_id))
                conn.commit()
                return True
            except Exception as e:
                st.error(f"Error updating description: {e}")
                return False
            finally:
                cursor.close()
                conn.close()



        # Custom CSS for Fancy Album
        st.markdown("""
        <style>
        .photo-card {
            background-color: white;
            border-radius: 15px;
            padding: 15px;
            box-shadow: 0 10px 20px rgba(0,0,0,0.19), 0 6px 6px rgba(0,0,0,0.23);
            transition: all 0.3s cubic-bezier(.25,.8,.25,1);
            margin-bottom: 20px;
            text-align: center;
        }
        .photo-card:hover {
            transform: scale(1.02);
            box-shadow: 0 14px 28px rgba(0,0,0,0.25), 0 10px 10px rgba(0,0,0,0.22);
        }
        .photo-caption {
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 1.1em;
            color: #333;
            margin-top: 10px;
            font-weight: 500;
        }
        .photo-meta {
            font-size: 0.85em;
            color: #777;
            margin-top: 5px;
            font-style: italic;
        }
        </style>
        """, unsafe_allow_html=True)

        # UI: Gallery Section (Moved Above Upload)
        ITEMS_PER_PAGE = 10
        total_photos = get_total_photo_count()
        
        # Calculate max pages
        import math
        total_pages = math.ceil(total_photos / ITEMS_PER_PAGE)
        if total_pages == 0: total_pages = 1
        
        # Validate current page
        if st.session_state['album_page'] >= total_pages:
             st.session_state['album_page'] = total_pages - 1
        if st.session_state['album_page'] < 0:
             st.session_state['album_page'] = 0
             
        current_page = st.session_state['album_page']
        offset = current_page * ITEMS_PER_PAGE
        
        # Fetch Photos
        photos = get_photos_paginated(ITEMS_PER_PAGE, offset)
        
        if not photos:
            st.info("No photos shared yet. Be the first!")
        else:
            # Pagination Controls (Top)
            c_prev, c_info, c_next = st.columns([1, 2, 1])
            
            # Callback for page selection
            def update_page_top():
                # Value will be "Page X"
                # But we can just use index referencing or parse the string if needed.
                # Actually, simpler: Use numbers 1..N and logic.
                pass 
            
            with c_prev:
                if current_page > 0:
                    st.button("⬅️ Previous 10", key="prev_top", on_click=set_page, args=(current_page - 1,))
            with c_info:
                # Page Selector
                page_options = list(range(1, total_pages + 1))
                
                def on_page_select_top():
                    new_val = st.session_state['page_select_top']
                    set_page(new_val - 1)

                st.selectbox(
                    "Go to Page", 
                    page_options, 
                    index=current_page,
                    key="page_select_top",
                    on_change=on_page_select_top
                )
                
            with c_next:
                if (current_page + 1) < total_pages:
                    st.button("Next 10 ➡️", key="next_top", on_click=set_page, args=(current_page + 1,))

            st.write("") # Spacer

            # Gallery Grid
            cols = st.columns(2)
            
            # Dialog for editing description
            @st.dialog("Edit Photo Description")
            def edit_description_dialog(photo_id, current_desc, filename):
                st.write(f"Filename: {filename}")
                new_desc = st.text_area("Description (List names, memories, etc.)", value=current_desc if current_desc else "", height=150)
                if st.button("Save"):
                    if update_photo_description(photo_id, new_desc):
                        st.success("Description updated!")
                        st.rerun()
                    else:
                        st.error("Failed to update.")

            current_user_roll = st.session_state['user_info']['roll_no'] if st.session_state.get('logged_in') else None

            for idx, row in enumerate(photos):
                col = cols[idx % 2]
                with col:
                    # Photo Card
                    st.markdown("""<div class="photo-card">""", unsafe_allow_html=True)
                    
                    img = get_image_from_blob(row['photo'])
                    if img:
                        st.image(img, width="stretch")
                    
                    # Display Description or Filename
                    display_text = row['description'] if row['description'] else row['filename']
                    
                    # Layout: Caption + Edit Button
                    c_text, c_edit_btn = st.columns([0.85, 0.15])
                    with c_text:
                         st.markdown(f"<div class='photo-caption'>{display_text}</div>", unsafe_allow_html=True)
                         if 'created_at' in row and row['created_at']:
                            st.markdown(f"<div class='photo-meta'>Uploaded by {row['uploader_name']} on {row['created_at'].strftime('%b %d, %Y')}</div>", unsafe_allow_html=True)
                    with c_edit_btn:
                        # Allow all viewers to edit description as requested
                        if st.button("✏️", key=f"edit_ph_{row['id']}", help="Edit Description"):
                                edit_description_dialog(row['id'], row['description'], row['filename'])

                    st.markdown("</div>", unsafe_allow_html=True)
                    
                    # Delete Button - Keep ownership check (will only work if we start tracking roll_no, or if logic changes)
                    # Currently effectively disables delete for non-tracked photos, which is safe.
                    if current_user_roll == row['roll_no']:
                        if st.button("Delete Photo", key=f"del_alb_{row['id']}", type="secondary"):
                            if delete_album_photo(row['id']):
                                st.success("Deleted!")
                                st.rerun()

            # Pagination Controls (Bottom)
            st.markdown("---")
            b_prev, b_info, b_next = st.columns([1, 2, 1])
            with b_prev:
                if current_page > 0:
                    st.button("⬅️ Previous 10", key="prev_bot", on_click=set_page, args=(current_page - 1,))

            with b_info:
                 # Page Selector Bottom
                 def on_page_select_bot():
                    new_val = st.session_state['page_select_bot']
                    set_page(new_val - 1)

                 st.selectbox(
                    "Go to Page", 
                    page_options, 
                    index=current_page,
                    key="page_select_bot",
                    on_change=on_page_select_bot
                )
            with b_next:
                 if (current_page + 1) < total_pages:
                    st.button("Next 10 ➡️", key="next_bot", on_click=set_page, args=(current_page + 1,))

        # UI: Upload Section (Moved Below)
        st.markdown("<br>", unsafe_allow_html=True)
        if st.session_state.get('logged_in'):
            with st.expander("📤 Upload New Photo", expanded=False):
                with st.form("upload_photo_form"):
                    st.write("Add your own memories to the album!")
                    caption = st.text_input("Caption (Optional)", max_chars=100)
                    photo_file = st.file_uploader("Choose a Photo (Max 5MB)", type=['jpg', 'jpeg', 'png'])
                    
                    if st.form_submit_button("Upload Photo"):
                        if not photo_file:
                            st.error("Please select a file.")
                        elif photo_file.size > 5242880:
                            st.error("File size exceeds 5MB limit. Please upload a smaller file.")
                        else:
                            photo_bytes = photo_file.getvalue()
                            user = st.session_state['user_info']
                            if save_album_photo(user['roll_no'], user['name'], photo_bytes, caption):
                                st.success("Photo uploaded successfully!")
                                # Reset page to 0 to see new upload? Or stay? 
                                # Usually better to stay or go to page 0. Let's go to page 0 to see it (since we order by created_at DESC).
                                # Use flag to safely reset state on next run
                                st.session_state['force_page_zero'] = True
                                st.rerun()
        else:
            st.info("Please login to upload photos.")

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
                    st.write("Generating In Memoriam Report...")
                    generate_memoriam_pdf("IITM_1971_In_Memoriam.pdf")
                    st.write("Generating Missing Contacts Report...")
                    generate_missing_pdf("IITM_1971_Missing_Contacts.pdf")
                    
                    status.update(label="Generation Complete!", state="complete", expanded=False)
                st.success("Reports generated and saved to DB successfully!")
                get_report_from_db.clear() # Clear cache
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
             # Complete Report
             rep_name = "IITM_1971_Graduates_Complete_Report.pdf"
             data, ts = get_report_from_db(rep_name)
             if data:
                 ts_str = ts.strftime('%Y-%m-%d %H:%M') if ts else ""
                 label = f"📄 Complete Report (PDF) - [{ts_str}]"
                 st.download_button(
                     label=label,
                     data=data,
                     file_name=rep_name,
                     mime="application/pdf",
                     width="stretch"
                 )
             else:
                 st.info("Complete Report not found in DB.")

        with c2:
             # Photo Directory
             rep_name = "IITM_1971_Graduates_Directory.pdf"
             data, ts = get_report_from_db(rep_name)
             if data:
                 ts_str = ts.strftime('%Y-%m-%d %H:%M') if ts else ""
                 label = f"🖼️ Photo Directory Only - [{ts_str}]"
                 st.download_button(
                     label=label,
                     data=data,
                     file_name=rep_name,
                     mime="application/pdf",
                     width="stretch"
                 )
             else:
                 st.info("Photo Directory not found in DB.")

        with c3:
             # Text Roster
             rep_name = "IITM_1971_Graduates_List.pdf"
             data, ts = get_report_from_db(rep_name)
             if data:
                 ts_str = ts.strftime('%Y-%m-%d %H:%M') if ts else ""
                 label = f"📝 Text Roster Only - [{ts_str}]"
                 st.download_button(
                     label=label,
                     data=data,
                     file_name=rep_name,
                     mime="application/pdf",
                     width="stretch"
                 )
             else:
                 st.info("Text Roster not found in DB.")

        # Second Row of Downloads
        st.markdown("<br>", unsafe_allow_html=True)
        rc1, rc2 = st.columns(2)
        
        with rc1:
             # In Memoriam
             rep_name = "IITM_1971_In_Memoriam.pdf"
             data, ts = get_report_from_db(rep_name)
             if data:
                 ts_str = ts.strftime('%Y-%m-%d %H:%M') if ts else ""
                 label = f"🌹 In Memoriam (PDF) - [{ts_str}]"
                 st.download_button(
                     label=label,
                     data=data,
                     file_name=rep_name,
                     mime="application/pdf",
                     width="stretch"
                 )
             else:
                 st.info("In Memoriam report not found in DB.")

        with rc2:
             # Missing Contacts
             rep_name = "IITM_1971_Missing_Contacts.pdf"
             data, ts = get_report_from_db(rep_name)
             if data:
                 ts_str = ts.strftime('%Y-%m-%d %H:%M') if ts else ""
                 label = f"🔍 Missing Contacts (PDF) - [{ts_str}]"
                 st.download_button(
                     label=label,
                     data=data,
                     file_name=rep_name,
                     mime="application/pdf",
                     width="stretch"
                 )
             else:
                 st.info("Missing Contacts report not found in DB.")

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


