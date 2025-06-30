from flask import Flask, render_template, request, redirect, session, flash, g, url_for
from werkzeug.utils import secure_filename
from fpdf import FPDF
from datetime import datetime, timedelta
import sqlite3
import os
import pandas as pd
import io
from flask import send_file
import calendar

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# ====== PERSISTENT DATABASE SETUP FOR AZURE ======
if 'WEBSITE_SITE_NAME' in os.environ:  # Check if running on Azure
    DATABASE = '/home/data/billing.db'  # Azure persistent storage path
else:
    DATABASE = 'data/billing.db'  # Local path for testing

# Ensure the folder exists
os.makedirs(os.path.dirname(DATABASE), exist_ok=True)

# Rest of your existing code (keep everything below this line)
# =================================================

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# ... (keep all other existing functions and routes below)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Initialize database if it doesn't exist
if not os.path.exists(DATABASE):
    with app.app_context():
        db = get_db()
        db.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            )
        """)
        db.execute("""
        CREATE TABLE billing (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            year TEXT NOT NULL,
            month TEXT NOT NULL,
            company_name TEXT NOT NULL,
            service TEXT NOT NULL,
            amount_usd REAL NOT NULL,
            conversion_rate REAL NOT NULL,
            amount_bdt REAL NOT NULL,
            service_charge REAL NOT NULL,
            vat REAL NOT NULL,
            total_bdt REAL NOT NULL,
            bill_received_date TEXT,
            bill_disbursed_date TEXT
        )
        """)
        db.execute("""
            CREATE TABLE metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                value TEXT NOT NULL,
                UNIQUE(type, value)
            )
        """)
        db.commit()


# Check user role before sensitive routes
@app.before_request
def check_role():
    restricted_routes = ['/entry', '/edit', '/delete', '/users']
    if any(request.path.startswith(route) for route in restricted_routes):
        if session.get('role') != 'admin':
            flash('Access denied - Admin only', 'error')
            return redirect('/dashboard')


@app.route('/')
def home():
    if 'user_id' in session:
        return redirect('/dashboard')
    return redirect('/login')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        role = 'admin' if user_count == 0 else 'monitor'
        db.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                   (username, password, role))
        db.commit()
        flash(f'Registered successfully as {role}.')
        return redirect('/login')
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ? AND password = ?",
                          (username, password)).fetchone()
        if user:
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['role'] = user[3]
            return redirect('/dashboard')
        flash('Invalid credentials')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    db = get_db()
    if session.get('role') == 'admin':
        azure_total = db.execute("SELECT SUM(total_bdt) FROM billing WHERE provider = 'Azure'").fetchone()[0] or 0
        gcp_total = db.execute("SELECT SUM(total_bdt) FROM billing WHERE provider = 'GCP'").fetchone()[0] or 0
    else:
        # For monitor users, show all data but without edit options
        azure_total = db.execute("SELECT SUM(total_bdt) FROM billing WHERE provider = 'Azure'").fetchone()[0] or 0
        gcp_total = db.execute("SELECT SUM(total_bdt) FROM billing WHERE provider = 'GCP'").fetchone()[0] or 0

    return render_template('dashboard.html', azure_total=azure_total, gcp_total=gcp_total)


@app.route('/entry', methods=['GET', 'POST'])
def entry():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied - Admin only', 'error')
        return redirect('/dashboard')

    db = get_db()
    if request.method == 'POST':
        for field in ['provider', 'year', 'month', 'company', 'service']:
            if f'new_{field}' in request.form and request.form[f'new_{field}']:
                db.execute("INSERT OR IGNORE INTO metadata (type, value) VALUES (?, ?)",
                           (field, request.form[f'new_{field}']))

        provider = request.form.get('new_provider') or request.form.get('provider')
        year = request.form.get('new_year') or request.form.get('year')
        month = request.form.get('new_month') or request.form.get('month')
        company = request.form.get('new_company') or request.form.get('company')
        service = request.form.get('new_service') or request.form.get('service')

        amount_usd = float(request.form['amount_usd'])
        conversion_rate = float(request.form['conversion_rate'])
        amount_bdt = round(amount_usd * conversion_rate, 2)
        service_charge = round(amount_bdt * 0.07, 2)
        vat = round(service_charge * 0.05, 2)
        total_bdt = round(amount_bdt + service_charge + vat, 2)

        db.execute("""
            INSERT INTO billing (
                provider, year, month, company_name, service,
                amount_usd, conversion_rate, amount_bdt,
                service_charge, vat, total_bdt,
                bill_received_date, bill_disbursed_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (provider, year, month, company, service, amount_usd, conversion_rate,
              amount_bdt, service_charge, vat, total_bdt,
              request.form.get('bill_received_date'), request.form.get('bill_disbursed_date')))
        db.commit()
        flash('Entry submitted successfully!', 'success')
        return redirect('/entry')

    # Get all existing values from imported data
    providers = sorted([row[0] for row in db.execute("SELECT DISTINCT provider FROM billing ORDER BY provider").fetchall()])
    years = sorted([row[0] for row in db.execute("SELECT DISTINCT year FROM billing ORDER BY year DESC").fetchall()])
    months = sorted([row[0] for row in db.execute("SELECT DISTINCT month FROM billing").fetchall()],
                   key=lambda x: list(['January', 'February', 'March', 'April', 'May', 'June',
                                      'July', 'August', 'September', 'October', 'November', 'December']).index(x)
                             if x in ['January', 'February', 'March', 'April', 'May', 'June',
                                     'July', 'August', 'September', 'October', 'November', 'December']
                             else 13)
    companies = sorted([row[0] for row in db.execute("SELECT DISTINCT company_name FROM billing ORDER BY company_name").fetchall()])
    services = sorted([row[0] for row in db.execute("SELECT DISTINCT service FROM billing ORDER BY service").fetchall()])

    return render_template('entry.html',
                         providers=providers,
                         years=years,
                         months=months,
                         companies=companies,
                         services=services)

