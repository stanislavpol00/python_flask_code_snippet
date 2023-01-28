import os
import sys
sys.dont_write_bytecode = True
import re
import csv
import json
import datetime
import subprocess

from flask import Flask, render_template, jsonify, redirect, url_for, request
from sqlalchemy import and_, case
from sqlalchemy.sql import func

from db import Session, LogLoaderdb, SMTPMail, LogReport
from mail import send_mail, email_tpl
from config import Config

DAYS_OF_WEEK = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']

date_re = [
    r'^(3[01]|[12][0-9]|0[1-9])/(1[0-2]|0[1-9])/[0-9]{4}$',
    r'^(1[0-2]|0[1-9])-(3[01]|[12][0-9]|0[1-9])-[0-9]{4}$',
]

EXCURSION_TEMP = '-10'
INCURSION_TEMP = '-20'

def row2dict(row):
    d = {}
    for column in row.__table__.columns:
        d[column.name] = str(getattr(row, column.name))

    return d

app = Flask(__name__)


@app.route('/', methods=['GET'])
def home():

    error = request.args.get('error', '')

    return render_template('index.html', error=error)


@app.route('/<date_from_str>/<date_to_str>', methods=['GET'])
def home_report(date_from_str, date_to_str):

    host = request.headers.get("Host")

    date_to     = datetime.datetime.strptime(date_to_str, "%Y-%m-%d").date()
    date_from   = datetime.datetime.strptime(date_from_str, "%Y-%m-%d").date()
    footer_text = request.args.get('footerText', None)

    session = Session()

    q = session.query(LogLoaderdb)
    if date_from != date_to:
        q = q.filter(
            and_(
                LogLoaderdb.logdate >= date_from,
                LogLoaderdb.logdate <= date_to,
            )
        )
    else:
        q = q.filter(LogLoaderdb.logdate==date_to)

    q = q.order_by(
        LogLoaderdb.logdate.asc(),
        LogLoaderdb.logtimein.asc()
    )

    log_list = [row2dict(r) for r in q.all()]

    if not log_list:
        session.close()
        return redirect(url_for('home', error='No data for this date range'))

    file_name = f'report_{datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")}.pdf'
    file_path = f'static/reports/{file_name}'

    if footer_text:
        url_path  = f'http://{host}/report/{date_from_str}/{date_to_str}?footerText={footer_text}'
    else:
        url_path  = f'http://{host}/report/{date_from_str}/{date_to_str}'

    p = subprocess.run(
        ['xvfb-run', '-s', '-screen 0 1024x768x24', '/usr/bin/wkhtmltopdf', '--no-stop-slow-scripts', '--javascript-delay', '5000', url_path, file_path], 
        # ['xvfb-run', '--', '/usr/bin/wkhtmltopdf', '--no-stop-slow-scripts', '--javascript-delay', '3000', url_path, file_path], 
        # ['/usr/bin/wkhtmltopdf', '--no-stop-slow-scripts', '--javascript-delay', '200', url_path, file_path], 
        stdout=subprocess.PIPE,
    )

    log_report = LogReport.create_log_report(
        session,
        filename=file_name,
        filepath=file_path
    )

    try:
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()

    return render_template('index.html', log_list=log_list, file_path=file_path)


