# SPDX-FileCopyrightText: Daniel Schaefer 2023 for Framework Computer
# SPDX-License-Identifier: MIT
#
# Handle button pressed on the macropad
# Send A-X key pressed
# The pressed button will light up, cycling through RGB colors
import time
import board
import busio
import digitalio
import analogio
import usb_hid
import usb_cdc
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from framework_is31fl3743 import IS31FL3743
import json
import traceback


MATRIX_COLS = 8
MATRIX_ROWS = 4 

ADC_THRESHOLD = 0.4
DEBUG = False

pressed = []

MATRIX = [
    ["f1", "b3", "c3", "d3", "e3", "f3", "b4", "d4"],
    ["f4", "a1", "a2", None, "a4", "b4", "e4", "f2"],
    ["b1", "c1", "d1", "e1", "b2", "c2", "d2", "e2"],
    [None, None, None, None, "a3", None, None, None]
]

MATRIX_LED_MAP = {
    "a1" : 40,  "a2" : 37,  "a3" : 52,  "a4" : 49,
    "b1" : 4,   "b2" : 1,   "b3" : 16,  "b4" : 13,
    "c1" : 22,  "c2" : 19,  "c3" : 34,  "c4" : 31,
    "d1" : 58,  "d2" : 55,  "d3" : 70,  "d4" : 67,
    "e1" : 25,  "e2" : 61,  "e3" : 64,  "e4" : 28,
    "f1" : 7,   "f2" : 43,  "f3" : 46,  "f4" : 10
}

SYMBOLS = {
    "A": "A",   "B": "B",   "C": "C",   "D": "D",   "E": "E",
    "F": "F",   "G": "G",   "H": "H",   "I": "I",   "J": "J",
    "K": "K",   "L": "L",   "M": "M",   "N": "N",   "O": "O",
    "P": "P",   "Q": "Q",   "R": "R",   "S": "S",   "T": "T",
    "U": "U",   "V": "V",   "W": "W",   "X": "X",   "Y": "Y",
    "Z": "Z",

    " ": "SPACE",

    "1": "ONE", "2": "TWO",     "3": "THREE",   "4": "FOUR",    "5": "FIVE",
    "6": "SIX", "7": "SEVEN",   "8": "EIGHT",   "9": "NINE",    "0": "ZERO",

    "-": "MINUS",   "=": "EQUALS",  "+": "EQUALS",  "/": "FORWARD_SLASH",

    "\\": "BACKSLASH",

    "[": "LEFT_BRACKET",    "]": "RIGHT_BRACKET",   "(": "NINE",    ")": "ZERO",

    ";": "SEMICOLON",       "'": "QUOTE",       "`": "GRAVE_ACCENT",    "!": "ONE",
    ",": "COMMA",           ".": "DOT",         "@":"TWO",              "#":"THREE",
    "$":"FOUR",             "%":"FIVE",         "^":"SIX",              "&":"SEVEN",
    "*":"EIGHT",            "_": "MINUS",       "{": "LEFT_BRACKET",    "}": "RIGHT_BRACKET",
    ":": "SEMICOLON",       "\"": "QUOTE",      "<": "COMMA",           ">": "DOT",
    "?": "FORWARD_SLASH",   "|": "BACKSLASH",

    "\\N": "ENTER",         "\\E": "ESCAPE",        "\\T": "TAB",           "\\C": "LEFT_CONTROL",
    "\\A": "LEFT_ALT",      "\\S": "LEFT_SHIFT",    "\\L": "CAPS_LOCK",     "\\W": "WINDOWS",

    "\\U": "UP_ARROW",      "\\D": "DOWN_ARROW",    "\\L": "LEFT_ARROW",    "\\R": "RIGHT_ARROW",

    "\\1": "F1",        "\\2": "F2",        "\\3": "F3",        "\\4": "F4",
    "\\5": "F5",        "\\6": "F6",        "\\7": "F7",        "\\8": "F8",
    "\\9": "F9",        "\\0": "F10"
}

config_path = '.'


MATRIX_COLORS = {}
MATRIX_COMMANDS = {}



keyboard = Keyboard(usb_hid.devices)

# Set unused pins to input to avoid interfering. They're hooked up to rows 5 and 6
gp6 = digitalio.DigitalInOut(board.GP6)
gp6.direction = digitalio.Direction.INPUT
gp7 = digitalio.DigitalInOut(board.GP7)
gp7.direction = digitalio.Direction.INPUT

# Set up analog MUX pins
mux_enable = digitalio.DigitalInOut(board.MUX_ENABLE)
mux_enable.direction = digitalio.Direction.OUTPUT
mux_enable.value = False  # Low to enable it
mux_a = digitalio.DigitalInOut(board.MUX_A)
mux_a.direction = digitalio.Direction.OUTPUT
mux_b = digitalio.DigitalInOut(board.MUX_B)
mux_b.direction = digitalio.Direction.OUTPUT
mux_c = digitalio.DigitalInOut(board.MUX_C)
mux_c.direction = digitalio.Direction.OUTPUT


# Set up KSO pins
kso_pins = [
    digitalio.DigitalInOut(x)
    for x in [
        # KSO0 - KSO7 for Keyboards and Numpad
        board.KSO0,
        board.KSO1,
        board.KSO2,
        board.KSO3,
        board.KSO4,
        board.KSO5,
        board.KSO6,
        board.KSO7,
        # KSO8 - KSO15 for Keyboards only
        board.KSO8,
        board.KSO9,
        board.KSO10,
        board.KSO11,
        board.KSO12,
        board.KSO13,
        board.KSO14,
        board.KSO15,
    ]
]
for kso in kso_pins:
    kso.direction = digitalio.Direction.OUTPUT
    kso.value = 1

