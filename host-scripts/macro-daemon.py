import serial
import time
import pystray
from pystray import MenuItem as item, Icon
from PIL import Image
import sys
import threading
import pygetwindow as gw
import win32gui
import win32con
import win32process
import json
import re
from pathlib import Path
import datetime
import os
import subprocess
import keyboard

import ctypes
import psutil
import uuid

latest_window = ''
latest_uuid = None


# Cambiar al directorio donde está el script
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Configurar el puerto COM4
ser = None
KLF_ACTIVATE = 0x00000001

layouts = {
    "EN": 67699721,
    "ES": 67767306
}

programs={
    "chrome":"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
}

configs={}

def obtener_layout_actual():
    # Obtiene el ID del thread con foco (ventana activa)
    hWnd = ctypes.windll.user32.GetForegroundWindow()
    threadID = ctypes.windll.user32.GetWindowThreadProcessId(hWnd, None)
    # Obtiene el layout del teclado (HKL)
    hkl = ctypes.windll.user32.GetKeyboardLayout(threadID)
    layout_id = hkl & 0xFFFFFFFF
    return layout_id


def cambiar_layout(layout,recheck):
    curr_layout = obtener_layout_actual()
    if curr_layout != layouts.get(layout,None):
        if recheck:
            time.sleep(0.1)
            cambiar_layout(layout,False)
        else:
            print (f"Cambiando layout a {layout} desde {curr_layout}")
            keyboard.press_and_release('alt+shift')

def open_window(filtro_regex):
    def callback(hwnd, lista):
        titulo = win32gui.GetWindowText(hwnd)
        if re.search(filtro_regex, titulo, re.IGNORECASE):  # Filtra las que tienen título
            lista.append(hwnd)

    ventanas=[]
    win32gui.EnumWindows(callback, ventanas)
    if len(ventanas)==0:
        print(f"Opening application")
        subprocess.Popen(programs[filtro_regex], shell=True)
    else:
        for hwnd in ventanas:
            if True or win32gui.IsIconic(hwnd):  # Si la ventana está minimizada, restaurarla
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                time.sleep(0.1)  # Pequeña pausa para asegurar la restauración
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.1)  # Pequeña pausa para asegurar la restauración

            # Intentar traer la ventana al frente
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)  # Asegurar que sea visible
            win32gui.BringWindowToTop(hwnd)  # Intentar traerla al frente
            try:
                win32gui.SetForegroundWindow(hwnd)  # Intentar darle el foco
            except Exception as ex:
                print("Could not bring to front")
            print(f"Ventana activada.")


# Función para obtener el nombre de la ventana activa
def get_active_window():
    window = win32gui.GetForegroundWindow()
    if not window:
        return 'None'

    window_title = win32gui.GetWindowText(window)
    _, pid = win32process.GetWindowThreadProcessId(window)
    try:
        proc = psutil.Process(pid)
        exe = proc.name()  # Nombre del ejecutable, por ejemplo: Teams.exe
        window_title = win32gui.GetWindowText(window)
    except psutil.NoSuchProcess:
        return None,None
    return exe,window_title

def lookup_config(window_title):
    global configs

    try:
        config_version = datetime.datetime.fromtimestamp(Path("./config.json").stat().st_mtime)

        if not configs or config_version > configs['version']:
            with open("./config.json", 'r') as file:
                configs = json.load(file)
                configs['version'] = config_version

        claves_ordenadas = sorted(configs.keys(), key=len, reverse=False)

        new_config = {
            "window": None,
            "colors": {},
            "keys": {}  
        }
        for clave in claves_ordenadas:
            #print (f"Procesando {clave} para {window_title}")
            if re.search(clave, window_title,re.IGNORECASE) or clave=='.':
                print(f"{clave} matched for {window_title}")  
                if not new_config['window']:
                    new_config['window'] = clave
                for key, value in configs[clave]['keys'].items():
                    new_config['keys'][key]=value
                for key, value in configs[clave]['colors'].items():
                    new_config['colors'][key]=value
                if (configs[clave]).get('symbols',None):
                    new_config['symbols'] = configs[clave]['symbols'] 
                if (configs[clave]).get('layout',None):
                    new_config['layout']=configs[clave]['layout']
        # prettyprint new_config
        #print (f"Configuración compuesta: {new_config}") # en prettyprint

        return new_config
    except Exception as e:
        print(f"Error loading json: {e}")
        
    
    return {
        "window": window_title,
        "colors": {},
        "keys": {}
    }

def type_chars(cadena):
    global latest_uuid
    if '#NEW_UUID#' in cadena:
        latest_uuid=str(uuid.uuid4())
        cadena = cadena.replace('#NEW_UUID#','')

    if '#UUID#' in cadena:
        if not latest_uuid:
            latest_uuid=str(uuid.uuid4())
        cadena = cadena.replace("#UUID#",latest_uuid)

    for char in cadena:
        keyboard.press_and_release(char)

# Función principal que monitorea el cambio de ventana 
def monitor_window_focus():
    global configs
    global ser
    while True:
        configs = {}
        if ser:
            ser.close()
            ser = None
        ser = serial.Serial('COM4', 115200, timeout=1)  # Asegúrate de que COM4 es el puerto correcto
        try:
            current_program = ''
            while True:
                if ser.in_waiting:
                    data = json.loads(ser.readline().decode('utf-8').strip())
                    print(f"{data} received")
                    if data['code'][:5]=='OPEN:':
                        app = data['code'][5:]
                        print(f"Told to open [{app}]")
                        open_window(app)
                    if data['code'][:5]=='TYPE:':
                        to_type = data['code'][5:]
                        print(f"Told to type {to_type}")
                        type_chars(to_type)

                try:
                    active_program, active_window = get_active_window()
                except Exception as ex:
                    print (f"Could not get active program")

                if not active_program:
                    continue
                elif active_program == 'chrome.exe':
                    active_program = active_window.split(' - ')[0]
                elif active_program == 'msrdc.exe':
                    active_program = active_window

                if  active_program != current_program:
                    current_program = active_program
                    active = lookup_config(active_program)
                    command = json.dumps(active) + '\n'
                    ser.write(command.encode())  # Enviar el comando al puerto (debe ser codificado en bytes)
                    if current_program!='explorer.exe' and active.get('layout'):
                        cambiar_layout(active['layout'],False)

                time.sleep(0.5)  # Espera un poco antes de volver a comprobar

        except Exception as ex:
            print(f"Process failed {ex}")
        finally:
            ser.close()
            time.sleep(5)

# Función para salir del programa
def salir(icon, item):
    icon.stop()
    sys.exit()

# Cargar una imagen para el icono
def crear_icono():
    image = Image.open("icono.png")  # Reemplaza con tu icono
    menu = (item('Salir', salir),)
    icon = Icon("MiApp", image, menu=menu)

    # Iniciar el proceso en segundo plano
    hilo = threading.Thread(target=monitor_window_focus, daemon=True)
    hilo.start()

    icon.run()

if __name__ == "__main__":
    crear_icono()

