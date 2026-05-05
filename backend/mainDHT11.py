import time
import board
import adafruit_dht
import math
import mariadb
import sys
import os
import RPi.GPIO as GPIO

# ---------------- GPIO ----------------
FAN_PIN = 21
GPIO.setmode(GPIO.BCM)
GPIO.setup(FAN_PIN, GPIO.OUT)

# ---------------- DB ----------------
try:
    conn = mariadb.connect(
        user="delta",
        password="delta",
        host="10.231.81.129",
        port=3306,
        database="deltataupunkt"
    )
    cur = conn.cursor()
    print("[DB] Connected")

except mariadb.Error as e:
    print(f"[DB ERROR] {e}")
    sys.exit(1)


def log_to_database(temp_in, hum_in, temp_out, hum_out, fan_state):
    try:
        sql = """
        INSERT INTO sensorwerte (
            temp_innen,
            temp_aussen,
            hum_innen,
            hum_aussen,
            fan_state
        )
        VALUES (?, ?, ?, ?, ?)
        """

        values = (
            temp_in,
            temp_out,
            hum_in,
            hum_out,
            fan_state
        )

        cur.execute(sql, values)
        conn.commit()

    except Exception as e:
        print(f"[DB INSERT ERROR] {e}")


# ---------------- SENSORS ----------------
sensor1 = adafruit_dht.DHT22(board.D4)
sensor2 = adafruit_dht.DHT22(board.D26)

# ---------------- LOGIC ----------------
rotation = 0
SCHALTmin = 0.5
HYSTERESE = 1.0

a = 7.5
b = 237.3


while True:
    try:
        # -------- SENSOR 1 --------
        temperature_c_sensor1 = sensor1.temperature
        humidity_sensor1 = sensor1.humidity

        # -------- SENSOR 2 --------
        temperature_c_sensor2 = sensor2.temperature
        humidity_sensor2 = sensor2.humidity

        # -------- TAUPUNKT SENSOR 1 --------
        SDD_sensor1 = 6.1078 * 10 ** ((a * temperature_c_sensor1) / (b + temperature_c_sensor1))
        DD_sensor1 = (humidity_sensor1 / 100 * SDD_sensor1)
        v_sensor1 = math.log10(DD_sensor1 / 6.1078)
        TD_sensor1 = b * v_sensor1 / (a - v_sensor1)

        # -------- TAUPUNKT SENSOR 2 --------
        SDD_sensor2 = 6.1078 * 10 ** ((a * temperature_c_sensor2) / (b + temperature_c_sensor2))
        DD_sensor2 = (humidity_sensor2 / 100 * SDD_sensor2)
        v_sensor2 = math.log10(DD_sensor2 / 6.1078)
        TD_sensor2 = b * v_sensor2 / (a - v_sensor2)

        # -------- FAN LOGIC (BLEIBT UNVERÄNDERT) --------
        if rotation == 0:
            DeltaPoint = TD_sensor2 - TD_sensor1
            if DeltaPoint > (SCHALTmin + HYSTERESE):
                print("open window")
                GPIO.output(FAN_PIN, GPIO.LOW)
                fan_state = "on"
                rotation = 1
            else:
                fan_state = "off"

        else:
            DeltaPoint = TD_sensor2 - TD_sensor1
            if DeltaPoint < (SCHALTmin - HYSTERESE):
                print("close window")
                GPIO.output(FAN_PIN, GPIO.HIGH)
                fan_state = "off"
                rotation = 0
            else:
                fan_state = "on"

        # -------- OUTPUT --------
        print(f"T1={temperature_c_sensor1}°C | H1={humidity_sensor1}%")
        print(f"T2={temperature_c_sensor2}°C | H2={humidity_sensor2}%")
        print(f"Fan: {fan_state}")
        print("-" * 40)

        # -------- DB WRITE --------
        log_to_database(
            temperature_c_sensor1,
            humidity_sensor1,
            temperature_c_sensor2,
            humidity_sensor2,
            fan_state
        )

        time.sleep(2)

    except RuntimeError as error:
        print(error.args[0])
        time.sleep(2)
        continue

    except Exception as error:
        sensor1.exit()
        sensor2.exit()
        GPIO.output(FAN_PIN, GPIO.HIGH)
        GPIO.cleanup()
        raise error
