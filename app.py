"""
Academic Scheduling Tool - Optimized Streamlit Application

Key optimizations:
1. Database status check is cached (not checked on every rerun)
2. Heavy imports are deferred until needed
3. Demand summary computed once and cached
4. No repeated database calls on widget interactions
5. Disk caching for session persistence across restarts
"""

import streamlit as st
import pandas as pd
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import course display helpers
from logic.course_matching import load_requirements, format_course_with_title, get_course_title

st.set_page_config(
    page_title="Academic Scheduling Tool",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def check_login():
    """Check if user is authenticated."""
    return st.session_state.get("authenticated", False)


def login_page():
    """Display login page."""
    st.title("🎓 Academic Scheduling Tool")
    st.subheader("Admin Login")

    # Center the login form
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login", type="primary", width="stretch")

            if submit:
                admin_user = os.getenv("ADMIN_USERNAME", "admin")
                admin_pass = os.getenv("ADMIN_PASSWORD", "admin")

                if username == admin_user and password == admin_pass:
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = username
                    st.rerun()
                else:
                    st.error("Invalid username or password")

        st.caption("Contact IT support if you need access.")


def load_cached_session():
    """Load cached session data on startup."""
    if "cache_loaded" not in st.session_state:
        from logic.cache import load_session_data
        cached = load_session_data()
        if cached:
            for key, value in cached.items():
                if key != "saved_at" and value is not None:
                    st.session_state[key] = value
            st.session_state["cache_loaded"] = True
            st.session_state["cache_saved_at"] = cached.get("saved_at")
        else:
            st.session_state["cache_loaded"] = True


def save_current_session():
    """Save current session to disk."""
    from logic.cache import save_session_data
    save_session_data(st.session_state)
    # Show brief confirmation toast
    st.toast("✓ Changes saved", icon="✅")


# Load cache on startup
load_cached_session()


def render_matrix_issues(issues):
    """Show students the needs matrix could not account for.

    These students appear in the matrix with zero required courses, which is
    indistinguishable from a student who genuinely needs nothing. Surfacing
    them here stops that from passing as a real result.
    """
    if not issues:
        return

    if issues.get("requirements_missing"):
        st.error(
            "Could not load the requirements file. Every student will show zero "
            "required courses until this is fixed."
        )

    unmapped = issues.get("unmapped") or []
    if not unmapped:
        return

    unmapped_df = pd.DataFrame(unmapped)
    prefix_counts = (
        unmapped_df.groupby("Prefix").size().sort_values(ascending=False)
    )
    prefix_summary = ", ".join(
        f"{prefix} ({count})" for prefix, count in prefix_counts.items()
    )

    st.warning(
        f"**{len(unmapped_df)} students show no required courses because their "
        f"major code is not in the curriculum file.** Unrecognized prefixes: "
        f"{prefix_summary}. Their numbers are missing from the demand counts below."
    )
    with st.expander(f"Show the {len(unmapped_df)} affected students"):
        st.caption(
            "Fix by correcting BatchIDForDoctor for these students, or by adding "
            "the prefix as a column in the curriculum requirements file."
        )
        st.dataframe(
            unmapped_df[["StudentId", "Name", "Major", "Prefix"]],
            width="stretch",
            hide_index=True,
        )
        st.download_button(
            "Download as CSV",
            unmapped_df.to_csv(index=False).encode("utf-8"),
            file_name="unmapped_students.csv",
            mime="text/csv",
        )


def remove_student_from_roster(course: str, student_id: str):
    """Remove a student from a specific course roster."""
    if "rosters" in st.session_state and course in st.session_state["rosters"]:
        st.session_state["rosters"][course] = [
            s for s in st.session_state["rosters"][course]
            if s["StudentId"] != student_id
        ]
        # Auto-save after roster change
        save_current_session()


@st.cache_data(ttl=30, show_spinner=False)  # Cache for 30 seconds
def check_db_status():
    """Check database connection status - CACHED to avoid repeated connections."""
    try:
        from database.connection import get_db_connection
        conn = get_db_connection()
        conn.close()
        return True, None
    except Exception as e:
        return False, str(e)


def main():
    st.title("🎓 Academic Scheduling Tool")

    # Sidebar for navigation and global settings
    with st.sidebar:
        # Show logged in user and logout button
        st.caption(f"👤 Logged in as: **{st.session_state.get('username', 'Admin')}**")
        if st.button("🚪 Logout", width="stretch"):
            st.session_state["authenticated"] = False
            st.session_state["username"] = None
            st.rerun()

        st.divider()
        st.header("Navigation")
        app_mode = st.radio("Go to", ["Admin Dashboard", "Student Portal"])

        st.divider()
        st.header("System Status")

        # Cached DB check - won't hit DB on every rerun
        is_connected, error_msg = check_db_status()
        if is_connected:
            st.write("Database: 🟢 Connected")
        else:
            st.write("Database: 🔴 Disconnected")
            if error_msg:
                st.error(f"Error: {error_msg}")

        # Button to force refresh DB status
        if st.button("🔄 Refresh Status", key="refresh_db"):
            check_db_status.clear()
            st.rerun()

        st.divider()
        st.header("💾 Session Cache")

        # Show cache status
        from logic.cache import get_cache_info, clear_cache
        cache_info = get_cache_info()

        if cache_info.get("exists"):
            if cache_info.get("saved_at"):
                st.caption(f"Last saved: {cache_info['saved_at'][:19]}")
            if cache_info.get("has_rosters"):
                st.caption(f"Rosters: {cache_info['roster_count']} classes")
        else:
            st.caption("No saved session")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Save", key="save_session", help="Save current work to disk"):
                save_current_session()
                st.success("Saved!")
                st.rerun()
        with col2:
            if st.button("🗑️ Clear", key="clear_cache", help="Delete saved session"):
                clear_cache()
                st.info("Cache cleared")
                st.rerun()

        st.divider()
        st.header("📸 Backup Snapshots")

        # Import backup functions
        from logic.cache import create_backup, list_backups, restore_backup, delete_backup

        # List available backups
        backups = list_backups()

        if backups:
            st.caption(f"{len(backups)} snapshot(s) available")
            
            # Select a backup to restore
            backup_options = {b["timestamp"]: b["filename"] for b in backups}
            selected_time = st.selectbox(
                "Select snapshot",
                options=list(backup_options.keys()),
                key="backup_select",
                label_visibility="collapsed"
            )
            
            if selected_time:
                selected_backup = backup_options[selected_time]
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("📸 Snapshot", key="create_backup", help="Create new backup snapshot"):
                        create_backup(st.session_state)
                        st.success("Backup created!")
                        st.rerun()
                with col2:
                    if st.button("↩️ Restore", key="restore_backup", help="Restore from selected snapshot"):
                        restored_data = restore_backup(selected_backup)
                        if restored_data:
                            for key, value in restored_data.items():
                                if key != "saved_at" and value is not None:
                                    st.session_state[key] = value
                            save_current_session()  # Save restored data to current cache
                            st.success(f"Restored from {selected_time}")
                            st.rerun()
                        else:
                            st.error("Failed to restore backup")
                with col3:
                    if st.button("🗑️ Delete", key="delete_backup", help="Delete selected snapshot"):
                        delete_backup(selected_backup)
                        st.info("Backup deleted")
                        st.rerun()
        else:
            st.caption("No backups yet")
            if st.button("📸 Create First Snapshot", key="create_first_backup", width="stretch"):
                create_backup(st.session_state)
                st.success("First backup created!")
                st.rerun()

    if app_mode == "Admin Dashboard":
        admin_dashboard()
    elif app_mode == "Student Portal":
        student_portal()


def admin_dashboard():
    st.header("Admin Dashboard")

    tabs = st.tabs([
        "Student Selection",
        "Course Matching",
        "Class Rosters",
        "Manage Rosters",
        "Schedule Optimization",
        "Download Rosters",
        "Communications",
        "Student Transcript",
    ])

    with tabs[0]:
        render_student_selection_tab()

    with tabs[1]:
        render_course_matching_tab()

    with tabs[2]:
        render_class_rosters_tab()

    with tabs[3]:
        render_manage_rosters_tab()

    with tabs[4]:
        render_schedule_optimization_tab()

    with tabs[5]:
        render_download_rosters_tab()

    with tabs[6]:
        render_communications_tab()

    with tabs[7]:
        render_student_transcript_tab()


def render_student_selection_tab():
    """Student Selection Tab - with cached data fetching."""
    st.subheader("Select Active Students")
    st.write("Filter students based on recent activity.")

    col1, col2 = st.columns([1, 3])

    with col1:
        months_option = st.selectbox(
            "Activity Period",
            options=[6, 12, 18, 24],
            format_func=lambda x: f"Last {x} months",
            index=0,
        )

        if st.button("Fetch Students", type="primary"):
            with st.spinner("Fetching students from database..."):
                # Import here to avoid loading on every page load
                from logic.student_selection import get_active_students

                # This is now CACHED - subsequent calls with same months_option are instant
                students_df = get_active_students(months_option)
                st.session_state["students_df"] = students_df
                st.session_state["months_option"] = months_option
                save_current_session()  # Auto-save
                st.success(f"Found {len(students_df)} active students.")

        # Select a student to view requirements
        if "students_df" in st.session_state and not st.session_state[
            "students_df"].empty:
            students_df = st.session_state["students_df"]
            st.selectbox(
                "Select Student to View Requirements",
                options=students_df["StudentId"].tolist(),
                format_func=lambda
                    x: f"{x} - {students_df[students_df['StudentId'] == x].iloc[0]['Name']}",
            )
        else:
            st.info("Fetch students first to select one.")

    with col2:
        if "students_df" in st.session_state and not st.session_state[
            "students_df"].empty:
            st.dataframe(
                st.session_state["students_df"],
                width="stretch",
                hide_index=True,
                column_config={
                    "StudentId": "ID",
                    "Name": "Name",
                    "Email": "Email",
                    "MajorCode": "Major Code",
                    "Cohort": "Cohort",
                    "LastActiveDate": st.column_config.DateColumn("Last Active"),
                },
            )
        elif "students_df" in st.session_state:
            st.info("No students found for the selected criteria.")


def render_course_matching_tab():
    """Course Matching Tab - with optimized bulk operations."""
    st.subheader("Match Courses")
    st.write("Match students to required courses.")

    if "students_df" not in st.session_state or st.session_state["students_df"].empty:
        st.warning("Please fetch students in the 'Student Selection' tab first.")
        return

    students_df = st.session_state["students_df"]

    col1, col2 = st.columns([1, 1])

    with col1:
        if st.button("Generate Needs Matrix", type="primary"):
            progress_bar = st.progress(0, text="Starting analysis...")

            def update_progress(current, total, name):
                percent = int((current / total) * 100)
                progress_bar.progress(percent,
                                      text=f"Analyzing {current}/{total}: {name}")

            with st.spinner("Analyzing student requirements..."):
                # Lazy import
                from logic.course_matching import generate_needs_matrix, \
                    compute_demand_summary

                # Generate needs matrix (uses cached bulk operations internally)
                needs_df, matrix_issues = generate_needs_matrix(
                    students_df, progress_callback=update_progress)
                st.session_state["needs_df"] = needs_df
                st.session_state["matrix_issues"] = matrix_issues

                # Compute demand summary ONCE here (cached)
                if not needs_df.empty:
                    # Create a hash for caching
                    df_hash = str(hash(needs_df.to_json()))
                    demand_df = compute_demand_summary(df_hash, needs_df)
                    st.session_state["demand_df"] = demand_df

            progress_bar.empty()
            save_current_session()  # Auto-save
            st.success("Needs Matrix Generated!")

    # Display results (no recomputation needed - just read from session_state)
    if "needs_df" in st.session_state and "demand_df" in st.session_state:
        demand_df = st.session_state["demand_df"].copy()

        render_matrix_issues(st.session_state.get("matrix_issues"))

        st.divider()
        st.subheader("Course Demand & History")
        st.write(
            "All courses with at least 1 student demand are shown. Consider prioritizing high demand and courses not offered recently.")

        if not demand_df.empty:
            # Load requirements for course titles
            requirements_df = load_requirements()
            
            # Add formatted course display column
            demand_df["Course Display"] = demand_df["Course"].apply(
                lambda x: format_course_with_title(x, requirements_df)
            )
            
            sort_col = st.selectbox("Sort by", ["Demand", "Months Ago"], index=0)

            display_df = demand_df.sort_values(by=sort_col, ascending=False)

            # Show total count
            st.caption(f"Showing all {len(display_df)} courses with demand")

            # Reorder columns to show Course Display first
            column_order = ["Course Display", "Demand", "Last Offered", "Months Ago"]
            display_df = display_df[column_order]

            st.dataframe(
                display_df,
                width="stretch",
                height=min(len(display_df) * 35 + 38, 600),  # Dynamic height, max 600px
                column_config={
                    "Course Display": "Course",
                    "Last Offered": st.column_config.DateColumn("Last Offered"),
                    "Demand": st.column_config.ProgressColumn(
                        "Student Demand",
                        min_value=0,
                        max_value=max(demand_df["Demand"]) if len(demand_df) > 0 else 1,
                        format="%d",
                    ),
                },
            )
        else:
            st.info("No course needs identified.")

        with st.expander("View Full Needs Matrix (Students x Courses)"):
            st.dataframe(st.session_state["needs_df"])

        with st.expander("🔍 Debug: Course Demand Breakdown"):
            # Use a copy to avoid modifying the original
            debug_df = st.session_state["needs_df"].copy()
            metadata_cols = ["StudentId", "Name", "Email", "Major", "Cohort", "LastEnroll", "MajorPrefix"]
            course_cols = [c for c in debug_df.columns if c not in metadata_cols]

            st.write(f"**Total students in matrix:** {len(debug_df)}")
            st.write(f"**Total course columns:** {len(course_cols)}")

            # Count demand for ALL courses
            all_demands = []
            for course in course_cols:
                try:
                    count = int(debug_df[course].sum())
                    all_demands.append({"Course": course, "Demand": count})
                except (ValueError, TypeError):
                    pass  # Skip non-numeric columns

            all_demands_df = pd.DataFrame(all_demands).sort_values("Demand", ascending=True)

            # Show courses with zero demand
            zero_demand = all_demands_df[all_demands_df["Demand"] == 0]
            nonzero_demand = all_demands_df[all_demands_df["Demand"] > 0]

            st.write(f"**Courses with 0 demand (all students have taken):** {len(zero_demand)}")
            st.write(f"**Courses with >0 demand (showing in table above):** {len(nonzero_demand)}")

            if len(nonzero_demand) > 0:
                st.write(f"**Demand range:** {nonzero_demand['Demand'].min()} to {nonzero_demand['Demand'].max()}")

            st.write("**All courses sorted by demand (lowest first):**")
            st.dataframe(all_demands_df, width="stretch", height=300)

            # Major distribution (on copy, not original)
            st.write("**Student count by major prefix:**")
            debug_df["MajorPrefix"] = debug_df["Major"].apply(lambda x: x.split("-")[0] if "-" in str(x) else str(x)[:3])
            major_counts = debug_df["MajorPrefix"].value_counts()
            st.dataframe(major_counts, width="stretch")


def render_class_rosters_tab():
    """Class Rosters Tab."""
    st.subheader("Class Rosters")
    st.write("Create classes and assign students.")

    if "needs_df" not in st.session_state:
        st.warning("Please generate the Needs Matrix in the 'Match Courses' tab first.")
        return

    needs_df = st.session_state["needs_df"]

    # Initialize rosters in session state if not present
    if "rosters" not in st.session_state:
        st.session_state["rosters"] = {}

    # Load requirements for course title display
    requirements_df = load_requirements()

    # Get ALL course options from curriculum (not just ones in needs matrix)
    course_options = sorted(requirements_df["course_code"].unique().tolist())
    
    selected_course = st.selectbox(
        "Select Course to Create/Manage",
        options=course_options,
        format_func=lambda x: format_course_with_title(x, requirements_df)
    )

    if selected_course:
        current_roster = st.session_state["rosters"].get(selected_course, [])
        st.info(
            f"Managing Roster for **{selected_course}** - Currently {len(current_roster)} students assigned.")

        # Check if course has any students needing it
        if selected_course not in needs_df.columns:
            st.info(f"**0 students require this course** ({selected_course})")
            st.write("This course is not needed by any current students based on their transcripts and degree requirements.")
        else:
            # Filter Eligible Students
            eligible_students = needs_df[needs_df[selected_course] == 1].copy()

            # Extract major prefix for filtering (e.g., "TES-53E" -> "TES")
            eligible_students["MajorPrefix"] = eligible_students["Major"].apply(
                lambda x: x.split("-")[0] if "-" in str(x) else str(x)[:3]
            )

            # Filter by Major (applied first)
            st.write("**Filter by Major:**")
            selected_major = st.radio(
                "Select Major",
                options=["All", "BUS", "TES", "INT", "TOU", "FIN"],
                horizontal=True,
                label_visibility="collapsed"
            )

            if selected_major != "All":
                # Map display names to actual prefixes
                major_mapping = {
                    "BUS": "BAD",  # Business Administration
                    "TES": "TES",  # TESOL
                    "INT": "INT",  # International Relations
                    "TOU": "THM",  # Tourism and Hospitality Management
                    "FIN": "FIN"   # Finance
                }
                actual_prefix = major_mapping.get(selected_major, selected_major)
                filtered_students = eligible_students[
                    eligible_students["MajorPrefix"] == actual_prefix
                ]
            else:
                filtered_students = eligible_students

            # Filter by Cohort (applied second, after major filter)
            cohorts = sorted(filtered_students["Cohort"].unique().tolist())
            selected_cohort = st.selectbox("Filter by Cohort", ["All"] + cohorts)

            if selected_cohort != "All":
                filtered_students = filtered_students[
                    filtered_students["Cohort"] == selected_cohort]

            # Display Interactive Table
            st.write("### Select Students to Assign")

            display_df = filtered_students[
                ["StudentId", "Name", "Major", "Cohort", "Email"]]

            event = st.dataframe(
                display_df,
                on_select="rerun",
                selection_mode="multi-row",
                width="stretch",
                hide_index=True,
            )

            # Assign Button
            if event.selection.rows:
                selected_indices = event.selection.rows
                selected_rows = display_df.iloc[selected_indices]

                if st.button(f"Assign {len(selected_rows)} Students to Roster"):
                    new_students = []
                    current_ids = [s["StudentId"] for s in current_roster]

                    for _, row in selected_rows.iterrows():
                        student_entry = row.to_dict()
                        if student_entry["StudentId"] not in current_ids:
                            new_students.append(student_entry)

                    st.session_state["rosters"][
                        selected_course] = current_roster + new_students
                    save_current_session()  # Auto-save
                    st.success(
                        f"Added {len(new_students)} students to {selected_course} roster!")
                    st.rerun()

        # View Current Roster
        st.divider()
        st.write(f"### Current Roster for {selected_course} ({len(current_roster)})")

        if current_roster:
            roster_df = pd.DataFrame(current_roster)
            st.dataframe(roster_df, width="stretch", hide_index=True)

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Clear Roster", type="secondary"):
                    st.session_state["rosters"][selected_course] = []
                    save_current_session()  # Auto-save
                    st.rerun()
            with col2:
                csv = roster_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download Roster (CSV)",
                    data=csv,
                    file_name=f"roster_{selected_course}.csv",
                    mime="text/csv",
                )
        else:
            st.info("Roster is empty.")