adc_in = analogio.AnalogIn(board.GP28)

# Signal boot done
boot_done = digitalio.DigitalInOut(board.BOOT_DONE)
boot_done.direction = digitalio.Direction.OUTPUT
boot_done.value = False


def mux_select_row(row):
    mux_a.value = row & 0x01
    mux_b.value = row & 0x02
    mux_c.value = row & 0x04


def drive_col(col, value):
    kso_pins[col].value = value


def to_voltage(adc_sample):
    return (adc_sample * 3.3) / 65536

# Enable LED controller via SDB pin
sdb = digitalio.DigitalInOut(board.GP29)
sdb.direction = digitalio.Direction.OUTPUT
sdb.value = True

i2c = busio.I2C(board.SCL, board.SDA)  # Or board.I2C()

# TODO: If I don't scan the bus, creating IS31FL3743 can't find the device. Why...?
i2c.try_lock()
i2c.scan()
i2c.unlock()

is31 = IS31FL3743(i2c)
is31.set_led_scaling(0x20)  # Brightness
is31.global_current = 0x20  # Current 
is31.enable = True

# SLEEP# pin. Low if the host is sleeping
sleep_pin = digitalio.DigitalInOut(board.GP0)
sleep_pin.direction = digitalio.Direction.INPUT

def matrix_paint():
    for key in MATRIX_LED_MAP.keys():
        value = MATRIX_COLORS.get(key,None)
        if value:
            is31[MATRIX_LED_MAP[key] +2 ] = int(value[:2],16)
            is31[MATRIX_LED_MAP[key] +1 ] = int(value[2:4],16)
            is31[MATRIX_LED_MAP[key] +0 ] = int(value[-2:],16)
        else:
            is31[MATRIX_LED_MAP[key] +2 ] = 0x00
            is31[MATRIX_LED_MAP[key] +1 ] = 0x00
            is31[MATRIX_LED_MAP[key] +0 ] = 0x00

def process_key(key, is_pressed):
    global pressed
    global MATRIX_COMMANDS

    if len(pressed)>1:
        key = "-".join(pressed)
    code = MATRIX_COMMANDS.get(key, None)

    if not code:
        ## No code for this key
        return
    elif is_pressed and code[0:4] == "MSG:":
        ## Process message key function
        to_send = {
            "key": key,
            "code": code[4:],
            "pressed": is_pressed
        }
        usb_serial.write((json.dumps(to_send) + '\n').encode())
        usb_serial.flush()
        return

    ## Process normal key function
    escaped = False
    for key in code:
        press = is_pressed
        release = True

        if escaped:
            ## Within escaped code
            escaped = False
            if key == key.upper():
                release = False
            else:
                release = True

            if key.upper() =='P':
                time.sleep(0.15)
                key = None
                continue
            else:
                key = "\\" + key
        else:
            ## Within normal operation
            if key == '\\':
                escaped = True
                key = None
                continue
            else:
                escaped = False


        # Actually press and/or release the keys
        if key:
            ## Resolve key
            key = SYMBOLS.get(key.upper(),None)
            key_code = getattr(Keycode, key)
            press and keyboard.press(key_code)
            release and keyboard.release(key_code)

    # Just in case    
    is_pressed or keyboard.release_all()

def matrix_scan():
    global pressed
    for col in range(MATRIX_COLS):
        drive_col(col, 0)
        for row in range(MATRIX_ROWS):
            key = MATRIX[row][col]
            if key:
                mux_select_row(row)
                if to_voltage(adc_in.value) < ADC_THRESHOLD:
                    if not key in pressed:
                        pressed.append(key)
                        process_key(key, True)
                else:
                    if key in pressed:
                        process_key(key, False)
                        pressed.remove(key)
        drive_col(col, 1)

last_voltage = [0]*32
def matrix_check():
    for col in range(MATRIX_COLS):
        drive_col(col, 0)
        for row in range(MATRIX_ROWS):
            mux_select_row(row)
            voltage = to_voltage(adc_in.value)
            if abs(voltage - last_voltage[8*row + col]) > 1.5:
                print (f"Voltage change on {row}/{col}: {voltage} {last_voltage[8*row + col]}")
                last_voltage[8*row + col] = voltage
        drive_col(col, 1)


## Reset output pins
for col in range(MATRIX_COLS):
    drive_col(col, 1)

def load_config(config):
    global MATRIX_COLORS
    global MATRIX_COMMANDS  
    MATRIX_COLORS = config['colors']
    MATRIX_COMMANDS = config['keys']
    if config.get('symbols',None):
        SYMBOLS = config['symbols']
    matrix_paint()

with open(config_path + '/default.json', 'r') as file:
    load_config(json.load(file))

try:
    usb_serial = usb_cdc.data
    usb_serial.flush()
except Exception as e:
    usb_serial = None

#try:
while True:
    print ("Starting up")
    while True:
        is31.enable = sleep_pin.value
        if sleep_pin.value:
            time.sleep(0.01)
            if usb_serial and usb_serial.in_waiting:
                data = usb_serial.readline(-1).decode()
                load_config(json.loads(data))
            matrix_scan()
            #matrix_check()
        else:
            time.sleep(5)
#except Exception as e:
    keyboard.release_all()
    print(f"Error: {e}")