@app.route('/report', methods=['GET', 'POST'])
def report():
    if 'user_id' not in session:
        return redirect('/login')

    db = get_db()
    query = "SELECT * FROM billing WHERE 1=1"
    params = []

    provider = request.args.get('provider')
    service = request.args.get('service')
    month = request.args.get('month')
    company = request.args.get('company')
    year = request.args.get('year')

    if provider:
        query += " AND provider = ?"
        params.append(provider)
    if service:
        query += " AND service = ?"
        params.append(service)
    if month:
        query += " AND month = ?"
        params.append(month)
    if company:
        query += " AND company_name = ?"
        params.append(company)
    if year:
        query += " AND year = ?"
        params.append(year)

    results = db.execute(query, params).fetchall()
    total = sum(row[11] for row in results) if results else 0

    services = sorted({row[0] for row in db.execute("SELECT DISTINCT service FROM billing").fetchall()})
    months = sorted({row[0] for row in db.execute("SELECT DISTINCT month FROM billing").fetchall()})
    companies = sorted({row[0] for row in db.execute("SELECT DISTINCT company_name FROM billing").fetchall()})
    years = sorted({row[0] for row in db.execute("SELECT DISTINCT year FROM billing").fetchall()})

    return render_template('report.html',
                           results=results,
                           total=total,
                           services=services,
                           months=months,
                           companies=companies,
                           years=years)