def render_manage_rosters_tab():
    """Manage Rosters Tab - View all rosters and remove students."""
    st.subheader("Manage Rosters")
    st.write("View and edit all class rosters. Remove students as needed.")

    if "rosters" not in st.session_state or not st.session_state["rosters"]:
        st.warning("No rosters created yet. Go to 'Class Rosters' tab to create some.")
        return

    rosters = st.session_state["rosters"]
    active_rosters = {c: r for c, r in rosters.items() if len(r) > 0}

    if not active_rosters:
        st.info("All rosters are empty. Go to 'Class Rosters' tab to add students.")
        return

    # Get student course counts
    from logic.cache import get_student_course_counts
    student_counts = get_student_course_counts(rosters)

    # Summary stats
    total_assignments = sum(len(r) for r in active_rosters.values())
    unique_students = len(student_counts)
    over_enrolled = [s for s in student_counts.values() if s["count"] > 3]
    under_enrolled = [s for s in student_counts.values() if s["count"] < 3]

    st.info(f"**{len(active_rosters)}** classes | **{unique_students}** unique students | **{total_assignments}** total assignments")

    # Course limit filter section
    st.divider()
    st.subheader("📊 Student Course Load Analysis")
    st.write("Students should have exactly 3 courses per term.")

    filter_col1, filter_col2, filter_col3 = st.columns(3)

    with filter_col1:
        if over_enrolled:
            st.error(f"⚠️ **{len(over_enrolled)}** over-enrolled (>3 courses)")
        else:
            st.success("✅ No over-enrolled students")

    with filter_col2:
        if under_enrolled:
            st.warning(f"📉 **{len(under_enrolled)}** under-enrolled (<3 courses)")
        else:
            st.success("✅ No under-enrolled students")

    with filter_col3:
        correct_load = [s for s in student_counts.values() if s["count"] == 3]
        st.info(f"✅ **{len(correct_load)}** with exactly 3 courses")

    # Filter selector
    enrollment_filter = st.radio(
        "Filter students by enrollment status:",
        ["Show All Rosters", "Show Over-Enrolled (>3)", "Show Exactly 3 Courses (=3)", "Show Under-Enrolled (<3)"],
        horizontal=True,
        key="enrollment_filter"
    )

    # Display filtered students if a filter is selected
    if enrollment_filter == "Show Over-Enrolled (>3)":
        st.divider()
        st.subheader("⚠️ Over-Enrolled Students (>3 courses)")
        
        # Load requirements for course title display
        requirements_df = load_requirements()
        
        if over_enrolled:
            for student in sorted(over_enrolled, key=lambda x: x["count"], reverse=True):
                # Format course names with titles
                courses_display = [format_course_with_title(c, requirements_df) for c in student['courses']]
                
                with st.expander(f"🔴 {student['Name']} - {student['count']} courses", expanded=True):
                    st.write(f"**ID:** {student['StudentId']} | **Major:** {student['Major']} | **Cohort:** {student['Cohort']}")
                    st.write(f"**Enrolled in:** {', '.join(courses_display)}")

                    # Quick remove buttons
                    st.write("**Remove from:**")
                    cols = st.columns(min(len(student['courses']), 4))
                    for i, course in enumerate(student['courses']):
                        if cols[i % 4].button(f"🗑️ {course}", key=f"over_remove_{student['StudentId']}_{course}"):
                            remove_student_from_roster(course, student['StudentId'])
                            st.rerun()
        else:
            st.success("No over-enrolled students!")
        return  # Don't show regular roster view

    elif enrollment_filter == "Show Exactly 3 Courses (=3)":
        st.divider()
        st.subheader("✅ Students with Exactly 3 Courses")
        
        # Load requirements for course title display
        requirements_df = load_requirements()
        
        if correct_load:
            for student in sorted(correct_load, key=lambda x: x["Name"]):
                # Format course names with titles
                courses_display = [format_course_with_title(c, requirements_df) for c in student['courses']]
                
                with st.expander(f"🟢 {student['Name']} - {student['count']} courses", expanded=False):
                    st.write(f"**ID:** {student['StudentId']} | **Major:** {student['Major']} | **Cohort:** {student['Cohort']}")
                    st.write(f"**Enrolled in:** {', '.join(courses_display)}")

                    # Quick remove buttons (in case adjustment needed)
                    st.write("**Remove from:**")
                    cols = st.columns(min(len(student['courses']), 3))
                    for i, course in enumerate(student['courses']):
                        if cols[i].button(f"🗑️ {course}", key=f"correct_remove_{student['StudentId']}_{course}"):
                            remove_student_from_roster(course, student['StudentId'])
                            st.rerun()
        else:
            st.info("No students have exactly 3 courses yet.")
        return  # Don't show regular roster view

    elif enrollment_filter == "Show Under-Enrolled (<3)":
        st.divider()
        st.subheader("📉 Under-Enrolled Students (<3 courses)")
        
        # Load requirements for course title display
        requirements_df = load_requirements()
        
        if under_enrolled:
            # Get needs_df to calculate total remaining courses
            needs_df = st.session_state.get("needs_df")
            metadata_cols = ["StudentId", "Name", "Email", "Major", "Cohort", "LastEnroll", "MajorPrefix"]

            for student in sorted(under_enrolled, key=lambda x: x["count"]):
                # Calculate total courses left for this student
                courses_left = 0
                if needs_df is not None and not needs_df.empty:
                    student_row = needs_df[needs_df["StudentId"] == student["StudentId"]]
                    if not student_row.empty:
                        course_cols = [c for c in needs_df.columns if c not in metadata_cols]
                        for col in course_cols:
                            try:
                                if student_row[col].iloc[0] == 1:
                                    courses_left += 1
                            except (KeyError, IndexError, TypeError):
                                pass

                # Format course names with titles
                courses_display = [format_course_with_title(c, requirements_df) for c in student['courses']] if student['courses'] else []

                # Display with courses left info
                left_text = f" [{courses_left} left]" if courses_left > 0 else ""
                with st.expander(f"🟡 {student['Name']} - {student['count']} course(s){left_text}", expanded=False):
                    st.write(f"**ID:** {student['StudentId']} | **Major:** {student['Major']} | **Cohort:** {student['Cohort']}")
                    if courses_display:
                        st.write(f"**Currently enrolled in:** {', '.join(courses_display)}")
                    else:
                        st.write("**Currently enrolled in:** None")
                    st.write(f"**Total courses remaining to graduate:** {courses_left}")
                    st.caption("Go to 'Class Rosters' tab to add more courses for this student.")
        else:
            st.success("No under-enrolled students!")
        return  # Don't show regular roster view

    # Regular roster view (Show All Rosters)
    st.divider()
    st.subheader("📚 All Class Rosters")

    # Load requirements for course title display
    requirements_df = load_requirements()

    # Option to clear all rosters
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🗑️ Clear All Rosters", type="secondary"):
            st.session_state["rosters"] = {}
            save_current_session()  # Auto-save
            st.rerun()

    st.divider()

    # Show each roster in an expander
    for course, students in active_rosters.items():
        course_display = format_course_with_title(course, requirements_df)
        with st.expander(f"📚 {course_display} ({len(students)} students)", expanded=False):
            if students:
                # Create a dataframe with a remove column
                roster_df = pd.DataFrame(students)

                # Display the roster
                st.dataframe(
                    roster_df[["StudentId", "Name", "Major", "Cohort"]],
                    width="stretch",
                    hide_index=True,
                )

                # Remove individual students
                st.write("**Remove a student:**")
                cols = st.columns([3, 1])
                with cols[0]:
                    student_to_remove = st.selectbox(
                        "Select student",
                        options=[s["StudentId"] for s in students],
                        format_func=lambda x: f"{x} - {next((s['Name'] for s in students if s['StudentId'] == x), 'Unknown')}",
                        key=f"remove_select_{course}",
                        label_visibility="collapsed",
                    )
                with cols[1]:
                    if st.button("Remove", key=f"remove_btn_{course}", type="secondary"):
                        remove_student_from_roster(course, student_to_remove)
                        st.success(f"Removed student from {course}")
                        st.rerun()

                # Clear entire roster
                if st.button(f"Clear entire {course} roster", key=f"clear_{course}"):
                    st.session_state["rosters"][course] = []
                    save_current_session()  # Auto-save
                    st.rerun()

                # Download option
                csv = roster_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label=f"Download {course} Roster (CSV)",
                    data=csv,
                    file_name=f"roster_{course}.csv",
                    mime="text/csv",
                    key=f"download_{course}",
                )


