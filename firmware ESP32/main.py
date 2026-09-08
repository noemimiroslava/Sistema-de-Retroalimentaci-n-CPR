# ESP32  VL6180X  BLE-CPR  v3.2  (orientado a objetos)

import struct, time, uasyncio as asyncio
from machine import Pin, I2C
import neopixel, aioble
from bluetooth import UUID
from vl6180x import Sensor

class BleCprDevice:
    # --- Constantes -----------------------
    PIN_PIX, N_PIXELS = 27, 76
    LED_PIN           = 14
    I2C_SCL, I2C_SDA  = 18, 19
    FREQ_HZ           = 20
    SAT_MM   = 200
    BASE_MM  = 70

    SVC   = UUID('19b10002-e8f2-537e-4f6c-d104768a1214')
    PROF  = UUID('19b10003-e8f2-537e-4f6c-d104768a1214')
    #FREQ  = UUID('19b10004-e8f2-537e-4f6c-d104768a1214')
    DATA_COMP  = UUID('19b10004-e8f2-537e-4f6c-d104768a1214')   # pico + cpm (8 B)
    MODE  = UUID('19b10005-e8f2-537e-4f6c-d104768a1214')

    OFF   = (0, 0, 0)
    RED   = (50, 0, 0)
    GREEN = (0, 40, 0)

    def __init__(self):
        # HW
        self.np  = neopixel.NeoPixel(Pin(self.PIN_PIX), self.N_PIXELS)
        self.led = Pin(self.LED_PIN, Pin.OUT)
        self.tof = Sensor(I2C(0, scl=Pin(self.I2C_SCL),
                                 sda=Pin(self.I2C_SDA), freq=400_000))

        # BLE
        svc = aioble.Service(self.SVC)
        self.char_prof = aioble.Characteristic(svc, self.PROF, notify=True)
        self.char_data = aioble.Characteristic(svc, self.DATA_COMP, notify=True)
        #self.char_freq = aioble.Characteristic(svc, self.FREQ, notify=True)
        self.char_mode = aioble.Characteristic(svc, self.MODE,
                                               write=True, capture=True)
        aioble.register_services(svc)

        # estado
        self.led_fb   = False
        self.in_cycle = False
        self.peak = self.prev = 0.0
        self.last_comp = None

    # ---------- helpers LED ----------
    def _pixels(self, col):
        colour = col
        if self.np.bpp == 4 and len(col) == 3:
            col = col + (0,)          # añade blanco
        self.np.fill(col)
        self.np.write()
    def _fb_ok (self):
        self._pixels(self.GREEN);
        self.led.off()
    def _fb_err(self):
        self._pixels(self.RED  );
        self.led.on()
    def _fb_off(self):
        self._pixels(self.OFF  );
        self.led.off()
        
    def mm_to_depth(self,mm):
        # convierte mm a cm, forzando fuera de rango a 0 cm
        if mm >= self.SAT_MM or mm > self.BASE_MM:
            mm = self.BASE_MM
        return max((self.BASE_MM - mm)/10, 0)

    # ---------- sensor → BLE ----------
    async def _cpr_loop(self, conn):
        per_ms = int(1000 / self.FREQ_HZ)
        self._fb_off()
        while conn.is_connected():
            # ----------- PROFUNDIDAD -----------
            mm = self.tof.range()
            depth  = self.mm_to_depth(mm)
            print(f"profundidad: {depth:.1f} cm")
            #depth = max((self.BASE_MM - min(mm, self.SAT_MM)) / 10, 0)
            self.char_prof.notify(conn, struct.pack('<f', depth))

            # ----------- DETECTOR DE COMPRESIÓN -----------
            H = 0.1
            if not self.in_cycle and depth > 0.5 and depth > self.prev + H:
                self.in_cycle, self.peak = True, depth
            if self.in_cycle and depth > self.peak:
                self.peak = depth
            if self.in_cycle and depth < self.prev - H:
                # ---- LED / Neopixel sólo en TRAIN ----
                if self.led_fb:
                    (self._fb_ok() if 5 <= self.peak <= 6 else self._fb_err())
                else:
                    self._fb_off()

                # ---- calcula CPM y la notifica SIEMPRE ----
                now = time.ticks_ms()
                cpm = (60000 / time.ticks_diff(now, self.last_comp)
                       if self.last_comp else 0)
                pkt = struct.pack('<ff', self.peak, cpm) 
                #self.char_freq.notify(conn, struct.pack('<f', cpm))
                self.char_data.notify(conn, pkt)     
                hz=cpm/60
                print(f"compresiones: {hz:.1f}")
                self.last_comp = now

                # reinicia ciclo
                self.in_cycle, self.peak = False, 0.0

            self.prev = depth
            await asyncio.sleep_ms(per_ms)

    # ---------- recibe modo ----------
    async def _mode_listener(self):
        while True:
            _, data = await self.char_mode.written()
            self.led_fb = (data.decode().strip().upper() == "TRAIN")
            print("MODE =", "TRAIN" if self.led_fb else "EVAL")

    # ---------- advertising ----------
    async def _ble_task(self):
        while True:
            async with await aioble.advertise(
                    250_000, name="ESP32-Noemi", services=[self.SVC]
            ) as conn:
                print("✓ central connected:", conn.device)
                task = asyncio.create_task(self._cpr_loop(conn))
                await conn.disconnected()
                task.cancel()
    
    async def _main(self):
    # *Ambas* tareas comparten el mismo event-loop
        asyncio.create_task(self._mode_listener())
        await self._ble_task()
        
    def run(self):
        asyncio.run(self._main())

    # ---------- API pública ----------


# ========= Main =========
print("VL6180X listo")
BleCprDevice().run()