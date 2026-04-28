import time
import board 
import adafruit_dht
import math
#import mysql.connector as mariadb
#import mariadb
import sys
import os
import RPi.GPIO as GPIO


""" This is for the LED-Matrix
import busio
import digitalio

spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI)
cs = digitalio.DigitalInOut(board.D7)
cs.direction = digitalio.Direction.OUTPUT
cs.value = True

def write_reg(register, data):
	cs.value = False
	spi.write(bytes([register, data]))
	cs.value = True
	
time.sleep(2)
for i in range(1, 9):
	write_reg(i, 0x00)

time.sleep(2)
for i in range(1, 257):
	time.sleep(0.25)
	write_reg(4, i)
	
time.sleep(2)

for i in range(1, 9):
	write_reg(i, 0x00)
"""



""" This is MariaDB Stuff
try:
    conn = mariadb.connect(
        user="db_user",
        password="db_user_passwd",
        host="192.0.2.1",
        port=3306,
        database="employees")
except mariadb.Error as e:
    print(f"Error connecting to MariaDB Platform: {e}")
    sys.exit(1)

cur = conn.cursor()
"""
sensor1 = adafruit_dht.DHT22(board.D4)
sensor2 = adafruit_dht.DHT22(board.D26)

  

FAN_PIN = 21
GPIO.setup(FAN_PIN, GPIO.OUT)
GPIO.setmode(GPIO.BCM)

mGWD = 18.016 # Molekulargewicht des Wasserdampfes in kg/kmol
AF = 8314.3 # Universelle Gaskonstante in J/(kmol*K)
rotation = 0
CondensationPoint1 = 0
CondensationPoint2 = 0
DeltaPoint = 0
SCHALTmin = 0.5 # minimaler Taupunktunterschied, bei dem das Relais schaltet
HYSTERESE = 1.0 # Abstand von Ein- und Ausschaltpunkt
a = 7.5
b = 237.3
	
while True:
	try:
		
		temperature_c_sensor1 = sensor1.temperature
		temperature_f_sensor1 = temperature_c_sensor1 * (9/5) + 32
		temperature_k_sensor1 = temperature_c_sensor1 + 273.15
		humidity_sensor1 = sensor1.humidity
		           
		SDD_sensor1 = 6.1078 * 10 ** ((a*temperature_c_sensor1) / (b+temperature_c_sensor1))
		DD_sensor1 = (humidity_sensor1 / 100 * SDD_sensor1)
		v_sensor1 = math.log10(DD_sensor1/6.1078) # Nur eine Variable für späteren Gebrauch
		TD_sensor1 = b*v_sensor1/(a-v_sensor1)
		CondensationPoint_sensor1 = TD_sensor1
		SDDvonTD_sensor1 = 6.1078 * 10 ** ((a*TD_sensor1) / (b+TD_sensor1))
		AWDF_sensor1 = 10**5 * mGWD / AF * SDDvonTD_sensor1 / temperature_k_sensor1 # Absolute Feuchte in g Wasserdampf pro m³ Luft
		
		
		temperature_c_sensor2 = sensor2.temperature
		temperature_f_sensor2 = temperature_c_sensor2 * (9/5) + 32
		temperature_k_sensor2 = temperature_c_sensor2 + 273.15
		humidity_sensor2 = sensor2.humidity
		           
		SDD_sensor2 = 6.1078 * 10 ** ((a*temperature_c_sensor2) / (b+temperature_c_sensor2))
		DD_sensor2 = (humidity_sensor2 / 100 * SDD_sensor2)
		v_sensor2 = math.log10(DD_sensor2/6.1078) # Nur eine Variable für späteren Gebrauch
		TD_sensor2 = b*v_sensor2/(a-v_sensor2)
		CondensationPoint_sensor2 = TD_sensor2
		SDDvonTD_sensor2 = 6.1078 * 10 ** ((a*TD_sensor2) / (b+TD_sensor2))
		AWDF_sensor2 = 10**5 * mGWD / AF * SDDvonTD_sensor2 / temperature_k_sensor2 # Absolute Feuchte in g Wasserdampf pro m³ Luft
        
		os.system('cls' if os.name == 'nt' else 'clear')
		print(f'Sensor 1: Temperatur in Celsius={temperature_c_sensor1}ºC, Temperatur in Fahrenheit={temperature_f_sensor1}ºF, Luftfeuchtigkeit={humidity_sensor1}%')
		print(f'Sensor 2: Temperatur in Celsius={temperature_c_sensor2}ºC, Temperatur in Fahrenheit={temperature_f_sensor2}ºF, Luftfeuchtigkeit={humidity_sensor2}%')
		
		
		if (humidity_sensor1 > humidity_sensor2):
			GPIO.output(FAN_PIN, GPIO.LOW)
		elif (humidity_sensor1 < humidity_sensor2):
			GPIO.output(FAN_PIN, GPIO.HIGH)
		
		"""if (rotation == 0):
			rotation = 1
			CondensationPoint_sensor2 = CondensationPoint_sensor1
		else:
			rotation = 0
			DeltaPoint = CondensationPoint_sensor2 - CondensationPoint_sensor1
			if (DeltaPoint > (SCHALTmin + HYSTERESE)):
				print('Hier Logik einfügen zum Fenster-öffnen')
				break"""
		
		time.sleep(2.0)
	except RuntimeError as error:
		print(error.args[0])
		time.sleep(2.0)
		GPIO.output(FAN_PIN, GPIO.HIGH)
		GPIO.cleanup()
		continue
	except Exception as error:
		sensor1.exit()
		sensor2.exit()
		GPIO.output(FAN_PIN, GPIO.HIGH)
		GPIO.cleanup()
		raise error
