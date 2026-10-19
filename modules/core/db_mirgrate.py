import sqlite3
import os
from modules import  cbpi
from modules.core.db import get_db

def execute_file(curernt_version, data):
    # current_version ist None, wenn die Tabelle schema_info beim allerersten
    # Start noch leer ist. Python 2 verglich None >= int und wertete das als
    # "nicht ueberspringen", Python 3 wirft TypeError - ein frischer Start
    # bricht ohne diese Zeile ab.
    if curernt_version is not None and curernt_version >= data["version"]:
        cbpi.app.logger.info("SKIP DB FILE: %s" % data["file"])
        return
    try:
        with sqlite3.connect("craftbeerpi.db") as conn:
            with open('./update/%s' % data["file"], 'r') as f:
                d = f.read()
                sqlCommands = d.split(";")
                cur = conn.cursor()
                for s in sqlCommands:
                    cur.execute(s)
                cur.execute("INSERT INTO schema_info (version,filename) values (?,?)", (data["version"], data["file"]))
                conn.commit()

    except sqlite3.OperationalError as err:
        print("EXCEPT")
        print(err)

@cbpi.initalizer(order=-9999)
def init(app=None):

    with cbpi.app.app_context():
        conn = get_db()
        cur = conn.cursor()
        current_version = None
        try:
            cur.execute("SELECT max(version) as m FROM schema_info")
            m = cur.fetchone()
            current_version =  m["m"]
        except:
            pass
        result = []
        for filename in os.listdir("./update"):
            if filename.endswith(".sql"):
                d = {"version": int(filename[:filename.index('_')]), "file": filename}
                result.append(d)
                execute_file(current_version, d)




