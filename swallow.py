"""Driver for Swallow weather station"""

from __future__ import with_statement
from swallow_lib import check_and_repair
import serial
import syslog
import time
import struct
import weewx.drivers

DRIVER_NAME = 'Swallow'
DRIVER_VERSION = '1.0'
DEFAULT_PORT = 'ttyUSB0'
BAUDRATE = 9600
DEBUG_READ = 0
PACKET_BYTE_COUNT = 49
BASE = 16
DATA_START_INDEX = 2
DATA_END_INDEX = -5

def loader(config_dict, _):
    return SwallowDriver(**config_dict[DRIVER_NAME])

def logmsg(level, msg):
    syslog.syslog(level, 'swallow: %s' % msg)

def logdbg(msg):
    logmsg(syslog.LOG_DEBUG, msg)

def loginf(msg):
    logmsg(syslog.LOG_INFO, msg)

def logerr(msg):
    logmsg(syslog.LOG_ERR, msg)


class SwallowDriver(weewx.drivers.AbstractDevice):
    def __init__(self, **stn_dict):
        self.port = stn_dict.get('port', DEFAULT_PORT)
        self.loop_interval = float(stn_dict.get('loop_interval', 60.0))
        loginf('driver version is %s ' % DRIVER_VERSION)
        loginf('using serial port %s ' % self.port)

        global DEBUG_READ
        DEBUG_READ = int(stn_dict.get('debug_read', DEBUG_READ))
        self.station = Station(self.port)
        self.station.open() 

    def closePort(self):
        if self.station is not None:
            self.station.close()
            self.station = None

    @property
    def hardware_name(self):
        return 'Swallow'

    def genLoopPackets(self):
        while True:
            readings = None
            while True:
                packet = {'dateTime': int(time.time() + 0.5),
                          'usUnits': weewx.METRIC}
                readings = self.station.get_readings()
                readings.reverse()
                if self.station.verify_readings(readings) == True:
                    break;
            data = check_and_repair(self.station.parse_readings(readings[DATA_START_INDEX:DATA_END_INDEX]))
            Station.print_data(data)
            packet.update(data)
            time.sleep(self.loop_interval)
            yield packet

class Station(object):
    REQUEST = b'\xAA\xBB\x00\x02\x2A\x6E\xFE'
    MAX_HUMI = 100.0
    MIN_HUMI = 0.0
    def __init__(self, port):
        self.port = port
        self.baudrate = BAUDRATE
        self.timeout = 3
        self.serial_port = None
        self.last_rain = 0.0
        self.last_geiger = 0
        self.last_outtemp = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, _, value, traceback):
        self.close()

    def open(self):
        self.serial_port = serial.Serial(self.port, self.baudrate,
                                         timeout=self.timeout)
                                              
    def close(self):
        if self.serial_port is not None:
            self.serial_port.close()
            self.serial_port = None

    def get_readings(self):
        data_left = 0
        while data_left < PACKET_BYTE_COUNT:
            self.serial_port.flushInput()
            self.serial_port.write(Station.REQUEST)
            time.sleep(10)
            data_left = self.serial_port.inWaiting()
        
        received_bytes = self.serial_port.read(PACKET_BYTE_COUNT)
        loginf('SUCCESS: GET READINGS')
        return [str(val) for val in received_bytes]

    def verify_readings(self, readings):
        data = 0xFFFF - sum([Station.hex_to_int(val) for val in readings[DATA_START_INDEX:]])
        crc = Station.hex_to_int(''.join(readings[0:DATA_START_INDEX]))
        if crc == data:
            loginf('SUCCESS: VERIFY READINGS')
            return True
        loginf('FAILED: VERIFY READINGS')
        return False

    def parse_readings(self, raw):
        data = dict()

        data['windDir'] = Station.hex_to_int(''.join(raw[40:42]))
        data['outTemp'] = self.get_verifyed_outtemp(Station.hex_to_float(''.join(raw[36:40])))
        data['pressure'] = Station.hex_to_float(''.join(raw[32:36]))
        data['long_term_rain'] = Station.hex_to_float(''.join(raw[28:32]))
        data['windSpeed'] = Station.hex_to_float(''.join(raw[24:28]))
        data['outHumidity'] = Station.get_humi(Station.hex_to_float(''.join(raw[20:24])))
        data['long_term_geiger'] = Station.hex_to_int(''.join(raw[16:20]))
        data['illumination'] = Station.hex_to_float(''.join(raw[12:16]))
        data['inTemp'] = Station.hex_to_float(''.join(raw[8:12]))
        data['maxWind'] = Station.hex_to_float(''.join(raw[4:8]))
        data['downfall'] = bool(Station.hex_to_int(''.join(raw[0:4])))
        data['deltarain'] = self.get_delta_rain(data['long_term_rain'])
        data['geiger'] = self.get_delta_geiger(data['long_term_geiger'])
        return data

    @staticmethod
    def hex_to_float(val):
        return round(struct.unpack('!f', val)[0], 1)

    @staticmethod
    def hex_to_int(val):
        return int(val.encode('hex'), BASE)

    @staticmethod
    def get_humi(val):
        if val > Station.MAX_HUMI: return Station.MAX_HUMI
        if val < Station.MIN_HUMI: return Station.MIN_HUMI
        return val

    @staticmethod
    def print_data(data):
        for k,v in data.items():
            loginf('{0}: {1}'.format(k,v))

    def get_delta_rain(self, longterm):
        delta = 0.0
        if (self.last_rain != 0.0) and (longterm > self.last_rain):
            delta = longterm - self.last_rain
        self.last_rain = longterm
        return round(delta, 1)

    def get_delta_geiger(self, longterm):
        delta = 0
        if (self.last_geiger != 0) and (longterm > self.last_geiger):
            delta = longterm - self.last_geiger
        self.last_geiger = longterm
        return delta

    def get_verifyed_outtemp(self, temp):
        if (self.last_outtemp == None) or (abs(self.last_outtemp - temp) < 5.0):
            self.last_outtemp = temp
            return temp
        else 
            return self.last_outtemp




