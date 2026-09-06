import subprocess
import serial
import time
from pynput import keyboard


# =========================
# Arduino
# =========================

ser = serial.Serial("COM10", 9600, timeout=0.1)
time.sleep(2)

print("Arduino 已連接")


# =========================
# GoPro
# =========================

gopro = subprocess.Popen([
    "gopro-webcam",
    "--log",
    "gopro.log"
])

print("GoPro Webcam 啟動中...")


# =========================
# 傳送指令
# =========================

def send(cmd):
    ser.write((cmd + "\n").encode())
    print("Arduino <-", cmd)


# =========================
# 鍵盤
# =========================

def on_press(key):
    try:
        k = key.char

        if k in ["T", "t", "F", "f"]:
            send(k)

    except AttributeError:
        pass


print()
print("======================")
print("T / t = 傳送 T / t")
print("F / f = 傳送 F / f")
print("======================")


with keyboard.Listener(on_press=on_press) as listener:
    listener.join()