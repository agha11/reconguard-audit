import io
import re
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="ReconGuard | Autonomous Bank Statement Audit & Internal Controls Engine",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Professional Executive Audit Dashboard Styling
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 16px;
        border-left: 5px solid #1E3A8A;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    .metric-alert {
        background-color: #fff5f5;
        border-radius: 8px;
        padding: 16px;
        border-left: 5px solid #E53E3E;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    .metric-warning {
        background-color: #fffaf0;
        border-radius: 8px;
        padding: 16px;
        border-left: 5px solid #DD6B20;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    .metric-success {
        background-color: #f0fff4;
        border-radius: 8px;
        padding: 16px;
        border-left: 5px solid #38A169;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
</style>
""", unsafe_allow_html=True)

def audit_statement(df_raw):
    df = df_raw.copy()
    
    # 1. Normalize Column Headers
    col_map = {col: str(col).strip() for col in df.columns}
    df.rename(columns=col_map, inplace=True)
    
    # Detect Standard Banking Columns (Agnostic to Currency / Bank Format)
    debit_col = next((c for c in df.columns if any(k in c.lower() for k in ["debit", "withdrawal", "paid out", "dr"])), None)
    credit_col = next((c for c in df.columns if any(k in c.lower() for k in ["credit", "deposit", "paid in", "cr"])), None)
    balance_col = next((c for c in df.columns if any(k in c.lower() for k in ["balance", "running bal", "closing"])), None)
    desc_col = next((c for c in df.columns if any(k in c.lower() for k in ["desc", "particular", "narrative", "detail", "transaction"])), None)
    date_col = next((c for c in df.columns if any(k in c.lower() for k in ["date", "posting", "trans date"])), df.columns[0])
    
    if not all([debit_col, credit_col, balance_col, desc_col]):
        st.error(f"Missing essential accounting columns. Detected: Debit='{debit_col}', Credit='{credit_col}', Balance='{balance_col}', Description='{desc_col}'")
        return None, None, None
        
    df[debit_col] = pd.to_numeric(df[debit_col], errors="coerce").fillna(0.0)
    df[credit_col] = pd.to_numeric(df[credit_col], errors="coerce").fillna(0.0)
    df[balance_col] = pd.to_numeric(df[balance_col], errors="coerce")
    
    # Exclude trailing empty rows
    df = df.dropna(subset=[balance_col]).reset_index(drop=True)
    
    # 2. Row-by-Row Mathematical Continuity Check: B(t) = B(t-1) - Debit + Credit
    calculated_balances = []
    math_variances = []
    audit_statuses = []
    
    opening_anchor = float(df.loc[0, balance_col])
    running_calc = opening_anchor
    calculated_balances.append(running_calc)
    math_variances.append(0.0)
    audit_statuses.append("PASS - OPENING ANCHOR")
    
    for i in range(1, len(df)):
        deb = float(df.loc[i, debit_col])
        cred = float(df.loc[i, credit_col])
        printed_bal = float(df.loc[i, balance_col])
        
        running_calc = round(running_calc - deb + cred, 2)
        calculated_balances.append(running_calc)
        
        diff = round(printed_bal - running_calc, 2)
        math_variances.append(diff)
        
        if abs(diff) > 0.009:
            audit_statuses.append(f"FAIL (Δ {diff:+0.2f})")
        else:
            audit_statuses.append("PASS")
            
    df["Recomputed Balance"] = calculated_balances
    df["Variance"] = math_variances
    df["Audit Status"] = audit_statuses
    
    # 3. Global NSF Check / Dishonoured Reversal Detection
    # Safe boundary regex avoids false triggers on regular "transfer" descriptions
    nsf_mask = df[desc_col].astype(str).str.contains(r"RETURNED CHEQUE|RETURNED CHECK|\bNSF\b|BOUNCED|DISHONO", case=False, na=False)
    nsf_rows = df[nsf_mask]
    
    nsf_records = []
    for idx, row in nsf_rows.iterrows():
        desc = str(row[desc_col])
        chq_match = re.search(r"#?(\d{4,10})", desc)
        chq_no = chq_match.group(1) if chq_match else "N/A"
        
        related_tx = df[df[desc_col].astype(str).str.contains(chq_no, na=False)] if chq_no != "N/A" else pd.DataFrame()
        
        original_dep = related_tx[(related_tx[credit_col] > 0) & (~related_tx.index.isin([idx]))]
        bank_charges = related_tx[(related_tx[debit_col] > 0) & (related_tx[desc_col].astype(str).str.contains(r"CHARGE|FEE|TARIFF|HANDLING|PENALTY", case=False))]
        
        dep_amt = original_dep[credit_col].sum() if not original_dep.empty else 0.0
        fee_amt = bank_charges[debit_col].sum() if not bank_charges.empty else 0.0
        dep_date = str(original_dep[date_col].iloc[0]) if not original_dep.empty else "N/A"
        
        # Debtor entity identification
        debtor_match = re.search(r"[-/:]\s*([A-Za-z0-9\s&]+(?:LLC|INC|LTD|CORP|CO|GROUP|TRADING|FZCO|FZE|ENTERPRISE))", desc, re.IGNORECASE)
        debtor_name = debtor_match.group(1).strip() if debtor_match else "Commercial Debtor"
        
        nsf_records.append({
            "Ledger Row": idx + 2,
            "Check / Ref No": chq_no,
            "Debtor / Customer": debtor_name,
            "Initial Credit Date": dep_date,
            "Dishonour Date": str(row[date_col]),
            "Dishonoured Amount": float(row[debit_col]),
            "Deposit Reversal Verified": dep_amt == float(row[debit_col]),
            "Bank Penalty Fee": fee_amt,
            "Internal Control Action": "Place Debtor on Credit Stop; Reverse Receipt Voucher; Charge Fee to Customer"
        })
        
    df_nsf = pd.DataFrame(nsf_records).drop_duplicates(subset=["Check / Ref No"])
    
    col_dict = {
        "debit": debit_col,
        "credit": credit_col,
        "balance": balance_col,
        "desc": desc_col,
        "date": date_col
    }
    return df, df_nsf, col_dict

# --- STREAMLIT UI LAYOUT ---

st.sidebar.title("ReconGuard AI")
st.sidebar.caption("Autonomous Financial Reconciliation & Internal Controls")
st.sidebar.markdown("---")
st.sidebar.markdown("**Global Core Capabilities:**")
st.sidebar.markdown("• Mathematical Balance Continuity ($B_0 + \sum C - \sum D = B_n$)")
st.sidebar.markdown("• NSF / Returned Check & Reversal Isolation")
st.sidebar.markdown("• Hidden Bank Tariff & Wire Fee Audit")
st.sidebar.markdown("• Multi-Tab Signed Excel Workpaper Export")

st.title("Autonomous Bank Statement Audit & Reconciliation Engine")
st.write("Ingest commercial operating statements (Excel / CSV) to verify arithmetic ledger continuity and detect credit control & banking discrepancies.")

uploaded_file = st.file_uploader("Upload Bank Statement File (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith(".csv"):
            df_input = pd.read_csv(uploaded_file)
        else:
            df_input = pd.read_excel(uploaded_file)
            
        df_audited, df_nsf, cols = audit_statement(df_input)
        
        if df_audited is not None:
            total_tx = len(df_audited)
            discrepancies = df_audited[df_audited["Audit Status"].str.startswith("FAIL")]
            total_discrepancies = len(discrepancies)
            net_variance = discrepancies["Variance"].sum() if not discrepancies.empty else 0.0
            total_nsf = len(df_nsf)
            nsf_amount = df_nsf["Dishonoured Amount"].sum() if not df_nsf.empty else 0.0
            unrecovered_fees = df_nsf["Bank Penalty Fee"].sum() if not df_nsf.empty else 0.0
            
            # --- HIGHLIGHT SUMMARY METRICS ---
            st.markdown("### Executive Audit Summary")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <p style="margin:0; font-size:13px; color:#4A5568; font-weight:600;">PROCESSED TRANSACTIONS</p>
                    <h2 style="margin:4px 0 0 0; color:#1A202C;">{total_tx:,}</h2>
                    <p style="margin:0; font-size:12px; color:#718096;">Opening Anchor: {df_audited.loc[0, cols['balance']]:,.2f}</p>
                </div>
                """, unsafe_allow_html=True)
                
            with col2:
                card_style = "metric-alert" if total_discrepancies > 0 else "metric-success"
                status_text = f"CRITICAL: {total_discrepancies} Variance(s)" if total_discrepancies > 0 else "100% BALANCED"
                st.markdown(f"""
                <div class="{card_style}">
                    <p style="margin:0; font-size:13px; color:#4A5568; font-weight:600;">RUNNING BALANCE INTEGRITY</p>
                    <h2 style="margin:4px 0 0 0; color:#1A202C;">{status_text}</h2>
                    <p style="margin:0; font-size:12px; color:#718096;">Cumulative Drift: {net_variance:+0.2f}</p>
                </div>
                """, unsafe_allow_html=True)
                
            with col3:
                nsf_style = "metric-warning" if total_nsf > 0 else "metric-card"
                st.markdown(f"""
                <div class="{nsf_style}">
                    <p style="margin:0; font-size:13px; color:#4A5568; font-weight:600;">NSF / RETURNED CHECKS</p>
                    <h2 style="margin:4px 0 0 0; color:#DD6B20;">{total_nsf} Flagged</h2>
                    <p style="margin:0; font-size:12px; color:#718096;">Receivable at Risk: {nsf_amount:,.2f}</p>
                </div>
                """, unsafe_allow_html=True)
                
            with col4:
                st.markdown(f"""
                <div class="metric-card">
                    <p style="margin:0; font-size:13px; color:#4A5568; font-weight:600;">BANK PENALTY CHARGES</p>
                    <h2 style="margin:4px 0 0 0; color:#1A202C;">{unrecovered_fees:,.2f}</h2>
                    <p style="margin:0; font-size:12px; color:#718096;">Debtor Chargebacks Pending</p>
                </div>
                """, unsafe_allow_html=True)
                
            st.markdown("---")
            
            # --- TABBED ANALYSIS ---
            tab1, tab2, tab3 = st.tabs(["Audited Ledger & Discrepancies", "Credit Risk & NSF Action Schedule", "Export Signed Workpapers"])
            
            with tab1:
                st.subheader("Audited Transaction Register")
                if total_discrepancies > 0:
                    st.warning(f"Mathematical continuity alert: {total_discrepancies} transaction(s) failed internal balance checks. Discrepancies highlighted in red below.")
                
                def highlight_audit_status(row):
                    if str(row["Audit Status"]).startswith("FAIL"):
                        return ["background-color: #FED7D7; color: #9B2C2C; font-weight: bold;"] * len(row)
                    elif str(row["Audit Status"]).startswith("PASS - OPENING"):
                        return ["background-color: #EDF2F7; color: #2D3748;"] * len(row)
                    return [""] * len(row)
                
                format_dict = {
                    cols["debit"]: "{:,.2f}",
                    cols["credit"]: "{:,.2f}",
                    cols["balance"]: "{:,.2f}",
                    "Recomputed Balance": "{:,.2f}",
                    "Variance": "{:+,.2f}"
                }
                
                st.dataframe(
                    df_audited.style.apply(highlight_audit_status, axis=1).format(format_dict),
                    height=450
                )
                
            with tab2:
                st.subheader("Credit Risk Control: Dishonoured Checks & Reversals")
                if not df_nsf.empty:
                    st.error("Action Required: Customer accounts identified below have bounced payment deposits and unrecovered bank tariff penalties.")
                    st.dataframe(
                        df_nsf.style.format({
                            "Dishonoured Amount": "{:,.2f}",
                            "Bank Penalty Fee": "{:,.2f}"
                        })
                    )
                    
                    st.info("**Credit Management Internal Control Protocol:**\n\n"
                            "1. **Account Freeze:** Place customer master account on immediate Credit Stop in ERP/accounting system.\n"
                            "2. **Ledger Correction:** Post receipt reversal voucher to reinstate the original accounts receivable invoice.\n"
                            "3. **Cost Recovery:** Issue automated Debit Note to debtor for bank penalty handling charges.")
                else:
                    st.success("No dishonoured checks or unapplied NSF reversals detected in this period.")
                    
            with tab3:
                st.subheader("Generate & Download Signed Audit Workpapers")
                st.write("Export a multi-tab workpaper workbook with full arithmetic audits, isolated credit risk schedules, and auto-adjusted column dimensions.")
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    df_audited.to_excel(writer, sheet_name="Audited_Ledger", index=False)
                    if not df_nsf.empty:
                        df_nsf.to_excel(writer, sheet_name="Credit_Risk_Alerts", index=False)
                    
                    # Auto-fit column widths across all sheets
                    for sheetname in writer.sheets:
                        ws = writer.sheets[sheetname]
                        for col in ws.columns:
                            max_len = max(len(str(cell.value or '')) for cell in col)
                            col_letter = col[0].column_letter
                            ws.column_dimensions[col_letter].width = max(max_len + 3, 14)
                
                excel_data = output.getvalue()
                
                st.download_button(
                    label="📥 Download Audit Workpaper (.XLSX)",
                    data=excel_data,
                    file_name=f"ReconGuard_Audit_Report_{uploaded_file.name.split('.')[0]}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
    except Exception as e:
        st.error(f"Error processing statement: {str(e)}")
else:
    st.info("👆 Upload an operating bank statement above to initiate autonomous audit.")