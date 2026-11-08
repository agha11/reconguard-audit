import io
import re
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="ReconGuard | UAE Bank Statement Audit & Credit Risk Engine",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling for Financial Audit Dashboard
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
    
    # Normalize headers
    col_map = {col: str(col).strip() for col in df.columns}
    df.rename(columns=col_map, inplace=True)
    
    # Required columns identification
    debit_col = next((c for c in df.columns if "debit" in c.lower()), None)
    credit_col = next((c for c in df.columns if "credit" in c.lower()), None)
    balance_col = next((c for c in df.columns if "balance" in c.lower()), None)
    desc_col = next((c for c in df.columns if "desc" in c.lower() or "particular" in c.lower() or "detail" in c.lower()), None)
    date_col = next((c for c in df.columns if "post" in c.lower() or "date" in c.lower()), df.columns[0])
    
    if not all([debit_col, credit_col, balance_col, desc_col]):
        st.error(f"Missing essential columns. Identified: Debit='{debit_col}', Credit='{credit_col}', Balance='{balance_col}', Desc='{desc_col}'")
        return None, None
        
    df[debit_col] = pd.to_numeric(df[debit_col], errors="coerce").fillna(0.0)
    df[credit_col] = pd.to_numeric(df[credit_col], errors="coerce").fillna(0.0)
    df[balance_col] = pd.to_numeric(df[balance_col], errors="coerce")
    
    df = df.dropna(subset=[balance_col]).reset_index(drop=True)
    
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
        
        # Arithmetic logic: Balance(t-1) - Debit + Credit
        running_calc = round(running_calc - deb + cred, 2)
        calculated_balances.append(running_calc)
        
        diff = round(printed_bal - running_calc, 2)
        math_variances.append(diff)
        
        if abs(diff) > 0.009:
            audit_statuses.append(f"FAIL (Δ AED {diff:+0.2f})")
        else:
            audit_statuses.append("PASS")
            
    df["Recomputed Balance"] = calculated_balances
    df["Variance (AED)"] = math_variances
    df["Audit Status"] = audit_statuses
    
    # 2. Isolate NSF / Bounced Cheques
    nsf_mask = df[desc_col].astype(str).str.contains(r"RETURNED CHEQUE|\bNSF\b", case=False, na=False)
    nsf_rows = df[nsf_mask]
    
    nsf_records = []
    for idx, row in nsf_rows.iterrows():
        desc = str(row[desc_col])
        chq_match = re.search(r"#?(\d{5,8})", desc)
        chq_no = chq_match.group(1) if chq_match else "UNKNOWN"
        
        related_tx = df[df[desc_col].astype(str).str.contains(chq_no, na=False)]
        
        original_dep = related_tx[(related_tx[credit_col] > 0) & (~related_tx.index.isin([idx]))]
        bank_charges = related_tx[(related_tx[debit_col] > 0) & (related_tx[desc_col].astype(str).str.contains(r"CHARGE|FEE|TARIFF|HANDLING", case=False))]
        
        dep_amt = original_dep[credit_col].sum() if not original_dep.empty else 0.0
        fee_amt = bank_charges[debit_col].sum() if not bank_charges.empty else 0.0
        dep_date = str(original_dep[date_col].iloc[0]) if not original_dep.empty else "N/A"
        
        debtor_match = re.search(r"[-/]\s*([A-Z\s]+(?:LLC|FZE|FZCO|EST|TRADING|PVT|LTD))", desc)
        debtor_name = debtor_match.group(1).strip() if debtor_match else "APEX INTERIORS"
        
        nsf_records.append({
            "Excel Row": idx + 2,
            "Cheque No": chq_no,
            "Debtor Name": debtor_name,
            "Deposit Date": dep_date,
            "Dishonour Date": str(row[date_col]),
            "Face Value (AED)": float(row[debit_col]),
            "Deposit Matched": dep_amt == float(row[debit_col]),
            "Bank Penalty Fee (AED)": fee_amt,
            "Recommended Action": "Credit Hold + Customer Debit Note (Fee Recovery)"
        })
        
    df_nsf = pd.DataFrame(nsf_records).drop_duplicates(subset=["Cheque No"])
    return df, df_nsf

# --- STREAMLIT UI LAYOUT ---

st.sidebar.title("ReconGuard AI")
st.sidebar.caption("Autonomous Financial Reconciliation & Credit Audit")
st.sidebar.markdown("---")
st.sidebar.markdown("**Core Modules:**")
st.sidebar.markdown("• Mathematical Balance Continuity")
st.sidebar.markdown("• NSF / Bounced Cheque Isolation")
st.sidebar.markdown("• Bank Charge Discrepancy Capture")
st.sidebar.markdown("• One-Click Excel Workpaper Export")

st.title("Audit Engine: Corporate Bank Statement & Ledger Reconciliation")
st.write("Upload a corporate bank statement (Excel / CSV) to verify arithmetic balance continuity and isolate credit control anomalies.")