@app.route('/edit/<int:entry_id>', methods=['GET', 'POST'])
def edit_entry(entry_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied - Admin only', 'error')
        return redirect('/report')

    db = get_db()
    if request.method == 'POST':
        provider = request.form['provider']
        year = request.form['year']
        month = request.form['month']
        company_name = request.form['company_name']
        service = request.form['service']
        amount_usd = float(request.form['amount_usd'])
        conversion_rate = float(request.form['conversion_rate'])

        amount_bdt = amount_usd * conversion_rate
        service_charge = round(amount_bdt * 0.07, 1)
        vat = round((amount_bdt + service_charge) * 0.05, 1)
        total_bdt = amount_bdt + service_charge + vat

        db.execute("""
            UPDATE billing SET 
                provider = ?, 
                year = ?, 
                month = ?, 
                company_name = ?, 
                service = ?, 
                amount_usd = ?, 
                conversion_rate = ?, 
                amount_bdt = ?, 
                service_charge = ?, 
                vat = ?, 
                total_bdt = ?
            WHERE id = ?
        """, (provider, year, month, company_name, service, amount_usd,
              conversion_rate, amount_bdt, service_charge, vat, total_bdt, entry_id))
        db.commit()
        flash('Entry updated successfully.')
        return redirect('/report')

    entry = db.execute("SELECT * FROM billing WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        flash('Entry not found')
        return redirect('/report')
    return render_template('edit_entry.html', entry=entry)


@app.route('/delete/<int:entry_id>', methods=['POST'])
def delete_entry(entry_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied - Admin only', 'error')
        return redirect('/report')

    db = get_db()
    db.execute("DELETE FROM billing WHERE id = ?", (entry_id,))
    db.commit()
    flash('Entry deleted successfully.')
    return redirect('/report')


@app.route('/users', methods=['GET', 'POST'])
def users():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied - Admin only', 'error')
        return redirect('/dashboard')

    db = get_db()
    if request.method == 'POST':
        user_id = request.form['user_id']
        new_role = request.form['role']
        db.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        db.commit()
        flash('User role updated.')

    users = db.execute("SELECT id, username, role FROM users").fetchall()
    return render_template('users.html', users=users)


@app.route('/export/excel')
def export_excel():
    if 'user_id' not in session:
        return redirect('/login')

    import io
    db = get_db()

    # Start with base query
    query = "SELECT * FROM billing WHERE 1=1"
    params = []

    # Apply the same filters as the report page
    provider = request.args.get('provider')
    service = request.args.get('service')
    month = request.args.get('month')
    company = request.args.get('company')
    year = request.args.get('year')

    if provider:
        query += " AND provider = ?"
        params.append(provider)
    if service:
        query += " AND service = ?"
        params.append(service)
    if month:
        query += " AND month = ?"
        params.append(month)
    if company:
        query += " AND company_name = ?"
        params.append(company)
    if year:
        query += " AND year = ?"
        params.append(year)

    df = pd.read_sql_query(query, db, params=params)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='BillingData', index=False)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        download_name='cloud_billing_data.xlsx',
        as_attachment=True
    )


@app.route('/export/pdf')
def export_pdf():
    if 'user_id' not in session:
        return redirect('/login')

    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from datetime import datetime

    db = get_db()

    # Start with base query
    query = "SELECT * FROM billing WHERE 1=1"
    params = []

    # Apply the same filters as the report page
    provider = request.args.get('provider')
    service = request.args.get('service')
    month = request.args.get('month')
    company = request.args.get('company')
    year = request.args.get('year')

    if provider:
        query += " AND provider = ?"
        params.append(provider)
    if service:
        query += " AND service = ?"
        params.append(service)
    if month:
        query += " AND month = ?"
        params.append(month)
    if company:
        query += " AND company_name = ?"
        params.append(company)
    if year:
        query += " AND year = ?"
        params.append(year)

    data = db.execute(query, params).fetchall()

    # Create PDF with professional design
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))

    # Title and metadata
    styles = getSampleStyleSheet()
    elements = []

    # Add header
    elements.append(Paragraph("Cloud Billing Report", styles['Title']))
    elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    elements.append(Paragraph(f"User: {session.get('username', 'Unknown')}", styles['Normal']))

    # Add filter details
    filter_text = "Filters: "
    filters = []
    if provider:
        filters.append(f"Provider: {provider}")
    if company:
        filters.append(f"Company: {company}")
    if year:
        filters.append(f"Year: {year}")
    if month:
        filters.append(f"Month: {month}")
    if service:
        filters.append(f"Service: {service}")

    if filters:
        filter_text += ", ".join(filters)
    else:
        filter_text += "All records"

    elements.append(Paragraph(filter_text, styles['Normal']))
    elements.append(Spacer(1, 0.25 * inch))

    # Prepare table data
    columns = ['ID', 'Provider', 'Year', 'Month', 'Company', 'Service',
               'Amount USD', 'Rate', 'Amount BDT', 'Charge', 'VAT', 'Total BDT',
               'Received', 'Disbursed']

    table_data = [columns]
    for row in data:
        table_data.append([
            str(row[0]), row[1], row[2], row[3], row[4], row[5],
            f"{row[6]:.2f}", f"{row[7]:.2f}", f"{row[8]:.2f}",
            f"{row[9]:.2f}", f"{row[10]:.2f}", f"{row[11]:.2f}",
            row[12] if row[12] else '-', row[13] if row[13] else '-'
        ])

    # Create table with professional styling
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4361ee')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.25 * inch))

    # Add footer
    elements.append(Paragraph(f"Total Records: {len(data)}", styles['Normal']))
    elements.append(Paragraph("Confidential - Transcom Limited", styles['Italic']))

    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype='application/pdf',
        download_name=f"cloud_billing_report_{datetime.now().strftime('%Y%m%d')}.pdf",
        as_attachment=True
    )

