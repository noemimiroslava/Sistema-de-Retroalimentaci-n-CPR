# diag.py  ·  Banco de pruebas del sistema CPR  v9
#
# Usa detector.py v3, el MISMO modulo que corre en main.py.
#
# Uso en Thonny:
#     import diag
#     diag.duelo(5, 20, patron=110)      crudo vs mediana+antirrebote
#     diag.punto(3, 60, patron=110)      caracterizacion final
#     diag.reloj(60)                     verifica el reloj del ESP32
#     diag.tasa()   diag.nivel()   diag.senal(5)

import time
from machine import Pin, I2C
from vl6180x import Sensor
from detector import Detector

I2C_SCL, I2C_SDA = 7, 6    # ESP32-C3 (18/19 son el USB nativo)
BASE_MM = 70
SAT_MM  = 200

tof = Sensor(I2C(0, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=400_000))


def mm_to_depth(mm):
    if mm >= SAT_MM or mm > BASE_MM:
        return 0.0
    return (BASE_MM - mm) / 10


def _desv(datos):
    n = len(datos)
    if n < 2:
        return (datos[0] if n else 0.0), 0.0
    media = sum(datos) / n
    var = sum((x - media) ** 2 for x in datos) / (n - 1)
    return media, var ** 0.5


def _mediana(v):
    s = sorted(v)
    n = len(s)
    if n == 0:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


# ======================================================================
def tasa(n=100):
    """Velocidad maxima de lectura del sensor."""
    t0 = time.ticks_ms()
    for _ in range(n):
        tof.range()
    ms = time.ticks_diff(time.ticks_ms(), t0)
    print("Por lectura : {:.2f} ms".format(ms / n))
    print("Tasa maxima : {:.1f} Hz".format(1000.0 * n / ms))


def nivel(segundos=3, dt=15):
    """Rango de la senal (informativo; el detector no lo necesita)."""
    vmin, vmax = 99.0, -99.0
    fin = time.ticks_add(time.ticks_ms(), segundos * 1000)
    while time.ticks_diff(fin, time.ticks_ms()) > 0:
        d = mm_to_depth(tof.range())
        vmin = min(vmin, d)
        vmax = max(vmax, d)
        time.sleep_ms(dt)
    print("min {:.2f}  max {:.2f}  amplitud {:.2f} cm".format(
        vmin, vmax, vmax - vmin))


def reloj(segundos=60):
    """Compara el reloj del ESP32 contra un cronometro externo."""
    print("Arranca tu cronometro AHORA y detenlo al ver LISTO.")
    t0 = time.ticks_ms()
    fin = time.ticks_add(t0, segundos * 1000)
    while time.ticks_diff(fin, time.ticks_ms()) > 0:
        time.sleep_ms(50)
    real = time.ticks_diff(time.ticks_ms(), t0)
    print("\nLISTO  -  el ESP32 midio {:.3f} s".format(real / 1000))


# ======================================================================
def correr(segundos=30, dt=15, patron=None, verbose=True,
           filtro=True, debounce=2):
    """Una corrida del detector real."""
    det = Detector(filtro=filtro, debounce=debounce)

    if verbose:
        print("\n--- {} s, filtro {}, debounce {} ---".format(
            segundos, "SI" if filtro else "NO", debounce))
        print("n,t_ms,periodo_ms,pico_cm,cpm")

    n = 0
    n_muestras = 0
    periodos, picos, cpms = [], [], []
    primer = ultima = None

    t0 = time.ticks_ms()
    siguiente = t0
    fin = time.ticks_add(t0, segundos * 1000)

    while time.ticks_diff(fin, time.ticks_ms()) > 0:
        ahora = time.ticks_ms()
        ev = det.procesar(mm_to_depth(tof.range()), ahora)
        n_muestras += 1

        if ev:
            n += 1
            if primer is None:
                primer = ev["t_subida"]
            ultima = ev["t_subida"]
            picos.append(ev["pico"])
            if ev["periodo"] > 0:
                periodos.append(ev["periodo"])
            if ev["cpm"] > 0:
                cpms.append(ev["cpm"])
            if verbose:
                print("{},{},{},{:.2f},{:.1f}".format(
                    n, time.ticks_diff(ev["t_subida"], t0),
                    ev["periodo"], ev["pico"], ev["cpm"]))

        siguiente = time.ticks_add(siguiente, dt)
        espera = time.ticks_diff(siguiente, time.ticks_ms())
        if espera > 0:
            time.sleep_ms(espera)
        else:
            siguiente = time.ticks_ms()

    transcurrido = time.ticks_diff(time.ticks_ms(), t0)
    cpm_global = 0.0
    if n >= 2:
        span = time.ticks_diff(ultima, primer)
        if span > 0:
            cpm_global = 60000.0 * (n - 1) / span

    m_cpm, s_cpm = _desv(cpms) if cpms else (0.0, 0.0)
    m_per, s_per = _desv(periodos) if periodos else (0.0, 0.0)
    m_pic, s_pic = _desv(picos) if picos else (0.0, 0.0)

    print("Tasa {:.1f} Hz | ciclos {} | CPM global {:.2f}".format(
        1000.0 * n_muestras / transcurrido, n, cpm_global))
    if verbose:
        print("CPM ventana {:.2f} +/- {:.2f} | periodo {:.1f} +/- {:.1f} ms"
              " | pico {:.2f} +/- {:.2f} cm".format(
                  m_cpm, s_cpm, m_per, s_per, m_pic, s_pic))
    if patron:
        sesgo = cpm_global - patron
        print("Sesgo {:+.2f} CPM ({:+.2f} %)".format(
            sesgo, 100.0 * sesgo / patron))

    return {"cpm_global": cpm_global, "ciclos": n,
            "s_cpm": s_cpm, "s_per": s_per}


