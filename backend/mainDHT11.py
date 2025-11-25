import time

# import mariadb

import RPi.GPIO as GPIO
import dht11


import random
import math
from datetime import datetime
import os

InDebug = True

# Establishing the connection

db_config = {
    'user': 'root',
    'password': 'admin',
    'host': 'localhost',
    'database': 'CondensationForecast',
    'port': 3306  # Standard port for MariaDB
}

# conn = mariadb.connect(**db_config)
# Create a cursor to execute queries
# cursor = conn.cursor()


mGWD = 18.016 # Molekulargewicht des Wasserdampfes in kg/kmol
AF = 8314.3 # Universelle Gaskonstante in J/(kmol*K)
rotation = 0
CondensationPoint1 = 0
CondensationPoint2 = 0
DeltaPoint = 0
SCHALTmin = 5.0 # minimaler Taupunktunterschied, bei dem das Relais schaltet
HYSTERESE = 1.0 # Abstand von Ein- und Ausschaltpunkt

clear = lambda: os.system('cls')

while True:
    try:

        if (InDebug):
            temperature_c = random.randint(-5, 40)
        else: # Need to implement a way to actually get the sensor in
            temperature_c = 1
        
        
        temperature_f = temperature_c * (9 / 5) + 32
        temperature_k = temperature_c + 273.15
        Humidity = random.randint(0, 100)
        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")

        a = 7.5
        b = 237.3
        if (temperature_c < 0):
            a = 7.6
            b = 240.7
        
        SDD = 6.1078 * 10 ** ((a*temperature_c) / (b+temperature_c)) # Das ist der Sättigungsdampfdruck in hPa
        DD = Humidity / 100 * SDD # Das ist der Dampfdruck in hPa
        v = math.log10(DD/6.1078) # Nur eine Variable für späteren Gebrauch
        TD = b*v/(a-v)
        CondensationPoint1 = TD
        SDDvonTD = 6.1078 * 10 ** ((a*TD) / (b+TD))
        AF = 10**5 * mGWD / AF * SDDvonTD / temperature_k # Absolute Feuchte in g Wasserdampf pro m³ Luft

        # Was noch fehlt:
        # Die Berechnung für den zweite Lüfter
        
        
        # insert_query = "INSERT INTO values (MeasuredWhen, HeatInCels, HeatInFahren, Humidity, Sättigungsdampfdruck, Dampfdruck, CondensationPoint1) VALUES (%s, %s, %s, %s, %s, %s, %s)"
        # values = (current_time, temperature_c, temperature_f, Humidity, SDD, DD, CondensationPoint1)
        # cursor.execute(insert_query, values)
        
        
                
        print(f'Temperatur in Celsius={temperature_c}ºC, Temperatur in Fahrenheit={temperature_f}ºF, Luftfeuchtigkeit={Humidity}%')

        if (rotation == 0):
            rotation = 1
            CondensationPoint2 = CondensationPoint1
        else:
            rotation = 0
            DeltaPoint = CondensationPoint2 - CondensationPoint1
            if (DeltaPoint > (SCHALTmin + HYSTERESE)):
                print('Hier Logik einfügen zum Fenster-öffnen')
                break

        
    except RuntimeError as error:
        # Errors happen fairly often, DHT's are hard to read, just keep going
        print(error.args[0])
        time.sleep(2.0)
        continue
    except Exception as error:
        # sensor.exit()
        # cursor.close()
        # conn.close()
        raise error

    time.sleep(2.0)
time.sleep(5.0)
clear()

# cursor.close()
# conn.close()