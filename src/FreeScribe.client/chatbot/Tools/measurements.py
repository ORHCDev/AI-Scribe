from chatbot.Tools.Tool import tool, ToolReturn as tr
from chatbot.Tools.utils import period_parser, export_data, wrap_text
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import datetime as dt
import os
import webbrowser



@tool(
    category="measurements",
    description=(
        "Returns the most recent available result for a predefined set of common laboratory tests "
        "for a specific patient (e.g., renal function, lipids, glucose control, hematology, INR). "
        "Each returned row includes the test name, numeric value, unit, reference range, abnormal flag, "
        "and the date the test was observed. "
        "This tool is most relevant when the user asks for current lab values, recent bloodwork, "
        "baseline labs, or a snapshot of the patient's latest laboratory status."
    ),
    context="These are the patient's lab results:",
    parameters={
        "demo_no": "Patient's demographic number"
    }
)
def get_recent_lab_results(db_conn, demo_no : str):
    """
    Fetches and returns the most recent lab results for given patient.
    """
    test_names = [
        'SCR','Napl','Kpl',
        'MG','ALT','A1C',
        'TG','TCHL','HDL',
        'LDL','FBS', 'EGFR',
        'CL', 'HGB', 'WBC',
        'INR', 
    ]
    name_str = "'" + "', '".join(test_names) + "'"

    query = f"""
    SELECT
        m.type AS "Name",
        m.dataField AS "Qty",
        me.unit AS "Unit",
        me.min AS "MIN",
        me.max AS "MAX",
        me.abnormal AS "Flag",
        DATE(m.dateObserved) AS "Date Observed"
    FROM measurements m
    JOIN (
        SELECT
            type,
            MAX(dateObserved) AS maxDate
        FROM measurements
        WHERE demographicNo = {demo_no}
        AND type IN ({name_str})
        GROUP BY type
    ) latest
        ON m.type = latest.type
    AND m.dateObserved = latest.maxDate
    LEFT JOIN (
        SELECT
            me.measurement_id,
            MAX(CASE WHEN me.keyval = 'minimum'  THEN me.val END) AS min,
            MAX(CASE WHEN me.keyval = 'maximum'  THEN me.val END) AS max,
            MAX(CASE WHEN me.keyval = 'abnormal' THEN me.val END) AS abnormal,
            MAX(CASE WHEN me.keyval = 'unit'     THEN me.val END) AS unit
        FROM measurementsExt me
        JOIN (
            SELECT
                id
            FROM measurements
            WHERE demographicNo = {demo_no}
            AND type IN ({name_str})
        ) relevant
            ON relevant.id = me.measurement_id
        GROUP BY me.measurement_id
    ) me
        ON me.measurement_id = m.id
    WHERE m.demographicNo = {demo_no}
    GROUP BY m.type, m.dataField, me.unit, me.min, me.max, me.abnormal, DATE(m.dateObserved)
    ORDER BY m.type ASC;
    """
    
    res = db_conn.query_database(query)
    return tr(
        label="Recent Lab Results",
        send_to_ai=False,
        query_results=res,
        save_results=res
    )