def render_schedule_optimization_tab():
    """Schedule Optimization Tab."""
    st.subheader("Optimize Schedule")
    st.write("Assign time slots to your created classes.")

    if "rosters" not in st.session_state or not st.session_state["rosters"]:
        st.warning("Please create classes in the 'Class Rosters' tab first.")
        return

    rosters = st.session_state["rosters"]
    active_classes = [c for c, r in rosters.items() if len(r) > 0]

    if not active_classes:
        st.info(
            "You haven't added any students to rosters yet. Go to 'Class Rosters' tab.")
        return

    st.write(f"You have created **{len(active_classes)}** active classes.")

    # Lazy import
    from logic.optimization import TIME_SLOTS, TIME_SLOT_LABELS, get_time_slot_label, check_roster_conflicts

    # Load requirements for course title display
    requirements_df = load_requirements()

    offered_courses = {}

    # Create display labels for selectbox (label -> code mapping)
    slot_display_to_code = {get_time_slot_label(slot): slot for slot in TIME_SLOTS}
    slot_options = ["Unassigned"] + [get_time_slot_label(slot) for slot in TIME_SLOTS]

    # Create a grid layout for slot assignment
    cols = st.columns(3)
    for i, course in enumerate(active_classes):
        with cols[i % 3]:
            student_count = len(rosters.get(course, []))
            course_display = format_course_with_title(course, requirements_df)

            # Get the current slot for this course (if previously assigned)
            current_slot_code = st.session_state.get("offered_courses", {}).get(course, "Unassigned")
            current_slot_display = get_time_slot_label(current_slot_code) if current_slot_code != "Unassigned" else "Unassigned"
            current_index = slot_options.index(current_slot_display) if current_slot_display in slot_options else 0

            slot_display = st.selectbox(
                f"{course_display} ({student_count} students)",
                options=slot_options,
                index=current_index,
                key=f"slot_{course}",
            )

            # Convert display label back to code
            if slot_display != "Unassigned":
                slot_code = slot_display_to_code[slot_display]
                offered_courses[course] = slot_code

    st.divider()

    if st.button("Check Conflicts", type="primary"):
        conflicts = check_roster_conflicts(offered_courses, rosters)
        st.session_state["detected_conflicts"] = conflicts
        st.session_state["offered_courses"] = offered_courses

    # Display conflicts with resolution options
    if "detected_conflicts" in st.session_state:
        conflicts = st.session_state["detected_conflicts"]

        if conflicts:
            st.error(f"Found {len(conflicts)} student conflict(s)!")
            st.write("**Resolve conflicts by removing a student from one of their conflicting courses:**")

            for idx, conflict in enumerate(conflicts):
                # Format course names with titles
                courses_display = [format_course_with_title(c, requirements_df) for c in conflict['Courses']]
                
                with st.container():
                    st.markdown(f"""
                    ---
                    **Student:** {conflict['Name']} (`{conflict['StudentId']}`)
                    **Conflicting Slot:** `{conflict['ConflictSlot']}`
                    **Courses in conflict:** {', '.join(courses_display)}
                    """)

                    # Create remove buttons for each conflicting course
                    cols = st.columns(len(conflict['Courses']) + 1)
                    cols[0].write("Remove from:")

                    for i, course in enumerate(conflict['Courses']):
                        if cols[i + 1].button(
                            f"🗑️ {course}",
                            key=f"resolve_{conflict['StudentId']}_{course}_{idx}",
                            help=f"Remove {conflict['Name']} from {course}",
                        ):
                            remove_student_from_roster(course, conflict['StudentId'])
                            # Clear conflicts to force re-check
                            if "detected_conflicts" in st.session_state:
                                del st.session_state["detected_conflicts"]
                            st.success(f"Removed {conflict['Name']} from {course}. Click 'Check Conflicts' to verify.")
                            st.rerun()

            st.divider()
            st.info("💡 After resolving conflicts, click **Check Conflicts** again to verify.")

        else:
            st.success("✅ No conflicts found! This schedule looks good.")
            st.session_state["final_schedule"] = st.session_state.get("offered_courses", offered_courses)
            save_current_session()  # Auto-save

            # Show summary of the valid schedule
            if st.session_state.get("offered_courses"):
                st.write("**Final Schedule:**")
                schedule_data = [
                    {
                        "Course": format_course_with_title(c, requirements_df),
                        "Time Slot": s,
                        "Students": len(rosters.get(c, []))
                    }
                    for c, s in st.session_state["offered_courses"].items()
                ]
                st.dataframe(pd.DataFrame(schedule_data), width="stretch", hide_index=True)