# ======================================================================
def duelo(repeticiones=5, segundos=20, dt=15, patron=None):
    """Crudo vs mediana+antirrebote, alternados para cancelar deriva."""
    print("\n" + "=" * 54)
    print("DUELO  crudo  vs  mediana+antirrebote")
    print("=" * 54)

    A = {"per": [], "cpm": [], "ciclos": []}
    B = {"per": [], "cpm": [], "ciclos": []}

    for i in range(repeticiones):
        print("\n[ronda {}] crudo".format(i + 1))
        r = correr(segundos, dt, patron, False, filtro=False, debounce=1)
        A["per"].append(r["s_per"])
        A["cpm"].append(r["cpm_global"])
        A["ciclos"].append(r["ciclos"])

        print("[ronda {}] mediana+antirrebote".format(i + 1))
        r = correr(segundos, dt, patron, False, filtro=True, debounce=2)
        B["per"].append(r["s_per"])
        B["cpm"].append(r["cpm_global"])
        B["ciclos"].append(r["ciclos"])

    print("\n" + "=" * 54)
    print("                         crudo    mediana+antir")
    print("Ciclos           : {}   {}".format(A["ciclos"], B["ciclos"]))
    print("Desv per mediana : {:>12.1f}   {:>12.1f}".format(
        _mediana(A["per"]), _mediana(B["per"])))
    print("Desv per PEOR    : {:>12.1f}   {:>12.1f}".format(
        max(A["per"]), max(B["per"])))
    print("CPM glob mediana : {:>12.2f}   {:>12.2f}".format(
        _mediana(A["cpm"]), _mediana(B["cpm"])))
    if patron:
        pa = max(abs(c - patron) for c in A["cpm"]) / patron * 100
        pb = max(abs(c - patron) for c in B["cpm"]) / patron * 100
        print("Error PEOR       : {:>11.2f} % {:>12.2f} %".format(pa, pb))
    print("=" * 54)


# ======================================================================
def punto(repeticiones=3, segundos=60, dt=15, patron=None,
          filtro=True, debounce=2):
    """Caracteriza un punto de frecuencia con repeticiones."""
    print("\n" + "=" * 52)
    print("PUNTO  {}x{} s  filtro {}  debounce {}".format(
        repeticiones, segundos, "SI" if filtro else "NO", debounce))
    print("=" * 52)

    globales, ciclos = [], []
    for i in range(repeticiones):
        print("\n[repeticion {}]".format(i + 1))
        r = correr(segundos, dt, patron, False, filtro, debounce)
        globales.append(r["cpm_global"])
        ciclos.append(r["ciclos"])

    m, s = _desv(globales)
    print("\n" + "=" * 52)
    print("Ciclos        : {}".format(ciclos))
    print("CPM global    : {}".format(
        ", ".join("{:.2f}".format(g) for g in globales)))
    print("Media         : {:.2f} CPM".format(m))
    print("Repetibilidad : {:.2f} CPM ({:.2f} %)".format(
        s, 100.0 * s / m if m else 0))
    if patron:
        print("Sesgo         : {:+.2f} CPM ({:+.2f} %)".format(
            m - patron, 100.0 * (m - patron) / patron))
    print("=" * 52)