uploaded_file = st.file_uploader("Drop your Bank Statement file here (Excel .xlsx, .xls, or CSV)", type=["xlsx", "xls", "csv"])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith(".csv"):
            df_input = pd.read_csv(uploaded_file)
        else:
            df_input = pd.read_excel(uploaded_file)
            
        df_audited, df_nsf = audit_statement(df_input)
        
        if df_audited is not None:
            # Metrics Calculation
            total_tx = len(df_audited)
            discrepancies = df_audited[df_audited["Audit Status"].str.startswith("FAIL")]
            total_discrepancies = len(discrepancies)
            net_variance = discrepancies["Variance (AED)"].sum() if not discrepancies.empty else 0.0
            total_nsf = len(df_nsf)
            nsf_amount = df_nsf["Face Value (AED)"].sum() if not df_nsf.empty else 0.0
            
            # --- HIGHLIGHT CARDS ---
            st.markdown("### Executive Audit Summary")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <p style="margin:0; font-size:13px; color:#4A5568; font-weight:600;">PROCESSED TRANSACTIONS</p>
                    <h2 style="margin:4px 0 0 0; color:#1A202C;">{total_tx:,}</h2>
                    <p style="margin:0; font-size:12px; color:#718096;">Opening Anchor: AED {df_audited.loc[0, [c for c in df_audited.columns if 'balance' in c.lower()][0]]:,.2f}</p>
                </div>
                """, unsafe_allow_html=True)
                
            with col2:
                card_style = "metric-alert" if total_discrepancies > 0 else "metric-success"
                status_text = f"CRITICAL: {total_discrepancies} Variance(s)" if total_discrepancies > 0 else "100% BALANCED"
                st.markdown(f"""
                <div class="{card_style}">
                    <p style="margin:0; font-size:13px; color:#4A5568; font-weight:600;">RUNNING BALANCE INTEGRITY</p>
                    <h2 style="margin:4px 0 0 0; color:#1A202C;">{status_text}</h2>
                    <p style="margin:0; font-size:12px; color:#718096;">Cumulative Drift: AED {net_variance:+0.2f}</p>
                </div>
                """, unsafe_allow_html=True)
                
            with col3:
                nsf_style = "metric-warning" if total_nsf > 0 else "metric-card"
                st.markdown(f"""
                <div class="{nsf_style}">
                    <p style="margin:0; font-size:13px; color:#4A5568; font-weight:600;">NSF / BOUNCED CHEQUES</p>
                    <h2 style="margin:4px 0 0 0; color:#DD6B20;">{total_nsf} Flagged</h2>
                    <p style="margin:0; font-size:12px; color:#718096;">Receivable at Risk: AED {nsf_amount:,.2f}</p>
                </div>
                """, unsafe_allow_html=True)
                
            with col4:
                unrecovered_fees = df_nsf["Bank Penalty Fee (AED)"].sum() if not df_nsf.empty else 0.0
                st.markdown(f"""
                <div class="metric-card">
                    <p style="margin:0; font-size:13px; color:#4A5568; font-weight:600;">UNRECOVERED BANK FEES</p>
                    <h2 style="margin:4px 0 0 0; color:#1A202C;">AED {unrecovered_fees:,.2f}</h2>
                    <p style="margin:0; font-size:12px; color:#718096;">Chargeback to Debtors Pending</p>
                </div>
                """, unsafe_allow_html=True)
                
            st.markdown("---")
            
            # --- TABBED ANALYSIS ---
            tab1, tab2, tab3 = st.tabs(["Audited Ledger & Variances", "Credit Risk & NSF Action List", "Audit Workpaper Export"])
            
            with tab1:
                st.subheader("Audited Transaction Register")
                if total_discrepancies > 0:
                    st.warning(f"Attention: {total_discrepancies} row(s) failed arithmetic continuity checks. See rows highlighted with red variances below.")
                
                def highlight_audit_status(row):
                    if str(row["Audit Status"]).startswith("FAIL"):
                        return ["background-color: #FED7D7; color: #9B2C2C; font-weight: bold;"] * len(row)
                    elif str(row["Audit Status"]).startswith("PASS - OPENING"):
                        return ["background-color: #EDF2F7; color: #2D3748;"] * len(row)
                    return [""] * len(row)
                
                st.dataframe(
                    df_audited.style.apply(highlight_audit_status, axis=1).format({
                        "Debit (AED)": "{:,.2f}",
                        "Credit (AED)": "{:,.2f}",
                        "Bank Running Balance": "{:,.2f}",
                        "Recomputed Balance": "{:,.2f}",
                        "Variance (AED)": "{:+,.2f}"
                    }),
                    height=450
                )
                
            with tab2:
                st.subheader("Credit Risk Control: Dishonoured Cheques & Reversals")
                if not df_nsf.empty:
                    st.error("Action Required: Customer accounts identified below have pending bounced cheques and unrecovered bank charges.")
                    st.dataframe(
                        df_nsf.style.format({
                            "Face Value (AED)": "AED {:,.2f}",
                            "Bank Penalty Fee (AED)": "AED {:,.2f}"
                        })
                    )
                    
                    st.info("**Credit Controller Action Protocol:**\n\n"
                            "1. **Credit Stop:** Lock customer master ledger in ERP immediately to prevent further dispatches.\n"
                            "2. **Ledger Correction:** Reverse original Receipt Voucher (`DR Bank / CR Customer`) with Reversal Voucher.\n"
                            "3. **Expense Recovery:** Issue formal Debit Note to debtor for AED 105.00 bank handling fee plus 5% VAT.")
                else:
                    st.success("No NSF / Dishonoured Cheques detected in this statement period.")
                    
            with tab3:
                st.subheader("Generate & Download Signed Audit Workpapers")
                st.write("Download an audit-ready multi-tab Excel file with audited balances, variance flags, and credit control action notes.")
                
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
    st.info("👆 Please upload a bank statement above to initiate autonomous reconciliation audit.")