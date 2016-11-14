"""Driver for Swallow weather station"""

from __future__ import with_statement
import serial
import syslog
import time
import struct


import weewx.drivers

DRIVER_NAME = 'Swallow'
DRIVER_VERSION = '1.0'

def loader(config_dict, _):
    return SwallowDriver(**config_dict[DRIVER_NAME])

DEFAULT_PORT = 'ttyUSB0'
BAUDRATE = 9600
DEBUG_READ = 0
PACKET_CHAR_COUNT = 98
PACKET_BYTE_COUNT = 49
MULT_1 = 0.1
BASE = 16


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
	self.last_rain = 0.0
	self.last_geiger = 0
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
	    packet = {'dateTime': int(time.time() + 0.5),
		      'usUnits': weewx.METRIC}
	    readings = self.station.get_readings()
	    data = Station.parse_readings(readings)
	    packet.update(data)
	    self._augment_packet(packet)
	    time.sleep(self.loop_interval)
	    yield packet

		
    def _augment_packet(self, packet):
	# calculate the rain delta from rain total
	if self.last_rain != 0.0:
	    packet['deltarain'] = packet['long_term_rain'] - self.last_rain
	    loginf("deltarain:    %.1f" % packet['deltarain'])
	else:
	    packet['deltarain'] = None
	self.last_rain = packet['long_term_rain']

	if self.last_geiger != 0:
	    packet['geiger'] = packet['long_term_geiger'] - self.last_geiger
	    loginf("deltageiger:  %.d" % packet['geiger'])
	else:
	    packet['geiger'] = None
	self.last_geiger = packet['long_term_geiger']

class Station(object):
    def __init__(self, port):
	self.port = port
	self.baudrate = BAUDRATE
	self.timeout = 3
	self.serial_port = None
	self._last_rain = 0

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
	try2send = 0
	while try2send < 3:
	    self.serial_port.flushInput()
	    self.serial_port.write(b'\xAA\xBB\x00\x02\x2A\x6E\xFE')
	    time.sleep(10)
	    data_left = 0
	    data_left = self.serial_port.inWaiting()
	    try2send += 1
#            loginf("WARNING! data_left is not right: %d. Trying again..." % data_left)
	    if  data_left >= PACKET_BYTE_COUNT:
		break
	    loginf("received data size: %d (must be 49)" % data_left)
	
	if data_left >=  PACKET_BYTE_COUNT:
	    received_bytes = self.serial_port.read(PACKET_BYTE_COUNT)
	    received_chars = ''
	    for i in range(0, PACKET_BYTE_COUNT):
		received_chars += (received_bytes[i]).encode('hex')
	    loginf("RECEIVED: %s" % received_chars)
	    validated_chars = Station.validate_string(received_chars)
	return validated_chars

    @property
    def last_rain(self):
	return self._last_rain
    

    @staticmethod
    def validate_string(buf):
	if len(buf) != PACKET_CHAR_COUNT:
	    raise weewx.WeeWxIOError("Unexpected buffer length %d" % len(buf))
	if buf[0:10] != 'ccdd00022a':
	    raise weewx.WeeWxIOError("Unexpected header bytes '%s'" % buf[0:10])
	buf = (buf.replace('ccdd00022a', ''))
	loginf("VALIDATION OK %s" % buf)
	return buf

    @staticmethod
    def parse_readings(raw):
	"""SWALLOW DATA FORMAT:
	    DDDDTTTTTTTTPPPPPPPPRRRRRRRRSSSSSSSSHHHHHHHHGGGGGGGGIIIIIIIIXXXXXXXX

	    DDDD - wind direction
	    TTTT - temperature
	    PPPP - pressure
	    RRRR - rain
	    SSSS - wind speed
	    HHHH - humidity
	    GGGG - geiger
	    IIII - illumination
	    XXXX - internal temperature """

	data = dict()

	data['windDir'] = int((raw[2:4] + raw[0:2]), BASE)
	loginf("windDir:          %d" % data['windDir'])

	data['outTemp'] =  struct.unpack('!f', (raw[10:12] + raw[8:10] + raw[6:8] + raw[4:6]).decode('hex'))[0]
	loginf("outTemp:          %.1f" % data['outTemp'])

	data['pressure'] = struct.unpack('!f', (raw[18:20] + raw[16:18] + raw[14:16] + raw[12:14]).decode('hex'))[0]
	loginf("pressure:         %.1f" % data['pressure'])

	data['long_term_rain'] = struct.unpack('!f', (raw[26:28] + raw[24:26] + raw[22:24] + raw[20:22]).decode('hex'))[0]
	loginf("long_term_rain:   %.1f" % data['long_term_rain'])

	data['windSpeed'] = struct.unpack('!f', (raw[34:36] + raw[32:34] + raw[30:32] + raw[28:30]).decode('hex'))[0]
	loginf("windSpeed:        %.1f" % data['windSpeed'])

	humi = struct.unpack('!f', (raw[42:44] + raw[40:42] + raw[38:40] + raw[36:38]).decode('hex'))[0] 
	if humi > 100.0:
	    data['outHumidity'] = 100.0
	else:
	    data['outHumidity'] = humi
	loginf("outHumidity:      %.1f" % data['outHumidity'])

	data['long_term_geiger'] = long((raw[50:52] + raw[48:50] + raw[46:48] + raw[44:46]), BASE)
	loginf("long_term_geiger: %d" % data['long_term_geiger'])

	data['illumination'] = struct.unpack('!f', (raw[58:60] + raw[56:58] + raw[54:56] + raw[52:54]).decode('hex'))[0]
	loginf("illumination:     %.1f" % data['illumination'])

	data['inTemp'] = struct.unpack('!f', (raw[66:68] + raw[64:66] + raw[62:64] + raw[60:62]).decode('hex'))[0]
	loginf("inTemp:           %.1f" % data['inTemp'])

	data['maxWind'] = struct.unpack('!f', (raw[74:76] + raw[72:74] + raw[70:72] + raw[68:70]).decode('hex'))[0]
	loginf("maxWind:          %.1f" % data['maxWind'])

	data['downfall'] = bool(long((raw[82:84] + raw[80:82] + raw[78:80] + raw[76:78]), BASE))
	loginf("downfall:         %r" % data['downfall'])

	return data


    @staticmethod
    def _decode(s, multiplier=None, neg=False):
	v = None
	try:
	    v = int(s, 16)
	    if neg:
		bits = 4 * len(s)
		if v & (1 << (bits - 1)) != 0:
		    v -= (1 << bits)
	    if multiplier is not None:
		v *= multiplier
	except ValueError, e:
	    logdbg("decode failed for '%s' : %s" % (s, e))
	return v