@app.route('/csv/import', methods=['GET', 'POST'])
def csv_import():

    mount_path = Config.mount_point
    csv_file_path = None

    for file in os.listdir(mount_path):
        if file.endswith('.csv') or file.endswith('.CSV'):
            csv_file_path = os.path.join(mount_path, file)
            break

    if not csv_file_path:
        print('-- No CSV file found --')
        return jsonify({
            'status': 'error', 
            'message': 'No CSV file found!'
        })

    data_to_import = []

    print(f'-- CSV file found ({csv_file_path}) --')

    ## Read CSV file
    with open(csv_file_path, mode='r') as csv_file:
        csv_reader = csv.reader(x.replace('\0', '') for x in csv_file)

        print('-- Start reading rows from csv file --')
        location_id = None
        for row in csv_reader:

            # print(f'row: {row}')

            if not row:
                if location_id:
                    location_id = None
                continue

            if location_id:

                # for date format dd/mm/yyyy
                date_match = re.match(date_re[0], row[0], re.M|re.I)
                if date_match:

                    # append zero values
                    while len(row) < 19:
                        row.append(0.00)

                    data_to_import.append([location_id] + row)
                    continue

                # for date format mm-dd-yyyy
                date_match = re.match(date_re[1], row[0], re.M|re.I)
                if date_match:

                    # append zero values
                    while len(row) < 19:
                        row.append(0.00)

                    m, d, y = row[0].split('-')
                    row[0] = f'{d}/{m}/{y}'
                    data_to_import.append([location_id] + row)
                    continue

            else:
                if row[0].startswith("Location ID:"):
                    try:
                        location_id = re.search('Location ID: (.+?)$', row[0]).group(1)
                    except AttributeError:
                        location_id = None

        print('-- End reading rows from csv file --')

    session = Session()

    ## Write data from CSV file to DataBase
    for row in data_to_import:

        try:
            dt = datetime.datetime.strptime(row[1] + ' ' + row[2], "%d/%m/%Y %H:%M:%S")
        except Exception as e:
            session.rollback()
            session.close()
            print(e)
            return jsonify({
                'status': 'error', 
                'message': 'Error while parsing date from csv!'
            })

        try:
            log_loader = LogLoaderdb.create_logloaderdb(
                session,
                location_id=row[0],
                logdate=dt.date(),
                logtimein=dt.time(),
                chann1=row[3],
                chann2=row[4],
                chann3=row[5],
                chann4=row[6],
                chann5=row[7],
                chann6=row[8],
                chann7=row[9],
                chann8=row[10],
                chann9=row[11],
                chann10=row[12],
                chann11=row[13],
                chann12=row[14],
                chann13=row[15],
                chann14=row[16],
                chann15=row[17],
                chann16=row[18],
            )
        except Exception as e:
            session.rollback()
            session.close()
            print(e)
            return jsonify({
                'status': 'error', 
                'message': 'Something has gone wrong!'
            })

        # print(row2dict(log_loader))

    # session.rollback()
    # session.close()

    try:
        session.commit()
    except Exception as e:
        session.rollback()
        print(e)
        raise
    finally:
        session.close()

    return jsonify({'status': 'success'})