def render_download_rosters_tab():
    """Download Rosters Tab - Export rosters to XLSX or CSV."""
    st.subheader("📥 Download Class Rosters")
    st.write("Export your class rosters for student feedback emails.")

    if "rosters" not in st.session_state or not st.session_state["rosters"]:
        st.warning("⚠️ No rosters available. Please create rosters in the 'Manage Rosters' tab first.")
        return

    rosters = st.session_state["rosters"]

    # Load requirements for course title display
    requirements_df = load_requirements()

    # Get schedule information for time slots
    schedule = st.session_state.get("offered_courses", {})

    # Calculate total courses per student
    from logic.cache import get_student_course_counts
    student_course_counts = get_student_course_counts(rosters)

    # Count total student-course pairings
    total_enrollments = sum(len(students) for students in rosters.values())
    unique_students = len(student_course_counts)

    st.info(f"📊 **{len(rosters)}** classes • **{unique_students}** students • **{total_enrollments}** total enrollments")

    st.divider()

    # Import time slot label function
    from logic.optimization import get_time_slot_label as get_slot_label

    # Preview section
    with st.expander("👁️ Preview Roster Data", expanded=False):
        st.caption("Showing first few rows of the export data:")

        # Build preview data (first 10 rows)
        preview_rows = []
        count = 0
        for course, students in rosters.items():
            course_display = format_course_with_title(course, requirements_df)
            time_slot_code = schedule.get(course, "Unassigned")
            time_slot = get_slot_label(time_slot_code) if time_slot_code != "Unassigned" else "Unassigned"

            for student in students:
                if count >= 10:
                    break
                student_id = student["StudentId"]
                total_courses = student_course_counts.get(student_id, {}).get("count", 0)

                preview_rows.append({
                    "Total Courses": total_courses,
                    "StudentID": student_id,
                    "Name": student.get("Name", ""),
                    "Email": student.get("Email", ""),
                    "LastActiveDate": student.get("LastActiveDate", ""),
                    "Major": student.get("Major", ""),
                    "Cohort": student.get("Cohort", ""),
                    "CourseCode": course,
                    "Course Title": get_course_title(course, requirements_df),
                    "Time Slot": time_slot,
                })
                count += 1
            if count >= 10:
                break

        if preview_rows:
            preview_df = pd.DataFrame(preview_rows)
            st.dataframe(preview_df, width="stretch", hide_index=True)

    st.divider()

    # Export section
    st.write("### 📤 Export Data")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.caption("""
        **Included Fields:**
        • Total Courses (count per student)
        • StudentID
        • Name
        • Email
        • LastActiveDate
        • Major
        • Cohort
        • CourseCode
        • Course Title
        • Time Slot
        """)

    with col2:
        export_format = st.radio(
            "Format:",
            options=["Excel (XLSX)", "CSV"],
            help="Choose your preferred format"
        )

    st.divider()

    # Import time slot label function
    from logic.optimization import get_time_slot_label

    # Generate export data
    export_rows = []
    for course, students in rosters.items():
        course_title = get_course_title(course, requirements_df)
        time_slot_code = schedule.get(course, "Unassigned")
        time_slot = get_time_slot_label(time_slot_code) if time_slot_code != "Unassigned" else "Unassigned"

        for student in students:
            student_id = student["StudentId"]
            total_courses = student_course_counts.get(student_id, {}).get("count", 0)

            export_rows.append({
                "Total Courses": total_courses,
                "StudentID": student_id,
                "Name": student.get("Name", ""),
                "Email": student.get("Email", ""),
                "LastActiveDate": student.get("LastActiveDate", ""),
                "Major": student.get("Major", ""),
                "Cohort": student.get("Cohort", ""),
                "CourseCode": course,
                "Course Title": course_title,
                "Time Slot": time_slot,
            })

    export_df = pd.DataFrame(export_rows)

    # Sort by StudentID, then by CourseCode for better organization
    export_df = export_df.sort_values(["StudentID", "CourseCode"])

    if export_format == "Excel (XLSX)":
        # Generate XLSX file
        import io
        from datetime import datetime

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            export_df.to_excel(writer, sheet_name='Student Enrollments', index=False)

            # Auto-adjust column widths
            worksheet = writer.sheets['Student Enrollments']
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width

        output.seek(0)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        st.download_button(
            label="📥 Download Roster (XLSX)",
            data=output,
            file_name=f"student_enrollments_{timestamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            width="stretch"
        )

    else:  # CSV format
        from datetime import datetime

        csv_data = export_df.to_csv(index=False)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        st.download_button(
            label="📥 Download Roster (CSV)",
            data=csv_data,
            file_name=f"student_enrollments_{timestamp}.csv",
            mime="text/csv",
            type="primary",
            width="stretch"
        )

    st.divider()

    # Statistics
    st.write("### 📊 Enrollment Statistics")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Total Classes", len(rosters))

    with col2:
        st.metric("Unique Students", unique_students)

    with col3:
        st.metric("Total Enrollments", total_enrollments)

    # Help section
    with st.expander("ℹ️ Using This Export for Student Feedback"):
        st.markdown("""
        **Purpose:**
        This export is designed for generating email communications to get feedback from students
        about accepting the courses selected for them.

        **Data Format:**
        - **One row per student-course pairing** (long format)
        - Each student appears multiple times (once per enrolled course)
        - "Total Courses" field shows how many courses each student is taking

        **Next Steps:**
        1. **Open in Excel/Google Sheets** for easy viewing and mail merge
        2. **Filter by student** to see all courses for one student
        3. **Generate emails** using mail merge with the Email field
        4. **Track responses** by adding columns for student feedback

        **Email Template Example:**
        ```
        Dear [Name],

        We have scheduled the following [Total Courses] courses for you:
        - [CourseCode]: [Course Title] at [Time Slot]
        ...

        Please confirm if you accept this schedule by [date].
        ```

        **Tips:**
        - Students with multiple courses will have multiple rows
        - Use pivot tables to summarize courses per student
        - Sort by Email to group communications
        - Filter by Major or Cohort for targeted outreach
        """)


