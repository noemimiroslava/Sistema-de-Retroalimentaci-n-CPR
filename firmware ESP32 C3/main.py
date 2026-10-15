# main.py  ·  ESP32 · VL6180X · BLE-CPR  v5
#
#   CONFIGURACION:  ANTIRREBOTE (sin mediana)
#
# Toda la deteccion vive en detector.py, el mismo modulo validado en el
# banco con diag.py.  Este archivo solo:
#   · lee el sensor a ritmo fijo y convierte mm a profundidad
#   · pasa cada muestra al detector
#   · notifica por BLE y enciende los LEDs
#
# El protocolo BLE es identico al de v3.2: la app no necesita cambios.
#
# Archivos que deben estar en el ESP32:
#   main.py (este)   detector.py   vl6180x.py   lib/aioble/

import struct, time, uasyncio as asyncio
from machine import Pin, I2C
import neopixel, aioble
from bluetooth import UUID
from vl6180x import Sensor
from detector import Detector

# ================= CONFIGURACION DEL DETECTOR =================
FILTRO   = False    # sin mediana: desafila la interpolacion del cruce
DEBOUNCE = 2        # muestras seguidas para confirmar un cruce
# ==============================================================

# ---------------- PINES ESP32-C3 ----------------

PIN_PIX, N_PIXELS = 4, 76      # datos de la tira NeoPixel (no usar GPIO 2: fuga hacia SCL)
I2C_SCL, I2C_SDA  = 1, 0       # comunicación I2C VL6180X


# VL6180X

DT_MS      = 15     # periodo de muestreo, ~66 Hz (validado en banco)
NOTIFY_DIV = 3      # notifica la profundidad 1 de cada 3 muestras (~22 Hz)

SAT_MM  = 200
CAL_A   = 1.1539   # pendiente:  lectura = CAL_A * real + CAL_B
CAL_B   = 1.7384   # ordenada (mm)
BASE_MM = 70       # distancia sensor-blanco en reposo, en mm.  (Ajustar sengún sea la distancia sensor - blanco)

SVC       = UUID('19b10002-e8f2-537e-4f6c-d104768a1214')
PROF      = UUID('19b10003-e8f2-537e-4f6c-d104768a1214')
DATA_COMP = UUID('19b10004-e8f2-537e-4f6c-d104768a1214')   # pico + cpm
MODE      = UUID('19b10005-e8f2-537e-4f6c-d104768a1214')

OFF   = (0, 0, 0)
RED   = (50, 0, 0)
GREEN = (0, 40, 0)


class BleCprDevice:

    def __init__(self):
        # GPIO 2 quedo con una fuga interna hacia el GPIO 1 (SCL).  Se fuerza
        # como entrada para que nunca jale la linea del sensor.
        Pin(2, Pin.IN)
        self.np  = neopixel.NeoPixel(Pin(PIN_PIX), N_PIXELS)
        self.tof = Sensor(I2C(0, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA),
                              freq=400_000))

        svc = aioble.Service(SVC)
        self.char_prof = aioble.Characteristic(svc, PROF, notify=True)
        self.char_data = aioble.Characteristic(svc, DATA_COMP, notify=True)
        self.char_mode = aioble.Characteristic(svc, MODE, write=True,
                                               capture=True)
        aioble.register_services(svc)

        self.led_fb  = False

    # ======================= LEDs =======================
    def _pixels(self, col):
        if self.np.bpp == 4 and len(col) == 3:
            col = col + (0,)
        self.np.fill(col)
        self.np.write()

    def _fb_ok(self):
        self._pixels(GREEN)

    def _fb_err(self):
        self._pixels(RED)

    def _fb_off(self):
        self._pixels(OFF)

    # ================= Conversion a profundidad =================
    def mm_to_depth(self, mm):
        if mm >= SAT_MM:
            return 0.0
        real = (mm - CAL_B) / CAL_A        # calibracion con vernier
        if real > BASE_MM:
            return 0.0
        return (BASE_MM - real) / 10

    # ==================== Bucle principal ====================
    async def _cpr_loop(self, conn):
        self._fb_off()
        det = Detector(filtro=FILTRO, debounce=DEBOUNCE)
        cont = 0
        siguiente = time.ticks_ms()

        while conn.is_connected():
            ahora = time.ticks_ms()
            try:
                mm = self.tof.range()
            except OSError as e:
                # falla de lectura I2C (cable flojo, ruido): se avisa y se
                # salta esta muestra en lugar de detener todo el programa
                print("Error leyendo el sensor:", e)
                await asyncio.sleep_ms(DT_MS)
                siguiente = time.ticks_ms()
                continue
            depth = self.mm_to_depth(mm)

            # profundidad en vivo para la barra de la app
            cont += 1
            if cont >= NOTIFY_DIV:
                cont = 0
                self.char_prof.notify(conn, struct.pack('<f', depth))

            # deteccion
            ev = det.procesar(depth, ahora)
            if ev:
                if self.led_fb:
                    if 5.0 <= ev["pico"] <= 6.0:
                        self._fb_ok()
                    else:
                        self._fb_err()
                else:
                    self._fb_off()
                self.char_data.notify(
                    conn, struct.pack('<ff', ev["pico"], ev["cpm"]))

            # planificacion por fecha limite: el tiempo de lectura del
            # sensor no se suma al periodo
            siguiente = time.ticks_add(siguiente, DT_MS)
            espera = time.ticks_diff(siguiente, time.ticks_ms())
            if espera > 0:
                await asyncio.sleep_ms(espera)
            else:
                siguiente = time.ticks_ms()
                await asyncio.sleep_ms(0)

    # ======================= Modo =======================
    async def _mode_listener(self):
        while True:
            _, data = await self.char_mode.written()
            self.led_fb = (data.decode().strip().upper() == "TRAIN")

    # ===================== Advertising =====================
    async def _ble_task(self):
        while True:
            async with await aioble.advertise(
                    250_000, name="ESP32-RCP", services=[SVC]) as conn:
                task = asyncio.create_task(self._cpr_loop(conn))
                await conn.disconnected()
                task.cancel()

    async def _main(self):
        asyncio.create_task(self._mode_listener())
        await self._ble_task()

    def run(self):
        asyncio.run(self._main())


print("BLE-CPR v5 - ESP32-C3")
BleCprDevice().run()