@app.route('/report/<date_from_str>/<date_to_str>', methods=['GET'])
def report(date_from_str, date_to_str):

    date_to     = datetime.datetime.strptime(date_to_str, "%Y-%m-%d").date()
    date_from   = datetime.datetime.strptime(date_from_str, "%Y-%m-%d").date()
    footer_text = request.args.get('footerText', None)

    report_path = None

    session = Session()

    query = []
    for i in range(1, 17):
        query.append(
            func.avg(getattr(LogLoaderdb, f'chann{i}'))
        )
        query.append(
            func.min(getattr(LogLoaderdb, f'chann{i}'))
        )
        query.append(
            func.max(getattr(LogLoaderdb, f'chann{i}'))
        )

    q = session.query(*query)
    if date_from != date_to:
        q = q.filter(
            and_(
                LogLoaderdb.location_id == '73',
                LogLoaderdb.logdate >= date_from,
                LogLoaderdb.logdate <= date_to,
            )
        )
    else:
        q = q.filter(LogLoaderdb.logdate==date_to)

    r = q.first()

    if None in r:
        session.close()
        return redirect(url_for('home', error='No data for this date range'))

    l15to25avg = [r[0], r[3], r[6], r[9], r[12], r[15], r[18]]
    l15to25min = [r[1], r[4], r[7], r[10], r[13], r[16], r[19]]
    l15to25max = [r[2], r[5], r[8], r[11], r[14], r[17], r[20]]
    l2to8avg = [r[21], r[24], r[27], r[30], r[33], r[36], r[39]]
    l2to8min = [r[22], r[25], r[28], r[31], r[34], r[37], r[40]]
    l2to8max = [r[23], r[26], r[29], r[32], r[35], r[38], r[41]]


    # query = []
    # for i in range(1, 17):
    #     query.append(
    #         func.coalesce(
    #             func.count(case([(getattr(LogLoaderdb, f'chann{i}')>EXCURSION_TEMP,  LogLoaderdb.id)], else_=None)), 
    #             0.00)
    #     )
    #     query.append(
    #         func.coalesce(
    #             func.count(case([(getattr(LogLoaderdb, f'chann{i}')<INCURSION_TEMP,  LogLoaderdb.id)], else_=None)), 
    #             0.00),
    #     )

    # q = session.query(*query)
    # if date_from != date_to:
    #     q = q.filter(
    #         and_(
    #             LogLoaderdb.location_id == '73',
    #             LogLoaderdb.logdate >= date_from,
    #             LogLoaderdb.logdate <= date_to,
    #         )
    #     )
    # else:
    #     q = q.filter(LogLoaderdb.logdate==date_to)

    # print('EXCURSION_TEMP - INCURSION_TEMP')
    # for res in q.all():
    #     print(res)


    header_dict = {
        'chann1': {
            'avg': r[0],
            'min': r[1],
            'max': r[2]
        },
        'chann2': {
            'avg': r[3],
            'min': r[4],
            'max': r[5]
        },
        'chann3': {
            'avg': r[6],
            'min': r[7],
            'max': r[8]
        },
        'chann4': {
            'avg': r[9],
            'min': r[10],
            'max': r[11]
        },
        'chann5': {
            'avg': r[12],
            'min': r[13],
            'max': r[14]
        },
        'chann6': {
            'avg': r[15],
            'min': r[16],
            'max': r[17]
        },
        'chann7': {
            'avg': r[18],
            'min': r[19],
            'max': r[20]
        },
        'chann8': {
            'avg': r[21],
            'min': r[22],
            'max': r[23]
        },
        'chann9': {
            'avg': r[24],
            'min': r[25],
            'max': r[26]
        },
        'chann10': {
            'avg': r[27],
            'min': r[28],
            'max': r[29]
        },
        'chann11': {
            'avg': r[30],
            'min': r[31],
            'max': r[32]
        },
        'chann12': {
            'avg': r[33],
            'min': r[34],
            'max': r[35]
        },
        'chann13': {
            'avg': r[36],
            'min': r[37],
            'max': r[38]
        },
        'chann14': {
            'avg': r[39],
            'min': r[40],
            'max': r[41]
        },
        'chann15': {
            'avg': r[42],
            'min': r[43],
            'max': r[44]
        },
        'chann16': {
            'avg': r[45],
            'min': r[46],
            'max': r[47]
        },
        'l15to25': {
            'avg': sum(l15to25avg) / len(l15to25avg),
            'min': min(l15to25min),
            'max': max(l15to25max)
        },
        'l2to8': {
            'avg': sum(l2to8avg) / len(l2to8avg),
            'min': min(l2to8min),
            'max': max(l2to8max)
        }
    }



    ## data for graphs
    q = session.query(LogLoaderdb)
    if date_from != date_to:
        q = q.filter(
            and_(
                LogLoaderdb.location_id == '73',
                LogLoaderdb.logdate >= date_from,
                LogLoaderdb.logdate <= date_to,
            )
        )
    else:
        q = q.filter(LogLoaderdb.logdate==date_to)

    q = q.order_by(
        LogLoaderdb.logdate.asc(),
        LogLoaderdb.logtimein.asc()
    )

    log_list = [row2dict(r) for r in q.all()]

    csv_g1 = ['Date, Temperature']
    csv_g2 = ['Date, 1, 2, 3, 4, 5, 6, 7']
    csv_g3 = ['Date, Temperature']
    csv_g4 = ['Date, 8, 9, 10, 11, 12, 13, 14']

    for r in log_list:
        d = r["logdate"] + " " + r["logtimein"]

        l15to25 = []
        g2 = ""
        for i in range(1, 8):
            l15to25.append(float(r[f'chann{i}']))
            g2 += r[f'chann{i}'] + ","

        l2to8 = []
        g4 = ""
        for i in range(8, 15):
            l2to8.append(float(r[f'chann{i}']))
            g4 += r[f'chann{i}'] + ","

        avg1 = int(sum(l15to25) / len(l15to25))
        csv_g1.append(f'{d}, {avg1}')

        avg2 = int(sum(l2to8) / len(l2to8))
        csv_g3.append(f'{d}, {avg2}')

        csv_g2.append(f'{d}, {g2[:-1]}')
        csv_g4.append(f'{d}, {g4[:-1]}')


    ## FREEZER LOG ##
    csv_g5 = ['Date, Temperature']
    csv_g6 = ['Date, Temperature']
    csv_g7 = ['Date, Temperature']

    q = session.query(
        LogLoaderdb.location_id,
        LogLoaderdb.logdate,
        func.avg(LogLoaderdb.chann1)
    )
    if date_from != date_to:
        q = q.filter(
            and_(
                LogLoaderdb.location_id.in_(['74', '75', '76']),
                LogLoaderdb.logdate >= date_from,
                LogLoaderdb.logdate <= date_to,
            )
        )
    else:
        q = q.filter(
            and_(
                LogLoaderdb.location_id.in_(['74', '75', '76']),
                LogLoaderdb.logdate==date_to
            )
        )

    q = q.group_by(
        LogLoaderdb.location_id,
        LogLoaderdb.logdate,
    )
    q = q.order_by(
        LogLoaderdb.logdate.asc(),
    )
    for r in q.all():
        print(r)
        print(DAYS_OF_WEEK[r[1].weekday()])
        d = r[1].strftime("%Y-%m-%d")
        # d = r[1].strftime("%Y-%m-%d") + " - " + DAYS_OF_WEEK[r[1].weekday()]

        if r[0] == '74':
            csv_g5.append(f'{d}, {r[2]}')

        elif r[0] == '75':
            csv_g6.append(f'{d}, {r[2]}')

        elif r[0] == '76':
            csv_g7.append(f'{d}, {r[2]}')


    session.close()

    return render_template(
        'report-format.html',
        title='DAILY' if date_from == date_to else 'WEEKLY',
        date_from=date_from.strftime("%d.%m.%Y"),
        date_to=date_to.strftime("%d.%m.%Y"), 
        csv_g1=csv_g1,
        csv_g2=csv_g2,
        csv_g3=csv_g3,
        csv_g4=csv_g4,
        csv_g5=csv_g5,
        csv_g6=csv_g6,
        csv_g7=csv_g7,
        header_dict=header_dict,
        report_path=report_path,
        footer_text=footer_text if footer_text else '',
    )