@app.route('/import/excel', methods=['GET', 'POST'])
def import_excel():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied - Admin only', 'error')
        return redirect('/dashboard')

    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            try:
                df = pd.read_excel(file)
                # Sort the DataFrame alphabetically before processing
                df = df.sort_values(by=['Provider', 'Company', 'Service'])
                db = get_db()

                # Validate required columns
                required_columns = ['Provider', 'Year', 'Month', 'Company', 'Service',
                                    'Amount USD', 'Conversion Rate']
                if not all(col in df.columns for col in required_columns):
                    missing = [col for col in required_columns if col not in df.columns]
                    flash(f'Missing required columns: {", ".join(missing)}', 'error')
                    return redirect(request.url)

                # Process each row
                for _, row in df.iterrows():
                    amount_usd = float(row['Amount USD'])
                    conversion_rate = float(row['Conversion Rate'])
                    amount_bdt = round(amount_usd * conversion_rate, 2)
                    service_charge = round(amount_bdt * 0.07, 2)
                    vat = round((amount_bdt + service_charge) * 0.05, 2)
                    total_bdt = round(amount_bdt + service_charge + vat, 2)

                    db.execute("""
                        INSERT INTO billing (
                            provider, year, month, company_name, service,
                            amount_usd, conversion_rate, amount_bdt,
                            service_charge, vat, total_bdt,
                            bill_received_date, bill_disbursed_date
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row['Provider'], str(row['Year']), row['Month'], row['Company'], row['Service'],
                        amount_usd, conversion_rate, amount_bdt,
                        service_charge, vat, total_bdt,
                        row.get('Bill Received Date'), row.get('Bill Disbursed Date')
                    ))

                db.commit()
                flash(f'Successfully imported {len(df)} records', 'success')
                return redirect('/report')

            except Exception as e:
                flash(f'Error importing file: {str(e)}', 'error')
                return redirect(request.url)

    return render_template('import_excel.html')


@app.route('/fix_calculations')
def fix_calculations():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied - Admin only', 'error')
        return redirect('/dashboard')

    db = get_db()
    entries = db.execute("SELECT * FROM billing").fetchall()

    for entry in entries:
        amount_bdt = entry[8]  # amount_bdt is at index 8
        service_charge = round(amount_bdt * 0.07, 2)
        vat = round(service_charge * 0.05, 2)  # 5% of service charge
        total_bdt = round(amount_bdt + service_charge + vat, 2)

        db.execute("""
            UPDATE billing SET
                service_charge = ?,
                vat = ?,
                total_bdt = ?
            WHERE id = ?
        """, (service_charge, vat, total_bdt, entry[0]))

    db.commit()
    flash('All calculations fixed with proper rounding', 'success')
    return redirect('/report')


if __name__ == '__main__':
    app.run(debug=True)