def render_communications_tab():
    """Communications Tab - Telegram Classroom Generation."""
    st.subheader("📱 Telegram Classroom Setup")
    st.write("Generate and manage Telegram classroom groups for scheduled courses.")
    st.caption("💡 Note: Email communications with students will be handled separately.")

    if "rosters" not in st.session_state or not st.session_state["rosters"]:
        st.warning("⚠️ No rosters available. Please create rosters first.")
        return

    rosters = st.session_state["rosters"]

    # Load requirements for course title display
    requirements_df = load_requirements()

    st.info(f"📊 **{len(rosters)}** class(es) ready for Telegram classroom setup")

    st.divider()

    # Telegram Bot Configuration
    st.write("### 1️⃣ Telegram Bot Configuration")
    st.caption("Set up your Telegram bot to create and manage classroom groups")

    # Restore telegram_chat_id from cache if available
    default_chat_id = st.session_state.get("telegram_chat_id", "")

    telegram_chat_id = st.text_input(
        "Telegram Bot Chat ID",
        value=default_chat_id,
        placeholder="@channel_name or -100xxxxx",
        help="Enter your Telegram bot's chat ID or channel username",
        key="telegram_chat_id"  # Auto-persists in session_state
    )

    if telegram_chat_id != default_chat_id:
        save_current_session()  # Auto-save when changed

    st.divider()

    # Message Template
    st.write("### 2️⃣ Message Template")
    st.caption("Customize the welcome message for classroom groups")

    # Restore telegram_draft from cache if available
    default_draft = st.session_state.get("telegram_draft", "")
    if not default_draft:
        default_draft = """📢 **Welcome to {course_name}!**

👥 **Class Information:**
- Course: {course_code}
- Time Slot: {time_slot}
- Students Enrolled: {student_count}

📚 This is your official Telegram classroom for course updates, materials, and discussions.

Please introduce yourself to the group!"""

    telegram_draft = st.text_area(
        "Message Template",
        value=default_draft,
        height=200,
        help="Use placeholders: {course_name}, {course_code}, {time_slot}, {student_count}",
        key="telegram_draft"  # Auto-persists in session_state
    )

    if telegram_draft != default_draft:
        save_current_session()  # Auto-save when changed

    st.divider()

    # Course Selection for Classroom Creation
    st.write("### 3️⃣ Create Telegram Classrooms")
    st.caption("Generate Telegram groups for your scheduled courses")

    # Get schedule information if available
    schedule = st.session_state.get("offered_courses", {})

    # Import time slot label function
    from logic.optimization import get_time_slot_label

    for course, students in rosters.items():
        course_display = format_course_with_title(course, requirements_df)
        time_slot_code = schedule.get(course, "Unassigned")
        time_slot = get_time_slot_label(time_slot_code) if time_slot_code != "Unassigned" else "Unassigned"

        with st.expander(f"📖 {course_display} — {len(students)} students", expanded=False):
            st.write(f"**Time Slot:** {time_slot}")
            st.write(f"**Enrolled:** {len(students)} students")

            # Preview message
            preview_message = telegram_draft.format(
                course_name=course_display,
                course_code=course,
                time_slot=time_slot,
                student_count=len(students)
            )

            st.write("**Message Preview:**")
            st.code(preview_message, language=None)

            col1, col2 = st.columns(2)
            with col1:
                if st.button(f"📤 Create Classroom", key=f"create_tg_{course}", width="stretch"):
                    if telegram_chat_id:
                        # TODO: Implement Telegram classroom creation
                        st.info("🚧 Creating Telegram classroom...")
                        st.write("Will perform:")
                        st.write("1. Create Telegram group")
                        st.write("2. Add students to group")
                        st.write("3. Send welcome message")
                        st.write("4. Configure group settings")
                        save_current_session()  # Auto-save
                    else:
                        st.error("⚠️ Please configure Telegram Bot Chat ID first")

            with col2:
                if st.button(f"📋 View Student List", key=f"view_tg_{course}", width="stretch"):
                    if students:
                        student_df = pd.DataFrame(students)
                        st.dataframe(student_df[["Name", "Email"]], width="stretch")

    st.divider()

    # Help Section
    with st.expander("ℹ️ How to Set Up Telegram Classrooms"):
        st.markdown("""
        **Step-by-Step Guide:**

        1. **Create a Telegram Bot**
           - Open Telegram and search for @BotFather
           - Send `/newbot` command and follow instructions
           - Save the bot token securely

        2. **Configure Bot Settings**
           - Enter the bot's chat ID in the configuration field above
           - Customize the welcome message template
           - Test with one course first

        3. **Create Classrooms**
           - Click "Create Classroom" for each course
           - Bot will create a group and add students
           - Welcome message will be sent automatically

        4. **Manage Classrooms**
           - Use Telegram to moderate discussions
           - Share course materials and announcements
           - Track student engagement

        **Tips:**
        - Use descriptive group names (e.g., "ENGL-110 Fall 2024")
        - Set group rules and pinned messages
        - Enable slow mode for large classes
        - Assign class monitors as group admins
        """)

    st.divider()

    st.caption("💾 Changes to Chat ID and Message Template are auto-saved")