@app.route('/send/mail', methods=['POST'])
def send_mail_report():

    data = json.loads(request.data)

    email_address = data.get('emailAddress', None)
    report_path   = data.get('path', None)
    date_from_str = data.get('dateFrom', None)
    date_to_str   = data.get('dateTo', None)

    if None in [email_address, report_path, date_from_str, date_to_str]:
        return jsonify({
            'status': 'error', 
            'message': 'Missing required data!'
        })

    date_from   = datetime.datetime.strptime(date_from_str, "%Y-%m-%d").date()
    date_to     = datetime.datetime.strptime(date_to_str, "%Y-%m-%d").date()
    report_type = 'DAILY' if date_from == date_to else 'WEEKLY'

    session = Session()

    try:
        email_params = session.query(SMTPMail).one()
    except Exception as e:
        session.close()
        return jsonify({
            'status': 'error', 
            'message': 'Something is wrong smtpmail table!'
        })
    
    email_params_dict = row2dict(email_params)

    session.close()

    send_cc = email_params_dict['temail'].split(',')
    if not isinstance(send_cc, list):
        send_cc = [send_cc]

    try:
        send_mail(
            send_from=email_params_dict['sfrom'], 
            send_to=[email_address],
            send_cc=send_cc,
            subject=f'MAA-FW-025 - {report_type} TEMPERATURE REPORT - {date_from} to {date_to}', 
            message=email_tpl.format(report_type, date_from, date_to), 
            attachment_path=report_path,
            server=email_params_dict['shost'], 
            port=email_params_dict['sport'], 
            username=email_params_dict['suser'], 
            password=email_params_dict['spass'],
            use_tls=True
        )
    except Exception as e:
        print(e)
        return jsonify({
            'status': 'error', 
            'message': 'Email is not sent!'
        })

    return jsonify({'status': 'success'})