# ======================================================================
def ciclos(n=10, dt=15, patron=None, filtro=False, debounce=2,
           limite=90, verbose=True):
    """Captura EXACTAMENTE n compresiones y reporta cada una.

    A diferencia de correr() (que mide durante un tiempo fijo) y de
    punto() (que hace varias corridas largas), esta funcion se detiene
    en cuanto junta n compresiones.  Es la adecuada para un barrido con
    muchos puntos: a 0.8 Hz junta 10 compresiones en 12 s, a 3 Hz en 3 s.

    limite   segundos maximos de espera, por si el detector no dispara
    """
    det = Detector(filtro=filtro, debounce=debounce)

    if verbose:
        print("\n--- {} compresiones, filtro {}, debounce {} ---".format(
            n, "SI" if filtro else "NO", debounce))
        print("n,periodo_ms,cpm_instantaneo,pico_cm")

    periodos, picos = [], []
    capturadas = 0
    primer = ultima = None

    t0 = time.ticks_ms()
    siguiente = t0
    fin = time.ticks_add(t0, limite * 1000)

    while capturadas < n and time.ticks_diff(fin, time.ticks_ms()) > 0:
        ahora = time.ticks_ms()
        ev = det.procesar(mm_to_depth(tof.range()), ahora)

        if ev and ev["periodo"] > 0:
            capturadas += 1
            if primer is None:
                primer = ev["t_subida"]
            ultima = ev["t_subida"]
            periodos.append(ev["periodo"])
            picos.append(ev["pico"])
            if verbose:
                print("{},{},{:.2f},{:.2f}".format(
                    capturadas, ev["periodo"],
                    60000.0 / ev["periodo"], ev["pico"]))

        siguiente = time.ticks_add(siguiente, dt)
        espera = time.ticks_diff(siguiente, time.ticks_ms())
        if espera > 0:
            time.sleep_ms(espera)
        else:
            siguiente = time.ticks_ms()

    if capturadas < n:
        print("AVISO: solo se capturaron {} de {} en {} s".format(
            capturadas, n, limite))
    if not periodos:
        print("Sin compresiones detectadas.")
        return None

    m_per, s_per = _desv(periodos)
    m_pic, s_pic = _desv(picos)
    cpm_medio = 60000.0 / m_per if m_per else 0.0

    # CPM global: usa solo los cruces extremos, asi el error de cada
    # marca se reparte entre todos los intervalos
    cpm_global = 0.0
    if capturadas >= 2 and primer is not None:
        span = time.ticks_diff(ultima, primer)
        if span > 0:
            cpm_global = 60000.0 * (capturadas - 1) / span

    print("\nPeriodo   : {:.1f} +/- {:.1f} ms".format(m_per, s_per))
    print("CPM medio : {:.2f}".format(cpm_medio))
    print("CPM global: {:.2f}".format(cpm_global))
    print("Pico      : {:.2f} +/- {:.2f} cm".format(m_pic, s_pic))
    if patron:
        print("Sesgo     : {:+.2f} CPM ({:+.2f} %)".format(
            cpm_global - patron, 100.0 * (cpm_global - patron) / patron))

    return {"periodos": periodos, "picos": picos,
            "m_per": m_per, "s_per": s_per,
            "cpm_global": cpm_global, "capturadas": capturadas}


# ======================================================================
def senal(segundos=5, dt=15):
    """Senal cruda para graficar en Excel."""
    print("\nt_ms,depth_cm")
    t0 = time.ticks_ms()
    siguiente = t0
    fin = time.ticks_add(t0, segundos * 1000)
    while time.ticks_diff(fin, time.ticks_ms()) > 0:
        t = time.ticks_ms()
        print("{},{:.2f}".format(time.ticks_diff(t, t0),
                                 mm_to_depth(tof.range())))
        siguiente = time.ticks_add(siguiente, dt)
        espera = time.ticks_diff(siguiente, time.ticks_ms())
        if espera > 0:
            time.sleep_ms(espera)
        else:
            siguiente = time.ticks_ms()


print("diag v10 (detector v3):")
print("  diag.ciclos(10, patron=48)   <- para barridos: n compresiones")
print("  diag.correr(20, patron=48)      mide durante 20 s")
print("  diag.punto(3, 60, patron=48)    3 corridas de 60 s")
print("  diag.duelo(5, 20, patron=48)")
print("  diag.reloj(60)   diag.tasa()   diag.nivel()   diag.senal(5)")