def render_student_transcript_tab():
    """Student Transcript Tab - Quick transcript lookup."""
    st.subheader("🎓 Student Transcript Lookup")
    st.write("Enter a student ID to view their complete transcript from the database.")

    # Input for student ID
    student_id = st.text_input(
        "Student ID",
        placeholder="Enter student ID...",
        help="Enter the student ID to query their transcript"
    )

    if student_id:
        if st.button("🔍 Lookup Transcript", type="primary"):
            with st.spinner(f"Fetching transcript for {student_id}..."):
                from database.connection import db_cursor

                # Query vw_BAlatestgrade for this student
                query = """
                SELECT *
                FROM vw_BAlatestgrade
                WHERE id = %s
                """

                try:
                    with db_cursor() as cursor:
                        cursor.execute(query, (student_id,))
                        results = cursor.fetchall()

                        if results:
                            # Convert to DataFrame for display
                            transcript_df = pd.DataFrame(results)

                            st.success(f"Found {len(transcript_df)} course record(s) for student {student_id}")

                            # Display the transcript
                            st.dataframe(
                                transcript_df,
                                width="stretch",
                                hide_index=True,
                                height=min(len(transcript_df) * 35 + 38, 600)
                            )

                            # Download option
                            csv = transcript_df.to_csv(index=False).encode("utf-8")
                            st.download_button(
                                label="📥 Download Transcript (CSV)",
                                data=csv,
                                file_name=f"transcript_{student_id}.csv",
                                mime="text/csv",
                            )
                        else:
                            st.warning(f"No transcript records found for student ID: {student_id}")

                except Exception as e:
                    st.error(f"Error fetching transcript: {e}")
                    import traceback
                    st.code(traceback.format_exc())
    else:
        st.info("👆 Enter a student ID above to view their transcript")


def student_portal():
    st.header("Student Portal")
    st.write("Please log in to view your recommended schedule.")
    # Placeholder for student login and schedule view


if __name__ == "__main__":
    if check_login():
        main()
    else:
        login_page()