@tool(
    category="measurements",
    description=(
        "Returns the full historical record of one or more specified measurements or lab tests "
        "for a patient, including numeric values, measurement instructions, and observation dates. "
        "Optionally generates time-series plots showing trends over time. "
        "This tool is most relevant when the user asks about trends, progression, stability, "
        "or historical changes in specific labs or measurements (e.g., LDL over time, A1C trend, "
        "renal function trajectory)."
    ),
    context="These are the patient's lab results, organize them as a table:",
    parameters={
        "demo_no": "Patient's demographic number",
        "test_names": "List of lab or measurement names to retrieve historical values for",
        "plot": "Boolean indicating whether to generate a time-series plot of the results"
    }
)
def get_measurement_history(db_conn, demo_no : str, test_names : list[str], plot : bool = False):
    """
    Fetches and returns all recorded measurements for a specific lab test associated with a given patient.
    """
    if type(test_names) == str:
        test_names = [test_names]
        
    name_str = "'" + "', '".join(test_names) + "'"

    query = f"""
    SELECT 
        type AS "Name",
        dataField AS "Qty",
        measuringInstruction AS "Measuring Instruction",
        DATE(dateObserved) AS "Date Observed"
    FROM measurements
    WHERE demographicNo = {demo_no}
      AND type IN ({name_str})
    GROUP BY type, dataField, measuringInstruction, dateObserved
    ORDER BY type ASC, dateObserved DESC;
    """

    res = db_conn.query_database(query)

    # Plot trend
    if bool(plot):
        plt.figure(figsize=(10, 6))
        for test in test_names:
            try:
                dates = []
                qtys = []
                for row in res:
                    try:
                        if row["Name"] == test:
                            qty = float(row["Qty"])
                            date = row["Date Observed"]
                            qtys.append(qty)
                            dates.append(date)
                    except:
                        pass

                plt.plot(dates, qtys, label=test)
            except Exception as e:
                print(f"Error reading entry: {e}")

        plt.xlabel("Date Observed")
        plt.ylabel("Quantity")
        plt.title("Historical Measurements")
        plt.legend()
        plt.gcf().autofmt_xdate()

        # Save and open the plot inside the default image viewer
        save_path = os.path.join(os.getcwd(), "reports")
        os.makedirs(save_path, exist_ok=True)
        filename = os.path.join(save_path, f"{demo_no}_{'_'.join(test_names)}.png")
        plt.savefig(filename, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Plot saved to {filename}")
        try:
            webbrowser.open(os.path.abspath(filename))
        except Exception as e:
            print(f"Unable to open plot: {e}")


    return tr(
        label=f"Measurement History of {test_names}",
        send_to_ai=False,
        query_results=res,
        save_results=res
    )


"""@tool(
    category="measurements",
    description=(
        "Returns a cohort of active patients whose most recent LDL cholesterol values fall within "
        "a specified numeric range during a defined recent time window. "
        "Each result includes patient identifiers, LDL value, observation date, and assigned provider. "
        "This tool is most relevant for population health queries, lipid management audits, "
        "risk stratification, or identifying patients who may need medication adjustment or follow-up."
        "Does not return relevant information for a specific patient."
    ),
    context="All patient's that have LDL level within given values.",
    parameters={
        "LDL_lower": "Lower bound for LDL cholesterol value",
        "LDL_upper": "Upper bound for LDL cholesterol value",
        "month": "Number of months in the past to search for LDL measurements"
    }
)"""
def LDL_lookup(db_conn, LDL_lower : float, LDL_upper : float, month : int):
    """
    Fetches and returns all patients that have an LDL level between LDL_lower and LDL_upper in the last n months.
    """

    query = f"""
SELECT 
    DISTINCT demo.last_name,
    demo.first_name, 
    type,dataField,
    max(dateObserved), 
    demo.provider_no 
FROM measurements, demographic demo 
WHERE type = "LDL" 
  AND dataField <> '> 120' 
  AND dataField <> 'Not report' 
  AND (dataField BETWEEN {LDL_lower} AND {LDL_upper}) 
  AND dateObserved > ((PERIOD_ADD(EXTRACT(YEAR_MONTH FROM CURDATE()),-{month})*100)+1) 
  AND demo.patient_status = 'AC'  
  AND demographicNo = demo.demographic_no 
GROUP BY demo.last_name, demo.first_name 
ORDER BY demo.last_name,demo.first_name and dateObserved
LIMIT 10;
"""
    
    res = db_conn.query_database(query)
    return tr(
        label=f"LDL Levels between {LDL_lower} and {LDL_upper}",
        send_to_ai=True,
        query_results=res,
        save_results=None
    )



"""@tool(
    category="measurements",
    description=(
        "Returns the most recent Holter monitor measurement results for a patient, grouped by metric. "
        "Each result includes recorded values, units, reference ranges, abnormal flags, and observation dates. "
        "This tool is most relevant when the user asks about Holter findings, rhythm monitoring results, "
        "arrhythmia assessment, or recent ambulatory ECG monitoring outcomes."
    ),
    context="These are the patient's holter results, organize them as a table:",
    parameters={
        "demo_no": "Patient's demographic number"
    }
)"""
def get_recent_holter_results(db_conn, demo_no : str):
    query = f"""
    SELECT
        m.type AS "Name",
        m.dataField AS "Data",
        me.unit AS "Unit",
        me.min AS "MIN",
        me.max AS "MAX",
        me.abnormal AS "Flag",
        DATE(m.dateObserved) AS "Date Observed"
    FROM measurements m
    JOIN (
        SELECT
            type,
            MAX(dateObserved) AS maxDate
        FROM measurements
        WHERE demographicNo = {demo_no}
        AND measuringInstruction = "Holter"
        GROUP BY type
    ) latest
        ON m.type = latest.type
    AND m.dateObserved = latest.maxDate
    LEFT JOIN (
        SELECT
            me.measurement_id,
            MAX(CASE WHEN me.keyval = 'minimum'  THEN me.val END) AS min,
            MAX(CASE WHEN me.keyval = 'maximum'  THEN me.val END) AS max,
            MAX(CASE WHEN me.keyval = 'abnormal' THEN me.val END) AS abnormal,
            MAX(CASE WHEN me.keyval = 'unit'     THEN me.val END) AS unit
        FROM measurementsExt me
        JOIN (
            SELECT
                id
            FROM measurements
            WHERE demographicNo = {demo_no}
            AND measuringInstruction = "Holter"
        ) relevant
            ON relevant.id = me.measurement_id
        GROUP BY me.measurement_id
    ) me
        ON me.measurement_id = m.id
    WHERE m.demographicNo = {demo_no}
    GROUP BY m.type, m.dataField, me.unit, me.min, me.max, me.abnormal, DATE(m.dateObserved)
    ORDER BY m.type ASC;
    """

    res = db_conn.query_database(query)
    return tr(
        label="Recent Holter Results",
        send_to_ai=False,
        query_results=res,
        save_results=res
    )



"""@tool(
    category="measurements",
    description=(
        "Returns the most recent echocardiographic measurement values for a patient, such as chamber sizes, "
        "ejection fraction, and structural or functional cardiac parameters. "
        "Results include values, units, reference ranges, abnormal indicators, and observation dates. "
        "This tool is most relevant when the user asks about echo findings, cardiac structure or function, "
        "or interpretation of the latest echocardiogram."
    ),
    context="These are the patient's echocardiogram results, organize them as a table:",
    parameters={
        "demo_no": "Patient's demographic number"
    }
)"""
def get_recent_echo_results(db_conn, demo_no : str):
    query = f"""
    SELECT
        m.type AS "Name",
        m.dataField AS "Data",
        me.unit AS "Unit",
        me.min AS "MIN",
        me.max AS "MAX",
        me.abnormal AS "Flag",
        DATE(m.dateObserved) AS "Date Observed"
    FROM measurements m
    JOIN (
        SELECT
            type,
            MAX(dateObserved) AS maxDate
        FROM measurements
        WHERE demographicNo = {demo_no}
        AND measuringInstruction = "ECHO"
        GROUP BY type
    ) latest
        ON m.type = latest.type
    AND m.dateObserved = latest.maxDate
    LEFT JOIN (
        SELECT
            me.measurement_id,
            MAX(CASE WHEN me.keyval = 'minimum'  THEN me.val END) AS min,
            MAX(CASE WHEN me.keyval = 'maximum'  THEN me.val END) AS max,
            MAX(CASE WHEN me.keyval = 'abnormal' THEN me.val END) AS abnormal,
            MAX(CASE WHEN me.keyval = 'unit'     THEN me.val END) AS unit
        FROM measurementsExt me
        JOIN (
            SELECT
                id
            FROM measurements
            WHERE demographicNo = {demo_no}
            AND measuringInstruction = "ECHO"
        ) relevant
            ON relevant.id = me.measurement_id
        GROUP BY me.measurement_id
    ) me
        ON me.measurement_id = m.id
    WHERE m.demographicNo = {demo_no}
    GROUP BY m.type, m.dataField, me.unit, me.min, me.max, me.abnormal, DATE(m.dateObserved)
    ORDER BY m.type ASC;
    """

    res = db_conn.query_database(query)
    return tr(
        label="Recent Echocardiogram Results",
        send_to_ai=False,
        query_results=res,
        save_results=res
    )


"""@tool(
    category="measurements",
    description=(
        "Returns the most recent electrocardiogram (ECG) measurement data for a patient, including "
        "recorded parameters, reference ranges, abnormal flags, and observation dates. "
        "This tool is most relevant when the user asks about ECG findings, rhythm abnormalities, "
        "or recent electrocardiographic results."
    ),
    context="These are the patient's electrocardiogram results, organize them as a table:",
    parameters={
        "demo_no": "Patient's demographic number"
    }
)"""
def get_recent_ecg_results(db_conn, demo_no : str):
    query = f"""
    SELECT
        m.type AS "Name",
        m.dataField AS "Data",
        me.unit AS "Unit",
        me.min AS "MIN",
        me.max AS "MAX",
        me.abnormal AS "Flag",
        DATE(m.dateObserved) AS "Date Observed"
    FROM measurements m
    JOIN (
        SELECT
            type,
            MAX(dateObserved) AS maxDate
        FROM measurements
        WHERE demographicNo = {demo_no}
        AND measuringInstruction = "ecg"
        GROUP BY type
    ) latest
        ON m.type = latest.type
    AND m.dateObserved = latest.maxDate
    LEFT JOIN (
        SELECT
            me.measurement_id,
            MAX(CASE WHEN me.keyval = 'minimum'  THEN me.val END) AS min,
            MAX(CASE WHEN me.keyval = 'maximum'  THEN me.val END) AS max,
            MAX(CASE WHEN me.keyval = 'abnormal' THEN me.val END) AS abnormal,
            MAX(CASE WHEN me.keyval = 'unit'     THEN me.val END) AS unit
        FROM measurementsExt me
        JOIN (
            SELECT
                id
            FROM measurements
            WHERE demographicNo = {demo_no}
            AND measuringInstruction = "ecg"
        ) relevant
            ON relevant.id = me.measurement_id
        GROUP BY me.measurement_id
    ) me
        ON me.measurement_id = m.id
    WHERE m.demographicNo = {demo_no}
    GROUP BY m.type, m.dataField, me.unit, me.min, me.max, me.abnormal, DATE(m.dateObserved)
    ORDER BY m.type ASC;
    """

    res = db_conn.query_database(query)
    return tr(
        label="Recent Electrocardiogram Results",
        send_to_ai=False,
        query_results=res,
        save_results=res
    )


"""@tool(
    category="measurements",
    description=(
        "Returns the most recent electrocardiogram (ECG) measurement data for a patient, including "
        "recorded parameters, reference ranges, abnormal flags, and observation dates. "
        "This tool is most relevant when the user asks about ECG findings, rhythm abnormalities, "
        "or recent electrocardiographic results."
    ),
    context="These are the patient's electrocardiogram results, organize them as a table:",
    parameters={
        "demo_no": "Patient's demographic number"
    }
)"""
def get_recent_est_results(db_conn, demo_no : str):
    query = f"""
    SELECT
        m.type AS "Name",
        m.dataField AS "Data",
        me.unit AS "Unit",
        me.min AS "MIN",
        me.max AS "MAX",
        me.abnormal AS "Flag",
        DATE(m.dateObserved) AS "Date Observed"
    FROM measurements m
    JOIN (
        SELECT
            type,
            MAX(dateObserved) AS maxDate
        FROM measurements
        WHERE demographicNo = {demo_no}
        AND measuringInstruction = "est"
        GROUP BY type
    ) latest
        ON m.type = latest.type
    AND m.dateObserved = latest.maxDate
    LEFT JOIN (
        SELECT
            me.measurement_id,
            MAX(CASE WHEN me.keyval = 'minimum'  THEN me.val END) AS min,
            MAX(CASE WHEN me.keyval = 'maximum'  THEN me.val END) AS max,
            MAX(CASE WHEN me.keyval = 'abnormal' THEN me.val END) AS abnormal,
            MAX(CASE WHEN me.keyval = 'unit'     THEN me.val END) AS unit
        FROM measurementsExt me
        JOIN (
            SELECT
                id
            FROM measurements
            WHERE demographicNo = {demo_no}
            AND measuringInstruction = "est"
        ) relevant
            ON relevant.id = me.measurement_id
        GROUP BY me.measurement_id
    ) me
        ON me.measurement_id = m.id
    WHERE m.demographicNo = {demo_no}
    GROUP BY m.type, m.dataField, me.unit, me.min, me.max, me.abnormal, DATE(m.dateObserved)
    ORDER BY m.type ASC;
"""
    
    res = db_conn.query_database(query)
    return tr(
        label="Recent EST Results",
        send_to_ai=False,
        query_results=res,
        save_results=res
    )


'''@tool(
    category="measurements",
    description="Fetches and returns the patient's vitals.",
    context="These are the patient's vitals results, organize them as a table:",
    parameters={
        "demo_no": "Patient's demographic number"
    }
)
def get_patient_vitals(db_conn, demo_no : str):
    """
    Fetches and returns the patient's vitals like Blood Pressure, Heart Rate, Weight, and Height.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection

    demo_no : str
        Patient's demographic number.
    """

    # Vitals to grab
    names = [
        'BP', 'HR', 'WT',
        'HT', 
    ]
    name_str = "'" + "', '".join(names) + "'"

    query = f"""
    SELECT
        m.type AS "Name",
        m.dataField AS "Qty",
        me.unit AS "Unit",
        me.min AS "MIN",
        me.max AS "MAX",
        me.abnormal AS "Flag",
        DATE(m.dateObserved) AS "Date Observed"
    FROM measurements m
    JOIN (
        SELECT
            type,
            MAX(dateObserved) AS maxDate
        FROM measurements
        WHERE demographicNo = {demo_no}
        AND type IN ({name_str})
        GROUP BY type
    ) latest
        ON m.type = latest.type
    AND m.dateObserved = latest.maxDate
    LEFT JOIN (
        SELECT
            me.measurement_id,
            MAX(CASE WHEN me.keyval = 'minimum'  THEN me.val END) AS min,
            MAX(CASE WHEN me.keyval = 'maximum'  THEN me.val END) AS max,
            MAX(CASE WHEN me.keyval = 'abnormal' THEN me.val END) AS abnormal,
            MAX(CASE WHEN me.keyval = 'unit'     THEN me.val END) AS unit
        FROM measurementsExt me
        JOIN (
            SELECT
                id
            FROM measurements
            WHERE demographicNo = {demo_no}
            AND type IN ({name_str})
        ) relevant
            ON relevant.id = me.measurement_id
        GROUP BY me.measurement_id
    ) me
        ON me.measurement_id = m.id
    WHERE m.demographicNo = {demo_no}
    GROUP BY m.type, m.dataField, me.unit, me.min, me.max, me.abnormal, DATE(m.dateObserved)
    ORDER BY m.type ASC;
    """
    
    res = db_conn.query_database(query)
    return tr(
        label="Patient Vitals",
        send_to_ai=False,
        query_results=res,
        save_results=res
    )

'''


@tool(
    category="measurements",
    description=(
        "Generates a longitudinal overview of a patient's vital signs and key physiologic measurements, "
        "including blood pressure, heart rate, weight, renal markers, cardiac function, and medication events. "
        "Produces visual time-series plots and returns a summarized snapshot of the most recent values "
        "with corresponding dates. "
        "This tool is most relevant for holistic patient review, trend assessment, "
        "medication impact analysis, or clinical summary preparation."
    ),
    context="These are the patient's vitals results, organize them as a table:",
    parameters={
        "demo_no": "Patient's demographic number"
    }
)
def vitals_overview(db_conn, demo_no : str):
    """
    Plots a historical overview of the patient's vitals.
    """

    sections = {
        "bp" : ['BP'],
        "hr" : ['HR'],
        "weight" : ['WT', 'BMI', 'BSA'],
        "cardiac_func" : ['EF_B'],
        "renal" : ['EGFR', 'CRCL', 'NAPL', 'KPL', 'HGB', 'HCT', 'A1C'],
        "meds" : ['MEDS'],
    }



    types = []
    [types.extend(n) for n in sections.values()]

    query = f"""
    SELECT 
        type,
        dataField,
        DATE(dateObserved) AS dateObserved
    FROM measurements
    WHERE demographicNo = {demo_no}
    AND type IN (
        {"'" + "', '".join(types) + "'"}    
        )
    GROUP BY type, dataField, DATE(dateObserved)
    ORDER BY type, dateObserved DESC;
    """


    # Get 
    res = db_conn.query_database(query)
    plot_vals = {}
    for mtype in types:
        
        dates = [row["dateObserved"] for row in res if row["type"].upper() == mtype]
        
        if mtype == "MEDS":
            data = [row["dataField"] for row in res if row["type"].upper() == mtype]
        elif mtype == "BP":
            sbp = []
            dbp = []
            for row in res:
                if row["type"].upper() == mtype:
                    bp = row["dataField"].split('/')
                    sbp.append(float(bp[0]))
                    dbp.append(float(bp[1]))
                    data = [sbp, dbp]
        else:
            data = [float(row["dataField"]) for row in res if row["type"].upper() == mtype]
        
        plot_vals[f"{mtype}_dates"] = dates
        plot_vals[f"{mtype}_data"] = data


    # Plot layout
    fig = plt.figure(figsize=(14, 10))
    gs = GridSpec(3, 2, height_ratios=[2.2, 1, 1], hspace=0.25)

    ax_top = fig.add_subplot(gs[0, :])
    ax1 = fig.add_subplot(gs[1, 0], sharex=ax_top)
    ax2 = fig.add_subplot(gs[1, 1], sharex=ax_top)
    ax3 = fig.add_subplot(gs[2, 0], sharex=ax_top)
    ax4 = fig.add_subplot(gs[2, 1], sharex=ax_top)
    axes_small = [ax1, ax2, ax3, ax4]

    # Draw vertical boxes to highlight meds
    med_dates = plot_vals["MEDS_dates"]
    med_text = plot_vals["MEDS_data"]
    box_width_days = 2
    for d in med_dates:
        if isinstance(d, str):
            d = dt.date.fromisoformat(d[:10])
        for plot in [ax_top, ax1, ax2, ax3, ax4]:
            plot.axvspan(
                d - dt.timedelta(days=box_width_days/2),
                d + dt.timedelta(days=box_width_days/2),
                color='lightgray',
                alpha=0.3
            )

    # For each med, add an invisible tall scatter
    med_scatter = ax_top.scatter(
        med_dates,
        [ax_top.get_ylim()[1]/2] * len(med_dates),
        s=120000,      
        alpha=0,
        picker=10,
        marker='|'
    )

    # Add meds annotation boxes
    annot = ax_top.annotate(
        "",
        xy=(0, 0),
        xytext=(10, 10),
        textcoords="offset points",
        bbox=dict(boxstyle="round", fc="w", ec="0.5"),
        arrowprops=dict(arrowstyle="->"),
    )
    annot.set_wrap(True)
    annot.set_visible(False)

    def on_move(event):
        """On hover function to display meds text"""
        if event.inaxes != ax_top:
            if annot.get_visible():
                annot.set_visible(False)
                fig.canvas.draw_idle()
            return

        cont, ind = med_scatter.contains(event)
        if cont:
            idx = ind["ind"][0]
            annot.xy = (med_dates[idx], 1)
            annot.set_text(wrap_text(med_text[idx]))
            if not annot.get_visible():
                annot.set_visible(True)
                fig.canvas.draw_idle()
        else:
            if annot.get_visible():
                annot.set_visible(False)
                fig.canvas.draw_idle()
    fig.canvas.mpl_connect("motion_notify_event", on_move)


    # Plotting
    ax_top.plot(plot_vals["BP_dates"], plot_vals["BP_data"][0], label="SBP", color='tab:red', linewidth=2)
    ax_top.plot(plot_vals["BP_dates"], plot_vals["BP_data"][1], label="DBP", color="tab:blue", linewidth=2)

    ax1.plot(plot_vals["HR_dates"], plot_vals["HR_data"], color='tab:blue')
    ax2.plot(plot_vals["WT_dates"], plot_vals["WT_data"], color='tab:green')
    ax3.plot(plot_vals["EF_B_dates"], plot_vals["EF_B_data"], color='tab:orange')
    ax4.plot(plot_vals["EGFR_dates"], plot_vals["EGFR_data"], color='tab:purple')

    ax_top.set_title("BP")
    ax_top.set_ylabel("mmHg")
    ax_top.legend()

    ax1.set_title("Heart Rate")
    ax1.set_ylabel("BPM")

    ax2.set_title("Weight")
    ax2.set_ylabel("Kg")

    ax3.set_title("EF")
    ax3.set_ylabel("%")

    ax4.set_title("eGFR")
    ax4.set_ylabel("mL/min/1.73 m²")

    #for ax in axes_small:
    #    plt.setp(ax.get_xticklabels(), visible=False)

    #ax4.tick_params(axis="x", labelrotation=45)

    # Save and open the plot inside the default image viewer
    save_path = os.path.join(os.getcwd(), "reports")
    os.makedirs(save_path, exist_ok=True)
    filename = os.path.join(save_path, f"{demo_no}_vitals_overview.png")
    fig.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved to {filename}")
    try:
        webbrowser.open(os.path.abspath(filename))
    except Exception as e:
        print(f"Unable to open plot: {e}")

    to_send = []
    for key, val in sections.items():
        for v in val:
            print(f"{v}: {plot_vals[f'{v}_data']}")
            if v == "BP":
                mr_data = f"{plot_vals[f'{v}_data'][0][0]}/{plot_vals[f'{v}_data'][1][0]}"
            elif v == "MEDS":
                mr_data = wrap_text(plot_vals[f'{v}_data'][0])
            else:
                mr_data = plot_vals[f'{v}_data'][0]

            mr_date = plot_vals[f'{v}_dates'][0]
            
            temp = {
                "Type" : v,
                "Data" : mr_data,
                "Date" : mr_date,
            }
            to_send.append(temp)

    return tr(
        label="Vitals Overview",
        send_to_ai=False,
        query_results=to_send,
        save_results=to_send
    )


"""@tool(
    category="measurements",
    description=(
        "Generates a population-level report of active patients matching a specified clinical category "
        "(e.g., medications, cardiac history, ECG findings, impressions, plans) and optional text-based flags "
        "within a defined time period. "
        "Results may include aggregated clinical entries, dates, and assigned providers, "
        "and can optionally be exported as a spreadsheet. "
        "This tool is most relevant for clinical audits, cohort identification, quality improvement initiatives, "
        "or provider-level reporting."
        "Does not return relevant information regarding a single patient, but used to generate lookup reports."
    ),
    context="This is a report of all the patients':",
    parameters={
        "lookup_type": "Clinical category to search (e.g., Medication, Cardiac, Holter, Impression, ECG, History)",
        "flags": "List of text flags or keywords to filter matching entries",
        "period": "Time window for inclusion (e.g., '6m' for six months)",
        "export": "Whether to export the report as an Excel file"
    }
)"""
def lookup(db_conn, lookup_type : str, flags : list[str], period : str = "6m", export : bool = True):
    """
    Queries and returns a report of patients with history relevant to the provided cardiac_flags.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.
    
    lookup_type : str
        The type to lookup. \\
        One of: Medication, Cardiac, Holter, Impression, Plan, ECG, ECHO, or CC.

    imp_flags : list[str]
        List of impression flags to search for patients.

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    
    export : bool
        If True, will export the queried results as an excel file.
    """
    date = period_parser(period)

    type_map = {
        "Medication" : "MEDS",
        "Cardiac"    : "CARD",
        "Holter"     : "HOL1",
        "Impression" : "SES",
        "ECG"        : "ECG",
        "CC"         : "CC",
        "History"    : "PMH",
    }

    filter = ""
    for i, flag in enumerate(flags):
        if i != 0:
            filter += f"OR (m.dataField LIKE '%{flag}%')\n"
        else:
            filter += f"(m.dataField LIKE '%{flag}%')\n"

    if filter:
        filter = f"AND ({filter})"
        
    print(f"FILTER: {filter}")


    if lookup_type == "Plan" or lookup_type == "ECHO":
        query = f"""
        SELECT
            d.last_name,
            d.first_name,
            m.type,
            m.dataField,
            m.dateObserved,
            d.provider_no
        FROM measurements m
        JOIN demographic d
            ON m.demographicNo = d.demographic_no
        WHERE m.type = '{lookup_type}'
        AND d.patient_status = 'AC'
        AND m.dateObserved >= '{date}'
        {filter}
        ORDER BY
            d.last_name,
            d.first_name,
            m.dateObserved;
        """

    else:
        query = f"""
        SELECT
            d.demographic_no,
            d.last_name,
            d.first_name,
            m.type,
            GROUP_CONCAT(
                CONCAT('{lookup_type}: ', m.dataField)
                ORDER BY m.dateObserved
                SEPARATOR '\n'
            ) AS Entries,
            GROUP_CONCAT(
                CONCAT('{lookup_type}: ', m.dateObserved)
                ORDER BY m.dateObserved
                SEPARATOR '\n'
            ) AS Dates,
            d.provider_no
        FROM measurements m
        JOIN demographic d
            ON m.demographicNo = d.demographic_no
        WHERE m.type = '{type_map.get(lookup_type)}'
        AND d.patient_status = 'AC'
        AND m.dateObserved >= '{date}'
        {filter}
        GROUP BY
            d.demographic_no,
            d.last_name,
            d.first_name,
            d.provider_no,
            m.type
        ORDER BY
            d.last_name,
            d.first_name;
        """

    res = db_conn.query_database(query)
    
    if bool(export):
        os.makedirs("..\\reports", exist_ok=True)
        file_name = f"..\\reports\\{lookup_type} Report_{date}.xlsx"
        print(f"Exporting as {file_name}")
        
        export_data(res, file_name)
        

    return tr(
        label=f"{lookup_type} report for patients with {flags}",
        send_to_ai=False,
        query_results=res,
        save_results=res
    )


"""@tool(
    category="measurements",
    description=(
        "Returns a report of active patients with laboratory investigations that appear incomplete or outstanding "
        "within a defined recent time period, based on related lab markers and thresholds. "
        "Each result includes patient identifiers, lab type, observed values, dates, and assigned provider. "
        "This tool is most relevant for follow-up tracking, care gap identification, "
        "and ensuring completion of ordered laboratory work."
        "Does not return relevant information for a specific single patient."
    ),
    context="This is a report of patients with labs outstanding:",
    parameters={
        "period": "Time window to evaluate for outstanding labs (e.g., '6m')",
        "export": "Whether to export the results as an Excel file"
    }
)"""
def labs_outstanding(db_conn, period : str = "6m", export : bool = False):
    """
    Queries and returns a report of patients with labs outstanding.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    
    export : bool
        If True, will export the queried results as an excel file.
    """

    date = period_parser(period)

    query = f"""
    SELECT
        d.demographic_no,
        d.first_name,
        d.last_name,
        m_labe.type,
        m_labe.dataField,
        m_labe.dateObserved,
        d.provider_no
    FROM demographic d
    JOIN measurements m_labe
        ON m_labe.demographicNo = d.demographic_no
    WHERE d.patient_status = 'AC'
    AND m_labe.type = 'LABE'
    AND m_labe.dataField < 5
    AND m_labe.dateObserved >= {date}
    AND EXISTS (
            SELECT 1
            FROM measurements m_cl
            WHERE m_cl.demographicNo = d.demographic_no
            AND m_cl.type = 'CL'
            AND m_cl.dataField < 2.5
            AND m_cl.dateObserved >= {date}
        )
    ORDER BY
        m_labe.dateObserved;
    """

    res = db_conn.query_database(query)

    if bool(export):
        file_name = f"Labs_outstanding_{date}"
        print(f"Exporting to {file_name}")
        export_data(res, file_name)

    return tr(
        label=f"Labs outstanding within {period}",
        send_to_ai=False,
        query_results=res,
        save_results=res
    )









